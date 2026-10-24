"""Workspace bundles, for instance administrators (app/bundle, docs/workspace-bundle.md).

- `GET /v1/admin/bundles` — the bundles exported here, the ones uploaded for import, and the demo bundles shipped
  with ARGUS.
- `POST /v1/admin/bundles/exports` `{workspace_id}`; `GET …/exports/{id}/download` (the ZIP);
  `DELETE …/exports/{id}`.
- `POST /v1/admin/bundles/imports` (a ZIP) — unpacked and checked; `POST …/imports/{id}/preview` and
  `…/apply` `{workspace_id, name, people_access}`; `DELETE …/imports/{id}`.
- `POST /v1/admin/bundles/demos/{name}/preview` and `…/apply` — a demo bundle, through the same import.
- `GET /v1/workspaces/{id}/tour` — a demo workspace's guided tour, for anyone who may read the workspace.

Only authenticated instance administrators (`is_admin`) export, download, preview and apply. Each action is in the
audit trail (`portability_events`, subjects `bundle-export` and `bundle-import`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity, require_permission
from app.bundle import core
from app.db import get_db

router = APIRouter(prefix="/v1", tags=["workspace bundles"])
DEMOS_DIR = Path(os.environ.get("ARGUS_DEMO_WORKSPACES", Path(__file__).resolve().parents[2] / "demo_workspaces"))
MAX_UPLOAD = 4 * 1024 ** 3


def store() -> Path:
    root = Path(os.environ.get("ARGUS_BUNDLES_DIR")
                or Path(os.environ.get("ARGUS_PORTABILITY_ROOT", "/data/portability")) / "bundles")
    root.mkdir(parents=True, exist_ok=True)
    return root


def require_admin(identity=Depends(get_identity)) -> OidcIdentity:
    if not isinstance(identity, OidcIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Workspace bundles are for instance administrators")
    return identity


def _actor(identity: OidcIdentity) -> str:
    return identity.user.email or identity.user.id


def _event(db: Session, subject: str, subject_id: str, kind: str, actor: str, detail: dict) -> None:
    from app.models.portability import PortabilityEvent
    db.add(PortabilityEvent(subject_kind=subject, subject_id=subject_id, kind=kind, actor=actor, detail=detail))


def _id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f-]{36}", value or ""):
        raise HTTPException(status_code=404, detail="No such bundle")
    return value


def _summary(m: dict) -> dict:
    return {"format_version": m.get("format_version"), "created_at": m.get("created_at"), "created_by": m.get("created_by"),
            "source": m.get("source"), "workspace": m.get("workspace"), "packages": m.get("packages"),
            "rows": {k: v.get("rows") for k, v in (m.get("families") or {}).items() if v.get("rows")},
            "files": len(m.get("files") or []), "bytes": sum(f.get("size", 0) for f in m.get("files") or []),
            "dependencies": m.get("dependencies") or [], "external_config": m.get("external_config") or [],
            "not_reproduced": m.get("not_reproduced") or [], "missing_files": m.get("missing_files") or [],
            "demo": m.get("demo")}


# --------------------------------------------------------------------------- listing

@router.get("/admin/bundles")
def list_bundles(identity=Depends(require_admin)):
    root = store()
    exports, imports = [], []
    for kind, out in (("exports", exports), ("imports", imports)):
        for d in sorted((root / kind).glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if (root / kind).exists() else []:
            m = d / "bundle" / "manifest.json"
            if m.is_file():
                try:
                    out.append({"id": d.name, **_summary(json.loads(m.read_text()))})
                except ValueError:
                    continue
    demos = []
    for d in sorted(DEMOS_DIR.glob("*")) if DEMOS_DIR.exists() else []:
        if (d / "manifest.json").is_file():
            try:
                b = core.read(d)
            except core.BundleError:
                continue
            demos.append({"name": d.name, **_summary(b.manifest), "packages_status": core.check_packages(b)})
    return {"exports": exports, "imports": imports, "demos": demos}


# --------------------------------------------------------------------------- export

class ExportIn(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=63)


@router.post("/admin/bundles/exports", status_code=201)
def export_workspace(body: ExportIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """The workspace as a bundle directory and its ZIP, kept here to download."""
    bid = str(uuid.uuid4())
    folder = store() / "exports" / bid
    try:
        manifest = core.export(db, body.workspace_id, folder / "bundle", actor=_actor(identity))
        core.zip_dir(folder / "bundle", folder / f"{body.workspace_id}.argus-workspace.zip")
    except core.BundleError as e:
        shutil.rmtree(folder, ignore_errors=True)
        _event(db, "bundle-export", bid, "export", _actor(identity),
               {"workspace": body.workspace_id, "outcome": "refused", "reason": str(e)})
        db.commit()
        raise HTTPException(status_code=422, detail=str(e))
    _event(db, "bundle-export", bid, "export", _actor(identity),
           {"workspace": body.workspace_id, "format_version": core.FORMAT_VERSION, "outcome": "exported",
            "rows": {k: v["rows"] for k, v in manifest["families"].items()}, "files": len(manifest["files"]),
            "missing_files": len(manifest["missing_files"]), "not_reproduced": manifest["not_reproduced"]})
    db.commit()
    return {"id": bid, **_summary(manifest)}


@router.get("/admin/bundles/exports/{bid}/download")
def download_export(bid: str, identity=Depends(require_admin), db: Session = Depends(get_db)):
    folder = store() / "exports" / _id(bid)
    zips = list(folder.glob("*.zip"))
    if not zips:
        raise HTTPException(status_code=404, detail="No such bundle")
    _event(db, "bundle-export", bid, "download", _actor(identity), {"file": zips[0].name})
    db.commit()
    return FileResponse(zips[0], media_type="application/zip", filename=zips[0].name)


@router.delete("/admin/bundles/{kind}/{bid}", status_code=204)
def delete_bundle(kind: str, bid: str, identity=Depends(require_admin), db: Session = Depends(get_db)):
    if kind not in ("exports", "imports"):
        raise HTTPException(status_code=404, detail="No such bundle")
    folder = store() / kind / _id(bid)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="No such bundle")
    shutil.rmtree(folder)
    _event(db, "bundle-export" if kind == "exports" else "bundle-import", bid, "delete", _actor(identity), {})
    db.commit()


# --------------------------------------------------------------------------- import

@router.post("/admin/bundles/imports", status_code=201)
async def upload_bundle(file: UploadFile = File(...), identity=Depends(require_admin), db: Session = Depends(get_db)):
    """A bundle ZIP, unpacked safely and checked (paths, sizes, checksums): nothing is imported yet."""
    bid = str(uuid.uuid4())
    folder = store() / "imports" / bid
    folder.mkdir(parents=True)
    zpath = folder / "upload.zip"
    size = 0
    with open(zpath, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(status_code=413, detail="A bundle ZIP is at most 4 GB")
            out.write(chunk)
    try:
        core.unpack(zpath, folder / "bundle")
        b = core.read(folder / "bundle")
        problems = core.verify(b)
    except core.BundleError as e:
        shutil.rmtree(folder, ignore_errors=True)
        _event(db, "bundle-import", bid, "upload", _actor(identity),
               {"file": file.filename, "outcome": "refused", "reason": str(e)})
        db.commit()
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        zpath.unlink(missing_ok=True)
    _event(db, "bundle-import", bid, "upload", _actor(identity),
           {"file": file.filename, "source": b.manifest.get("source"), "workspace": b.manifest.get("workspace"),
            "format_version": b.manifest.get("format_version"), "problems": problems,
            "outcome": "checked" if not problems else "problems"})
    db.commit()
    return {"id": bid, **_summary(b.manifest), "problems": problems, "packages_status": core.check_packages(b)}


class ApplyIn(BaseModel):
    workspace_id: str = Field(min_length=2, max_length=63)
    name: str = Field(min_length=1, max_length=200)
    people_access: bool = False


def _run(db: Session, b: core.Bundle, body: ApplyIn, identity, subject_id: str, source: str, dry_run: bool) -> dict:
    report = core.apply(db, b, workspace_id=body.workspace_id, name=body.name, actor=_actor(identity),
                        people_access=body.people_access, dry_run=dry_run)
    view = report.view()
    outcome = ("previewed" if dry_run else "imported") if view["ok"] else "refused"
    if dry_run or not view["ok"]:
        db.rollback()
    _event(db, "bundle-import", subject_id, "preview" if dry_run else "apply", _actor(identity),
           {"source": source, "bundle_source": b.manifest.get("source"), "from_workspace": b.manifest.get("workspace"),
            "to_workspace": body.workspace_id, "format_version": b.manifest.get("format_version"),
            "people_access": body.people_access, "outcome": outcome, "blockers": view["blockers"],
            "added": view["added"], "renamed": view["renamed_count"]})
    db.commit()
    return view


def _staged(bid: str) -> core.Bundle:
    folder = store() / "imports" / _id(bid) / "bundle"
    if not folder.exists():
        raise HTTPException(status_code=404, detail="No such bundle")
    return core.read(folder)


@router.post("/admin/bundles/imports/{bid}/preview")
def preview_import(bid: str, body: ApplyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """What applying would do — run and rolled back: added, renamed, people, dependencies, blockers."""
    return _run(db, _staged(bid), body, identity, bid, "upload", dry_run=True)


@router.post("/admin/bundles/imports/{bid}/apply")
def apply_import(bid: str, body: ApplyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """Clone the bundle into a new workspace, all or nothing."""
    view = _run(db, _staged(bid), body, identity, bid, "upload", dry_run=False)
    if not view["ok"]:
        raise HTTPException(status_code=422, detail=view)
    return view


def _demo(name: str) -> core.Bundle:
    if not re.fullmatch(r"[a-z0-9-]{1,63}", name or "") or not (DEMOS_DIR / name / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail="No such demo")
    return core.read(DEMOS_DIR / name)


@router.post("/admin/bundles/demos/{name}/preview")
def preview_demo(name: str, body: ApplyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    return _run(db, _demo(name), body, identity, f"demo:{name}", f"demo {name}", dry_run=True)


@router.post("/admin/bundles/demos/{name}/apply")
def apply_demo(name: str, body: ApplyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    view = _run(db, _demo(name), body, identity, f"demo:{name}", f"demo {name}", dry_run=False)
    if not view["ok"]:
        raise HTTPException(status_code=422, detail=view)
    return view


# --------------------------------------------------------------------------- a demo's tour

@router.get("/workspaces/{workspace_id}/tour")
def workspace_tour(workspace_id: str, ws: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """A demo workspace's guided tour (its title, what it is, the steps to start exploring), or none."""
    from app.models.app_setting import AppSetting
    if ws != workspace_id:
        raise HTTPException(status_code=404, detail="No tour")
    row = db.get(AppSetting, f"demo.tour.{workspace_id}")
    return {"workspace_id": workspace_id, "tour": row.value if row is not None else None}
