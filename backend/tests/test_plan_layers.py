"""A floor plan's layers (docs/plan-layers.md): the drawing is the base, the records go over it by layer; a rack is
one point holding its units, whose tickets it shows; zones and routes come from the map onto the plan."""
import uuid

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ledger import engine
from app.main import app
from app.models.asset import Asset, Relation
from app.models.issue import Issue
from app.services import spatial
from tests.test_indoor import at, cp, png
from tests.test_spatial import world  # noqa: F401 — the same workspaces, records and token

client = TestClient(app)


def _unit(w, name, type_name):
    db = SessionLocal()
    schema = engine.ensure_type(db, w["ws"], type_name)
    schema.metadata_json = {**(schema.metadata_json or {}), "locatable": True}
    a = Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=schema.uid,
              key=f"{name}-{w['ws']}", name=name, type=type_name, attributes={}, record_status="Active")
    db.add(a)
    db.commit()
    uid = a.uid
    db.close()
    return uid


def test_the_plan_shows_its_records_by_layer_and_a_rack_holds_its_units(world):
    w, h = world, world["headers"]
    hall = _unit(w, "Hall L", "Building")
    plan = client.post(f"/v1/assets/{hall}/plans", headers=h, data={"name": "Hall L plan"},
                       files={"file": ("hall.png", png(), "image/png")}).json()
    assert client.put(f"/v1/plans/{plan['uid']}/placement", headers=h,
                      json={"points": [cp(0, 0), cp(1000, 0), cp(0, 500)]}).status_code == 200
    rack, server = _unit(w, "Rack R1", "Rack"), _unit(w, "Server S1", "Server")
    chiller, cam, door = _unit(w, "Chiller C1", "Chiller"), _unit(w, "Camera K1", "Camera"), _unit(w, "Door D1", "Door")
    room, zone, cable = _unit(w, "Room 12", "Room"), _unit(w, "Controlled area", "Radiation Area"), _unit(w, "Cable X", "Power Cable")
    for uid, x, y in ((rack, 100, 100), (server, 104, 100), (chiller, 600, 300), (cam, 800, 50), (door, 0, 250)):
        r = client.put(f"/v1/assets/{uid}/indoors", headers=h, json={"place_uid": hall, "plan_uid": plan["uid"],
                                                                     "x": x, "y": y})
        assert r.status_code == 200, r.text
    db = SessionLocal()
    db.add(Relation(workspace_id=w["ws"], from_asset_uid=server, to_asset_uid=rack, relation_type="located in"))
    db.add(Issue(uid=str(uuid.uuid4()), workspace_id=w["ws"], asset_uid=server, title="Fan noisy", state="new"))
    db.add(Issue(uid=str(uuid.uuid4()), workspace_id=w["ws"], asset_uid=chiller, title="Done", state="closed"))

    def ring(x0, y0, x1, y1):
        return [list(at(x0, y0)), list(at(x1, y0)), list(at(x1, y1)), list(at(x0, y1)), list(at(x0, y0))]
    for uid, coords in ((room, ring(50, 50, 400, 300)), (zone, ring(500, 200, 900, 450)),
                        (hall, ring(-10, -10, 1010, 510))):                  # the hall's own outline: left out
        spatial.set_location(db, db.get(Asset, uid), spatial.shape(db, {"type": "Polygon", "coordinates": [coords]},
                                                                   "outline"), actor="t", source="manual", role="outline")
    spatial.set_location(db, db.get(Asset, cable), spatial.shape(db, {"type": "LineString", "coordinates": [
        list(at(0, 400)), list(at(1000, 400))]}, "route"), actor="t", source="manual", role="route")
    db.commit()
    db.close()

    r = client.get(f"/v1/plans/{plan['uid']}/layers", headers=h)
    assert r.status_code == 200, r.text
    v = r.json()
    layers = {lyr["id"]: lyr for lyr in v["layers"]}
    assert [k for k, lyr in layers.items() if lyr["on"]] == ["places", "beamline", "racks", "fixed"]
    items = {i["name"]: i for i in v["items"]}
    # The server is in its rack, not a point of its own; its open ticket shows at the rack.
    assert "Server S1" not in items and v["in_racks"] == 1 and v["held"] == {server: rack}
    assert items["Rack R1"]["layer"] == "racks" and items["Rack R1"]["rack"]["holds"] == 1
    assert items["Rack R1"]["tickets"] == 1 and items["Chiller C1"]["tickets"] == 0      # a closed one is not shown
    assert v["tickets"][0]["title"] == "Fan noisy" and v["tickets"][0]["shown_at"] == rack
    assert (items["Chiller C1"]["layer"], items["Camera K1"]["layer"], items["Door D1"]["layer"]) == ("fixed", "devices", "places")
    shapes = {s["name"]: s for s in v["outlines"] + v["routes"]}
    assert set(shapes) == {"Room 12", "Controlled area", "Cable X"}
    assert shapes["Room 12"]["layer"] == "places" and shapes["Controlled area"]["layer"] == "zones"
    assert shapes["Cable X"]["layer"] == "paths"
    x, y = shapes["Room 12"]["points"][0]
    assert abs(x - 50) < 0.5 and abs(y - 50) < 0.5                      # back in the plan's pixels
    assert layers["tickets"]["count"] == 1 and layers["zones"]["count"] == 1 and layers["racks"]["count"] == 1


def test_a_plan_not_on_the_map_still_shows_its_points_without_shapes(world):
    w, h = world, world["headers"]
    store = _unit(w, "Store S", "Building")
    plan = client.post(f"/v1/assets/{store}/plans", headers=h, files={"file": ("s.png", png(200, 100), "image/png")}).json()
    pump = _unit(w, "Pump P", "Water Pump")
    client.put(f"/v1/assets/{pump}/indoors", headers=h, json={"place_uid": store, "plan_uid": plan["uid"], "x": 10, "y": 10})
    v = client.get(f"/v1/plans/{plan['uid']}/layers", headers=h).json()
    assert [i["layer"] for i in v["items"]] == ["fixed"] and v["outlines"] == [] and v["routes"] == []


def test_the_scene_has_the_scale_the_units_at_their_height_and_the_relations_between_what_is_shown(world):
    w, h = world, world["headers"]
    hall = _unit(w, "Hall S", "Building")
    plan = client.post(f"/v1/assets/{hall}/plans", headers=h, files={"file": ("h.png", png(), "image/png")}).json()
    client.put(f"/v1/plans/{plan['uid']}/placement", headers=h, json={"points": [cp(0, 0), cp(1000, 0), cp(0, 500)]})
    rack, server, ups = _unit(w, "Rack Q", "Rack"), _unit(w, "Server Q", "Server"), _unit(w, "UPS Q", "UPS")
    for uid, x in ((rack, 100), (ups, 300)):
        client.put(f"/v1/assets/{uid}/indoors", headers=h, json={"place_uid": hall, "plan_uid": plan["uid"], "x": x, "y": 100})
    assert client.post(f"/v1/racks/{rack}/apply", headers=h, json={"operations": [
        {"op": "place", "asset_uid": server, "start_u": 10, "height_u": 2}]}).status_code == 200
    db = SessionLocal()
    db.add(Relation(workspace_id=w["ws"], from_asset_uid=ups, to_asset_uid=server, relation_type="powers"))
    db.commit()
    db.close()
    s = client.get(f"/v1/plans/{plan['uid']}/scene", headers=h).json()
    assert s["scale_known"] and abs(s["metres_per_px"] - 0.1) < 0.002
    assert [(u["name"], u["rack_uid"], u["start_u"], u["height_u"], u["face"]) for u in s["units"]] == \
        [("Server Q", rack, 10, 2, "front")]
    # The server's place in its rack is shown by placing it; that the UPS powers it is a line.
    assert s["relations"] == [{"from": ups, "to": server, "type": "powers"}]


def test_other_workspaces_copies_at_the_same_spot_do_not_hide_the_plans_own(world, monkeypatch):
    """The map is looked up within a limit: copies of the same records in other workspaces (a demo imported twice)
    are not looked for, so they cannot use it up before the plan's own are found."""
    from app.models.workspace import Workspace
    from app.services import plan_layers
    w, h = world, world["headers"]
    hall = _unit(w, "Hall M", "Building")
    plan = client.post(f"/v1/assets/{hall}/plans", headers=h, data={"name": "Hall M plan"},
                       files={"file": ("hall.png", png(), "image/png")}).json()
    assert client.put(f"/v1/plans/{plan['uid']}/placement", headers=h,
                      json={"points": [cp(0, 0), cp(1000, 0), cp(0, 500)]}).status_code == 200
    db = SessionLocal()
    other = Workspace(id=f"copy-{uuid.uuid4().hex[:6]}", name="A copy")
    db.add(other)
    db.flush()
    line = {"type": "LineString", "coordinates": [list(at(0, 300)), list(at(1000, 300))]}
    own = _unit(w, "Cable own", "Power Cable")
    copies = []
    for k in range(3):
        schema = engine.ensure_type(db, other.id, "Power Cable")
        schema.metadata_json = {**(schema.metadata_json or {}), "locatable": True}
        a = Asset(uid=str(uuid.uuid4()), workspace_id=other.id, schema_uid=schema.uid, key=f"C-{k}", name=f"Copy {k}",
                  type="Power Cable", attributes={}, record_status="Active")
        db.add(a)
        db.flush()
        copies.append(a)
    for a in copies + [db.get(Asset, own)]:
        spatial.set_location(db, a, spatial.shape(db, line, "route"), actor="t", source="manual", role="route")
    other_id = other.id
    db.commit()
    db.close()
    within = spatial.within
    monkeypatch.setattr(plan_layers.spatial, "within", lambda db, f, bbox, limit=2000: within(db, f, bbox, limit=1))
    v = client.get(f"/v1/plans/{plan['uid']}/layers", headers=h).json()
    assert [r["name"] for r in v["routes"]] == ["Cable own"]
    db = SessionLocal()
    db.delete(db.get(Workspace, other_id))
    db.commit()
    db.close()


def test_a_record_said_to_be_in_a_place_with_a_plan_is_offered_that_plan_until_it_is_on_it(world):
    """Created with "Located in" a room drawn on its building's plan: the record's indoors view offers that plan
    (the web asks whether to put it there); once it has a point on it, or when it is a unit in a rack, no offer."""
    w, h = world, world["headers"]
    hall = _unit(w, "Hall O", "Building")
    plan = client.post(f"/v1/assets/{hall}/plans", headers=h, data={"name": "Hall O plan"},
                       files={"file": ("hall.png", png(), "image/png")}).json()
    room, pump, unit, rack = (_unit(w, "Room O1", "Room"), _unit(w, "Pump O", "Water Pump"),
                              _unit(w, "Switch O", "Switch"), _unit(w, "Rack O", "Rack"))
    assert client.put(f"/v1/assets/{room}/indoors", headers=h,
                      json={"place_uid": hall, "plan_uid": plan["uid"], "x": 200, "y": 100}).status_code == 200
    db = SessionLocal()
    for uid, where in ((pump, f"Room O1-{w['ws']}"), (unit, f"Rack O-{w['ws']}")):
        a = db.get(Asset, uid)
        a.attributes = {**(a.attributes or {}), "argus_location": where}
    db.commit()
    db.close()

    offer = client.get(f"/v1/assets/{pump}/indoors", headers=h).json()["plan_offer"]
    assert offer["place"]["uid"] == room                                       # the room it is said to be in
    assert [p["uid"] for p in offer["plans"]] == [plan["uid"]]                 # drawn on its building's plan
    assert offer["plans"][0]["place"]["uid"] == hall
    assert client.get(f"/v1/assets/{unit}/indoors", headers=h).json()["plan_offer"] is None    # in a rack
    assert client.get(f"/v1/assets/{hall}/indoors", headers=h).json()["plan_offer"] is None    # in nothing

    assert client.put(f"/v1/assets/{pump}/indoors", headers=h,
                      json={"place_uid": room, "plan_uid": plan["uid"], "x": 210, "y": 110}).status_code == 200
    assert client.get(f"/v1/assets/{pump}/indoors", headers=h).json()["plan_offer"] is None    # on it now

    # A building with two floors, each with its plan: the floor the record is said to be on comes first, else the
    # lowest — not the first by name ("first floor" before "ground floor").
    two = _unit(w, "Hall T", "Building")
    ground = client.post(f"/v1/assets/{two}/levels", headers=h, json={"name": "Ground floor", "ordinal": 0}).json()
    first = client.post(f"/v1/assets/{two}/levels", headers=h, json={"name": "First floor", "ordinal": 1}).json()
    plans = {}
    for lvl, name in ((first, "Hall T — first floor"), (ground, "Hall T — ground floor")):
        plans[name] = client.post(f"/v1/assets/{two}/plans", headers=h, data={"name": name, "level_uid": lvl["uid"]},
                                  files={"file": ("t.png", png(), "image/png")}).json()["uid"]
    desk, office = _unit(w, "Desk T", "Workstation"), _unit(w, "Office T", "Room")
    db = SessionLocal()
    db.get(Asset, desk).attributes = {"argus_location": f"Hall T-{w['ws']}"}
    db.commit()
    db.close()
    offer = client.get(f"/v1/assets/{desk}/indoors", headers=h).json()["plan_offer"]
    assert offer["plans"][0]["uid"] == plans["Hall T — ground floor"]
    assert client.put(f"/v1/assets/{office}/indoors", headers=h,
                      json={"place_uid": two, "level_uid": first["uid"]}).status_code == 200
    offer = client.get(f"/v1/assets/{office}/indoors", headers=h).json()["plan_offer"]
    assert offer["plans"][0]["uid"] == plans["Hall T — first floor"]          # the floor it is on
