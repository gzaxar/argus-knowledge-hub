"""Quotas (services/quotas.py).

- `GET /v1/admin/quotas` — the defaults, the installation's own quota, and every workspace with what it uses
  (instance administrators);
- `PUT /v1/admin/quotas/defaults` `{values: {key: n|null}, reset: [key]}` — the installation-wide defaults
  (null: unlimited; reset: back to the built-in default);
- `PUT /v1/admin/quotas/workspaces/{id}` `{values, reset}` — a workspace's overrides (reset: follow the default);
- `GET /v1/workspaces/{id}/quotas` — a workspace's quotas and what it uses, for its administrators.

Changing a quota is an administrator's, signed in, and is audited.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity
from app.db import get_db
from app.models.workspace import Workspace
from app.routers.statistics import _admin, _person_admin
from app.services import quotas

router = APIRouter(prefix="/v1", tags=["quotas"])
log = logging.getLogger("argus.quotas")


def _definitions(db: Session) -> list[dict]:
    d = quotas.defaults(db)
    return [{"key": q.key, "label": q.label, "unit": q.unit, "what": q.what, "builtin": q.default,
             "default": d[q.key], "scope": "installation" if q in quotas.INSTALLATION else "workspace"}
            for q in quotas.QUOTAS + quotas.INSTALLATION]


@router.get("/admin/quotas")
def all_quotas(identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    workspaces = []
    for ws in db.scalars(select(Workspace).order_by(Workspace.name)):
        rows = quotas.status(db, ws.id)
        workspaces.append({"id": ws.id, "name": ws.name, "quotas": rows, "overrides": quotas.overrides(db, ws.id),
                           "level": "over" if any(r["level"] == "over" for r in rows)
                           else "warn" if any(r["level"] == "warn" for r in rows) else "ok"})
    from app.models.portability import PortabilityImport
    open_imports = list(db.scalars(select(PortabilityImport.id).where(
        PortabilityImport.state.notin_(("finalized", "discarded", "invalid")), PortabilityImport.purged_at.is_(None))))
    return {"quotas": _definitions(db), "workspaces": workspaces,
            "installation": {"imports_at_once": {"limit": quotas.defaults(db)["imports_at_once"],
                                                 "used": len(open_imports), "imports": open_imports}}}


class QuotaValues(BaseModel):
    values: dict[str, Optional[int]] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list)


def _audit(db: Session, identity, scope: str, body: QuotaValues) -> None:
    from app.models.portability import PortabilityEvent
    db.add(PortabilityEvent(subject_kind="quota", subject_id=scope, kind="set",
                            actor=identity.user.email or identity.user.id,
                            detail={"values": body.values, "reset": body.reset}))
    log.info("quotas of %s set by %s: %s, reset %s", scope, identity.user.id, body.values, body.reset)


@router.put("/admin/quotas/defaults")
def set_defaults(body: QuotaValues, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _person_admin(identity)
    try:
        quotas.set_defaults(db, body.values, tuple(body.reset))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _audit(db, identity, "defaults", body)
    db.commit()
    quotas.forget_cache()
    return {"quotas": _definitions(db)}


@router.put("/admin/quotas/workspaces/{workspace_id}")
def set_workspace(workspace_id: str, body: QuotaValues, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _person_admin(identity)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="No such workspace")
    try:
        quotas.set_workspace(db, workspace_id, body.values, tuple(body.reset))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _audit(db, identity, f"workspace:{workspace_id}", body)
    db.commit()
    quotas.forget_cache()
    return {"quotas": quotas.status(db, workspace_id), "overrides": quotas.overrides(db, workspace_id)}


@router.get("/workspaces/{workspace_id}/quotas")
def workspace_quotas(workspace_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    from app.routers.storage import _workspace_admin
    _workspace_admin(workspace_id, identity, db)
    return {"workspace_id": workspace_id, "quotas": quotas.status(db, workspace_id)}
