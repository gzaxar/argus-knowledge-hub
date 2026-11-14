"""The tunnel along a beam path (docs/plan-layers.md): elements by s, the hardware installed at each, its room, the
supply that powers it and that supply's rack, its open tickets; rooms crossed as bands along s."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ledger import service
from app.main import app
from app.models.asset import Asset, Relation
from app.models.issue import Issue
from app.models.schema import Schema
from app.services import beam_model as bm
from app.services import indoor
from tests.test_beam_model import db, el, path, world  # noqa: F401 — the same imported models

client = TestClient(app)


def test_the_tunnel_says_what_is_installed_along_s_and_where_it_is(world, db):  # noqa: F811
    ws = world["ws"]
    types = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}

    def rec(name, type_):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types[type_], key=f"{ws}:{name}", name=name,
                  type=type_, attributes={"serial": f"SN-{name}"} if type_ == "Magnet Assembly" else {})
        db.add(a)
        db.flush()
        return a
    magnet, psu = rec("QUA01", "Magnet Assembly"), rec("PS-Q1", "Power Supply")
    rack, hall = rec("RK-1", "Rack"), rec("Linac hall", "Area")
    db.commit()
    q = el(db, ws, "QUA01")
    bm.propose_bindings(db, ws)
    db.commit()
    proposal = next(b for b in bm.bindings(db, ws) if b["position"]["uid"] == q.uid)
    service.confirm_installation(db, ws, "test", proposal["installation_uid"],
                                 valid_from={"kind": "date", "nominal": "2025-01-01T00:00:00+00:00", "precision": "instant"})
    indoor.place(db, magnet, place_uid=hall.uid, actor="test")
    indoor.place(db, rack, place_uid=hall.uid, actor="test")
    db.add_all([Relation(workspace_id=ws, from_asset_uid=psu.uid, to_asset_uid=magnet.uid, relation_type="powers"),
                Relation(workspace_id=ws, from_asset_uid=psu.uid, to_asset_uid=rack.uid, relation_type="located in"),
                Issue(uid=str(uuid.uuid4()), workspace_id=ws, asset_uid=magnet.uid, title="Coil warm", state="new")])
    db.commit()

    r = client.get(f"/v1/beam-paths/{path(db, ws, 'Linac').uid}/tunnel", headers=world["h"])
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["with_s"] and [e["s"] for e in t["elements"]] == sorted(e["s"] for e in t["elements"])
    e = next(x for x in t["elements"] if x["name"] == "QUA01")
    hw = e["hardware"][0]
    assert (hw["name"], hw["serial"], hw["room"]["name"], hw["rack"]) == ("QUA01", "SN-QUA01", "Linac hall", None)
    assert [(s["name"], s["rack"]["name"], s["room"]["name"]) for s in hw["supplies"]] == [("PS-Q1", "RK-1", "Linac hall")]
    assert [x["title"] for x in hw["tickets"]] == ["Coil warm"]
    # Nothing else is installed: those elements are positions only.
    assert all(x["hardware"] == [] for x in t["elements"] if x["name"] != "QUA01")
    assert t["rooms"] == [{"uid": hall.uid, "key": hall.key, "name": "Linac hall", "type": "Area",
                           "from_s": e["s"], "to_s": e["s"] + (e["length"] or 0)}]
