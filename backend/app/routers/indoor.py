"""Indoors: a place's floors and floor plans, placing a plan on the map, records placed inside, and the plans in
view on the map (services/indoor.py). Records are read and changed under the same rules as their locations.

- `GET/POST /v1/assets/{uid}/levels`, `PATCH/DELETE /v1/levels/{uid}` — a place's floors.
- `GET/POST /v1/assets/{uid}/plans`, `GET/PATCH/DELETE /v1/plans/{uid}`, `GET /v1/plans/{uid}/image`,
  `PUT/DELETE /v1/plans/{uid}/placement` — floor plans; placing one on the map by control points.
- `GET/PUT/DELETE /v1/assets/{uid}/indoors` — where a record is inside; `GET /v1/map/plans?bbox=` — the plans
  placed on the map in view, for a floor switcher.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_grants, get_identity, require_permission
from app.db import get_db
from app.models.asset import Asset
from app.models.indoor import FloorPlan, PlaceLevel
from app.routers.ledger import actor_of
from app.routers.spatial import _permitted, _readable_asset, _scope, _workspaces
from app.services import indoor, spatial

router = APIRouter(prefix="/v1", tags=["indoors"])


def _bad(e: Exception):
    raise HTTPException(status_code=422, detail={"error": str(e), "code": "indoors"})


def _hidden(db: Session, asset: Asset, grants) -> bool:
    return spatial.location_hidden(db, asset, grants)


def _place(db: Session, uid: str, workspace_id: str, grants, modify: bool = False) -> Asset:
    asset = _readable_asset(db, uid, workspace_id, grants)
    if _hidden(db, asset, grants):
        raise HTTPException(status_code=404, detail="Asset not found")
    if modify and asset.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Not permitted")
    return asset


def _level(db: Session, uid: str, workspace_id: str) -> PlaceLevel:
    level = db.get(PlaceLevel, uid)
    if level is None or level.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Floor not found")
    return level


def _plan(db: Session, uid: str, workspace_id: str, grants) -> FloorPlan:
    plan = db.get(FloorPlan, uid)
    if plan is None or plan.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    _place(db, plan.place_uid, workspace_id, grants)          # who may not see the place may not see its plan
    return plan


# --------------------------------------------------------------------------- floors

class LevelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ordinal: int = 0
    elevation_m: Optional[float] = None
    height_m: Optional[float] = None


@router.get("/assets/{uid}/levels")
def list_levels(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                db: Session = Depends(get_db)):
    """A place's floors, lowest first, and the plans of each (and those of the place as a whole)."""
    place = _place(db, uid, workspace_id, grants)
    plans = list(db.scalars(select(FloorPlan).where(FloorPlan.place_uid == place.uid).order_by(FloorPlan.created_at)))
    return {"levels": [indoor.level_out(level) for level in indoor.levels(db, place.uid)],
            "plans": [indoor.plan_out(db, p) for p in plans]}


@router.post("/assets/{uid}/levels", status_code=201)
def add_level(uid: str, body: LevelIn, workspace_id: str = Depends(require_permission("modify")),
              grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    place = _place(db, uid, workspace_id, grants, modify=True)
    try:
        level = indoor.save_level(db, place, actor=actor_of(identity), **body.model_dump())
    except indoor.IndoorError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return indoor.level_out(level)


@router.patch("/levels/{uid}")
def change_level(uid: str, body: LevelIn, workspace_id: str = Depends(require_permission("modify")),
                 grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    level = _level(db, uid, workspace_id)
    place = _place(db, level.place_uid, workspace_id, grants, modify=True)
    try:
        indoor.save_level(db, place, actor=actor_of(identity), level=level, **body.model_dump())
    except indoor.IndoorError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return indoor.level_out(level)


@router.delete("/levels/{uid}", status_code=204)
def delete_level(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                 db: Session = Depends(get_db)):
    """A floor goes; its plans stay with the place, and what was placed on it keeps its place and its point."""
    level = _level(db, uid, workspace_id)
    _place(db, level.place_uid, workspace_id, grants, modify=True)
    db.delete(level)
    db.commit()


# --------------------------------------------------------------------------- plans

@router.post("/assets/{uid}/plans", status_code=201)
async def add_plan(uid: str, file: UploadFile = File(...), name: str = Form(""), level_uid: str = Form(""),
                   workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                   identity=Depends(get_identity), db: Session = Depends(get_db)):
    """A floor plan of the place (or of one of its floors): an image, an SVG, a PDF (its first page) or a DXF
    or DWG drawing."""
    place = _place(db, uid, workspace_id, grants, modify=True)
    level = _level(db, level_uid, workspace_id) if level_uid else None
    if level is not None and level.place_uid != place.uid:
        raise HTTPException(status_code=422, detail={"error": "that floor is another place's", "code": "indoors"})
    content = await file.read()
    try:
        plan = indoor.add_plan(db, place, file.filename or "plan", content, name=name or None, level=level,
                               actor=actor_of(identity))
    except indoor.IndoorError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return indoor.plan_out(db, plan)


@router.get("/plans/{uid}")
def get_plan(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
             identity=Depends(get_identity), db: Session = Depends(get_db)):
    """A plan, and the records placed on it that the person may see (their point on it)."""
    plan = _plan(db, uid, workspace_id, grants)
    spaces = [workspace_id]
    cache: dict = {}
    placed = []
    for asset, p in indoor.on_plan(db, plan.uid):
        if _permitted(db, identity, asset, spaces, cache):
            placed.append({"uid": asset.uid, "key": asset.key, "name": asset.name, "type": asset.type,
                           "x": p.plan_x, "y": p.plan_y, "place_uid": p.place_uid})
    return {**indoor.plan_out(db, plan), "placed": placed}


@router.get("/plans/{uid}/image")
def plan_image(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
               db: Session = Depends(get_db)):
    plan = _plan(db, uid, workspace_id, grants)
    return FileResponse(plan.storage_path, media_type=plan.mime_type,
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                 "Cache-Control": "private, max-age=3600"})


class PlanChange(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    level_uid: Optional[str] = None


@router.patch("/plans/{uid}")
def change_plan(uid: str, body: PlanChange, workspace_id: str = Depends(require_permission("modify")),
                grants=Depends(get_grants), db: Session = Depends(get_db)):
    plan = _plan(db, uid, workspace_id, grants)
    if body.name is not None and body.name.strip():
        plan.name = body.name.strip()
    if "level_uid" in body.model_fields_set:
        if body.level_uid:
            level = _level(db, body.level_uid, workspace_id)
            if level.place_uid != plan.place_uid:
                raise HTTPException(status_code=422, detail={"error": "that floor is another place's", "code": "indoors"})
        plan.level_uid = body.level_uid or None
    db.commit()
    return indoor.plan_out(db, plan)


@router.delete("/plans/{uid}", status_code=204)
def delete_plan(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                db: Session = Depends(get_db)):
    """The plan goes; what was placed on it keeps its place (and the position its point gave it)."""
    plan = _plan(db, uid, workspace_id, grants)
    db.delete(plan)
    db.commit()


class ControlPoint(BaseModel):
    x: float
    y: float
    longitude: float
    latitude: float


class PlacementIn(BaseModel):
    points: list[ControlPoint] = Field(min_length=2, max_length=50)


@router.put("/plans/{uid}/placement")
def place_plan(uid: str, body: PlacementIn, workspace_id: str = Depends(require_permission("modify")),
               grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Place the plan on the map by control points (a pixel of the plan and the longitude and latitude it is
    at): two keep its shape, three or more fit it by least squares and say each point's residual in metres."""
    plan = _plan(db, uid, workspace_id, grants)
    try:
        result = indoor.georeference(db, plan, [p.model_dump() for p in body.points])
    except indoor.IndoorError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return {**indoor.plan_out(db, plan), **result}


@router.delete("/plans/{uid}/placement", status_code=204)
def unplace_plan(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                 db: Session = Depends(get_db)):
    plan = _plan(db, uid, workspace_id, grants)
    indoor.unplace(db, plan)
    db.commit()


# --------------------------------------------------------------------------- records placed inside

class IndoorIn(BaseModel):
    place_uid: Optional[str] = None
    level_uid: Optional[str] = None
    plan_uid: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/assets/{uid}/indoors")
def get_indoors(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Where the record is inside (its place, floor and point on a plan), the places that place is in, its
    history, and — for a place — what is placed in it."""
    _place(db, uid, workspace_id, grants)
    now_ = indoor.current(db, uid)
    spaces = [workspace_id]
    cache: dict = {}
    contents = [{"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "level_uid": p.level_uid,
                 "plan_uid": p.plan_uid} for a, p in indoor.placed_in(db, uid) if _permitted(db, identity, a, spaces, cache)]
    return {"uid": uid, "placement": indoor.placement_out(db, now_) if now_ else None,
            "in": [{"uid": c.uid, "key": c.key, "name": c.name, "type": c.type}
                   for c in indoor.containers(db, uid) if _permitted(db, identity, c, spaces, cache)],
            "contents": contents,
            "history": [indoor.placement_out(db, p) for p in indoor.history(db, uid)]}


@router.put("/assets/{uid}/indoors")
def set_indoors(uid: str, body: IndoorIn, workspace_id: str = Depends(require_permission("modify")),
                grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Place the record inside: in a place (a room, a hall), on a floor, at a point of a plan. A point on a plan
    placed on the map gives it its position too."""
    asset = _place(db, uid, workspace_id, grants, modify=True)
    if body.place_uid:
        _place(db, body.place_uid, workspace_id, grants)
    if body.plan_uid:
        _plan(db, body.plan_uid, workspace_id, grants)
    try:
        placed = indoor.place(db, asset, place_uid=body.place_uid, level_uid=body.level_uid, plan_uid=body.plan_uid,
                              x=body.x, y=body.y, actor=actor_of(identity), note=body.note)
    except indoor.IndoorError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return indoor.placement_out(db, placed)


@router.delete("/assets/{uid}/indoors", status_code=204)
def remove_indoors(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                   identity=Depends(get_identity), db: Session = Depends(get_db)):
    asset = _place(db, uid, workspace_id, grants, modify=True)
    indoor.remove(db, asset, actor_of(identity))
    db.commit()


# --------------------------------------------------------------------------- the map

@router.get("/map/plans")
def map_plans(bbox: str = Query(..., description="west,south,east,north in WGS 84 degrees"),
              workspaces: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
              identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The plans placed on the map whose corners reach into the box, with their floor, for a floor switcher."""
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "bbox is west,south,east,north", "code": "indoors"})
    spaces = _workspaces(db, identity, workspaces, workspace_id)
    cond = _scope(db, identity, spaces, None, None)
    visible = set(db.scalars(select(Asset.uid).where(cond)))
    cache: dict = {}
    out = []
    for plan in db.scalars(select(FloorPlan).where(FloorPlan.workspace_id.in_(spaces), FloorPlan.transform.is_not(None))):
        c = indoor.corners(plan)
        lons, lats = [p[0] for p in c], [p[1] for p in c]
        if max(lons) < west or min(lons) > east or max(lats) < south or min(lats) > north:
            continue
        place_rec = db.get(Asset, plan.place_uid)
        if place_rec is None or place_rec.uid not in visible or not _permitted(db, identity, place_rec, spaces, cache):
            continue
        out.append(indoor.plan_out(db, plan))
    return out
