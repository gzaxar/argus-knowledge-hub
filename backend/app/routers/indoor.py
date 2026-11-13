"""Indoors: a place's floors and floor plans, placing a plan on the map, records placed inside, and the plans in
view on the map (services/indoor.py). Records are read and changed under the same rules as their locations.

- `GET/POST /v1/assets/{uid}/levels`, `PATCH/DELETE /v1/levels/{uid}` — a place's floors.
- `GET/POST /v1/assets/{uid}/plans`, `GET/PATCH/DELETE /v1/plans/{uid}`, `GET /v1/plans/{uid}/image`,
  `PUT/DELETE /v1/plans/{uid}/placement` — floor plans; placing one on the map by control points.
- `GET/PUT/DELETE /v1/assets/{uid}/indoors` — where a record is inside; `GET /v1/map/plans?bbox=` — the plans
  placed on the map in view, for a floor switcher.
- `GET/PUT /v1/assets/{uid}/site-sharing` — a site's place shared with its facilities or withheld (docs/sites.md).

A floor and a plan are seen where their place is seen — its own workspace, a global place, or a place the
workspace's site shares with it — and changed only by the workspace that holds them. What a plan, a place or a
record's containers show is filtered record by record: what the viewer could see of that record from where they
are, or in its own workspace if they may read it.
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
from app.services import indoor, sites, spatial
from app.services.visibility import reachable_in

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


def _level(db: Session, uid: str, workspace_id: str, grants=None, modify: bool = False) -> PlaceLevel:
    """A floor seen where its place is seen; changed only by the workspace that holds it."""
    level = db.get(PlaceLevel, uid)
    if level is None or (level.workspace_id != workspace_id and (modify or grants is None)):
        raise HTTPException(status_code=404, detail="Floor not found")
    if level.workspace_id != workspace_id:
        _place(db, level.place_uid, workspace_id, grants)
    return level


def _plan(db: Session, uid: str, workspace_id: str, grants, modify: bool = False) -> FloorPlan:
    """A plan seen where its place is seen (who may not see the place may not see its plan); changed only by the
    workspace that holds it."""
    plan = db.get(FloorPlan, uid)
    if plan is None or (modify and plan.workspace_id != workspace_id):
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        _place(db, plan.place_uid, workspace_id, grants)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Plan not found") from None
    return plan


def _viewer(db: Session, identity, workspace_id: str):
    """Whether the viewer may see a record placed somewhere they look (a plan, a place, a record's containers):
    reachable from their workspace (own, global, site-shared) with that workspace's grants, or — a person — in the
    record's own workspace, which they may read, with its grants. A token sees what its workspace can."""
    from app.auth import OidcIdentity, grants_of
    from app.services.permissions import resolve_permission
    grants: dict = {}
    readable: dict = {}

    def may(asset: Asset) -> bool:
        if workspace_id not in grants:
            grants[workspace_id] = grants_of(db, identity, workspace_id)
        if reachable_in(asset, workspace_id) and spatial.may_see(db, asset, grants[workspace_id]):
            return True
        home = asset.workspace_id
        if not isinstance(identity, OidcIdentity) or home == workspace_id:
            return False
        if home not in readable:
            readable[home] = resolve_permission(db, identity.user, home, "read", "objects")
        if not readable[home]:
            return False
        if home not in grants:
            grants[home] = grants_of(db, identity, home)
        return spatial.may_see(db, asset, grants[home])
    return may


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
    level = _level(db, uid, workspace_id, modify=True)
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
    level = _level(db, uid, workspace_id, modify=True)
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
    level = _level(db, level_uid, workspace_id, modify=True) if level_uid else None
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
    may = _viewer(db, identity, workspace_id)
    placed = []
    for asset, p in indoor.on_plan(db, plan.uid):
        if may(asset):
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
    plan = _plan(db, uid, workspace_id, grants, modify=True)
    if body.name is not None and body.name.strip():
        plan.name = body.name.strip()
    if "level_uid" in body.model_fields_set:
        if body.level_uid:
            level = _level(db, body.level_uid, workspace_id, modify=True)
            if level.place_uid != plan.place_uid:
                raise HTTPException(status_code=422, detail={"error": "that floor is another place's", "code": "indoors"})
        plan.level_uid = body.level_uid or None
    db.commit()
    return indoor.plan_out(db, plan)


@router.delete("/plans/{uid}", status_code=204)
def delete_plan(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                db: Session = Depends(get_db)):
    """The plan goes; what was placed on it keeps its place (and the position its point gave it)."""
    plan = _plan(db, uid, workspace_id, grants, modify=True)
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
    plan = _plan(db, uid, workspace_id, grants, modify=True)
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
    plan = _plan(db, uid, workspace_id, grants, modify=True)
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
    may = _viewer(db, identity, workspace_id)
    contents = [{"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "level_uid": p.level_uid,
                 "plan_uid": p.plan_uid} for a, p in indoor.placed_in(db, uid) if may(a)]
    return {"uid": uid, "placement": indoor.placement_out(db, now_) if now_ else None,
            # Where to show it on a plan: its own point, or the nearest place it is in that has one.
            "spot": indoor.spot(db, uid, may),
            "in": [{"uid": c.uid, "key": c.key, "name": c.name, "type": c.type}
                   for c in indoor.containers(db, uid) if may(c)],
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


@router.get("/floor-plan/show")
def show_on_plans(records: str = Query(..., description="comma-separated record uids or keys, the first one asked about"),
                  workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                  identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Records on their floor plans: each one's point, or that of the nearest place it is in that has one (its
    rack, its room); the plans they are on; and from the first to each other on the same plan, how far and which
    way. Only records and places this person may see."""
    may = _viewer(db, identity, workspace_id)
    uids = []
    for ref in [r.strip() for r in records.split(",") if r.strip()][:20]:
        a = db.get(Asset, ref) or db.scalar(select(Asset).where(Asset.key == ref))
        if a is not None:
            uids.append(a.uid)
    return indoor.show(db, uids, may)


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
    cache: dict = {}
    out = []
    # Every plan placed on the map whose place the person sees from these workspaces: theirs, global places',
    # and those their site shares with them.
    for plan in db.scalars(select(FloorPlan).join(Asset, Asset.uid == FloorPlan.place_uid)
                           .where(cond, FloorPlan.transform.is_not(None))):
        c = indoor.corners(plan)
        lons, lats = [p[0] for p in c], [p[1] for p in c]
        if max(lons) < west or min(lons) > east or max(lats) < south or min(lats) > north:
            continue
        place_rec = db.get(Asset, plan.place_uid)
        if place_rec is None or not _permitted(db, identity, place_rec, spaces, cache):
            continue
        out.append(indoor.plan_out(db, plan))
    return out


# --------------------------------------------------------------------------- a site's place, shared or withheld

class SharingIn(BaseModel):
    shared: bool
    # withholding ends facility placements: true once the preview (the answer without it) has been seen
    confirm: bool = False


def _sharing(db: Session, place: Asset) -> dict:
    inside = sites.inside(db, place.uid)
    blocked_by = None
    if not place.site_withheld and not place.site_shared:
        for c in indoor.containers(db, place.uid):
            if c.site_withheld:
                blocked_by = {"uid": c.uid, "key": c.key, "name": c.name}
                break
    return {"uid": place.uid, "site": place.workspace_id, "facilities": sites.facilities(db, place.workspace_id),
            "shared": place.site_shared, "withheld": place.site_withheld, "withheld_by": blocked_by,
            "inside": len(inside) - 1}


@router.get("/assets/{uid}/site-sharing")
def get_site_sharing(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                     db: Session = Depends(get_db)):
    """Whether a site's place is shared with the site's facilities, or withheld (itself, or by a place it is in)."""
    place = _place(db, uid, workspace_id, grants, modify=True)
    if not sites.is_site(db, place.workspace_id):
        raise HTTPException(status_code=422, detail={"error": "this workspace is not a site", "code": "site"})
    return _sharing(db, place)


@router.put("/assets/{uid}/site-sharing")
def set_site_sharing(uid: str, body: SharingIn, workspace_id: str = Depends(require_permission("modify")),
                     grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Withhold a site's place — and every place inside it, their floors and plans — from the site's facilities,
    or share it again. Withholding ends the facilities' placements there (their records keep the position a plan
    gave them; their history says why): without `confirm`, the answer is the preview of those, and nothing
    changes. Sharing again does not bring placements back."""
    place = _place(db, uid, workspace_id, grants, modify=True)
    if not sites.is_site(db, place.workspace_id):
        raise HTTPException(status_code=422, detail={"error": "this workspace is not a site", "code": "site"})
    if not body.shared and not body.confirm:
        places = [u for u in sites.inside(db, uid) if db.get(Asset, u).site_shared]
        return {**_sharing(db, place), "preview": True, "would_withhold": len(places),
                "would_end": sites.affected_by_withdrawal(db, place.workspace_id, places)}
    place.site_withheld = not body.shared
    ended = sites.refresh(db, place.workspace_id, actor=actor_of(identity),
                          reason=f"{place.name} is no longer shared with the facilities")
    db.commit()
    return {**_sharing(db, place), "ended": ended}
