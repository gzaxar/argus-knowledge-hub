"""Draw a plan (docs/plan-drawing.md): a plan drawn from a layout in metres when there is no drawing, its rooms
standing for room records placed at their centre, opened again as its layout and redrawn without moving what is on
it; an overlap or a room past the walls refused; an uploaded drawing not redrawn."""
import secrets
import uuid

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ledger import engine
from app.main import app
from app.models.asset import Asset
from app.models.workspace import Workspace
from app.services import indoor
from tests.test_indoor import png
from tests.test_ledger_transition import token

client = TestClient(app)


def site():
    t = secrets.token_hex(3)
    ws = f"drawn-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()

    def rec(type_, name):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=engine.ensure_type(db, ws, type_).uid,
                  key=f"{name.upper().replace(' ', '-')}-{t}", name=name, type=type_, attributes={},
                  record_status="Active")
        db.add(a)
        db.flush()
        return a.uid
    w = {"ws": ws, "hall": rec("Building", "Hall B"), "racks": rec("Room", "Rack room"),
         "ctrl": rec("Room", "Control room"), "switch": rec("Switch", "Core switch")}
    w["h"] = token(db, ws)
    db.commit()
    db.close()
    return w


LAYOUT = {"title": "Hall B — ground floor", "width_m": 40, "depth_m": 20, "rooms": [
    {"name": "Rack room", "number": "B0.01", "x": 0, "y": 0, "w": 12, "d": 8},
    {"name": "Control room", "number": "B0.02", "x": 12, "y": 0, "w": 10, "d": 8},
    {"name": "Experimental hall", "number": "B0.10", "x": 0, "y": 10, "w": 40, "d": 10},
]}


def test_a_plan_drawn_from_its_rooms_places_them_and_is_redrawn_without_moving_anything():
    w = site()
    layout = {**LAYOUT, "rooms": [{**LAYOUT["rooms"][0], "record": w["racks"]}, {**LAYOUT["rooms"][1], "record": w["ctrl"]},
                                  LAYOUT["rooms"][2]]}
    preview = client.post("/v1/plans/drawing-preview", headers=w["h"], json={"layout": layout})
    assert preview.status_code == 200 and preview.headers["content-type"].startswith("image/svg+xml")
    assert "RACK ROOM" in preview.text and "B0.01 · 96 m²" in preview.text                  # 12 m × 8 m

    r = client.post(f"/v1/assets/{w['hall']}/plans/drawn", headers=w["h"], json={"layout": layout})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["source_kind"] == "drawn" and plan["name"] == "Hall B — ground floor" and plan["rooms_placed"] == 2
    assert (plan["width_px"], plan["height_px"]) == (440, 304)                     # 40 m × 20 m at 10 px a metre, margins
    image = client.get(f"/v1/plans/{plan['uid']}/image", headers=w["h"])
    assert image.status_code == 200 and "Drawn in ARGUS" in image.text
    # The rack room's record is at its room's centre: 20 px margin + 6 m, 20 px + 4 m.
    where = client.get(f"/v1/assets/{w['racks']}/indoors", headers=w["h"]).json()["placement"]
    assert (where["plan"]["uid"], where["x"], where["y"]) == (plan["uid"], 80, 60)
    # Something placed by hand on the plan.
    assert client.put(f"/v1/assets/{w['switch']}/indoors", headers=w["h"],
                      json={"plan_uid": plan["uid"], "x": 300, "y": 250}).status_code == 200

    got = client.get(f"/v1/plans/{plan['uid']}/layout", headers=w["h"]).json()
    assert got["editable"] and got["layout"]["width_m"] == 40
    assert [(x["name"], x["record"], x["x"], x["w"]) for x in got["layout"]["rooms"]] == [
        ("Rack room", w["racks"], 0, 12), ("Control room", w["ctrl"], 12, 10), ("Experimental hall", None, 0, 40)]

    # Wider control room, a new store: redrawn; the switch keeps its point, the control room's record moves to
    # its new centre, the rack room stays put.
    changed = got["layout"]
    changed["rooms"][1]["w"] = 14
    changed["rooms"].append({"name": "Spares store", "x": 30, "y": 0, "w": 6, "d": 8})
    r = client.put(f"/v1/plans/{plan['uid']}/layout", headers=w["h"], json={"layout": changed})
    assert r.status_code == 200, r.text
    assert r.json()["rooms_placed"] == 1
    assert ">SPARES" in client.get(f"/v1/plans/{plan['uid']}/image", headers=w["h"]).text
    sw = client.get(f"/v1/assets/{w['switch']}/indoors", headers=w["h"]).json()["placement"]
    assert (sw["x"], sw["y"]) == (300, 250)
    ctrl = client.get(f"/v1/assets/{w['ctrl']}/indoors", headers=w["h"]).json()["placement"]
    assert (ctrl["x"], ctrl["y"]) == (210, 60)                                     # 20 + (12 + 7) m, 20 + 4 m

    # A building made smaller than what is on it is refused.
    small = {**changed, "width_m": 20, "rooms": changed["rooms"][:1]}
    r = client.put(f"/v1/plans/{plan['uid']}/layout", headers=w["h"], json={"layout": small})
    assert r.status_code == 422 and "outside it" in r.json()["detail"]["error"]


def test_a_layout_that_cannot_be_drawn_is_refused_and_an_uploaded_drawing_is_not_redrawn():
    w = site()
    for rooms, message in (
            ([{"name": "A", "x": 0, "y": 0, "w": 6, "d": 6}, {"name": "B", "x": 5, "y": 5, "w": 4, "d": 4}], "B overlaps A"),
            ([{"name": "A", "x": 36, "y": 0, "w": 6, "d": 6}], "past the building's walls"),
            ([{"name": "", "x": 0, "y": 0, "w": 6, "d": 6}], "a name")):
        r = client.post(f"/v1/assets/{w['hall']}/plans/drawn", headers=w["h"], json={"layout": {**LAYOUT, "rooms": rooms}})
        assert r.status_code == 422 and message in r.json()["detail"]["error"], (message, r.text)
    up = client.post(f"/v1/assets/{w['hall']}/plans", headers=w["h"], files={"file": ("hall.png", png(400, 200), "image/png")})
    assert up.status_code == 201, up.text
    assert client.get(f"/v1/plans/{up.json()['uid']}/layout", headers=w["h"]).json() == {"editable": False, "layout": None}
    r = client.put(f"/v1/plans/{up.json()['uid']}/layout", headers=w["h"], json={"layout": LAYOUT})
    assert r.status_code == 422 and "uploaded drawing" in r.json()["detail"]["error"]
    db = SessionLocal()
    assert indoor.plan_layout(db.get(indoor.FloorPlan, up.json()["uid"])) is None
    db.close()
