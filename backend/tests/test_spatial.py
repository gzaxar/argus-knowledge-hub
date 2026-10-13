"""Locations: approved positions with their history, field observations that never move a record by
themselves, and the map and nearby search under the same rules as lists."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.packages.install import install
from app.services import asset_types, spatial
from tests.test_ledger_transition import token

client = TestClient(app)
# Frascati: the LNF site.
LNF = (41.8217, 12.6726)


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    ws, other = f"geo-{t}", f"geo-other-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=ws, name=ws), Workspace(id=other, name=other)])
    db.flush()
    for w in (ws, other):
        install(db, w, ["accelerator"])
    pump_type = db.get(Schema, asset_types.type_uid(ws, "Ion Pump"))
    # A type whose location is restricted: only holders of the class see where its units are.
    secret_type = Schema(uid=f"{ws}:secret-store", workspace_id=ws, name="Secret Store", applies_to="objects",
                         parent_schema_uid=asset_types.type_uid(ws, "Asset"), is_concrete=True,
                         attributes=[{"key": "location", "name": "Location", "type": "string", "restricted": "site_security"}])
    db.add(secret_type)
    db.flush()

    def unit(w, key, schema_uid, type_name, attrs=None):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=w, schema_uid=schema_uid, key=key, name=key, type=type_name,
                  attributes=attrs or {}, record_status="Active")
        db.add(a)
        db.flush()
        return a.uid
    ids = {
        "pump": unit(ws, f"{t}-IP-1", pump_type.uid, "Ion Pump"),
        "far": unit(ws, f"{t}-IP-2", pump_type.uid, "Ion Pump"),
        "restricted": unit(ws, f"{t}-IP-3", pump_type.uid, "Ion Pump", {"classification": "restricted:security_incident"}),
        "secret": unit(ws, f"{t}-ST-1", secret_type.uid, "Secret Store"),
        "elsewhere": unit(other, f"{t}-IP-9", asset_types.type_uid(other, "Ion Pump"), "Ion Pump"),
        "section": unit(ws, f"{t}-SEC", asset_types.type_uid(ws, "Section"), "Section"),
    }
    headers = token(db, ws)
    db.commit()
    db.close()
    yield {"ws": ws, "other": other, "headers": headers, **ids}
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in (ws, other):
        db.delete(db.get(Workspace, w))
    db.commit()
    db.close()


def _set(w, uid, lat, lon, **extra):
    return client.put(f"/v1/assets/{uid}/location", headers=w["headers"],
                      json={"latitude": lat, "longitude": lon, **extra})


# --------------------------------------------------------------------------- coordinates

@pytest.mark.parametrize("lat,lon,message", [
    (95, 12.6, "outside −90…90"), (41.8, 200, "outside −180…180"), (0, 0, "Gulf of Guinea"),
    ("north", 12.6, "numbers")])
def test_impossible_coordinates_are_refused(lat, lon, message):
    with pytest.raises(spatial.SpatialError, match=message):
        spatial.point(lat, lon)


def test_only_wgs84_is_taken_and_accuracy_must_be_plausible():
    with pytest.raises(spatial.SpatialError, match="not supported yet"):
        spatial.point(41.8, 12.6, crs="EPSG:3003")
    with pytest.raises(spatial.SpatialError, match="not plausible"):
        spatial.point(41.8, 12.6, accuracy_m=-3)
    assert spatial.point(41.8, 12.6, crs="EPSG:4326") == {"type": "Point", "coordinates": [12.6, 41.8]}


# --------------------------------------------------------------------------- the approved location

def test_a_location_is_set_superseded_and_kept_in_the_history(world):
    first = _set(world, world["pump"], *LNF, accuracy_m=3)
    assert first.status_code == 200, first.text
    assert (first.json()["latitude"], first.json()["longitude"]) == LNF
    moved = _set(world, world["pump"], 41.8221, 12.6731, accuracy_m=2, note="moved to the new rack")
    loc = client.get(f"/v1/assets/{world['pump']}/location", headers=world["headers"]).json()
    assert loc["locatable"] and loc["map_layer"] == "equipment"
    assert loc["location"]["uid"] == moved.json()["uid"]
    assert [h["state"] for h in loc["history"]] == ["confirmed", "superseded"]
    assert loc["history"][1]["valid_until"] is not None
    history = client.get(f"/v1/assets/{world['pump']}/history", headers=world["headers"]).json()
    assert any(h["type"] == "location" and h["details"].startswith("Location set: 41.822100, 12.673100") for h in history)


def test_a_type_its_package_does_not_place_on_the_map_has_no_location(world):
    r = _set(world, world["section"], *LNF)
    assert r.status_code == 422 and "not mark the type locatable" in r.json()["detail"]["error"]


# --------------------------------------------------------------------------- observations

def test_an_observation_never_moves_a_record_it_agrees_or_waits_for_review(world):
    _set(world, world["pump"], *LNF, accuracy_m=3)
    near = client.post(f"/v1/assets/{world['pump']}/location/observations", headers=world["headers"],
                       json={"latitude": 41.82172, "longitude": 12.67262, "accuracy_m": 5}).json()
    assert near["status"] == "consistent" and near["distance_m"] < 15
    far = client.post(f"/v1/assets/{world['pump']}/location/observations", headers=world["headers"],
                      json={"latitude": 41.8260, "longitude": 12.6800, "accuracy_m": 8}).json()
    assert far["status"] == "pending" and far["distance_m"] > 500
    loc = client.get(f"/v1/assets/{world['pump']}/location", headers=world["headers"]).json()
    assert (loc["location"]["latitude"], loc["location"]["longitude"]) == LNF, "not moved by an observation"

    queue = client.get("/v1/location-reviews", headers=world["headers"]).json()
    assert [q["id"] for q in queue] == [far["id"]] and queue[0]["approved"]["latitude"] == LNF[0]
    rejected = client.post(f"/v1/location-reviews/{far['id']}/reject", headers=world["headers"], json={"note": "GPS drift"})
    assert rejected.json()["status"] == "rejected"
    assert client.post(f"/v1/location-reviews/{far['id']}/accept", headers=world["headers"], json={}).status_code == 422


def test_an_accepted_observation_becomes_the_approved_location_with_its_reviewer(world):
    first = client.post(f"/v1/assets/{world['far']}/location/observations", headers=world["headers"],
                        json={"latitude": 41.8230, "longitude": 12.6740, "accuracy_m": 4}).json()
    assert first["status"] == "pending" and first["note"] == "no approved location yet"
    client.post(f"/v1/location-reviews/{first['id']}/accept", headers=world["headers"], json={"note": "checked on site"})
    loc = client.get(f"/v1/assets/{world['far']}/location", headers=world["headers"]).json()["location"]
    assert loc["source"] == "field" and loc["accuracy_m"] == 4 and loc["reviewer"]
    assert (loc["latitude"], loc["longitude"]) == (41.8230, 12.6740)


# --------------------------------------------------------------------------- the map

def test_the_map_and_nearby_search_show_only_what_the_person_may_see(world):
    db = SessionLocal()
    for key, (lat, lon) in {"pump": LNF, "far": (41.9, 12.5), "restricted": (41.8218, 12.6727),
                            "secret": (41.8219, 12.6728), "elsewhere": (41.8216, 12.6725)}.items():
        a = db.get(Asset, world[key])
        spatial.set_location(db, a, spatial.point(lat, lon), actor="test")
    db.commit()
    db.close()
    box = "12.67,41.82,12.68,41.83"
    found = client.get("/v1/map/features", params={"bbox": box}, headers=world["headers"]).json()
    uids = {f["properties"]["uid"] for f in found["features"]}
    assert uids == {world["pump"]}, "not the far one, nor another workspace's, a restricted record or a restricted location"
    assert found["features"][0]["properties"]["map_layer"] == "equipment"

    near = client.get("/v1/map/nearby", params={"latitude": LNF[0], "longitude": LNF[1], "radius_m": 200},
                      headers=world["headers"]).json()
    assert [f["properties"]["uid"] for f in near["features"]] == [world["pump"]]
    wide = client.get("/v1/map/nearby", params={"latitude": LNF[0], "longitude": LNF[1], "radius_m": 30_000},
                      headers=world["headers"]).json()
    distances = [f["properties"]["distance_m"] for f in wide["features"]]
    assert [f["properties"]["uid"] for f in wide["features"]] == [world["pump"], world["far"]]
    assert distances == sorted(distances) and distances[1] > 10_000
    assert client.get("/v1/map/features", params={"bbox": box, "types": "Vacuum Gauge"},
                      headers=world["headers"]).json()["features"] == []
    assert client.get("/v1/map/features", params={"bbox": box, "status": "Retired"},
                      headers=world["headers"]).json()["features"] == []
    secret = client.get(f"/v1/assets/{world['secret']}/location", headers=world["headers"]).json()
    assert secret["hidden"] is True and secret["location"] is None
    layers = client.get("/v1/map/layers", headers=world["headers"]).json()
    # core-objects' layers, and those of the packages the accelerator stands on since 1.35.26
    assert {layer["id"] for layer in layers} == {"equipment", "places", "safety", "safety-zones", "cryogenics",
                                                 "gas-handling", "optics", "survey"}


# --------------------------------------------------------------------------- importing locations

def test_a_location_import_checks_every_row_and_never_overwrites_an_approved_location(world):
    db = SessionLocal()
    keys = {k: db.get(Asset, world[k]).key for k in ("pump", "far", "restricted")}
    spatial.set_location(db, db.get(Asset, world["far"]), spatial.point(41.8300, 12.6800), actor="surveyor",
                         accuracy_m=1)
    db.commit()
    db.close()
    csv = ("key,lat,lon,accuracy\n"
           f"{keys['pump']},41.8217,12.6726,3\n"          # no location yet: set, with its provenance
           f"{keys['far']},41.83001,12.68001,2\n"          # where it already is: consistent
           f"{keys['far']},41.8400,12.7000,2\n"            # elsewhere: to review, not overwritten
           f"{keys['pump']},141.8217,12.6726,3\n"          # an impossible latitude: refused
           "NO-SUCH-UNIT,41.82,12.67,3\n"
           f"{keys['restricted']},41.82,12.67,3\n")        # not visible to this person: as if absent
    files = {"file": ("survey.csv", csv.encode(), "text/csv")}
    preview = client.post("/v1/locations/import", headers=world["headers"], files=files).json()
    assert preview["dry_run"] and preview["counts"] == {"set": 1, "to_review": 1, "consistent": 1, "rejected": 3}
    outcomes = [(r["row"], r["outcome"]) for r in preview["rows"]]
    assert outcomes == [(1, "set"), (2, "consistent"), (3, "to_review"), (4, "rejected"), (5, "rejected"), (6, "rejected")]
    assert "outside −90…90" in preview["rows"][3]["problem"]
    assert preview["rows"][4]["problem"] == "no record of this workspace carries it"
    assert client.get(f"/v1/assets/{world['pump']}/location", headers=world["headers"]).json()["location"] is None

    done = client.post("/v1/locations/import", params={"dry_run": False}, headers=world["headers"], files=files).json()
    assert done["counts"]["set"] == 1
    pump = client.get(f"/v1/assets/{world['pump']}/location", headers=world["headers"]).json()["location"]
    assert pump["source"] == "import" and pump["provenance"]["file"] == "survey.csv" and pump["provenance"]["row"] == 1
    far = client.get(f"/v1/assets/{world['far']}/location", headers=world["headers"]).json()
    assert (far["location"]["latitude"], far["location"]["longitude"]) == (41.83, 12.68), "never overwritten"
    assert [o["status"] for o in far["observations"]] == ["pending", "consistent"]


def test_a_geojson_location_file_is_read_too(world):
    db = SessionLocal()
    key = db.get(Asset, world["pump"]).key
    db.close()
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.6726, 41.8217]},
         "properties": {"key": key, "accuracy_m": 2}}]}
    import json
    r = client.post("/v1/locations/import", headers=world["headers"],
                    files={"file": ("survey.geojson", json.dumps(geo).encode(), "application/geo+json")}).json()
    assert r["counts"]["set"] == 1
