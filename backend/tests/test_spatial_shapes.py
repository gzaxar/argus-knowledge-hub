"""Routes and outlines: a record's line (a cable, a pipe, a beamline) and polygon (a building, hall, room or zone —
with heights, a volume), each checked before it is kept and with its own history; what a shape says about the
others (what lies inside a hall, which cables cross it, what lies along a cable, which zones a unit is in); the
map and nearby search with shapes; and shapes from a GeoJSON file, never overwriting one a record has."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.services import asset_types, spatial
from tests.test_spatial import LNF, world  # noqa: F401 — the same workspaces, records and token

client = TestClient(app)

# A hall around the LNF point, a zone inside it, and a cable across both.
HALL = {"type": "Polygon", "coordinates": [[[12.6720, 41.8212], [12.6730, 41.8212], [12.6730, 41.8222],
                                            [12.6720, 41.8222], [12.6720, 41.8212]]]}
ZONE = {"type": "Polygon", "coordinates": [[[12.6724, 41.8215], [12.6728, 41.8215], [12.6728, 41.8219],
                                            [12.6724, 41.8219]]]}                      # left open: closed for it
CABLE = {"type": "LineString", "coordinates": [[12.6715, 41.8217], [12.6735, 41.8217]]}
BOWTIE = {"type": "Polygon", "coordinates": [[[12.672, 41.821], [12.673, 41.822], [12.673, 41.821],
                                              [12.672, 41.822], [12.672, 41.821]]]}


def _unit(w, key, type_name):
    db = SessionLocal()
    a = Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=asset_types.type_uid(w["ws"], type_name),
              key=key, name=key, type=type_name, attributes={}, record_status="Active")
    db.add(a)
    db.commit()
    uid = a.uid
    db.close()
    return uid


def _put(w, uid, role, geometry, **extra):
    return client.put(f"/v1/assets/{uid}/location/{role}", headers=w["headers"], json={"geometry": geometry, **extra})


def test_a_shape_is_checked_before_it_is_kept():
    db = SessionLocal()
    try:
        closed = spatial.shape(db, ZONE, "outline")
        assert closed["coordinates"][0][0] == closed["coordinates"][0][-1]
        with pytest.raises(spatial.SpatialError, match="a route is a LineString or MultiLineString"):
            spatial.shape(db, HALL, "route")
        with pytest.raises(spatial.SpatialError, match="not a valid shape: Self-intersection"):
            spatial.shape(db, BOWTIE, "outline")
        with pytest.raises(spatial.SpatialError, match="two different positions"):
            spatial.shape(db, {"type": "LineString", "coordinates": [[12.67, 41.82], [12.67, 41.82]]}, "route")
        with pytest.raises(spatial.SpatialError, match="three corners"):
            spatial.shape(db, {"type": "Polygon", "coordinates": [[[12.67, 41.82], [12.68, 41.82]]]}, "outline")
        with pytest.raises(spatial.SpatialError, match="not a WGS 84"):
            spatial.shape(db, {"type": "LineString", "coordinates": [[412000, 4630000], [412100, 4630000]]}, "route")
        with pytest.raises(spatial.SpatialError, match="not supported yet"):
            spatial.shape(db, CABLE, "route", crs="EPSG:3004")
        with pytest.raises(spatial.SpatialError, match="the top is above the bottom"):
            spatial.heights(3, 1)
    finally:
        db.close()


def test_a_route_and_an_outline_are_measured_and_keep_their_history(world):
    hall, cable = _unit(world, "HALL-1", "Area"), _unit(world, "CBL-1", "Power Cable")
    r = _put(world, hall, "outline", HALL, base_m=0, top_m=6.5)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["role"] == "outline" and (out["base_m"], out["top_m"]) == (0, 6.5)
    assert 9000 < out["area_m2"] < 9500 and out["latitude"] is None         # about 83 m × 111 m
    route = _put(world, cable, "route", CABLE).json()
    assert 160 < route["length_m"] < 170
    assert _put(world, cable, "route", BOWTIE).status_code == 422             # a polygon is not a route
    bad = _put(world, hall, "outline", BOWTIE)
    assert bad.status_code == 422 and "Self-intersection" in bad.json()["detail"]["error"]

    _put(world, hall, "outline", ZONE)                                        # moved: the old one is kept
    view = client.get(f"/v1/assets/{hall}/location", headers=world["headers"]).json()
    assert view["outline"]["area_m2"] < 2000 and view["outline"]["base_m"] is None and view["location"] is None
    assert [h["state"] for h in view["history"] if h["role"] == "outline"] == ["confirmed", "superseded"]
    assert client.delete(f"/v1/assets/{hall}/location/outline", headers=world["headers"]).status_code == 204
    assert client.get(f"/v1/assets/{hall}/location", headers=world["headers"]).json()["outline"] is None
    db = SessionLocal()
    from app.models.asset_subresources import AssetHistory
    said = [h.details for h in db.query(AssetHistory).filter(AssetHistory.asset_uid == hall)]
    db.close()
    assert any(d.startswith("Outline set:") and "m², from 0 m to 6.5 m" in d for d in said)
    assert "Outline removed" in said


def test_what_a_shape_says_about_the_others(world):
    hall, zone, cable = _unit(world, "HALL-2", "Area"), _unit(world, "ZONE-2", "Area"), _unit(world, "CBL-2", "Power Cable")
    assert _put(world, hall, "outline", HALL, base_m=0, top_m=6).status_code == 200
    assert _put(world, zone, "outline", ZONE).status_code == 200
    assert _put(world, cable, "route", CABLE).status_code == 200
    db = SessionLocal()
    spatial.set_location(db, db.get(Asset, world["pump"]), spatial.point(*LNF), actor="test")
    spatial.set_location(db, db.get(Asset, world["far"]), spatial.point(41.9, 12.5), actor="test")
    spatial.set_location(db, db.get(Asset, world["restricted"]), spatial.point(41.8218, 12.6727), actor="test")
    db.commit()
    db.close()

    def ctx(uid, **params):
        r = client.get(f"/v1/assets/{uid}/location/context", headers=world["headers"], params=params)
        assert r.status_code == 200, r.text
        return {k: {(i["uid"], i["role"]) for i in v} for k, v in r.json().items() if isinstance(v, list)}
    h = ctx(hall)
    assert h["inside"] == {(world["pump"], "position"), (zone, "outline")}      # not the far one, nor a restricted one
    assert h["crossing"] == {(cable, "route")}
    c = ctx(cable)
    assert (world["pump"], "position") in c["along"] and (world["far"], "position") not in c["along"]
    assert c["within"] == {(hall, "outline"), (zone, "outline")}
    assert ctx(world["pump"])["within"] == {(hall, "outline"), (zone, "outline")}
    assert ctx(zone)["within"] == {(hall, "outline")}

    box = "12.67,41.82,12.68,41.83"
    found = client.get("/v1/map/features", params={"bbox": box}, headers=world["headers"]).json()["features"]
    by_id = {f["id"]: f for f in found}
    assert by_id[f"{hall}:outline"]["geometry"]["type"] == "Polygon"
    assert by_id[f"{hall}:outline"]["properties"]["top_m"] == 6
    assert by_id[f"{cable}:route"]["properties"]["role"] == "route" and world["pump"] in by_id
    # Near a point: a shape by its nearest part (inside an outline is 0 m), each record once.
    near = client.get("/v1/map/nearby", params={"latitude": 41.8221, "longitude": 12.6729, "radius_m": 100},
                      headers=world["headers"]).json()["features"]
    dist = {f["properties"]["uid"]: f["properties"]["distance_m"] for f in near}
    assert dist[hall] == 0 and dist[cable] > 30 and len(near) == len(dist)


def test_shapes_from_a_geojson_file_never_replace_one_a_record_has(world):
    hall = _unit(world, "HALL-3", "Area")

    def run(geometry, dry_run):
        data = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": geometry, "properties": {"key": "HALL-3", "base_m": 0, "top_m": 5}}]}
        r = client.post(f"/v1/locations/import?dry_run={'true' if dry_run else 'false'}", headers=world["headers"],
                        files={"file": ("halls.geojson", json.dumps(data).encode(), "application/geo+json")})
        assert r.status_code == 200, r.text
        return r.json()["rows"][0]
    assert run(HALL, True)["outcome"] == "set"
    assert client.get(f"/v1/assets/{hall}/location", headers=world["headers"]).json()["outline"] is None
    first = run(HALL, False)
    assert (first["outcome"], first["role"]) == ("set", "outline")
    view = client.get(f"/v1/assets/{hall}/location", headers=world["headers"]).json()["outline"]
    assert (view["source"], view["top_m"]) == ("import", 5)
    assert run(HALL, False)["outcome"] == "consistent"
    moved = run(ZONE, False)
    assert moved["outcome"] == "rejected" and "different outline already" in moved["problem"]
    assert client.get(f"/v1/assets/{hall}/location", headers=world["headers"]).json()["outline"]["area_m2"] > 9000
