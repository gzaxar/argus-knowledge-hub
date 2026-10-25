"""Migrations of records to a package type, for instance administrators (app/services/type_migration.py).

- `GET  /v1/admin/type-migrations` — the plans; `GET …/{id}` one, with its log; `GET …/{id}/items` its records.
- `GET  /v1/admin/type-migrations/sources?kind=` — types records can come from, with records by owning workspace.
- `GET  /v1/admin/type-migrations/targets?kind=` — package types, and `…/targets/resolve` where each is installed.
- `POST /v1/admin/type-migrations/install-preview` — what installing the target's package would do where needed.
- `POST /v1/admin/type-migrations` — a plan (source, target, workspaces, reason) with a proposed mapping.
- `PATCH …/{id}` — decisions: field actions and value maps, defaults, states, records left out, workspaces.
- `POST …/{id}/preview` (writes nothing), `…/apply` (needs the preview's token), `…/verify`, `…/revert`.
- `POST /v1/admin/type-proposals` — a custom type written as package YAML for review; nothing is installed.

Only an authenticated instance administrator may create, preview, apply, verify or revert; the API checks it.
Records are judged with the administrator's grants in each record's own workspace.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity, grants_of
from app.db import get_db
from app.models.type_migration import TypeMigration, TypeMigrationItem
from app.services import type_migration as tm
from app.services import type_proposal

router = APIRouter(prefix="/v1/admin", tags=["type migrations"])


def require_admin(identity=Depends(get_identity)) -> OidcIdentity:
    if not isinstance(identity, OidcIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Type migrations are for instance administrators")
    return identity


def _actor(identity: OidcIdentity) -> str:
    return identity.user.email or identity.user.id


def _get(db: Session, mid: str) -> TypeMigration:
    m = db.get(TypeMigration, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="No such migration")
    return m


def _grants(db: Session, identity):
    cache: dict = {}

    def of(ws: str):
        if ws not in cache:
            cache[ws] = grants_of(db, identity, ws)
        return cache[ws]
    return of


def _problem(e: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(e))


@router.get("/type-migrations")
def list_migrations(identity=Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(TypeMigration).order_by(TypeMigration.created_at.desc()))
    return [tm.view(m, with_log=False) for m in rows]


@router.get("/type-migrations/sources")
def list_sources(kind: str = "objects", identity=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return tm.sources(db, kind)
    except tm.MigrationError as e:
        raise _problem(e)


@router.get("/type-migrations/targets")
def list_targets(kind: str = "objects", identity=Depends(require_admin)):
    return [t for t in tm.shipped_types(kind) if not t["abstract"]]


@router.get("/type-migrations/targets/resolve")
def resolve_targets(kind: str, package_id: str, type: str, workspaces: str, home: str = "installed",
                    identity=Depends(require_admin), db: Session = Depends(get_db)):
    """Where the package type is (or is not) available for records of these workspaces: per workspace, the
    workspace or shared catalogue that holds it, the installed version, and what is missing."""
    declared = {(t["package_id"], t["type"]): t for t in tm.shipped_types(kind)}
    t = declared.get((package_id, type))
    if t is None:
        raise HTTPException(status_code=404, detail="Not a type of a shipped package")
    target = {"package_id": package_id, "type": type, "version": t["version"], "home": home}
    out = []
    for ws in [w for w in workspaces.split(",") if w]:
        r = tm.resolve_target(db, ws, kind, target)
        if home == "own" and r["status"] != "ok":
            st = tm.bring_home_status(db, ws, kind, target)
            if st["status"] == "will_create":
                r = {**r, "status": "will_create", "detail": st["detail"], "copy_of": st["copy_of"]}
        out.append(r)
    return out


class InstallPreviewIn(BaseModel):
    workspace_id: str
    package_id: str


@router.post("/type-migrations/install-preview")
def install_preview(body: InstallPreviewIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """What installing or upgrading the package would do in the workspace (or catalogue) that needs it —
    applied and rolled back. Installing is done on that workspace's Packages page."""
    return tm.install_preview(db, body.workspace_id, body.package_id)


class CreateIn(BaseModel):
    kind: str = "objects"
    source_schema_uid: str
    target: dict
    workspaces: Optional[list[str]] = None
    include_descendants: bool = False
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/type-migrations", status_code=201)
def create_migration(body: CreateIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        m = tm.create(db, _actor(identity), body.kind, body.source_schema_uid, body.target, body.workspaces,
                      body.include_descendants, body.reason)
    except tm.MigrationError as e:
        db.rollback()
        raise _problem(e)
    return tm.view(m)


@router.get("/type-migrations/{mid}")
def get_migration(mid: str, identity=Depends(require_admin), db: Session = Depends(get_db)):
    return tm.view(_get(db, mid))


@router.get("/type-migrations/{mid}/fields")
def migration_fields(mid: str, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """The fields and states the mapping step offers, for this plan."""
    out = tm.fields(db, _get(db, mid))
    db.rollback()                      # a copy a plan would bring home is shown, not kept
    return out


@router.patch("/type-migrations/{mid}")
def change_migration(mid: str, body: dict, identity=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return tm.view(tm.change(db, _get(db, mid), _actor(identity), body))
    except tm.MigrationError as e:
        db.rollback()
        raise _problem(e)


@router.post("/type-migrations/{mid}/preview")
def preview_migration(mid: str, identity=Depends(require_admin), db: Session = Depends(get_db)):
    m = _get(db, mid)
    out = tm.preview(db, m, _grants(db, identity))
    db.rollback()                      # a preview writes nothing
    return out


class ApplyIn(BaseModel):
    token: str
    batch_size: int = Field(default=tm.BATCH, ge=1, le=1000)


@router.post("/type-migrations/{mid}/apply")
def apply_migration(mid: str, body: ApplyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return tm.apply(db, _get(db, mid), body.token, _actor(identity), _grants(db, identity), body.batch_size)
    except tm.MigrationError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))


class VerifyIn(BaseModel):
    deprecate: bool = False


@router.post("/type-migrations/{mid}/verify")
def verify_migration(mid: str, body: VerifyIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return tm.verify(db, _get(db, mid), _actor(identity), body.deprecate)
    except tm.MigrationError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))


class RevertIn(BaseModel):
    uids: Optional[list[str]] = None


@router.post("/type-migrations/{mid}/revert")
def revert_migration(mid: str, body: RevertIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    return tm.revert(db, _get(db, mid), _actor(identity), body.uids)


@router.get("/type-migrations/{mid}/items")
def migration_items(mid: str, status: Optional[str] = None, identity=Depends(require_admin),
                    db: Session = Depends(get_db)):
    q = select(TypeMigrationItem).where(TypeMigrationItem.migration_id == _get(db, mid).id)
    if status:
        q = q.where(TypeMigrationItem.status == status)
    return [{"record_uid": i.record_uid, "workspace_id": i.workspace_id, "status": i.status, "batch": i.batch,
             "error": i.error, "before": i.before, "after": i.after, "provenance": i.provenance, "actor": i.actor,
             "at": i.at} for i in db.scalars(q.order_by(TypeMigrationItem.id))]


class ProposalIn(BaseModel):
    schema_uid: str
    package_id: str
    name: Optional[str] = None


@router.post("/type-proposals")
def type_proposal_endpoint(body: ProposalIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """A custom type written as a package's YAML entry, checked, for code review and a release. Nothing in
    this installation is changed."""
    try:
        return type_proposal.propose(db, body.schema_uid, body.package_id, body.name)
    except ValueError as e:
        raise _problem(e)
