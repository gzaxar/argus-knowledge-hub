"""A rack surveyed from a phone (docs/rack-census.md): a new rack from its photo, new and existing units, a duplicate
recognised, a unit read from its photo with evidence and confidence, a proposed position corrected, an overlap
refused, a survey left and resumed — and all of it carried by an export and import."""
import json
import secrets
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bundle import core
from app.db import SessionLocal
from app.ledger import engine
from app.main import app
from app.models.asset import Asset
from app.models.attachment import Attachment
from app.models.llm_config import LLMConfig
from app.models.rack import RackMounting
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import indoor
from tests.test_indoor import png
from tests.test_ledger_transition import token

client = TestClient(app)
PHOTO = b"\xff\xd8\xff\xe0" + b"0" * 64


@pytest.fixture()
def site():
    t = secrets.token_hex(3)
    ws = f"census-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()
    for name in ("Room", "Product Model", "Server", "Switch"):
        db.add(Schema(uid=f"{ws}:ledger:{name.lower().replace(' ', '-')}", workspace_id=ws, name=name,
                      applies_to="objects"))
    db.flush()

    def rec(type_, name, **attrs):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=engine.ensure_type(db, ws, type_).uid,
                  key=f"{name.upper().replace(' ', '-')}-{t}", name=name, type=type_, attributes=attrs,
                  record_status="Active")
        db.add(a)
        db.flush()
        return a.uid
    w = {"ws": ws, "t": t,
         "room": rec("Room", "Server room"),
         "model": rec("Product Model", "Halberd R7 server", model_code="R7", vendor="Halberd", rack_units=2),
         "old": rec("Server", "Backup host", serial="SN-OLD"),
         "spare": rec("Switch", "Spare switch")}
    engine.ensure_type(db, ws, "Rack")
    # A Server type of this workspace's own, as the packages give it: what is written on a unit's nameplate. (Not
    # ensure_type, which could hand back a global Server another test left, and this would change it.)
    server = db.get(Schema, f"{ws}:ledger:server")
    server.attributes = [{"key": k, "name": k.title(), "type": "string"} for k in ("manufacturer", "model", "serial")]
    db.add(LLMConfig(workspace_id=ws, base_url="https://gateway.example/v1", model="m", vision_model="v",
                     enabled=True, last_check_ok=True))
    w["h"] = token(db, ws)
    db.commit()
    plan = indoor.add_plan(db, db.get(Asset, w["room"]), "room.png", png(400, 200), name="Server room plan",
                           level=None, actor="t")
    db.commit()
    w["plan"] = plan.uid
    db.close()
    return w


def reads(monkeypatch, reply: dict):
    monkeypatch.setattr("app.services.llm.look", lambda endpoint, image, mime, system, user, **_: json.dumps(reply))


def photo(w, uid, role, item=""):
    r = client.post(f"/v1/rack-census/{uid}/photos", headers=w["h"], data={"role": role, "item": item},
                    files={"file": ("p.jpg", PHOTO, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def put_item(w, uid, item, **body):
    r = client.put(f"/v1/rack-census/{uid}/items/{item}", headers=w["h"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_rack_surveyed_from_its_photos_goes_into_the_inventory(site, monkeypatch, tmp_path):
    w = site
    s = client.post("/v1/rack-census", headers=w["h"], json={"place_uid": w["room"]}).json()
    uid = s["uid"]

    # 1. The rack's front: the label read on it is a proposal; no rack has it, so a new one is proposed.
    reads(monkeypatch, {"name": "Rack B07", "key": "RK-B07", "confidence": {"name": 0.8}, "evidence": {"name": "B07"}})
    r = photo(w, uid, "rack_front")
    rack = r["survey"]["rack"]
    assert rack["proposals"]["name"]["value"] == "Rack B07" and rack["proposals"]["name"]["evidence"] == "B07"
    assert rack["candidates"] == [] and rack["record"] is None
    # 2. The person confirms its name, size, room and its point on the plan.
    assert client.put(f"/v1/rack-census/{uid}/rack", headers=w["h"], json={"values": {
        "name": "Rack B07", "units": 42, "place_uid": w["room"], "plan_uid": w["plan"], "x": 120, "y": 80,
        "position_confirmed": True}}).status_code == 200

    # 3. A unit: what is read comes back as proposals with their evidence; the catalogue says how tall it is.
    reads(monkeypatch, {"type": "Server", "name": "Compute node 7", "attributes": {
        "manufacturer": "Halberd", "model": "R7", "serial": "SN-NEW-7"},
        "confidence": {"attributes.serial": 0.95, "name": 0.6}, "evidence": {"attributes.serial": "S/N SN-NEW-7"}})
    r = photo(w, uid, "device")
    a = r["item"]
    item = next(i for i in r["survey"]["items"] if i["id"] == a)
    p = item["proposals"]
    assert p["serial"]["value"] == "SN-NEW-7" and p["serial"]["confidence"] == 0.95 and p["serial"]["evidence"] == "S/N SN-NEW-7"
    assert p["height_u"] == {"value": 2, "confidence": 0.9, "grounded": True, "evidence": "catalogue: Halberd R7 server is 2 U",
                             "source": "catalogue"}
    assert "start_u" not in p and item["values"] == {}          # nothing taken for the person, no unit invented
    # Its label, photographed apart, is read for the unit's own identity.
    reads(monkeypatch, {"attributes": {"serial": "SN-NEW-7B"}, "confidence": {"attributes.serial": 0.99},
                        "evidence": {"attributes.serial": "SN-NEW-7B"}})
    r = photo(w, uid, "label", item=a)
    item = next(i for i in r["survey"]["items"] if i["id"] == a)
    assert item["proposals"]["serial"]["value"] == "SN-NEW-7B" and item["proposals"]["serial"]["source"] == "label"
    put_item(w, uid, a, decision="create", values={
        "type": {"value": "Server", "source": "photo"}, "name": "Compute node 7",
        "serial": {"value": "SN-NEW-7B", "source": "label", "confidence": 0.99},
        "product_model": {"value": w["model"], "source": "catalogue"},
        "height_u": {"value": 2, "source": "catalogue"}})

    # 4. A unit whose photo shows the serial of one already recorded: a possible duplicate.
    reads(monkeypatch, {"type": "Server", "name": "Backup", "attributes": {"serial": "SN-OLD"},
                        "confidence": {"attributes.serial": 0.9}, "evidence": {"attributes.serial": "SN-OLD"}})
    r = photo(w, uid, "device")
    b = r["item"]
    dup = next(i for i in r["survey"]["items"] if i["id"] == b)["duplicates"]
    assert dup[0]["uid"] == w["old"] and dup[0]["strength"] == "strong" and "SN-OLD" in dup[0]["why"]
    put_item(w, uid, b, decision="create", values={"type": "Server", "name": "Backup", "height_u": 1, "start_u": 10})

    # 5. An existing unit, chosen; nothing read (no photo needed).
    reads(monkeypatch, {})
    c = photo(w, uid, "device")["item"]
    put_item(w, uid, c, asset_uid=w["spare"], values={"start_u": 10, "height_u": 1})

    review = client.get(f"/v1/rack-census/{uid}/review", headers=w["h"]).json()
    assert not review["ok"]
    said = {m["field"]: m["message"] for m in review["missing"]}
    assert "was not read — type it" in said["start_u"]                  # the first unit: no U was read
    assert "may already be" in said["duplicate"]                         # the second: SN-OLD
    assert [p["code"] for p in review["problems"]] == ["overlap"]        # the second and the third at U10
    assert client.post(f"/v1/rack-census/{uid}/apply", headers=w["h"]).status_code == 409   # and nothing is made
    db = SessionLocal()
    assert db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.name == "Rack B07").count() == 0
    db.close()

    # 6. The person resolves it: types the first unit's U, links the duplicate to the record it is, corrects a U.
    put_item(w, uid, a, values={"start_u": 20})
    put_item(w, uid, b, asset_uid=w["old"])
    put_item(w, uid, c, values={"start_u": 12})
    review = client.get(f"/v1/rack-census/{uid}/review", headers=w["h"]).json()
    assert review["ok"], review
    assert review["changes"] == ["Compute node 7: U20–U21 front", "Backup: U10 front", "unit 3: U12 front"] or \
        len(review["changes"]) == 3

    # Left and resumed: it is listed as open until applied.
    assert [o["uid"] for o in client.get("/v1/rack-census", headers=w["h"]).json()] == [uid]
    done = client.post(f"/v1/rack-census/{uid}/apply", headers=w["h"])
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["rack"]["name"] == "Rack B07" and [x["name"] for x in out["created"]] == ["Compute node 7"]
    assert client.get("/v1/rack-census", headers=w["h"]).json() == []

    db = SessionLocal()
    rack = db.get(Asset, out["rack"]["uid"])
    assert rack.attributes["rack_units"] == 42
    spot = indoor.current(db, rack.uid)
    assert (spot.place_uid, spot.plan_uid, spot.plan_x, spot.plan_y) == (w["room"], w["plan"], 120, 80)
    new = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.name == "Compute node 7").one()
    assert new.attributes["serial"] == "SN-NEW-7B" and new.attributes["product_model"] == w["model"]
    rows = {m.asset_uid: m for m in db.query(RackMounting).filter(RackMounting.rack_uid == rack.uid,
                                                                  RackMounting.state == "confirmed")}
    assert (rows[new.uid].start_u, rows[new.uid].height_u, rows[new.uid].source) == (20, 2, "census")
    assert rows[new.uid].evidence["values"]["serial"] == {"source": "label", "confidence": 0.99}
    assert set(rows) == {new.uid, w["old"], w["spare"]}
    photos = {x.asset_uid for x in db.query(Attachment).filter(Attachment.workspace_id == w["ws"])}
    assert {rack.uid, new.uid, w["old"], w["spare"]} <= photos            # each photo on what it shows
    db.close()

    # 7. Exported and imported elsewhere: the same rack, units and photos.
    db = SessionLocal()
    out_dir = tmp_path / "bundle"
    core.export(db, w["ws"], out_dir, actor="t")
    db.close()
    other = f"census-copy-{secrets.token_hex(3)}"
    db = SessionLocal()
    rep = core.apply(db, core.read(out_dir), workspace_id=other, name="copy", actor="t", dry_run=False,
                     files_root=tmp_path / "files")
    assert rep.view()["ok"], rep.view()
    db.commit()
    copied = db.query(RackMounting).filter(RackMounting.workspace_id == other, RackMounting.state == "confirmed").count()
    files = db.query(Attachment).filter(Attachment.workspace_id == other, Attachment.asset_uid.is_not(None)).count()
    assert copied == 3 and files >= 4
    db.close()


def test_without_a_vision_model_nothing_is_proposed_and_everything_is_typed(site):
    w = site
    db = SessionLocal()
    db.get(LLMConfig, w["ws"]).vision_model = None
    db.commit()
    db.close()
    uid = client.post("/v1/rack-census", headers=w["h"], json={}).json()["uid"]
    r = photo(w, uid, "device")
    item = r["survey"]["items"][0]
    assert item["proposals"] == {} and "fill in what you see" in item["note"]
    assert client.delete(f"/v1/rack-census/{uid}", headers=w["h"]).json()["state"] == "abandoned"
    assert client.post(f"/v1/rack-census/{uid}/photos", headers=w["h"], data={"role": "device"},
                       files={"file": ("p.jpg", PHOTO, "image/jpeg")}).status_code == 422
