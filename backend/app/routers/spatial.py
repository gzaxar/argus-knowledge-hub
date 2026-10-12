"""Locations: a record's approved location and its history, field observations and their review, and the
map — the records in an area or near a point — under the same rules as lists and search (services/spatial)."""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_grants, get_identity, grants_of, require_permission
from app.db import get_db
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.spatial import LocationObservation
from app.models.workspace import Workspace
from app.routers.ledger import actor_of
from app.services import spatial
from app.services.permissions import resolve_permission
from app.services.visibility import asset_visible_in, visible_assets_clause

router = APIRouter(prefix="/v1", tags=["locations"])


class PointIn(BaseModel):
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    crs: Optional[str] = None              # WGS 84 only in this release
    note: Optional[str] = None


class ObservationIn(PointIn):
    observed_at: Optional[str] = None
    device_id: Optional[str] = None


class DecisionIn(BaseModel):
    note: Optional[str] = None


def _bad(e: spatial.SpatialError):
    raise HTTPException(status_code=422, detail={"error": str(e), "code": "location"})


def _readable_asset(db: Session, uid: str, workspace_id: str, grants) -> Asset:
    asset = db.get(Asset, uid)
    if asset is None or asset.deleted_at is not None or not asset_visible_in(asset, workspace_id, grants):
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _when(value: Optional[str]):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": f"not a time: {value!r}", "code": "location"}) from None


# --------------------------------------------------------------------------- one record

@router.get("/assets/{uid}/location")
def get_location(uid: str, workspace_id: str = Depends(require_permission("read")), grants=Depends(get_grants),
                 db: Session = Depends(get_db)):
    """The record's approved location (or none), whether its type may have one and on which map layer, the
    history of its approved locations, and the field observations of it."""
    asset = _readable_asset(db, uid, workspace_id, grants)
    locatable, layer = spatial.placement(db, asset.schema_uid)
    if spatial.location_hidden(db, asset, grants):
        return {"uid": uid, "locatable": locatable, "map_layer": layer, "hidden": True, "location": None,
                "history": [], "observations": []}
    approved = spatial.current(db, uid)
    return {"uid": uid, "locatable": locatable, "map_layer": layer, "hidden": False,
            "location": spatial.feature_out(approved) if approved else None,
            "history": [spatial.feature_out(f) for f in spatial.history(db, uid)],
            "observations": [spatial.observation_out(o) for o in db.scalars(
                select(LocationObservation).where(LocationObservation.subject_uid == uid)
                .order_by(LocationObservation.id.desc()).limit(50))]}


@router.put("/assets/{uid}/location")
def set_location(uid: str, body: PointIn, workspace_id: str = Depends(require_permission("modify")),
                 grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Approve a location for the record (WGS 84 latitude and longitude, with its accuracy). The one it had is
    kept in the history."""
    asset = _readable_asset(db, uid, workspace_id, grants)
    if asset.workspace_id != workspace_id or spatial.location_hidden(db, asset, grants):
        raise HTTPException(status_code=403, detail="Not permitted")
    try:
        geometry = spatial.point(body.latitude, body.longitude, crs=body.crs, accuracy_m=body.accuracy_m)
        feature = spatial.set_location(db, asset, geometry, actor=actor_of(identity), source="manual",
                                       accuracy_m=body.accuracy_m, note=body.note)
    except spatial.SpatialError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return spatial.feature_out(feature)


@router.delete("/assets/{uid}/location", status_code=204)
def remove_location(uid: str, workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                    identity=Depends(get_identity), db: Session = Depends(get_db)):
    asset = _readable_asset(db, uid, workspace_id, grants)
    if asset.workspace_id != workspace_id or spatial.location_hidden(db, asset, grants):
        raise HTTPException(status_code=403, detail="Not permitted")
    spatial.remove_location(db, asset, actor_of(identity))
    db.commit()


@router.post("/assets/{uid}/location/observations", status_code=201)
def observe(uid: str, body: ObservationIn, workspace_id: str = Depends(require_permission("read")),
            grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Where someone saw the record (a phone's GPS fix and its accuracy). It never moves the record: it
    agrees with the approved location, or it waits for a person to review it."""
    asset = _readable_asset(db, uid, workspace_id, grants)
    if spatial.location_hidden(db, asset, grants):
        raise HTTPException(status_code=404, detail="Asset not found")
    try:
        geometry = spatial.point(body.latitude, body.longitude, crs=body.crs, accuracy_m=body.accuracy_m)
        obs = spatial.observe(db, asset, geometry, accuracy_m=body.accuracy_m, actor=actor_of(identity),
                              observed_at=_when(body.observed_at), device_id=body.device_id)
    except spatial.SpatialError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return spatial.observation_out(obs)


# --------------------------------------------------------------------------- review

@router.get("/location-reviews")
def location_reviews(status: str = Query("pending"), workspace_id: str = Depends(require_permission("read")),
                     grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Field observations of this workspace's records waiting for a decision (or decided: status=…)."""
    out = []
    for o in db.scalars(select(LocationObservation).where(LocationObservation.workspace_id == workspace_id,
                                                          LocationObservation.status == status)
                        .order_by(LocationObservation.id.desc()).limit(200)):
        asset = db.get(Asset, o.subject_uid)
        if not spatial.may_see(db, asset, grants):
            continue
        approved = spatial.current(db, o.subject_uid)
        out.append({**spatial.observation_out(o), "record": {"uid": asset.uid, "key": asset.key, "name": asset.name,
                                                              "type": asset.type},
                    "approved": spatial.feature_out(approved) if approved else None})
    return out


def _decide(obs_id: int, accept: bool, body: DecisionIn, workspace_id: str, grants, identity, db: Session):
    obs = db.get(LocationObservation, obs_id)
    if obs is None or obs.workspace_id != workspace_id or not spatial.may_see(db, db.get(Asset, obs.subject_uid), grants):
        raise HTTPException(status_code=404, detail="Observation not found")
    try:
        spatial.decide(db, obs, accept, actor_of(identity), body.note)
    except spatial.SpatialError as e:
        db.rollback()
        _bad(e)
    db.commit()
    return spatial.observation_out(obs)


@router.post("/location-reviews/{obs_id}/accept")
def accept_observation(obs_id: int, body: DecisionIn, workspace_id: str = Depends(require_permission("modify")),
                       grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Accept an observation: it becomes the record's approved location (the previous one kept in history)."""
    return _decide(obs_id, True, body, workspace_id, grants, identity, db)


@router.post("/location-reviews/{obs_id}/reject")
def reject_observation(obs_id: int, body: DecisionIn, workspace_id: str = Depends(require_permission("modify")),
                       grants=Depends(get_grants), identity=Depends(get_identity), db: Session = Depends(get_db)):
    return _decide(obs_id, False, body, workspace_id, grants, identity, db)


# --------------------------------------------------------------------------- the map

def _workspaces(db: Session, identity, requested: Optional[str], current: str) -> list[str]:
    if not requested:
        return [current]
    wanted = [w.strip() for w in requested.split(",") if w.strip()]
    if not isinstance(identity, OidcIdentity):
        return [w for w in wanted if w == current]
    return [w for w in wanted if db.get(Workspace, w) is not None and
            resolve_permission(db, identity.user, w, "read", "objects")]


def _type_filter(db: Session, types: Optional[str]):
    """Records of these types (names or uids) and every type under them."""
    if not types:
        return None
    wanted = {t.strip() for t in types.split(",") if t.strip()}
    rows = list(db.scalars(select(Schema).where(Schema.applies_to == "objects")))
    roots = {s.uid for s in rows if s.uid in wanted or s.name in wanted}
    children: dict = {}
    for s in rows:
        children.setdefault(s.parent_schema_uid, []).append(s.uid)
    out, todo = set(), list(roots)
    while todo:
        uid = todo.pop()
        if uid not in out:
            out.add(uid)
            todo.extend(children.get(uid, []))
    return Asset.schema_uid.in_(out)


def _scope(db: Session, identity, workspaces: list[str], types: Optional[str], status: Optional[str]):
    clauses = [visible_assets_clause(w, grants_of(db, identity, w)) for w in workspaces]
    cond = or_(*clauses) if clauses else Asset.uid.is_(None)
    cond = cond & Asset.deleted_at.is_(None)
    tf = _type_filter(db, types)
    if tf is not None:
        cond = cond & tf
    if status:
        cond = cond & Asset.record_status.in_([s.strip() for s in status.split(",") if s.strip()])
    return cond


def _feature(db: Session, asset: Asset, f, layers: dict, distance: Optional[float] = None) -> dict:
    if asset.schema_uid not in layers:
        layers[asset.schema_uid] = spatial.placement(db, asset.schema_uid)[1]
    props = {"uid": asset.uid, "key": asset.key, "name": asset.name, "type": asset.type,
             "workspace_id": asset.workspace_id, "status": asset.record_status, "map_layer": layers[asset.schema_uid],
             "accuracy_m": f.accuracy_m, "source": f.source, "confirmed_at": f.confirmed_at}
    if distance is not None:
        props["distance_m"] = round(distance, 1)
    return {"type": "Feature", "id": asset.uid, "geometry": spatial.geojson(f.geometry), "properties": props}


def _permitted(db: Session, identity, asset: Asset, workspaces: list[str], cache: dict) -> bool:
    home = asset.workspace_id if asset.workspace_id in workspaces else workspaces[0]
    if home not in cache:
        cache[home] = grants_of(db, identity, home)
    return spatial.may_see(db, asset, cache[home])


@router.get("/map/features")
def map_features(bbox: str = Query(..., description="west,south,east,north in WGS 84 degrees"),
                 workspaces: Optional[str] = Query(None, description="comma-separated; the current one if left out"),
                 types: Optional[str] = Query(None, description="type names or uids; their subtypes included"),
                 status: Optional[str] = Query(None, description="record status, e.g. Active,Provisional"),
                 workspace_id: str = Depends(require_permission("read")), identity=Depends(get_identity),
                 db: Session = Depends(get_db)):
    """The records with an approved location inside the box, as GeoJSON, that the person may see — with the
    same rules as a list: their workspaces, restricted records and a restricted location left out."""
    try:
        west, south, east, north = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "bbox is west,south,east,north", "code": "location"})
    spaces = _workspaces(db, identity, workspaces, workspace_id)
    cond = _scope(db, identity, spaces, types, status)
    layers, cache, out = {}, {}, []
    for asset, f in spatial.within(db, cond, (west, south, east, north)):
        if _permitted(db, identity, asset, spaces, cache):
            out.append(_feature(db, asset, f, layers))
    return {"type": "FeatureCollection", "features": out, "truncated": len(out) >= 2000}


@router.get("/map/nearby")
def map_nearby(latitude: float, longitude: float, radius_m: float = Query(500, gt=0, le=100_000),
               workspaces: Optional[str] = None, types: Optional[str] = None, status: Optional[str] = None,
               workspace_id: str = Depends(require_permission("read")), identity=Depends(get_identity),
               db: Session = Depends(get_db)):
    """The records within a distance of a point, nearest first, as GeoJSON with each one's distance."""
    try:
        centre = spatial.point(latitude, longitude)
    except spatial.SpatialError as e:
        _bad(e)
    spaces = _workspaces(db, identity, workspaces, workspace_id)
    cond = _scope(db, identity, spaces, types, status)
    layers, cache, out = {}, {}, []
    for asset, f, d in spatial.nearby(db, cond, centre, radius_m):
        if _permitted(db, identity, asset, spaces, cache):
            out.append(_feature(db, asset, f, layers, d))
    return {"type": "FeatureCollection", "features": out, "centre": centre, "radius_m": radius_m}


@router.get("/map/layers")
def map_layers(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The map layers the workspace's packages define."""
    from app.packages.install import installed
    from app.packages.loader import available
    shipped = available()
    out = []
    for pid in installed(db, workspace_id):
        p = shipped.get(pid)
        for layer in (p.section("map_layers") or []) if p else []:
            out.append({**layer, "package": pid})
    return out


# --------------------------------------------------------------------------- importing locations

@router.post("/locations/import")
async def import_locations(file: UploadFile = File(...), dry_run: bool = Query(True),
                           workspace_id: str = Depends(require_permission("modify")), grants=Depends(get_grants),
                           identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Locations from a CSV or (Geo)JSON file. Every row's coordinates are checked; a record without a location
    gets the imported one (with the file and row it came from); a record with an approved location is never
    overwritten — a different position goes to review. `dry_run` (the default) says what would happen."""
    try:
        rows = spatial.read_rows(file.filename or "locations.csv", await file.read())
        result = spatial.import_locations(db, workspace_id, rows, source_name=file.filename or "upload",
                                          actor=actor_of(identity), grants=grants, dry_run=dry_run)
    except (spatial.SpatialError, ValueError) as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "location"})
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result
