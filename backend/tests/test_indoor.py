"""Indoors: a place's floors, its floor plans (from an image, an SVG, a PDF or a DXF), placing a plan on the map by
control points (two keep its shape; three or more give each point's residual, so a mis-clicked one shows), records
placed in a room or at a point of a plan (which gives them their position), what a room holds and what a record
is in, and a vague GPS fix that does not disturb a record placed indoors."""
import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.services import asset_types, indoor, spatial
from tests.test_spatial import world  # noqa: F401 — the same workspaces, records and token

client = TestClient(app)

# A 1000 × 500 px plan of a hall 100 m × 50 m (0.1 m a pixel), its top edge along east, near LNF.
LON0, LAT0 = 12.6720, 41.8222
KX = 111_320 * 0.74488            # metres per degree of longitude at 41.82° (cos 41.82° ≈ 0.7449)
KY = 110_540


def at(x, y):
    """The longitude and latitude of a pixel of that plan."""
    return LON0 + (x * 0.1) / KX, LAT0 - (y * 0.1) / KY


def cp(x, y, shift_m=0.0):
    lon, lat = at(x, y)
    return {"x": x, "y": y, "longitude": lon + shift_m / KX, "latitude": lat}


def png(w=1000, h=500):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


def test_a_plan_is_fitted_to_the_map_and_a_wrong_point_shows():
    two = indoor.fit([cp(0, 0), cp(1000, 500)], 1000, 500)
    assert two["residual_m"] == 0 and two["metres_per_px"] == pytest.approx(0.1, rel=1e-3)
    lon, lat = indoor.to_lonlat(two["transform"], 1000, 0)                 # not mirrored: top right is east
    assert lon == pytest.approx(at(1000, 0)[0], abs=1e-6) and lat == pytest.approx(at(1000, 0)[1], abs=1e-6)
    good = indoor.fit([cp(0, 0), cp(1000, 0), cp(0, 500), cp(1000, 500)], 1000, 500)
    assert good["residual_m"] < 0.05
    x, y = indoor.to_plan(good["transform"], *at(250, 125))
    assert (round(x), round(y)) == (250, 125)
    bad = indoor.fit([cp(0, 0), cp(1000, 0), cp(0, 500), cp(1000, 500, shift_m=8)], 1000, 500)
    assert bad["residual_m"] > 1 and max(bad["residuals_m"]) == bad["residuals_m"][3]
    for points, message in (([cp(0, 0)], "two control points"), ([cp(0, 0), cp(500, 0), cp(1000, 0)], "in a line"),
                            ([cp(0, 0), cp(2000, 0)], "outside the plan"), ([cp(0, 0), cp(0, 0)], "same place")):
        with pytest.raises(indoor.IndoorError, match=message):
            indoor.fit(points, 1000, 500)


def test_plans_come_from_images_svg_pdf_and_drawings():
    _, mime, w, h, kind = indoor.picture("floor.png", png(800, 400))
    assert (mime, w, h, kind) == ("image/png", 800, 400, "image")
    _, mime, w, h, _ = indoor.picture("floor.gif", _gif())
    assert mime == "image/png" and (w, h) == (20, 10)                       # anything else becomes a PNG
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600"><rect width="10" height="10"/></svg>'
    assert indoor.picture("hall.svg", svg)[1:4] == ("image/svg+xml", 1200, 600)
    from fpdf import FPDF
    pdf = FPDF(orientation="L", format="A4")
    pdf.add_page()
    pdf.rect(10, 10, 100, 50)
    _, mime, w, h, kind = indoor.picture("plan.pdf", bytes(pdf.output()))
    assert (mime, kind) == ("image/png", "pdf") and w > h and max(w, h) == indoor.PDF_LONG_SIDE_PX
    import ezdxf
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True)
    stream = io.StringIO()
    doc.write(stream)
    _, mime, w, h, kind = indoor.picture("hall.dxf", stream.getvalue().encode())
    assert (mime, kind) == ("image/svg+xml", "dxf") and w > 0 and h > 0
    for name, data in (("x.docx", b"PK"), ("empty.png", b""), ("bad.pdf", b"%PDF-broken")):
        with pytest.raises(indoor.IndoorError):
            indoor.picture(name, data)


def _gif():
    from PIL import Image
    out = io.BytesIO()
    Image.new("P", (20, 10)).save(out, "GIF")
    return out.getvalue()


def _unit(w, key, type_name):
    db = SessionLocal()
    a = Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=asset_types.type_uid(w["ws"], type_name),
              key=key, name=key, type=type_name, attributes={}, record_status="Active")
    db.add(a)
    db.commit()
    uid = a.uid
    db.close()
    return uid


def test_floors_plans_and_equipment_placed_on_them(world):
    h = world["headers"]
    building, hall, room = _unit(world, "BLD-B", "Building"), _unit(world, "HALL-B1", "Area"), _unit(world, "ROOM-12", "Area")
    ground = client.post(f"/v1/assets/{building}/levels", headers=h, json={"name": "Ground floor", "ordinal": 0,
                                                                             "elevation_m": 0, "height_m": 6})
    assert ground.status_code == 201, ground.text
    first = client.post(f"/v1/assets/{building}/levels", headers=h, json={"name": "First floor", "ordinal": 1}).json()
    again = client.post(f"/v1/assets/{building}/levels", headers=h, json={"name": "Ground floor", "ordinal": 2})
    assert again.status_code == 422 and "already" in again.json()["detail"]["error"]
    up = client.post(f"/v1/assets/{building}/plans", headers=h, data={"name": "Ground floor plan",
                                                                       "level_uid": ground.json()["uid"]},
                     files={"file": ("ground.png", png(), "image/png")})
    assert up.status_code == 201, up.text
    plan = up.json()
    assert (plan["width_px"], plan["height_px"], plan["level"]["name"], plan["corners"]) == (1000, 500, "Ground floor", None)
    img = client.get(f"/v1/plans/{plan['uid']}/image", headers=h)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    listing = client.get(f"/v1/assets/{building}/levels", headers=h).json()
    assert [lv["name"] for lv in listing["levels"]] == ["Ground floor", "First floor"] and len(listing["plans"]) == 1

    placed_plan = client.put(f"/v1/plans/{plan['uid']}/placement", headers=h,
                             json={"points": [cp(0, 0), cp(1000, 0), cp(0, 500), cp(1000, 500)]})
    assert placed_plan.status_code == 200, placed_plan.text
    assert placed_plan.json()["residual_m"] < 0.05 and len(placed_plan.json()["corners"]) == 4

    # Rooms in the hall, in the building; the pump in the room, at a point of the plan.
    assert client.put(f"/v1/assets/{hall}/indoors", headers=h, json={"place_uid": building,
                                                                    "level_uid": ground.json()["uid"]}).status_code == 200
    assert client.put(f"/v1/assets/{room}/indoors", headers=h, json={"place_uid": hall}).status_code == 200
    put = client.put(f"/v1/assets/{world['pump']}/indoors", headers=h,
                     json={"place_uid": room, "plan_uid": plan["uid"], "x": 250, "y": 125})
    assert put.status_code == 200, put.text
    assert put.json()["level"]["name"] == "Ground floor"                     # the plan's floor
    where = client.get(f"/v1/assets/{world['pump']}/indoors", headers=h).json()
    assert [c["key"] for c in where["in"]] == ["ROOM-12", "HALL-B1", "BLD-B"]
    loc = client.get(f"/v1/assets/{world['pump']}/location", headers=h).json()["location"]
    lon, lat = at(250, 125)
    assert loc["source"] == "plan" and loc["longitude"] == pytest.approx(lon, abs=1e-6)
    assert loc["latitude"] == pytest.approx(lat, abs=1e-6)
    on_plan = client.get(f"/v1/plans/{plan['uid']}", headers=h).json()["placed"]
    assert [(p["uid"], p["x"], p["y"]) for p in on_plan] == [(world["pump"], 250, 125)]
    assert [c["uid"] for c in client.get(f"/v1/assets/{room}/indoors", headers=h).json()["contents"]] == [world["pump"]]
    ctx = client.get(f"/v1/assets/{world['pump']}/location/context", headers=h).json()
    assert {(i["uid"], i["role"]) for i in ctx["within"]} >= {(room, "indoors"), (hall, "indoors"), (building, "indoors")}
    assert (world["pump"], "indoors") in {(i["uid"], i["role"]) for i in
                                         client.get(f"/v1/assets/{room}/location/context", headers=h).json()["inside"]}

    loop = client.put(f"/v1/assets/{building}/indoors", headers=h, json={"place_uid": room})
    assert loop.status_code == 422 and "inside what is inside it" in loop.json()["detail"]["error"]
    outside = client.put(f"/v1/assets/{world['far']}/indoors", headers=h, json={"plan_uid": plan["uid"], "x": 5000, "y": 1})
    assert outside.status_code == 422

    # Indoors, a vague GPS fix is noted, not sent to review; a precise one still is.
    vague = client.post(f"/v1/assets/{world['pump']}/location/observations", headers=h,
                        json={"latitude": 41.83, "longitude": 12.68, "accuracy_m": 25}).json()
    assert vague["status"] == "noted" and "indoors" in vague["note"]
    sharp = client.post(f"/v1/assets/{world['pump']}/location/observations", headers=h,
                        json={"latitude": 41.83, "longitude": 12.68, "accuracy_m": 3}).json()
    assert sharp["status"] == "pending"

    view = client.get("/v1/map/plans", headers=h, params={"bbox": "12.67,41.82,12.68,41.83"}).json()
    assert [p["uid"] for p in view] == [plan["uid"]]
    assert client.get("/v1/map/plans", headers=h, params={"bbox": "12.0,41.0,12.1,41.1"}).json() == []
    assert client.delete(f"/v1/levels/{first['uid']}", headers=h).status_code == 204


def test_a_plan_of_a_place_one_may_not_see_is_not_shown(world):
    db = SessionLocal()
    secret = db.get(Asset, world["secret"])                               # its location is restricted
    plan = indoor.add_plan(db, secret, "s.png", png(10, 10), name="Secret store", level=None, actor="test")
    db.commit()
    uid = plan.uid
    db.close()
    assert client.get(f"/v1/plans/{uid}", headers=world["headers"]).status_code == 404
    assert client.get(f"/v1/plans/{uid}/image", headers=world["headers"]).status_code == 404


def test_a_vague_fix_of_a_record_placed_only_outdoors_still_goes_to_review(world):
    db = SessionLocal()
    a = db.get(Asset, world["far"])
    spatial.set_location(db, a, spatial.point(41.9, 12.5), actor="test")
    db.commit()
    db.close()
    obs = client.post(f"/v1/assets/{world['far']}/location/observations", headers=world["headers"],
                      json={"latitude": 41.8, "longitude": 12.6, "accuracy_m": 25}).json()
    assert obs["status"] == "pending"
