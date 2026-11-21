"""Storage administration (services/storage.py, services/storage_cleanup.py).

- `GET /v1/admin/storage` — every area now, its trend and what is left (instance administrators);
- `GET|PUT /v1/admin/storage/settings` — each area's planned room (the default, the deployment's, or one set here);
- `GET /v1/workspaces/{id}/storage` — one workspace's share: its attachment files and the bundles exported of it
  (the workspace's administrators);
- `DELETE /v1/workspaces/{id}/storage/bundles/{bundle_id}` — remove a bundle exported of it (instance administrators,
  signed in).

The cleanups of the portability area stay at `/v1/admin/statistics/storage/cleanup`.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_identity
from app.db import get_db
from app.models.workspace import Workspace
from app.routers.statistics import _admin, _person_admin
from app.services import storage

router = APIRouter(prefix="/v1", tags=["storage"])


@router.get("/admin/storage")
def storage_report(days: int = Query(30, ge=1, le=366), refresh: bool = False, identity=Depends(get_identity),
                   db: Session = Depends(get_db)):
    _admin(identity)
    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    return {**storage.report(db, start, refresh=refresh), "planned": storage.planned_view(db)}


@router.get("/admin/storage/settings")
def storage_settings(identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    return {"planned": storage.planned_view(db)}


class PlannedIn(BaseModel):
    # area -> bytes, or null to go back to the deployment's (or the default)
    planned: dict[str, Optional[int]]


@router.put("/admin/storage/settings")
def set_storage_settings(body: PlannedIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _person_admin(identity)
    try:
        view = storage.set_planned(db, body.planned)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        storage.snapshot(db)                 # today's measurement against the new room
    except Exception:  # noqa: BLE001 — the setting stands; the next hourly measurement takes it
        pass
    db.commit()
    return {"planned": view}


def _workspace_admin(workspace_id: str, identity, db: Session) -> None:
    from app.routers.workspaces import _require_owner_or_admin
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="No such workspace")
    _require_owner_or_admin(workspace_id, identity, db)


@router.get("/workspaces/{workspace_id}/storage")
def workspace_storage(workspace_id: str, days: int = Query(30, ge=1, le=366), identity=Depends(get_identity),
                      db: Session = Depends(get_db)):
    _workspace_admin(workspace_id, identity, db)
    return storage.workspace_report(db, workspace_id, days)


@router.delete("/workspaces/{workspace_id}/storage/bundles/{bundle_id}")
def remove_workspace_bundle(workspace_id: str, bundle_id: str, identity=Depends(get_identity),
                            db: Session = Depends(get_db)):
    _person_admin(identity)
    if not re.fullmatch(r"[0-9a-f-]{36}", bundle_id):
        raise HTTPException(status_code=404, detail="No such bundle")
    if bundle_id not in {b["id"] for b in storage.workspace_bundles(workspace_id)}:
        raise HTTPException(status_code=404, detail="No such bundle of this workspace")
    from app.models.portability import PortabilityEvent
    from app.routers.bundles import store
    target = store() / "exports" / bundle_id
    freed = storage.dir_usage(str(target))[0]
    shutil.rmtree(target, ignore_errors=True)
    db.add(PortabilityEvent(subject_kind="bundle-export", subject_id=bundle_id, kind="delete",
                            actor=identity.user.email or identity.user.id,
                            detail={"workspace": workspace_id, "freed_bytes": freed}))
    db.commit()
    return {"removed": bundle_id, "freed": freed}
