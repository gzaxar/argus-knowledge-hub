"""Rack elevations (docs/rack-elevation.md): what is mounted in a rack, a preview of a change, the change, its past."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_grants, get_identity, require_permission
from app.db import get_db
from app.models.asset import Asset
from app.routers.ledger import actor_of
from app.services import racks
from app.services.visibility import asset_visible_in

router = APIRouter(prefix="/v1/racks", tags=["racks"])


class RackOp(BaseModel):
    op: str = Field(description="place | shelf | reserve | update | remove")
    asset_uid: Optional[str] = None
    mounting_uid: Optional[str] = None
    kind: Optional[str] = Field(None, description="for place: device (default) or zero_u")
    start_u: Optional[int] = Field(None, description="the lowest unit taken, counted from the bottom")
    height_u: Optional[int] = Field(None, description="units taken; the product model's height when left out")
    face: Optional[str] = Field(None, description="front (default), rear or both")
    shelf_uid: Optional[str] = Field(None, description="the shelf mounting the unit stands on")
    ref: Optional[str] = Field(None, description="a name for the mounting this operation makes, for a later one "
                                                   "in the same change to stand on (shelf_uid)")
    label: Optional[str] = None
    note: Optional[str] = None
    source: Optional[str] = Field(None, description="manual (default), field or import")
    evidence: Optional[dict[str, Any]] = Field(None, description="what a photograph showed: attachment, quote, confidence")


class RackChange(BaseModel):
    operations: list[RackOp]


def _rack(db: Session, uid: str, workspace_id: str, grants) -> Asset:
    try:
        rack = racks.rack_of(db, uid)
    except racks.RackError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not asset_visible_in(rack, workspace_id, grants):
        raise HTTPException(status_code=404, detail="no such rack")
    return rack


def _ops(body: RackChange) -> list[dict]:
    return [op.model_dump(exclude_unset=True) for op in body.operations]


@router.get("/candidates")
def rack_candidates(q: str = Query(..., min_length=1), workspace_id: str = Depends(require_permission("read")),
                    db: Session = Depends(get_db)):
    """Records that could be mounted: where each is now, and the height its model suggests."""
    return racks.candidates(db, workspace_id, q)


@router.get("/of/{asset_uid}")
def rack_of_asset(asset_uid: str, workspace_id: str = Depends(require_permission("read")),
                  grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Where a unit is mounted now: its rack, unit, height and face; null when it is in no rack."""
    m = racks.mounting_of(db, asset_uid)
    if m is None:
        return None
    rack = db.get(Asset, m.rack_uid)
    if rack is None or not asset_visible_in(rack, workspace_id, grants):
        return None
    return {"mounting_uid": m.uid, "rack": {"uid": rack.uid, "key": rack.key, "name": rack.name},
            "kind": m.kind, "start_u": m.start_u, "height_u": m.height_u, "face": m.face, "shelf_uid": m.shelf_uid}


@router.get("/{uid}")
def rack_elevation(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                   db: Session = Depends(get_db)):
    return racks.elevation(db, _rack(db, uid, workspace_id, grants))


@router.get("/{uid}/history")
def rack_history(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                 db: Session = Depends(get_db)):
    """Every mounting the rack has had, newest first: what stood where, from when until when, and who said so."""
    rack = _rack(db, uid, workspace_id, grants)
    return racks.history(db, rack.uid)


@router.post("/{uid}/preview")
def rack_preview(uid: str, body: RackChange, workspace_id: str = Depends(require_permission("read")),
                 grants=Depends(get_grants), db: Session = Depends(get_db)):
    """What the operations would do: the changes in words, what is wrong, and the rack as it would be. Writes nothing."""
    return racks.plan(db, _rack(db, uid, workspace_id, grants), _ops(body))


@router.post("/{uid}/apply")
def rack_apply(uid: str, body: RackChange, identity=Depends(get_identity),
               workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
               db: Session = Depends(get_db)):
    """The operations, all or none: refused (409, with what is wrong) when a unit would not fit or two would overlap."""
    rack = _rack(db, uid, workspace_id, grants)
    if rack.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="a rack is changed from its own workspace")
    actor = actor_of(identity)
    try:
        result = racks.apply(db, rack, _ops(body), actor)
    except racks.RackError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "operation"})
    if not result["ok"]:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": "the rack would not be consistent",
                                                     "problems": result["problems"]})
    result["notes"] = racks.follow_location(db, rack, result["changes"], actor)
    db.commit()
    result["elevation"] = racks.elevation(db, rack)
    return result
