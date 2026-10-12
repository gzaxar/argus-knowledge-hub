"""Locations of records, and the observations that propose them (models/spatial.py).

* A record has a location only when its type may (a package marks types `locatable`, and their descendants
  inherit it, with the map layer they are shown on).
* Setting a location supersedes the previous one, which stays in the history.
* An observation (a phone's GPS fix, with its accuracy) never moves a record: it is compared with the approved
  location — close enough, it is noted as consistent; otherwise it waits for a person to accept or reject it.
* Who may see a location is who may see the record, and only if its type does not restrict the `location`
  field from them (I-ACL-1) — on a record page, a list, the map and a nearby search alike.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.schema import Schema
from app.models.spatial import SRID, LocationObservation, SpatialFeature

# A field (or a type) restricted under this key keeps the location from those without its class.
LOCATION_FIELD = "location"
# An observation within this distance of the approved location (plus both accuracies) agrees with it.
TOLERANCE_M = 15.0
MAX_ACCURACY_M = 5000.0
CRS = "EPSG:4326"


class SpatialError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- coordinates

def point(lat, lon, *, crs: Optional[str] = None, accuracy_m=None) -> dict:
    """A validated GeoJSON point (longitude, latitude) in WGS 84."""
    if crs not in (None, "", CRS, "WGS84", "WGS 84", "4326"):
        raise SpatialError(f"coordinates in {crs} are not supported yet: give WGS 84 latitude and longitude ({CRS})")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise SpatialError("latitude and longitude are numbers") from None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise SpatialError("latitude and longitude are numbers")
    if not -90 <= lat <= 90:
        raise SpatialError(f"latitude {lat} is outside −90…90 (are latitude and longitude swapped?)")
    if not -180 <= lon <= 180:
        raise SpatialError(f"longitude {lon} is outside −180…180")
    if lat == 0 and lon == 0:
        raise SpatialError("0, 0 is in the Gulf of Guinea: most likely a missing position, not a location")
    if accuracy_m is not None:
        try:
            accuracy_m = float(accuracy_m)
        except (TypeError, ValueError):
            raise SpatialError("accuracy is a distance in metres") from None
        if not (0 <= accuracy_m <= MAX_ACCURACY_M):
            raise SpatialError(f"accuracy {accuracy_m} m is not plausible (0…{MAX_ACCURACY_M:g} m)")
    return {"type": "Point", "coordinates": [round(lon, 8), round(lat, 8)]}


def geojson(value) -> dict:
    """A stored geometry as a GeoJSON dict: an object reloaded after a commit may come back as its text."""
    if isinstance(value, (str, bytes)):
        import json
        return json.loads(value)
    return value


def lat_lon(geometry) -> tuple[float, float]:
    lon, lat = geojson(geometry)["coordinates"][:2]
    return lat, lon


def distance_m(db: Session, a: dict, b: dict) -> float:
    """Metres between two WGS 84 geometries, on the ellipsoid."""
    import json
    return float(db.scalar(select(func.ST_Distance(
        func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(a)), SRID).cast(_geography()),
        func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(b)), SRID).cast(_geography())))))


def _geography():
    from sqlalchemy.types import UserDefinedType

    class Geography(UserDefinedType):
        cache_ok = True

        def get_col_spec(self, **kw):
            return "geography"
    return Geography()


# --------------------------------------------------------------------------- which types, and who sees

def _lineage(db: Session, schema_uid: Optional[str]) -> list[Schema]:
    out, seen = [], set()
    while schema_uid and schema_uid not in seen:
        seen.add(schema_uid)
        s = db.get(Schema, schema_uid)
        if s is None:
            break
        out.append(s)
        schema_uid = s.parent_schema_uid
    return out


def placement(db: Session, schema_uid: Optional[str]) -> tuple[bool, Optional[str]]:
    """Whether records of this type may have a location, and the map layer they are shown on (the nearest
    one up the type tree)."""
    locatable, layer = False, None
    for s in _lineage(db, schema_uid):
        meta = s.metadata_json or {}
        if layer is None and meta.get("map_layer"):
            layer = meta["map_layer"]
        if meta.get("locatable"):
            locatable = True
    return locatable, layer


def location_hidden(db: Session, asset: Asset, grants=None) -> bool:
    from app.services.visibility import hidden_fields
    return LOCATION_FIELD in hidden_fields(db, asset, grants)


def may_see(db: Session, asset: Optional[Asset], grants=None) -> bool:
    from app.services.visibility import can_see
    return asset is not None and asset.deleted_at is None and can_see(asset, grants) and \
        not location_hidden(db, asset, grants)


# --------------------------------------------------------------------------- the approved location

def current(db: Session, asset_uid: str) -> Optional[SpatialFeature]:
    return db.scalar(select(SpatialFeature).where(SpatialFeature.subject_kind == "asset",
                                                  SpatialFeature.subject_uid == asset_uid,
                                                  SpatialFeature.role == "position",
                                                  SpatialFeature.state == "confirmed"))


def history(db: Session, asset_uid: str) -> list[SpatialFeature]:
    return list(db.scalars(select(SpatialFeature).where(SpatialFeature.subject_kind == "asset",
                                                        SpatialFeature.subject_uid == asset_uid)
                           .order_by(SpatialFeature.valid_from.desc())))


def set_location(db: Session, asset: Asset, geometry: dict, *, actor: Optional[str], source: str = "manual",
                 accuracy_m: Optional[float] = None, observed_at=None, note: Optional[str] = None,
                 reviewer: Optional[str] = None, observation_id: Optional[int] = None,
                 provenance: Optional[dict] = None) -> SpatialFeature:
    """Approve a location for a record: the one it had is superseded (kept, with when it stopped)."""
    locatable, _layer = placement(db, asset.schema_uid)
    if not locatable:
        raise SpatialError(f"records of type {asset.type!r} have no location on the map: its package does not mark "
                           f"the type locatable")
    at = now()
    previous = current(db, asset.uid)
    if previous is not None:
        previous.state, previous.valid_until = "superseded", at
        db.flush()
    feature = SpatialFeature(
        uid=str(uuid.uuid4()), workspace_id=asset.workspace_id, subject_kind="asset", subject_uid=asset.uid,
        role="position", geometry=geometry, geometry_type=geometry["type"], crs=CRS, source=source,
        accuracy_m=accuracy_m, observed_at=observed_at or at, valid_from=at, state="confirmed",
        confirmed_by=actor, confirmed_at=at, reviewer=reviewer, observation_id=observation_id, note=note,
        provenance=provenance, created_at=at)
    db.add(feature)
    _record_history(db, asset, f"Location set: {_describe(geometry, accuracy_m)}"
                    + (f" (from a field observation, accepted by {reviewer})" if reviewer else ""), actor, at)
    db.flush()
    return feature


def remove_location(db: Session, asset: Asset, actor: Optional[str]) -> bool:
    previous = current(db, asset.uid)
    if previous is None:
        return False
    at = now()
    previous.state, previous.valid_until = "removed", at
    _record_history(db, asset, "Location removed", actor, at)
    db.flush()
    return True


def _describe(geometry: dict, accuracy_m: Optional[float]) -> str:
    lat, lon = lat_lon(geometry)
    return f"{lat:.6f}, {lon:.6f}" + (f" (±{accuracy_m:.0f} m)" if accuracy_m is not None else "")


def _record_history(db: Session, asset: Asset, details: str, actor: Optional[str], at) -> None:
    from app.models.asset_subresources import AssetHistory
    db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=asset.uid, type="location", author=actor or "argus",
                        details=details, timestamp=at))
    asset.updated_at = at
    from app.services import notify
    notify.asset_changed(db, asset.uid, details, actor)


# --------------------------------------------------------------------------- observations

def observe(db: Session, asset: Asset, geometry: dict, *, accuracy_m: Optional[float], actor: Optional[str],
            observed_at=None, device_id: Optional[str] = None, source: str = "field") -> LocationObservation:
    """Note where someone saw the record. It never moves the record: close to the approved location it is
    consistent; otherwise — or with no approved location yet — it waits for review."""
    locatable, _layer = placement(db, asset.schema_uid)
    if not locatable:
        raise SpatialError(f"records of type {asset.type!r} have no location on the map")
    obs = LocationObservation(workspace_id=asset.workspace_id, subject_kind="asset", subject_uid=asset.uid,
                              geometry=geometry, accuracy_m=accuracy_m, observed_at=observed_at or now(),
                              observed_by=actor, device_id=device_id, source=source, created_at=now())
    approved = current(db, asset.uid)
    if approved is None:
        obs.status = "pending"
        obs.note = "no approved location yet"
    else:
        d = distance_m(db, geojson(approved.geometry), geometry)
        obs.distance_m, obs.feature_uid = round(d, 1), approved.uid
        tolerance = TOLERANCE_M + (accuracy_m or 0) + (approved.accuracy_m or 0)
        obs.status = "consistent" if d <= tolerance else "pending"
    db.add(obs)
    db.flush()
    if obs.status == "pending":
        from app.services import notify
        where = f"{obs.distance_m:.0f} m from its approved location" if obs.distance_m is not None else \
            "no approved location yet"
        notify.asset_changed(db, asset.uid, f"location observed {where}: to review", actor)
    return obs


def decide(db: Session, obs: LocationObservation, accept: bool, actor: Optional[str], note: Optional[str] = None):
    """A person's decision on an observation waiting for review: accepted, it becomes the approved location."""
    if obs.status != "pending":
        raise SpatialError(f"this observation is {obs.status}, not waiting for review")
    asset = db.get(Asset, obs.subject_uid)
    if asset is None:
        raise SpatialError("the record is gone")
    obs.status = "accepted" if accept else "rejected"
    obs.decided_by, obs.decided_at, obs.note = actor, now(), note or obs.note
    if accept:
        set_location(db, asset, geojson(obs.geometry), actor=obs.observed_by, source=obs.source, accuracy_m=obs.accuracy_m,
                     observed_at=obs.observed_at, reviewer=actor, observation_id=obs.id, note=note)
    db.flush()
    return obs


# --------------------------------------------------------------------------- searching by place

def _geom(geometry: dict):
    import json
    return func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), SRID)


def nearby(db: Session, asset_filter, centre: dict, radius_m: float, limit: int = 200):
    """(asset, feature, distance in metres) of the records with an approved location within `radius_m`,
    nearest first; `asset_filter` is the SQL condition on Asset deciding what the person may list."""
    geo = _geography()
    dist = func.ST_Distance(SpatialFeature.geometry.cast(geo), _geom(centre).cast(geo))
    q = (select(Asset, SpatialFeature, dist.label("d"))
         .join(SpatialFeature, (SpatialFeature.subject_uid == Asset.uid) & (SpatialFeature.subject_kind == "asset"))
         .where(SpatialFeature.state == "confirmed", asset_filter,
                func.ST_DWithin(SpatialFeature.geometry.cast(geo), _geom(centre).cast(geo), radius_m))
         .order_by(dist).limit(limit))
    return [(a, f, float(d)) for a, f, d in db.execute(q)]


def within(db: Session, asset_filter, bbox: tuple[float, float, float, float], limit: int = 2000):
    """(asset, feature) of the records with an approved location inside the box (west, south, east, north)."""
    west, south, east, north = bbox
    envelope = func.ST_MakeEnvelope(west, south, east, north, SRID)
    q = (select(Asset, SpatialFeature)
         .join(SpatialFeature, (SpatialFeature.subject_uid == Asset.uid) & (SpatialFeature.subject_kind == "asset"))
         .where(SpatialFeature.state == "confirmed", asset_filter, SpatialFeature.geometry.op("&&")(envelope),
                func.ST_Intersects(SpatialFeature.geometry, envelope))
         .limit(limit))
    return list(db.execute(q))


def feature_out(f: SpatialFeature) -> dict:
    lat, lon = lat_lon(f.geometry)
    return {"uid": f.uid, "latitude": lat, "longitude": lon, "geometry": geojson(f.geometry), "crs": f.crs,
            "accuracy_m": f.accuracy_m, "source": f.source, "observed_at": f.observed_at, "valid_from": f.valid_from,
            "valid_until": f.valid_until, "state": f.state, "confirmed_by": f.confirmed_by,
            "confirmed_at": f.confirmed_at, "reviewer": f.reviewer, "note": f.note, "provenance": f.provenance}


def observation_out(o: LocationObservation) -> dict:
    lat, lon = lat_lon(o.geometry)
    return {"id": o.id, "subject_uid": o.subject_uid, "latitude": lat, "longitude": lon, "accuracy_m": o.accuracy_m,
            "observed_at": o.observed_at, "observed_by": o.observed_by, "device_id": o.device_id,
            "source": o.source, "status": o.status, "distance_m": o.distance_m, "decided_by": o.decided_by,
            "decided_at": o.decided_at, "note": o.note}


# --------------------------------------------------------------------------- importing locations

def import_locations(db: Session, workspace_id: str, rows: list[dict], *, source_name: str, actor: Optional[str],
                     grants=None, dry_run: bool = True) -> dict:
    """Locations from a file: each row names a record (`key`, `label` or `serial` — matched as a scan is) and
    gives `latitude`, `longitude`, optionally `accuracy_m`, `crs`, `observed_at`. Each row is checked; a record
    with no approved location gets the imported one (its provenance: the file and the row); one that has an
    approved location is never overwritten — a different position becomes an observation for review, the same
    one is noted as consistent. With dry_run, says what would happen and writes nothing."""
    import hashlib
    import json as _json
    from datetime import datetime as _dt
    from app.services.identifiers import exact_clause
    from app.services.visibility import visible_assets_clause
    results, counts = [], {"set": 0, "to_review": 0, "consistent": 0, "rejected": 0}
    digest = hashlib.sha256(_json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]
    for i, row in enumerate(rows, start=1):
        ident = str(row.get("key") or row.get("label") or row.get("serial") or "").strip()
        out = {"row": i, "identifier": ident}
        try:
            if not ident:
                raise SpatialError("names no record (key, label or serial)")
            geometry = point(row.get("latitude"), row.get("longitude"), crs=row.get("crs"),
                             accuracy_m=row.get("accuracy_m") if row.get("accuracy_m") not in ("", None) else None)
            accuracy = float(row["accuracy_m"]) if row.get("accuracy_m") not in ("", None) else None
            observed = None
            if row.get("observed_at"):
                try:
                    observed = _dt.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
                except ValueError:
                    raise SpatialError(f"observed_at {row['observed_at']!r} is not a date and time") from None
            matches = [a for a in db.scalars(select(Asset).where(
                visible_assets_clause(workspace_id, grants), Asset.workspace_id == workspace_id,
                Asset.deleted_at.is_(None), exact_clause(db, grants, ident)).limit(3)) if may_see(db, a, grants)]
            if not matches:
                raise SpatialError("no record of this workspace carries it")
            if len(matches) > 1:
                raise SpatialError(f"{len(matches)} records carry it: {', '.join(a.key for a in matches)}")
            asset = matches[0]
            out["record"] = {"uid": asset.uid, "key": asset.key, "name": asset.name}
            if not placement(db, asset.schema_uid)[0]:
                raise SpatialError(f"records of type {asset.type!r} have no location on the map")
            provenance = {"file": source_name, "row": i, "import": digest}
            approved = current(db, asset.uid)
            if approved is None:
                out["outcome"] = "set"
                if not dry_run:
                    set_location(db, asset, geometry, actor=actor, source="import", accuracy_m=accuracy,
                                 observed_at=observed, provenance=provenance)
            else:
                d = distance_m(db, geojson(approved.geometry), geometry)
                out["distance_m"] = round(d, 1)
                agrees = d <= TOLERANCE_M + (accuracy or 0) + (approved.accuracy_m or 0)
                out["outcome"] = "consistent" if agrees else "to_review"
                if not dry_run:
                    obs = observe(db, asset, geometry, accuracy_m=accuracy, actor=actor, observed_at=observed,
                                  source="import")
                    obs.note = f"{source_name}, row {i}"
            counts[out["outcome"]] += 1
        except SpatialError as e:
            out["outcome"], out["problem"] = "rejected", str(e)
            counts["rejected"] += 1
        results.append(out)
    if not dry_run:
        db.flush()
    return {"dry_run": dry_run, "counts": counts, "rows": results, "import": digest}


def read_rows(filename: str, content: bytes) -> list[dict]:
    """A location file's rows: CSV with a header (key/label/serial, latitude, longitude, accuracy_m, crs,
    observed_at; `lat`/`lon`/`lng`/`accuracy` accepted), or JSON (a list of such objects, or GeoJSON points
    whose properties name the record)."""
    import csv
    import io
    import json as _json
    aliases = {"lat": "latitude", "lon": "longitude", "lng": "longitude", "long": "longitude",
               "accuracy": "accuracy_m", "accuracy (m)": "accuracy_m", "tag": "label"}
    text_ = content.decode("utf-8-sig", errors="replace")
    if filename.lower().endswith((".json", ".geojson")):
        data = _json.loads(text_)
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            rows = []
            for f in data.get("features") or []:
                geom, props = f.get("geometry") or {}, dict(f.get("properties") or {})
                if geom.get("type") == "Point":
                    props["longitude"], props["latitude"] = geom["coordinates"][:2]
                rows.append(props)
            data = rows
        if not isinstance(data, list):
            raise SpatialError("a JSON location file is a list of rows, or GeoJSON points")
        rows = data
    else:
        rows = list(csv.DictReader(io.StringIO(text_)))
    return [{aliases.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in r.items()} for r in rows
            if isinstance(r, dict)]
