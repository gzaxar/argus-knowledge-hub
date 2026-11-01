"""Sites (docs/sites.md): which workspaces are sites, which facilities are at each, and changing that —
administrators. A change that stops places being shared with a facility ends its placements in them, after a
preview that names them."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Identity, PatIdentity, get_identity
from app.db import get_db
from app.models.asset import Asset
from app.models.workspace import Workspace
from app.services import sites

router = APIRouter(prefix="/v1/admin/sites", tags=["sites"])


def _admin(identity: Identity) -> None:
    if isinstance(identity, PatIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")


def _problem(e: Exception):
    raise HTTPException(status_code=422, detail={"error": str(e), "code": "site"})


@router.get("")
def list_sites(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Every site, its facilities, and how many of its places they see."""
    _admin(identity)
    out = []
    for ws in db.scalars(select(Workspace).where(Workspace.role == sites.ROLE).order_by(Workspace.id)):
        shared = db.scalar(select(func.count()).select_from(Asset).where(
            Asset.workspace_id == ws.id, Asset.site_shared.is_(True)))
        withheld = db.scalar(select(func.count()).select_from(Asset).where(
            Asset.workspace_id == ws.id, Asset.site_withheld.is_(True)))
        out.append({"id": ws.id, "name": ws.name, "facilities": sites.facilities(db, ws.id),
                    "shared_places": shared, "withheld": withheld})
    return out


class RoleIn(BaseModel):
    site: bool
    # with `site: false` on a site whose facilities have placements, they end: true once the preview was seen
    confirm: bool = False


@router.put("/{workspace_id}/role")
def set_role(workspace_id: str, body: RoleIn, identity: Identity = Depends(get_identity),
             db: Session = Depends(get_db)):
    """Make a workspace a site, or stop it being one (refused while facilities are at it)."""
    _admin(identity)
    try:
        ended = sites.set_role(db, workspace_id, body.site)
    except sites.SiteProblem as e:
        db.rollback()
        _problem(e)
    db.commit()
    return {"workspace_id": workspace_id, "role": db.get(Workspace, workspace_id).role, "ended": ended}


class SiteIn(BaseModel):
    site_id: Optional[str] = None
    # a facility leaving its site loses its placements on the site's places: true once the preview was seen
    confirm: bool = False


@router.put("/{workspace_id}/site")
def set_site(workspace_id: str, body: SiteIn, identity: Identity = Depends(get_identity),
             db: Session = Depends(get_db)):
    """Put a facility workspace at a site, move it, or take it from its site. Leaving a site ends the facility's
    placements on the site's places: without `confirm`, the answer is the preview of those, and nothing changes."""
    _admin(identity)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.site_id and ws.site_id != body.site_id and not body.confirm:
        affected = sites.affected_by_withdrawal(db, ws.site_id, list(db.scalars(
            select(Asset.uid).where(Asset.workspace_id == ws.site_id))), only_workspace=workspace_id)
        if affected:
            return {"workspace_id": workspace_id, "site_id": ws.site_id, "preview": True, "would_end": affected}
    try:
        ended = sites.set_site(db, workspace_id, body.site_id, actor=identity.user.id)
    except sites.SiteProblem as e:
        db.rollback()
        _problem(e)
    db.commit()
    return {"workspace_id": workspace_id, "site_id": body.site_id, "ended": ended}
