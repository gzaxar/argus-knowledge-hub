"""Workspace bundles: export a workspace to a directory, read one (or its ZIP) safely, preview an import and clone
it into a new workspace (docs/workspace-bundle.md; what is carried: registry.py).

Export writes `manifest.json`, `records/<family>.jsonl` (one row a line, sorted by key) and `files/<aa>/<sha256>`.
Import checks everything before writing anything; the preview is the import itself, rolled back, so what it says is
what applying does. Identifiers are kept when the target does not use them, otherwise renamed deterministically.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from sqlalchemy import Text, inspect as sa_inspect, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.bundle import registry

FORMAT = "argus-workspace-bundle"
FORMAT_VERSION = 1
NAMESPACE = uuid.UUID("6f1f5d1e-6a1c-4c5e-9b5b-6d2f3f0a4b11")
MAX_ZIP_MEMBERS = 200_000
MAX_ZIP_BYTES = 8 * 1024 ** 3
MAX_RATIO = 200
MAX_JSONL_LINE = 64 * 1024 * 1024


class BundleError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (bytes, memoryview)):
        import base64
        return {"$base64": base64.b64encode(bytes(v)).decode()}
    return v


def _columns(model) -> list[tuple[str, str]]:
    """(attribute name, column name) of a model's columns."""
    return [(p.key, p.columns[0].name) for p in sa_inspect(model).column_attrs]


def _geometry(col) -> bool:
    return type(col.type).__name__ == "Geometry"


# =========================================================================== export

def export(db: Session, workspace_id: str, out: Path, *, actor: Optional[str], demo: Optional[dict] = None) -> dict:
    """Write the workspace as a bundle directory `out` (made, or empty). Returns the manifest."""
    from app.models.workspace import Workspace
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise BundleError(f"no workspace {workspace_id!r}")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise BundleError(f"{out} is not empty")
    (out / "records").mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(exist_ok=True)

    sel = registry.Selection(workspace_id)
    families = registry.build()
    people: set[str] = set()
    missing: list[dict] = []
    stored: dict[str, int] = {}
    fam_meta: dict[str, dict] = {}

    def keep_file(fam, row_key, column, path):
        if not path:
            return None
        p = Path(path)
        if not p.is_file():
            missing.append({"family": fam.name, "key": row_key, "column": column, "path": os.path.basename(path)})
            return {"$file": None, "missing": True, "name": os.path.basename(path)}
        digest = sha256_file(p)
        target = out / "files" / digest[:2] / digest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            stored[digest] = target.stat().st_size
        return {"$file": digest, "name": os.path.basename(path)}

    for fam in families:
        objs = fam.select(db, workspace_id, sel)
        keys = fam.keys
        if len(keys) == 1 and not fam.numbered:
            sel.uids[fam.name] = {getattr(o, _attr(fam.model, keys[0])) for o in objs}
        table = fam.model.__table__
        rows = []
        for o in objs:
            row = {}
            for attr, col in _columns(fam.model):
                if col in fam.drop:
                    continue
                value = getattr(o, attr)
                if fam.numbered and col == keys[0]:
                    row["$row"] = value
                    continue
                if _geometry(table.columns[col]) and isinstance(value, (str, bytes)):
                    value = json.loads(value)
                if col in fam.files:
                    value = keep_file(fam, "|".join(str(getattr(o, _attr(fam.model, k))) for k in keys), col, value)
                row[col] = _jsonable(value)
            for col in registry.USER_COLUMNS.get(fam.table, ()):
                if row.get(col):
                    people.add(row[col])
            if fam.table == "issues" and row.get("assignee"):
                people.add(row["assignee"])
            rows.append(row)
        rows.sort(key=lambda r: json.dumps([r.get(k, r.get("$row")) for k in keys], default=str))
        path = out / "records" / f"{fam.name}.jsonl"
        data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")
        path.write_bytes(data)
        fam_meta[fam.name] = {"file": f"records/{fam.name}.jsonl", "rows": len(rows), "sha256": sha256_bytes(data)}

    from app.models.user import User
    users = [u for u in db.scalars(select(User).where(User.id.in_(people)).order_by(User.id))] if people else []
    data = "".join(json.dumps({c: getattr(u, c) for c in registry.PEOPLE_COLUMNS}, ensure_ascii=False, sort_keys=True)
                   + "\n" for u in users).encode("utf-8")
    (out / "records" / "people.jsonl").write_bytes(data)
    fam_meta["people"] = {"file": "records/people.jsonl", "rows": len(users), "sha256": sha256_bytes(data)}

    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION, "created_at": now().isoformat(), "created_by": actor,
        "source": _source(db), "workspace": {"id": ws.id, "name": ws.name},
        "packages": _packages(db, workspace_id),
        "families": fam_meta,
        "dependencies": _dependencies(db, workspace_id, sel),
        "external_config": _external(db, workspace_id),
        "not_reproduced": _not_reproduced(db, workspace_id),
        "missing_files": missing,
    }
    if demo:
        manifest["demo"] = demo
    manifest["files"] = inventory(out)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def _attr(model, column: str) -> str:
    for attr, col in _columns(model):
        if col == column:
            return attr
    return column


def inventory(root: Path) -> list[dict]:
    out = []
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            rel = p.relative_to(root).as_posix()
            out.append({"path": rel, "sha256": sha256_file(p), "size": p.stat().st_size})
    return out


def _source(db: Session) -> dict:
    from app.portability.exporter import instance, schema_head
    try:
        inst = instance(db).get("id")
    except Exception:  # noqa: BLE001 — an installation without the archive configured still exports bundles
        inst = None
    version = os.environ.get("ARGUS_VERSION") or os.environ.get("APP_VERSION")
    return {"instance": inst, "argus_version": version, "schema_revision": schema_head(db)}


def _packages(db: Session, workspace_id: str) -> list[dict]:
    from app.models.package import WorkspacePackage
    return [{"id": r.package_id, "version": r.version, "checksum": r.checksum}
            for r in db.scalars(select(WorkspacePackage).where(WorkspacePackage.workspace_id == workspace_id)
                                .order_by(WorkspacePackage.id))]


def _dependencies(db: Session, ws: str, sel: registry.Selection) -> list[dict]:
    """What the bundle's rows name outside it: types and icons of the installation, other workspaces' records,
    roles and directory groups. Checked again in the target."""
    from app.models.asset import Asset, Relation
    from app.models.activity import ActivityWorkspace
    from app.models.role import RoleBinding
    from app.models.schema import Schema
    out: list[dict] = []
    mine = sel.of("types")
    used = {a.schema_uid for a in db.scalars(select(Asset).where(Asset.workspace_id == ws)) if a.schema_uid}
    for uid in sorted(used - mine):
        s = db.get(Schema, uid)
        out.append({"kind": "type", "uid": uid, "name": s.name if s else None,
                    "why": "a type of another workspace or of the whole installation, used by its records"})
    assets = sel.of("assets")
    for r in db.scalars(select(Relation).where(Relation.workspace_id == ws)):
        for end in (r.from_asset_uid, r.to_asset_uid):
            if end not in assets:
                other = db.get(Asset, end)
                out.append({"kind": "asset", "uid": end, "name": other.name if other else None,
                            "workspace": other.workspace_id if other else None,
                            "why": f"the other end of a {r.relation_type!r} relation"})
    for aw in db.scalars(select(ActivityWorkspace).where(ActivityWorkspace.workspace_id != ws)):
        if aw.activity_uid in sel.of("activities") or aw.series_uid in sel.of("activity_series"):
            out.append({"kind": "workspace", "uid": aw.workspace_id, "why": "an activity is shared with it"})
    for b in db.scalars(select(RoleBinding).where(RoleBinding.workspace_id == ws)):
        if b.subject_type == "group":
            out.append({"kind": "group", "uid": b.subject_id, "why": "a role is granted to this directory group"})
    seen, unique = set(), []
    for d in out:
        k = (d["kind"], d["uid"])
        if k not in seen:
            seen.add(k)
            unique.append(d)
    return unique


def _external(db: Session, ws: str) -> list[dict]:
    from app.models.import_config import ImportConfig
    from app.models.llm_config import LLMConfig
    out = [{"what": "map tiles", "detail": "the background map is the installation's (VITE_MAP_TILES_URL for the web, "
                                           "ARGUS_MAP_TILES for the phone); floor plans and drawn shapes are in the bundle"}]
    c = db.get(LLMConfig, ws)
    if c is not None:
        out.append({"what": "AI endpoint", "detail": f"{c.base_url} ({c.model}): give its API key and check it in "
                                                     f"Administration → AI; it is off until then"})
    for ic in db.scalars(select(ImportConfig).where(ImportConfig.workspace_id == ws)):
        out.append({"what": f"saved import {ic.name!r} ({ic.source})",
                    "detail": "give its credential again" + (" and set its schedule again" if ic.schedule_kind != "off"
                                                             else "")})
    return out


def _not_reproduced(db: Session, ws: str) -> list[dict]:
    """The workspace's rows in tables a bundle does not carry, counted, with the reason."""
    from sqlalchemy import func
    from app.db import Base
    out = []
    for table, reason in sorted(registry.NOT_CARRIED.items()):
        t = Base.metadata.tables.get(table)
        if t is None or "workspace_id" not in t.columns:
            continue
        n = db.scalar(select(func.count()).select_from(t).where(t.c.workspace_id == ws)) or 0
        if n:
            out.append({"table": table, "rows": int(n), "reason": reason})
    return out


def zip_dir(src: Path, dest: Path) -> Path:
    """The bundle directory as a ZIP (stored paths relative, sorted, no links)."""
    src, dest = Path(src), Path(dest)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(src.rglob("*")):
            if p.is_symlink():
                raise BundleError(f"{p} is a link: a bundle holds files only")
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return dest


# =========================================================================== reading safely

def safe_relpath(name: str) -> str:
    """A member's path, if it is a plain relative path inside the bundle."""
    if not name or "\x00" in name or "\\" in name:
        raise BundleError(f"unsafe path {name!r}")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts) or re.match(r"^[A-Za-z]:", name):
        raise BundleError(f"unsafe path {name!r}")
    return p.as_posix()


def unpack(zip_path: Path, dest: Path) -> Path:
    """A bundle ZIP into `dest`, refusing unsafe paths, links, and archives that are too large or too compressed."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise BundleError("that is not a ZIP file") from None
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise BundleError(f"the ZIP has more than {MAX_ZIP_MEMBERS} members")
        total = sum(i.file_size for i in infos)
        if total > MAX_ZIP_BYTES:
            raise BundleError("the ZIP unpacks to more than 8 GB")
        packed = sum(i.compress_size for i in infos) or 1
        if total / packed > MAX_RATIO:
            raise BundleError("the ZIP is compressed beyond any plausible bundle (a ZIP bomb?)")
        root = None
        names = [i.filename for i in infos if not i.is_dir()]
        # A ZIP made by hand may hold the bundle in one folder: that folder is its root.
        tops = {n.split("/", 1)[0] for n in names}
        if "manifest.json" not in names and len(tops) == 1 and f"{next(iter(tops))}/manifest.json" in names:
            root = next(iter(tops))
        for info in infos:
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise BundleError(f"{info.filename} is a link: a bundle holds files only")
            if info.is_dir():
                continue
            rel = safe_relpath(info.filename)
            if root:
                rel = rel[len(root) + 1:]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return dest


@dataclass
class Bundle:
    root: Path
    manifest: dict

    def rows(self, family: str) -> list[dict]:
        meta = self.manifest.get("families", {}).get(family)
        if not meta:
            return []
        path = self.root / safe_relpath(meta["file"])
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if len(line) > MAX_JSONL_LINE:
                    raise BundleError(f"{meta['file']} line {n} is too long")
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        raise BundleError(f"{meta['file']} line {n} is not JSON") from None
        return out

    def file(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            raise BundleError(f"not a file digest: {digest!r}")
        return self.root / "files" / digest[:2] / digest


def read(root: Path) -> Bundle:
    root = Path(root)
    m = root / "manifest.json"
    if not m.is_file():
        raise BundleError("no manifest.json: not a workspace bundle")
    try:
        manifest = json.loads(m.read_text(encoding="utf-8"))
    except ValueError:
        raise BundleError("manifest.json is not JSON") from None
    if manifest.get("format") != FORMAT:
        raise BundleError(f"not a workspace bundle (format {manifest.get('format')!r})")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise BundleError(f"bundle format version {manifest.get('format_version')} is not one this ARGUS reads "
                          f"(it reads {FORMAT_VERSION})")
    return Bundle(root, manifest)


def verify(b: Bundle) -> list[dict]:
    """Problems with the bundle's files: each one's path, size and SHA-256 against the inventory; no link; no file
    outside it; each family's file and checksum. Nothing is a problem when the list is empty."""
    problems: list[dict] = []
    listed = {}
    for f in b.manifest.get("files") or []:
        try:
            rel = safe_relpath(f.get("path", ""))
        except BundleError as e:
            problems.append({"kind": "unsafe_path", "detail": str(e)})
            continue
        listed[rel] = f
    for p in sorted(b.root.rglob("*")):
        rel = p.relative_to(b.root).as_posix()
        if p.is_symlink():
            problems.append({"kind": "link", "path": rel, "detail": "a link: a bundle holds files only"})
        elif p.is_file() and rel != "manifest.json" and rel not in listed:
            problems.append({"kind": "unlisted_file", "path": rel, "detail": "a file the inventory does not list"})
    for rel, f in listed.items():
        p = b.root / rel
        if not p.is_file():
            problems.append({"kind": "missing_file", "path": rel, "detail": "listed in the inventory, not in the bundle"})
            continue
        if p.stat().st_size != f.get("size"):
            problems.append({"kind": "size", "path": rel, "detail": f"{p.stat().st_size} bytes, the inventory says {f.get('size')}"})
        elif sha256_file(p) != f.get("sha256"):
            problems.append({"kind": "checksum", "path": rel, "detail": "its SHA-256 is not the inventory's"})
        elif rel.startswith("files/") and PurePosixPath(rel).name != f.get("sha256"):
            problems.append({"kind": "checksum", "path": rel, "detail": "a stored file is named by its SHA-256"})
    for name, meta in (b.manifest.get("families") or {}).items():
        if meta.get("file") not in listed:
            problems.append({"kind": "missing_family", "path": meta.get("file"), "detail": f"the rows of {name}"})
        elif listed[meta["file"]].get("sha256") != meta.get("sha256"):
            problems.append({"kind": "checksum", "path": meta["file"], "detail": "not the checksum the manifest gives it"})
    return problems


# =========================================================================== importing

@dataclass
class Report:
    blockers: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    added: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    renamed: list[dict] = field(default_factory=list)
    people: dict[str, int] = field(default_factory=lambda: {"matched": 0, "created": 0})
    packages: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    not_reproduced: list[dict] = field(default_factory=list)
    external_config: list[dict] = field(default_factory=list)
    files: dict[str, int] = field(default_factory=lambda: {"stored": 0, "missing_at_source": 0})

    def view(self) -> dict:
        return {"ok": not self.blockers, "blockers": self.blockers, "warnings": self.warnings, "added": self.added,
                "updated": self.updated, "renamed": self.renamed[:500], "renamed_count": len(self.renamed),
                "people": self.people, "packages": self.packages, "dependencies": self.dependencies,
                "not_reproduced": self.not_reproduced, "external_config": self.external_config, "files": self.files}


WS_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


def check_target(db: Session, workspace_id: str, name: str) -> list[dict]:
    from app.models.workspace import Workspace
    out = []
    if not WS_ID.match(workspace_id or ""):
        out.append({"kind": "workspace_id", "detail": "a workspace id is 2–63 lower-case letters, digits, - or _"})
    elif db.get(Workspace, workspace_id) is not None:
        out.append({"kind": "workspace_exists", "detail": f"workspace {workspace_id!r} exists: a bundle is cloned into "
                                                          f"a new workspace (choose another id)"})
    if not (name or "").strip():
        out.append({"kind": "workspace_name", "detail": "the new workspace needs a name"})
    return out


def check_packages(b: Bundle) -> list[dict]:
    from app.packages.loader import available
    have = available()
    out = []
    for p in b.manifest.get("packages") or []:
        got = have.get(p.get("id"))
        if got is None:
            status, detail = "missing", "this installation does not have the package"
        elif got.version != p.get("version"):
            status, detail = "other_version", f"this installation has {got.version}, the bundle was made with {p.get('version')}"
        elif got.checksum != p.get("checksum"):
            status, detail = "other_content", "same version, different content (checksum): not the same package"
        else:
            status, detail = "ok", None
        out.append({"id": p.get("id"), "version": p.get("version"), "status": status, "detail": detail})
    return out


class _Ids:
    """Old identifier → new, for the rows renamed in the target, and the workspace id."""

    def __init__(self, old_ws: str, new_ws: str):
        self.old_ws, self.new_ws = old_ws, new_ws
        self.map: dict[str, str] = {}
        self._token: Optional[re.Pattern] = None

    def rename(self, old: str) -> str:
        new = str(uuid.uuid5(NAMESPACE, f"{self.new_ws}:{old}"))
        self.map[old] = new
        self._token = None
        return new

    def string(self, v: str) -> str:
        if v in self.map:
            return self.map[v]
        if v == self.old_ws:
            return self.new_ws
        if v.startswith(self.old_ws + ":"):
            return self.new_ws + v[len(self.old_ws):]
        return v

    def value(self, v: str) -> str:
        """An identifier, or a text that may name some (a Markdown body, a description, a tour step's link)."""
        out = self.string(v)
        if out is v and (any(c.isspace() for c in v) or "/" in v or "](" in v):
            return self.text(v)
        return out

    def deep(self, v):
        if isinstance(v, str):
            return self.value(v)
        if isinstance(v, list):
            return [self.deep(x) for x in v]
        if isinstance(v, dict):
            return {k: self.deep(x) for k, x in v.items()}
        return v

    def text(self, v: str) -> str:
        """Identifiers inside free text (Markdown links to a record or an attachment)."""
        if not self.map:
            return v
        if self._token is None:
            keys = sorted(self.map, key=len, reverse=True)
            self._token = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z0-9_-])")
        return self._token.sub(lambda m: self.map[m.group(1)], v)


def apply(db: Session, b: Bundle, *, workspace_id: str, name: str, actor: Optional[str], people_access: bool = False,
          dry_run: bool = True, files_root: Optional[Path] = None) -> Report:
    """Clone the bundle into a new workspace. With `dry_run` the import runs and is rolled back: the report is
    what applying would do. The caller commits when it is not a dry run and the report has no blockers."""
    rep = Report()
    rep.not_reproduced = list(b.manifest.get("not_reproduced") or [])
    rep.external_config = list(b.manifest.get("external_config") or [])
    rep.external_config.append({"what": "search index", "detail": "Ask ARGUS's meaning search is indexed again here, "
                                                                  "with this installation's embedding model "
                                                                  "(Administration → AI → index)"})
    for m in b.manifest.get("missing_files") or []:
        rep.not_reproduced.append({"table": m["family"], "rows": 1,
                                   "reason": f"the file {m.get('path')} of {m['family']} {m['key']} was missing at the source"})
        rep.files["missing_at_source"] += 1
    rep.blockers += [{"kind": p["kind"], "detail": f"{p.get('path', '')}: {p['detail']}".strip(": ")} for p in verify(b)]
    rep.blockers += check_target(db, workspace_id, name)
    rep.packages = check_packages(b)
    rep.blockers += [{"kind": "package", "detail": f"{p['id']} {p['version']}: {p['detail']}"}
                     for p in rep.packages if p["status"] != "ok"]
    if rep.blockers:
        return rep
    savepoint = db.begin_nested()
    try:
        _load(db, b, rep, workspace_id, name.strip(), actor, people_access, dry_run, files_root)
    except BundleError as e:
        rep.blockers.append({"kind": "invalid", "detail": str(e)})
    except Exception as e:  # noqa: BLE001 — anything the database refuses is a blocker, said in its own words
        rep.blockers.append({"kind": "refused", "detail": f"{type(e).__name__}: {str(e).splitlines()[0][:400]}"})
    if dry_run or rep.blockers:
        savepoint.rollback()
        if not dry_run:
            db.rollback()
    else:
        savepoint.commit()
    return rep


def _load(db: Session, b: Bundle, rep: Report, new_ws: str, name: str, actor: Optional[str], people_access: bool,
          dry_run: bool, files_root: Optional[Path]) -> None:
    from app.models.membership import Membership
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.packages.install import install

    old_ws = (b.manifest.get("workspace") or {}).get("id")
    if not old_ws:
        raise BundleError("the manifest names no workspace")
    ids = _Ids(old_ws, new_ws)
    declared = {(d.get("kind"), ids.string(d.get("uid") or "")) for d in b.manifest.get("dependencies") or []}
    families = {f.name: f for f in registry.build()}
    rows = {name_: b.rows(name_) for name_ in list(families) + ["people"]}

    # ---- the workspace and its packages
    [w] = rows["workspace"] or [None]
    if w is None:
        raise BundleError("the bundle has no workspace row")
    ws = Workspace(id=new_ws, name=name)
    for attr, col in _columns(Workspace):
        if col not in ("id", "name", "created_at") and col in w:
            setattr(ws, attr, _value(Workspace, col, w[col]))
    db.add(ws)
    db.flush()
    package_ids = [p["id"] for p in b.manifest.get("packages") or []]
    if package_ids:
        install(db, new_ws, package_ids, actor=actor)
    if actor:
        owner = db.scalar(select(User).where(User.email == actor)) or db.get(User, actor)
        if owner is not None:
            db.add(Membership(workspace_id=new_ws, user_id=owner.id, can_read=True, can_create=True, can_modify=True,
                              can_delete=True, can_read_tickets=True, can_create_tickets=True, can_modify_tickets=True,
                              can_delete_tickets=True, can_read_documents=True, can_create_documents=True,
                              can_modify_documents=True, can_delete_documents=True, can_approve_documents=True))
            db.flush()

    # ---- people: matched by e-mail, else made (no rights of their own, no login identity)
    for p in rows["people"]:
        email = (p.get("email") or "").strip()
        match = db.scalar(select(User).where(User.email.ilike(email))) if email else None
        if match is not None:
            if match.id != p["id"]:
                ids.map[p["id"]] = match.id
                ids._token = None
            rep.people["matched"] += 1
            continue
        uid = p["id"] if db.get(User, p["id"]) is None else ids.rename(p["id"])
        db.add(User(id=uid, email=email or f"{uid}@unknown.invalid", name=p.get("name"), username=p.get("username"),
                    source="bundle", is_admin=False, active=True))
        rep.people["created"] += 1
    db.flush()

    # ---- which identifiers the target uses already: renamed (deterministically)
    for fname, fam in families.items():
        if fam.numbered or fname == "workspace":
            continue
        keys = fam.keys
        if len(keys) != 1:
            continue
        col = fam.model.__table__.columns[keys[0]]
        if col.type.python_type is not str:
            continue
        olds = [r[keys[0]] for r in rows[fname] if isinstance(r.get(keys[0]), str)]
        news = [ids.string(o) for o in olds]
        if not news:
            continue
        has_ws = "workspace_id" in fam.model.__table__.columns
        owners = dict(db.execute(select(col, fam.model.__table__.columns["workspace_id"]).where(col.in_(news))).all()) \
            if has_ws else {k: None for k in db.scalars(select(col).where(col.in_(news)))}
        for old, new in zip(olds, news):
            if new not in owners:
                continue
            if fam.upsert and (not has_ws or owners[new] == new_ws):
                continue                       # made by a package in the new workspace (or an installation role)
            ids.rename(old)
            rep.renamed.append({"family": fname, "from": old, "to": ids.map[old], "why": "identifier in use"})

    # ---- installation-wide unique values: asset keys, document codes
    from app.models.asset import Asset
    from app.models.document import Document
    unique_cols = {"assets": (Asset.key, "key"), "documents": (Document.code, "code")}
    unique_new: dict[str, dict[str, str]] = {}
    for fname, (col, field_) in unique_cols.items():
        vals = [r[field_] for r in rows[fname] if r.get(field_)]
        taken = set(db.scalars(select(col).where(col.in_(vals)))) if vals else set()
        unique_new[fname] = {}
        for v in vals:
            if v in taken:
                unique_new[fname][v] = f"{v}-{new_ws}"
                rep.renamed.append({"family": fname, "from": v, "to": f"{v}-{new_ws}",
                                    "why": f"{field_} used in this installation"})

    # ---- rows, in order
    obs_map: dict[int, int] = {}
    deferred: list[tuple[Any, str, Any]] = []
    for fname, fam in families.items():
        if fname == "workspace" or fname == "workspace_packages":
            continue
        if fam.people and not people_access:
            if rows[fname]:
                rep.warnings.append({"kind": "people", "detail": f"{len(rows[fname])} {fname} not applied: "
                                                                 f"tick “apply people's access” to apply them"})
            continue
        model, table = fam.model, fam.model.__table__
        added = updated = 0
        for r in rows[fname]:
            values: dict[str, Any] = {}
            for col, v in r.items():
                if col == "$row" or col not in table.columns:
                    if col not in ("$row",) and col not in table.columns:
                        raise BundleError(f"{fname}: no column {col!r} in this installation")
                    continue
                if col in fam.files:
                    v = _store_file(b, v, files_root, dry_run, rep)
                elif isinstance(table.columns[col].type, JSONB) or _geometry(table.columns[col]):
                    v = ids.deep(v)
                elif isinstance(v, str):
                    v = ids.text(v) if isinstance(table.columns[col].type, Text) else ids.value(v)
                if col == "workspace_id" and v is None:
                    v = new_ws
                values[col] = v
            if fname in unique_new:
                field_ = unique_cols[fname][1]
                if values.get(field_) in unique_new[fname]:
                    values[field_] = unique_new[fname][values[field_]]
            if fname == "spatial_features" and values.get("observation_id") is not None:
                values["observation_id"] = obs_map.get(values["observation_id"])
            if fname == "llm_configs":
                values["enabled"], values["last_check_ok"] = False, False
            if fname == "import_configs":
                values["schedule_kind"], values["schedule_failures"] = "off", 0
            if fname == "types" and not isinstance(values.get("attributes"), list):
                raise BundleError(f"types: {values.get('name')!r} has attributes that are not a list")
            if fname == "spatial_features" or fname == "location_observations":
                _check_geometry(db, fname, values)
            outside = _points_outside(db, fname, values, new_ws, declared)
            if outside:
                rep.not_reproduced.append({"table": fname, "rows": 1, "reason": outside})
                continue
            later = {c: values.pop(c) for c in fam.deferred if values.get(c) is not None}
            obj, changed = _upsert(db, fam, values, new_ws) if fam.upsert else (None, False)
            if obj is None:
                obj = model(**{_attr(model, c): _value(model, c, v) for c, v in values.items()})
                db.add(obj)
                added += 1
            elif changed:
                updated += 1
            if later:
                deferred.append((obj, later))
            if fname == "location_observations" and "$row" in r:
                db.flush()
                obs_map[r["$row"]] = obj.id
        db.flush()
        if added:
            rep.added[fname] = added
        if updated:
            rep.updated[fname] = updated
    for obj, later in deferred:
        for c, v in later.items():
            setattr(obj, _attr(type(obj), c), _value(type(obj), c, v))
    db.flush()

    # ---- rebuilt: links between tickets and the equipment they name
    from app.ledger.tickets import derive_for_ticket
    from app.models.issue import Issue
    for issue in db.scalars(select(Issue).where(Issue.workspace_id == new_ws)):
        derive_for_ticket(db, issue)
    db.flush()
    rep.dependencies = _check_dependencies(db, b, ids)
    if b.manifest.get("demo"):
        from app.models.app_setting import AppSetting
        key = f"demo.tour.{new_ws}"
        tour = ids.deep(b.manifest["demo"])        # its links name records, which may have been renamed
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=tour))
        else:
            row.value = tour
        db.flush()


def _value(model, col: str, v):
    if v is None:
        return None
    from sqlalchemy import Date, DateTime
    c = model.__table__.columns[col]
    if isinstance(c.type, DateTime) and isinstance(v, str):
        return datetime.fromisoformat(v)
    if isinstance(c.type, Date) and isinstance(v, str):
        return date.fromisoformat(v)
    if isinstance(v, dict) and set(v) == {"$base64"}:
        import base64
        return base64.b64decode(v["$base64"])
    return v


def _upsert(db: Session, fam, values: dict, new_ws: str) -> tuple[Any, bool]:
    """(the row, whether it changed) when a package made it in the new workspace already: the bundle's version of it
    replaces it. An installation-wide role that exists is used as it is, never changed by a bundle."""
    model = fam.model
    key = {c: values.get(c) for c in fam.keys}
    if any(v is None for v in key.values()):
        return None, False
    obj = db.get(model, tuple(key.values()) if len(key) > 1 else next(iter(key.values())))
    if obj is None:
        return None, False
    if "workspace_id" not in model.__table__.columns:
        return obj, False
    if getattr(obj, "workspace_id", None) != new_ws:
        raise BundleError(f"{fam.name} {key}: a row of another workspace")
    changed = False
    for c, v in values.items():
        if c in fam.keys or c in fam.deferred or c in ("created_at", "updated_at"):
            continue
        new = _value(model, c, v)
        if getattr(obj, _attr(model, c)) != new:
            setattr(obj, _attr(model, c), new)
            changed = True
    return obj, changed


def _points_outside(db: Session, fname: str, values: dict, new_ws: str, declared: set) -> Optional[str]:
    """A row naming a record of another workspace the bundle declared (its `dependencies`) and this installation
    lacks: skipped and reported. A row naming something neither in the bundle nor declared is a broken bundle."""
    """Why a row cannot be made: it names a record of another workspace that the target does not have."""
    from app.models.asset import Asset
    from app.models.workspace import Workspace
    if fname == "relations":
        for end in ("from_asset_uid", "to_asset_uid"):
            if db.get(Asset, values.get(end)) is None:
                if ("asset", values.get(end)) not in declared:
                    raise BundleError(f"relations: a {values.get('relation_type')!r} relation names {values.get(end)}, "
                                      f"which is neither in the bundle nor among its declared dependencies")
                return (f"a {values.get('relation_type')!r} relation to {values.get(end)}, a record of another workspace "
                        f"this installation does not have")
    if fname == "activity_workspaces" and values.get("workspace_id") != new_ws:
        if db.get(Workspace, values.get("workspace_id")) is None:
            if ("workspace", values.get("workspace_id")) not in declared:
                raise BundleError(f"activity_workspaces: an activity is shared with workspace "
                                  f"{values.get('workspace_id')!r}, which the bundle does not declare")
            return f"an activity shared with workspace {values.get('workspace_id')!r}, which this installation does not have"
    return None


def _store_file(b: Bundle, v, files_root: Optional[Path], dry_run: bool, rep: Report) -> Optional[str]:
    """A file of the bundle, stored where the installation keeps files: its path."""
    if not isinstance(v, dict) or "$file" not in v:
        return v
    digest = v.get("$file")
    if digest is None:
        return f"/missing/{v.get('name') or 'file'}"           # missing at the source: listed in not_reproduced
    src = b.file(digest)
    if not src.is_file():
        raise BundleError(f"the file {digest} a row names is not in the bundle")
    root = Path(files_root or os.environ.get("ATTACHMENTS_DIR", "/data/attachments"))
    target = root / "bundles" / digest[:2] / digest
    if not dry_run and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        if sha256_file(target) != digest:
            raise BundleError(f"the file {digest} changed while it was stored")
        rep.files["stored"] += 1
    return str(target)


def _check_geometry(db: Session, fname: str, values: dict) -> None:
    from app.services import spatial
    g = values.get("geometry")
    if g is None:
        raise BundleError(f"{fname}: a row has no geometry")
    try:
        if fname == "location_observations" or values.get("role", "position") == "position":
            if not isinstance(g, dict) or g.get("type") != "Point":
                raise spatial.SpatialError("a position is a GeoJSON Point")
            lon, lat = g["coordinates"][:2]
            spatial.point(lat, lon)
        else:
            spatial.shape(db, g, values.get("role"))
    except (spatial.SpatialError, KeyError, TypeError, ValueError) as e:
        raise BundleError(f"{fname} {values.get('uid') or ''}: {e}") from None


def _check_dependencies(db: Session, b: Bundle, ids: _Ids) -> list[dict]:
    from app.models.asset import Asset
    from app.models.schema import Schema
    from app.models.workspace import Workspace
    out = []
    for d in b.manifest.get("dependencies") or []:
        uid = ids.string(d["uid"])
        found = {"type": lambda: db.get(Schema, uid), "asset": lambda: db.get(Asset, uid),
                 "workspace": lambda: db.get(Workspace, uid), "group": lambda: _group(db, uid)}.get(d["kind"], lambda: None)()
        out.append({**d, "uid": uid, "present": found is not None})
    return out


def _group(db: Session, uid: str):
    from app.models.group import Group
    return db.get(Group, uid)
