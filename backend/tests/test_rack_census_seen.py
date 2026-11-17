"""A rack full of units, from one photo of its front (docs/rack-census.md): the units are seen top down and become
units of the survey at once — counted down from the top unit the person says — and the rack itself a new record.
The vision model is scripted."""
import json

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.intake import IntakeRun
from app.models.rack import RackMounting
from app.services import rack_census as census
from tests.test_rack_census import client, photo, put_item, site  # noqa: F401  (site is a fixture)

SEEN = {"rack": {"label": "BPM-R3", "total_units": None, "evidence": "BPM-R3 on the top panel"},
        "units": [{"kind": "Server", "manufacturer": "Halberd", "model": "R7", "label": None, "height_u": 2,
                   "gap_above_u": 0, "start_u": None, "confidence": 0.8, "evidence": "Halberd logo, two units"},
                  {"kind": "Switch", "label": "SW-12", "height_u": 1, "gap_above_u": 3, "confidence": 0.9,
                   "evidence": "SW-12 on its label"},
                  {"kind": "Oscilloscope", "height_u": 4, "gap_above_u": 1, "confidence": 0.5}]}


def sees(monkeypatch, whole=SEEN, one=None):
    def look(endpoint, image, mime, system, user, **_):
        return json.dumps(whole if system == census.UNITS_SYSTEM else (one or {}))
    monkeypatch.setattr("app.services.llm.look", look)


def test_the_units_on_a_photo_of_the_whole_rack_are_proposed_top_down(site, monkeypatch):
    w = site
    uid = client.post("/v1/rack-census", headers=w["h"], json={"place_uid": w["room"]}).json()["uid"]
    sees(monkeypatch)
    r = photo(w, uid, "rack_front")["survey"]["rack"]
    seen = r["seen"]
    assert [u["kind"] for u in seen["units"]] == ["Server", "Switch", "Oscilloscope"]
    assert seen["units"][0]["type"] == "Server" and seen["units"][2]["type"] is None   # not a type here
    assert seen["face"] == "front" and seen["taken"] == []
    assert r["proposals"]["name"]["value"] == "BPM-R3"                               # what is written on the rack
    # Only proposals: nothing is in the survey until the person takes them.
    assert client.get(f"/v1/rack-census/{uid}", headers=w["h"]).json()["items"] == []

    # Counted down from U40: 2 U at U39-40, three empty, 1 U at U35, one empty, 4 U at U30-33.
    assert census.positions(seen["units"], 40) == [39, 35, 30]
    assert census.positions(seen["units"], None) == [None, None, None]
    out = client.post(f"/v1/rack-census/{uid}/seen", headers=w["h"],
                      json={"top_u": 40, "units": [0, 1], "rack": True})
    assert out.status_code == 200, out.text
    s = out.json()
    first, second = s["items"]
    assert first["values"] == {"face": {"value": "front", "source": "rack photo"}} and first["decision"] is None
    assert first["proposals"]["start_u"]["value"] == 39 and "counted down from U40" in first["proposals"]["start_u"]["evidence"]
    assert first["proposals"]["name"]["grounded"] is False and first["proposals"]["name"]["value"] == "Halberd R7 1"
    assert first["proposals"]["product_model"]["value"] == w["model"]                 # the catalogue knows the R7
    assert second["proposals"]["name"] == {"value": "SW-12", "confidence": 0.9, "evidence": "written on it: SW-12",
                                           "grounded": True, "source": "rack photo"}
    assert s["rack"]["values"]["name"] == "BPM-R3" and s["rack"]["values"]["units"] == 40   # the rack, a new record
    # Taken once: the same units again are refused; the rest can follow.
    assert client.post(f"/v1/rack-census/{uid}/seen", headers=w["h"], json={"units": [1]}).status_code == 422
    db = SessionLocal()
    try:
        runs = db.query(IntakeRun).filter(IntakeRun.workspace_id == w["ws"], IntakeRun.operation == "rack.units").all()
        assert len(runs) == 1 and runs[0].model == "v" and runs[0].output["units"][1]["label"] == "SW-12"
    finally:
        db.close()


def test_a_rack_of_units_taken_as_read_is_saved_with_the_rack_and_its_photo(site, monkeypatch):
    w = site
    uid = client.post("/v1/rack-census", headers=w["h"], json={"place_uid": w["room"]}).json()["uid"]
    sees(monkeypatch, {"rack": {"label": "BPM-R4", "total_units": 42},
                       "units": [{"kind": "Switch", "label": f"BPM-{n}", "height_u": 1, "gap_above_u": 1,
                                  "start_u": 30 if n == 1 else None, "confidence": 0.85} for n in range(1, 5)]})
    photo(w, uid, "rack_front")
    s = client.post(f"/v1/rack-census/{uid}/seen", headers=w["h"], json={"use": True, "rack": True}).json()
    assert [(i["values"]["name"]["value"], i["values"]["start_u"]["value"], i["decision"]) for i in s["items"]] == [
        ("BPM-1", 30, "create"), ("BPM-2", 28, "create"), ("BPM-3", 26, "create"), ("BPM-4", 24, "create")]
    assert s["rack"]["values"]["units"] == 42
    review = client.get(f"/v1/rack-census/{uid}/review", headers=w["h"]).json()
    assert review["ok"], review
    done = client.post(f"/v1/rack-census/{uid}/apply", headers=w["h"])
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["rack"]["name"] == "BPM-R4" and len(out["created"]) == 4
    db = SessionLocal()
    try:
        rows = db.query(RackMounting).filter(RackMounting.rack_uid == out["rack"]["uid"],
                                             RackMounting.state == "confirmed").all()
        assert sorted(m.start_u for m in rows) == [24, 26, 28, 30]
        front = s["rack"]["seen"]["photo"]
        assert all(front in m.evidence["photos"] and m.evidence["values"]["name"]["source"] == "rack photo" for m in rows)
        assert db.get(Asset, out["rack"]["uid"]).attributes["rack_units"] == 42
    finally:
        db.close()


def test_a_unit_that_may_be_recorded_already_is_left_to_the_person(site, monkeypatch):
    w = site
    uid = client.post("/v1/rack-census", headers=w["h"], json={}).json()["uid"]
    sees(monkeypatch, {"units": [{"kind": "Server", "label": "Backup host", "height_u": 1, "start_u": 5}]})
    photo(w, uid, "rack_front")
    item = client.post(f"/v1/rack-census/{uid}/seen", headers=w["h"], json={"use": True}).json()["items"][0]
    assert item["duplicates"][0]["uid"] == w["old"] and item["decision"] is None
    put_item(w, uid, item["id"], asset_uid=w["old"])


def test_without_a_whole_rack_reading_nothing_is_taken(site, monkeypatch):
    w = site
    uid = client.post("/v1/rack-census", headers=w["h"], json={}).json()["uid"]
    sees(monkeypatch, {"units": []}, one={"name": "Rack B07"})
    r = photo(w, uid, "rack_front")["survey"]["rack"]
    assert r["seen"]["units"] == [] and "one by one" in r["seen"]["note"]
    assert client.post(f"/v1/rack-census/{uid}/seen", headers=w["h"], json={}).status_code == 422


def test_a_phone_photo_is_sent_smaller_for_the_units_and_the_wait_is_longer(monkeypatch):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4080, 3060), "grey").save(buf, "JPEG")
    small, mime = census._smaller(buf.getvalue(), "image/jpeg")
    assert mime == "image/jpeg" and max(Image.open(io.BytesIO(small)).size) == census.UNITS_SIDE
    assert census._smaller(b"not a picture", "image/png") == (b"not a picture", "image/png")
    assert census.UNITS_TIMEOUT > 120
