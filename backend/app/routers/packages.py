"""Template packages: what this installation ships, what a workspace uses (exact versions and checksums,
with its history), and installing them — previewed first, applied all or nothing (app.packages)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, PatIdentity, get_identity
from app.db import get_db
from app.models.workspace import Workspace
from app.packages import install as installer
from app.packages.behaviors import describe as behaviors
from app.packages.loader import available
from app.packages.validate import validate

router = APIRouter(prefix="/v1", tags=["packages"])


class PackagesIn(BaseModel):
    packages: list[str]
    # for the accelerator catalogue: hang from this catalogue workspace's shared types
    catalogue_workspace_id: Optional[str] = None
    # for the accelerator catalogue: "global" makes this workspace the catalogue others hang from
    scope: Optional[str] = None


def _may_read(db: Session, identity: Identity, workspace_id: str) -> None:
    from app.services.permissions import resolve_permission
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(identity, PatIdentity):
        if identity.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return
    if identity.user.is_admin:
        return
    if not any(resolve_permission(db, identity.user, workspace_id, "read", r) for r in ("objects", "tickets", "documents")):
        raise HTTPException(status_code=404, detail="Workspace not found")


def _may_install(db: Session, identity: Identity, workspace_id: str) -> None:
    from app.routers.workspaces import _require_owner_or_admin
    _require_owner_or_admin(workspace_id, identity, db)


@router.get("/packages")
def list_packages(identity: Identity = Depends(get_identity)):
    """The template packages this installation ships, each with what it holds and whether it is valid."""
    catalog = available()
    return [{**p.describe(), "installable": p.id in installer.APPLIERS,
             "problems": [str(x) for x in validate(p, catalog)]} for p in catalog.values()]


@router.get("/packages/behaviors")
def list_behaviors(identity=Depends(get_identity)):
    """The behaviour ids a package may give a type, and the type each is bound to in this release."""
    return behaviors()


@router.get("/packages/{package_id}")
def get_package(package_id: str, identity=Depends(get_identity)):
    """One package: its manifest and the names of what it defines."""
    p = available().get(package_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No such package")
    objects = (p.section("object_types") or {}).get("types") or []
    return {**p.describe(), "problems": [str(x) for x in validate(p)],
            "object_types": [{"name": t.get("name"), "parent": t.get("parent"), "abstract": bool(t.get("abstract")),
                              "locatable": bool(t.get("locatable")), "map_layer": t.get("map_layer")} for t in objects],
            "ticket_types": [k.get("name") for k in (p.section("ticket_types") or {}).get("kinds") or []],
            "document_types": [k.get("name") for k in (p.section("document_types") or {}).get("kinds") or []],
            "enumerations": [f"{e.get('applies_to')}.{e.get('key')}" for e in p.section("enumerations") or []],
            "workflows": [w.get("name") for w in p.section("workflows") or []],
            "map_layers": p.section("map_layers") or []}


@router.post("/packages/resolve")
def resolve_packages(body: PackagesIn, identity=Depends(get_identity)):
    """What a new workspace starting from these packages would get: each package (dependencies first) and
    what it holds. For the form that creates a workspace, before there is one to preview in."""
    try:
        order = installer.resolve(list(dict.fromkeys(["core-facility", *body.packages])))
    except installer.PackageProblem as e:
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "package"})
    return [{**p.describe(), "requested": requested} for p, requested in order]


def _history(db: Session, workspace_id: str) -> list[dict]:
    return [{"package_id": h.package_id, "action": h.action, "from_version": h.from_version,
             "to_version": h.to_version, "checksum": h.checksum, "actor": h.actor, "at": h.at,
             "result": h.result} for h in installer.history(db, workspace_id)]


@router.get("/workspaces/{workspace_id}/packages")
def workspace_packages(workspace_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Exactly which package versions this workspace uses (with the checksum of what was applied, and how it
    was put in), what newer versions this installation ships, and the history."""
    _may_read(db, identity, workspace_id)
    catalog = available()
    rows = []
    for r in installer.installed(db, workspace_id).values():
        shipped = catalog.get(r.package_id)
        rows.append({"package_id": r.package_id, "name": shipped.name if shipped else r.package_id,
                     "version": r.version, "checksum": r.checksum, "options": r.options,
                     "installed_at": r.installed_at, "installed_by": r.installed_by,
                     "shipped_version": shipped.version if shipped else None,
                     "upgrade_available": bool(shipped and shipped.version != r.version)})
    return {"workspace_id": workspace_id, "packages": sorted(rows, key=lambda x: x["package_id"]),
            "history": _history(db, workspace_id)}


@router.post("/workspaces/{workspace_id}/packages/preview")
def preview_install(workspace_id: str, body: PackagesIn, identity=Depends(get_identity),
                    db: Session = Depends(get_db)):
    """What installing these packages would do here — install, upgrade or leave unchanged, and what it would
    create and extend — worked out by applying it and rolling it back. Nothing is kept."""
    _may_install(db, identity, workspace_id)
    try:
        plan = installer.plan(db, workspace_id, body.packages, catalogue_workspace_id=body.catalogue_workspace_id,
                              scope=body.scope)
    except installer.PackageProblem as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "package"})
    db.rollback()
    return plan.as_dict()


@router.post("/workspaces/{workspace_id}/packages/install")
def install_packages(workspace_id: str, body: PackagesIn, identity=Depends(get_identity),
                     db: Session = Depends(get_db)):
    """Install these packages (and what they depend on) in this workspace, all or nothing. Reinstalling the
    version it already has changes nothing."""
    _may_install(db, identity, workspace_id)
    actor = identity.user.id if isinstance(identity, OidcIdentity) else "api-token"
    try:
        plan = installer.install(db, workspace_id, body.packages, actor=actor,
                                 catalogue_workspace_id=body.catalogue_workspace_id, scope=body.scope)
    except installer.PackageProblem as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "package"})
    db.commit()
    return {**plan.as_dict(), "history": _history(db, workspace_id)}
