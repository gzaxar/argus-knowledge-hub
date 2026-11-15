"""Which hardware a control channel drives: proposed from the naming convention and the network, confirmed
by a person, then IOC → hardware `drives` derived (control_binding)."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.ledger import control_binding as cb
from app.ledger import service
from app.main import app
from app.models.asset import Asset, Relation
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services.asset_types import ensure_asset_types
from tests.confirm import typed

client = TestClient(app)


def test_tags_parse_in_both_spellings():
    assert cb.parse_tag("FI33-V-PMP-TRB-001") == ("FI33", {"V", "PMP", "TRB"}, 1)
    assert cb.parse_tag("FI33TRB01") == ("FI33", {"TRB"}, 1)
    assert cb.parse_tag("FI8-HMN-02") == ("FI8", {"HMN"}, 2)
    assert cb.parse_tag("SIM01") is None


@pytest.fixture()
def beamline():
    t = secrets.token_hex(3)
    ws = f"ctl-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()
    ensure_asset_types(db, ws)
    types = {s.name: s.uid for s in db.query(Schema).filter(Schema.workspace_id == ws)}
    admin = User(id=str(uuid.uuid4()), email=f"ctl-{t}@argus.test", is_admin=True)
    db.add(admin)
    uids = {}

    def make(type_name, name, **attrs):
        uid = str(uuid.uuid4())
        service.create_record(db, ws, "test", uid=uid, schema_uid=types[type_name], key=f"{name}-{t}", name=name,
                              type_name=type_name, attributes=attrs)
        uids[name] = uid
        return uid

    make("Turbo Pump", "FI33-V-PMP-TRB-001")
    make("Motor Axis", "FI8-W-MOT-HMN-002")
    make("Camera", "FI8-B-CAM-VIS-006")
    make("Address Record", "FI8-B-CAM-VIS-006 address", hostname="cceuapscam14", record_kind="Ethernet configuration")
    make("Vacuum Gauge", "FP2-V-VUG-FR-001")
    make("Vacuum Gauge", "FP2-V-VUG-PI-001")                 # two gauges share zone, code and number
    ioc = make("IOC", "agilent-twistorr-305-fi-02")
    make("Control Device", "FI33TRB01", pv="EUAPS:FICTR1:VAC:02:FI33TRB01")
    make("Control Device", "FI8-HMN-02", pv="EUAPS:FIRCK2:W:CTR:FI8-HMN-02")
    make("Control Device", "FI8-CAM-06", address="cceuapscam14.lnf.infn.it")
    make("Control Device", "FP2VUG01")
    make("Control Device", "SIM01")
    make("Access Point", "cceuapscam14", hostname="cceuapscam14", endpoint_kind="Camera")
    service.relate(db, ws, "test", uids["FI8-B-CAM-VIS-006"], "described by", uids["FI8-B-CAM-VIS-006 address"])
    for device in ("FI33TRB01", "FI8-HMN-02"):
        service.relate(db, ws, "test", uids[device], "provided by", ioc)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"ws": ws, "uids": uids, "h": {"X-Workspace-Id": ws}}
    client.delete(f"/v1/workspaces/{ws}", headers=typed(ws))
    app.dependency_overrides.pop(get_identity, None)


def edges(ws, kind):
    db = SessionLocal()
    out = {(db.get(Asset, r.from_asset_uid).name, db.get(Asset, r.to_asset_uid).name)
           for r in db.query(Relation).filter(Relation.workspace_id == ws, Relation.relation_type == kind)}
    db.close()
    return out


def test_channels_are_proposed_to_their_hardware_and_bound_only_once_confirmed(beamline):
    b = beamline
    report = client.post("/v1/ledger/control-bindings/propose", headers=b["h"]).json()
    assert report["by_tag"] == 3 and report["by_host"] == 0
    assert [a["device"] for a in report["ambiguous"]] == ["FP2VUG01"]                 # two gauges FP2 VUG 1
    assert [u["device"] for u in report["unmatched"]] == ["SIM01"]
    pending = client.get("/v1/ledger/control-bindings", headers=b["h"]).json()
    pairs = {(p["subject"]["name"], p["predicate"], p["target"]["name"]) for p in pending}
    assert pairs == {("FI33TRB01", "acts on", "FI33-V-PMP-TRB-001"), ("FI8-HMN-02", "acts on", "FI8-W-MOT-HMN-002"),
                     ("FI8-CAM-06", "acts on", "FI8-B-CAM-VIS-006"),
                     ("cceuapscam14", "implemented by", "FI8-B-CAM-VIS-006")}
    camera = next(p for p in pending if p["subject"]["name"] == "FI8-CAM-06")
    assert camera["confidence"] == 0.95 and "network address" in camera["evidence"]["matched_on"]
    assert edges(b["ws"], "acts on") == set()                                         # proposed, not effective

    # A re-run with nothing new changes nothing.
    client.post("/v1/ledger/control-bindings/propose", headers=b["h"])
    assert len(client.get("/v1/ledger/control-bindings", headers=b["h"]).json()) == 4

    out = client.post("/v1/ledger/control-bindings/decide", headers=b["h"], json={"min_confidence": 0.9}).json()
    assert out == {"decided": 3}
    assert edges(b["ws"], "acts on") == {("FI33TRB01", "FI33-V-PMP-TRB-001"), ("FI8-HMN-02", "FI8-W-MOT-HMN-002"),
                                         ("FI8-CAM-06", "FI8-B-CAM-VIS-006")}
    # B: the IOC drives the hardware of its devices, derived from provided by + acts on.
    assert edges(b["ws"], "drives") == {("agilent-twistorr-305-fi-02", "FI33-V-PMP-TRB-001"),
                                        ("agilent-twistorr-305-fi-02", "FI8-W-MOT-HMN-002")}
    left = client.get("/v1/ledger/control-bindings", headers=b["h"]).json()
    assert [p["predicate"] for p in left] == ["implemented by"]                       # 0.85: one by one
    client.post("/v1/ledger/control-bindings/decide", headers=b["h"],
                json={"claim_ids": [left[0]["claim_id"]], "accept": False, "reason": "not this camera"})
    assert client.get("/v1/ledger/control-bindings", headers=b["h"]).json() == []
    assert ("cceuapscam14", "FI8-B-CAM-VIS-006") not in edges(b["ws"], "implemented by")
