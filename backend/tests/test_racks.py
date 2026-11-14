"""Rack elevations (docs/rack-elevation.md): a unit takes units on a face, nothing overlaps or sticks out, a change
is previewed before it is made, and a move leaves its trace."""
import secrets

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ledger import engine
from app.main import app
from app.models.asset import Asset
from app.models.workspace import Workspace
from tests.test_ledger_transition import token

client = TestClient(app)


@pytest.fixture()
def world():
    ws = f"rack-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()

    def asset(type_, name, **attrs):
        a = Asset(uid=f"{name.lower().replace(' ', '-')}-{ws}", workspace_id=ws,
                  schema_uid=engine.ensure_type(db, ws, type_).uid, key=f"{name.upper().replace(' ', '-')}-{ws}",
                  name=name, type=type_, attributes=attrs)
        db.add(a)
        db.flush()
        return a.uid

    w = {"ws": ws, "rack": asset("Rack", "Rack A", rack_units=12), "other": asset("Rack", "Rack B", rack_units=12),
         "model": asset("Product Model", "Big server model", rack_units=2)}
    w["server"] = asset("Server", "Server one", product_model=w["model"], serial="S-1")
    w["switch"] = asset("Switch", "Switch one")
    w["pdu"] = asset("Equipment", "PDU left")
    w["kvm"] = asset("Equipment", "KVM drawer")
    w["headers"] = token(db, ws)
    db.commit()
    db.close()
    return w


def go(w, ops, rack="rack", how="apply"):
    return client.post(f"/v1/racks/{w[rack]}/{how}", headers=w["headers"], json={"operations": ops})


def test_a_unit_takes_its_units_and_the_model_suggests_the_height(world):
    w = world
    found = client.get("/v1/racks/candidates", headers=w["headers"], params={"q": "S-1"}).json()
    assert found[0]["uid"] == w["server"] and found[0]["suggested_height_u"] == 2 and found[0]["mounted"] is None
    r = go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 3}])      # no height: the model's
    assert r.status_code == 200, r.text
    view = r.json()["elevation"]
    m = view["mountings"][0]
    assert (m["start_u"], m["height_u"], m["top_u"], m["face"]) == (3, 2, 4, "front")
    assert view["used_units"] == {"front": 2, "rear": 0}
    assert view["free"]["front"] == [{"from_u": 1, "to_u": 2, "units": 2}, {"from_u": 5, "to_u": 12, "units": 8}]
    # The suggestion is only that: the person mounting it says 3.
    r = go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 3, "height_u": 3}])
    assert r.json()["elevation"]["mountings"][0]["top_u"] == 5
    at = client.get(f"/v1/racks/of/{w['server']}", headers=w["headers"]).json()
    assert at["rack"]["uid"] == w["rack"] and at["start_u"] == 3 and at["height_u"] == 3


def test_overlaps_and_what_sticks_out_are_refused_and_nothing_is_written(world):
    w = world
    assert go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 3, "height_u": 2}]).status_code == 200
    clash = go(w, [{"op": "place", "asset_uid": w["switch"], "start_u": 4, "height_u": 1}])
    assert clash.status_code == 409
    p = clash.json()["detail"]["problems"][0]
    assert p["code"] == "overlap" and "U4" in p["message"] and "Server one" in p["message"]
    out = go(w, [{"op": "place", "asset_uid": w["switch"], "start_u": 12, "height_u": 2}])
    assert out.status_code == 409 and out.json()["detail"]["problems"][0]["code"] == "capacity"
    assert len(client.get(f"/v1/racks/{w['rack']}", headers=w["headers"]).json()["mountings"]) == 1
    # The rear of the same units is free; a unit through both faces is not.
    assert go(w, [{"op": "place", "asset_uid": w["switch"], "start_u": 4, "face": "rear"}]).status_code == 200
    both = go(w, [{"op": "place", "asset_uid": w["kvm"], "start_u": 4, "face": "both"}])
    assert both.status_code == 409 and len(both.json()["detail"]["problems"]) == 2


def test_a_preview_says_what_would_change_and_changes_nothing(world):
    w = world
    go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 1, "height_u": 2}])
    pre = go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 5, "height_u": 2},
                 {"op": "place", "asset_uid": w["switch"], "start_u": 1}], how="preview").json()
    assert pre["ok"] and [c["text"] for c in pre["changes"]] == ["Server one: U1–U2 front → U5–U6 front",
                                                                 "Switch one: U1 front"]
    assert len(pre["elevation"]["mountings"]) == 2
    now = client.get(f"/v1/racks/{w['rack']}", headers=w["headers"]).json()
    assert [(m["asset"]["uid"], m["start_u"]) for m in now["mountings"]] == [(w["server"], 1)]
    bad = go(w, [{"op": "place", "asset_uid": w["switch"], "start_u": 2}], how="preview").json()
    assert not bad["ok"] and bad["problems"][0]["code"] == "overlap"


def test_shelves_zero_u_devices_and_reserved_space(world):
    w = world
    r = go(w, [{"op": "shelf", "start_u": 6, "height_u": 2, "label": "Shelf for small boxes", "ref": "shelf-1"},
               {"op": "place", "asset_uid": w["kvm"], "shelf_uid": "shelf-1"},
               {"op": "place", "asset_uid": w["pdu"], "kind": "zero_u", "face": "rear"},
               {"op": "reserve", "start_u": 10, "height_u": 3, "label": "For the second switch"}])
    assert r.status_code == 200, r.text
    view = r.json()["elevation"]
    kinds = sorted(m["kind"] for m in view["mountings"])
    assert kinds == ["device", "reserved", "shelf", "zero_u"]
    assert view["used_units"]["front"] == 5                       # the shelf and the reserved space; not what stands on it
    taken = go(w, [{"op": "place", "asset_uid": w["switch"], "start_u": 11}])
    assert taken.status_code == 409 and "For the second switch" in taken.json()["detail"]["problems"][0]["message"]
    shelf = next(m for m in view["mountings"] if m["kind"] == "shelf")
    carries = go(w, [{"op": "remove", "mounting_uid": shelf["uid"]}])
    assert carries.status_code == 422 and "still carries" in carries.text


def test_a_move_to_another_rack_leaves_its_trace(world):
    w = world
    go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 1, "height_u": 2}])
    moved = go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 7, "height_u": 2}], rack="other")
    assert moved.status_code == 200 and "Rack A, U1–U2 front → U7–U8 front" in moved.json()["changes"][0]["text"]
    assert client.get(f"/v1/racks/{w['rack']}", headers=w["headers"]).json()["mountings"] == []
    past = client.get(f"/v1/racks/{w['rack']}/history", headers=w["headers"]).json()
    assert [(h["state"], h["start_u"], bool(h["until"])) for h in past] == [("superseded", 1, True)]
    gone = go(w, [{"op": "remove", "asset_uid": w["server"]}], rack="other")
    assert gone.status_code == 200
    assert client.get(f"/v1/racks/of/{w['server']}", headers=w["headers"]).json() is None
    states = [h["state"] for h in client.get(f"/v1/racks/{w['other']}/history", headers=w["headers"]).json()]
    assert states == ["removed"]


def test_what_is_not_a_rack_and_a_rack_in_a_rack_are_refused(world):
    w = world
    assert client.get(f"/v1/racks/{w['server']}", headers=w["headers"]).status_code == 404
    r = go(w, [{"op": "place", "asset_uid": w["other"], "start_u": 1}])
    assert r.status_code == 422 and "not mounted in a rack" in r.text


def test_racks_travel_in_a_workspace_bundle(world, tmp_path):
    """Exported and imported elsewhere, a rack keeps what is mounted where and its past."""
    from app.bundle import core
    w = world
    go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 1, "height_u": 2},
           {"op": "reserve", "start_u": 10, "height_u": 2, "label": "kept"}])
    go(w, [{"op": "place", "asset_uid": w["server"], "start_u": 5, "height_u": 2}])
    db = SessionLocal()
    try:
        core.export(db, w["ws"], tmp_path / "out", actor="test")
    finally:
        db.close()
    copy = f"rack-copy-{secrets.token_hex(3)}"
    db = SessionLocal()
    try:
        rep = core.apply(db, core.read(tmp_path / "out"), workspace_id=copy, name="copy", actor=None, dry_run=False,
                         files_root=tmp_path / "files")
        assert rep.view()["ok"], rep.view()["blockers"]
        db.commit()
        from sqlalchemy import select
        from app.models.rack import RackMounting
        rows = list(db.scalars(select(RackMounting).where(RackMounting.workspace_id == copy)))
        live = sorted((r.kind, r.start_u) for r in rows if r.state == "confirmed")
        assert live == [("device", 5), ("reserved", 10)]
        assert sorted(r.state for r in rows) == ["confirmed", "confirmed", "superseded"]
        racks_copy = {r.rack_uid for r in rows}
        from app.models.asset import Asset
        assert all(db.get(Asset, uid).workspace_id == copy for uid in racks_copy)
    finally:
        db.close()
