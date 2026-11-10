"""Beamline asset synchronization in the hub (docs/beam-asset-sync.md) and the v2 model's own endpoints.

The DAΦNE-accumulator-like ring (argus.beam-model/2) is imported by a person; the mock assets of
`ring_assets.json` become physical records of the workspace; a corrector is already bound by a person, and a
kicker is bound to a unit that has since been retired. Then: preview writes nothing, apply records decisions as
Installations, confirmed bindings survive later syncs, rejected pairs stay rejected, a replaced unit is a swap
that leaves the position's identity alone, and everything travels in the v2 export.
"""
import json
import secrets
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.ledger import engine, service
from app.main import app
from app.models.asset import Asset, Relation
from app.models.beam_model import BeamAssetBinding
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import beam_asset_sync as sync
from app.services import beam_model as bm
from app.services.asset_types import ensure_asset_types

FX = Path(__file__).parent / "fixtures" / "beam_model"
client = TestClient(app)
WHEN = {"kind": "date", "nominal": "2025-01-01T00:00:00+00:00", "precision": "instant"}


def load(name):
    return json.loads((FX / name).read_text())


@pytest.fixture()
def ring():
    t = secrets.token_hex(4)
    ws = f"sync-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Asset sync"))
    db.flush()
    ensure_asset_types(db, ws)
    admin = User(id=str(uuid.uuid4()), email=f"sync-{t}@argus.test", is_admin=True)
    db.add(admin)
    engine.activate_policy(db)
    report = bm.import_canonical(db, ws, load("ring.beam.json"), "person", trusted=True)
    assert report["state"] == "published" and report["format"] == "2"
    types = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}
    fx = load("ring_assets.json")
    uid = {}
    for a in fx["assets"]:
        row = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types[a["type"]], key=f"{ws}:{a['id']}",
                    name=a["name"], type=a["type"], attributes={**a.get("attributes", {}),
                                                                 **({"aliases": a["aliases"]} if a.get("aliases") else {})},
                    record_status="Retired" if a.get("retired") else "Active")
        db.add(row)
        uid[a["id"]] = row.uid
    db.flush()
    # The pickup's electronics, connected as the hub keeps them.
    db.add(Relation(workspace_id=ws, from_asset_uid=uid["a-pu-bpsa101"], to_asset_uid=uid["a-el-bpsa101"],
                    relation_type="connected to"))
    # Bound before any sync: a corrector by a person, a kicker to a unit retired since.
    for comp, asset in (("CHHA101", "a-cor-h-01"), ("KCKA101", "a-kck-old")):
        inst = service.new_installation_claims(db, ws, "person", pos(db, ws, comp), uid[asset], WHEN)
        service.confirm_installation(db, ws, "person", inst)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"ws": ws, "h": {"X-Workspace-Id": ws}, "uid": uid, "rules": fx["naming_rules"]}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def pos(db, ws, component) -> str:
    return next((u for u, i in bm.model_ids(db, ws, "dafne-accumulator-v2", "element").items() if i == component), None)


def by_comp(result) -> dict:
    return {p["component"]: p for p in result["proposals"]}


def opts(ring):
    return {"dataset": "design-2026", "naming_rules": ring["rules"]}


# --------------------------------------------------------------------------- preview and apply

def test_preview_proposes_with_evidence_and_writes_nothing(ring, db):
    ws = ring["ws"]
    before = db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == ws))
    r = sync.preview(db, ws, "dafne-accumulator-v2", opts(ring))
    p = by_comp(r)
    assert p["QUAA101"]["asset"]["name"] == "MAG-ACC-QF01" and p["QUAA101"]["auto_acceptable"]
    assert p["QUAA103"]["status"] == "proposed" and not p["QUAA103"]["auto_acceptable"]
    assert p["BPSA103"]["status"] == "ambiguous" and p["SEPA101"]["status"] == "unmatched"
    assert p["CHHA101"]["status"] == "confirmed" and p["CHHA101"]["authority"] == "human_confirmed"
    assert p["KCKA101"]["diff"] == "missing_asset" and p["KCKA101"]["candidates"][0]["asset"]["name"] == "KCK-NEW"
    assert "ION-PUMP-07" in [a["name"] for a in r["unmodelled_assets"]]
    assert p["QUAA101"]["component_uid"] == pos(db, ws, "QUAA101")
    db.rollback()
    assert db.scalar(select(func.count()).select_from(BeamAssetBinding).where(BeamAssetBinding.workspace_id == ws)) == 0
    assert db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == ws)) == before


def test_accepting_high_confidence_confirms_them_as_installations_and_keeps_the_rest_for_review(ring, db):
    ws = ring["ws"]
    out = sync.apply(db, ws, "dafne-accumulator-v2", "alice", {"accept_high_confidence": True, "keep_proposals": True,
                                                               "options": opts(ring)})
    db.commit()
    names = {c["component"]: c["asset"] for c in out["confirmed"]}
    assert names["QUAA101"] == "MAG-ACC-QF01" and names["BPSA101"] == "BPM-BPSA101" and "QUAA103" not in names
    assert all(c["authority"] == "human_confirmed" for c in out["confirmed"])     # a person accepted the batch
    eq = bm.equipment(db, ws, pos(db, ws, "QUAA101"))
    assert eq["installed"][0]["asset"]["name"] == "MAG-ACC-QF01"
    rows = {(b.component_id, b.status) for b in db.scalars(select(BeamAssetBinding).where(BeamAssetBinding.workspace_id == ws))}
    assert ("QUAA103", "proposed") in rows and ("BPSA103", "ambiguous") in rows
    row = db.scalar(select(BeamAssetBinding).where(BeamAssetBinding.component_id == "QUAA101",
                                                   BeamAssetBinding.workspace_id == ws))
    assert row.matcher == "beamline_asset_matcher" and row.matcher_version and row.installation_uid
    assert "exact_name" in row.evidence and row.confidence >= 0.9 and row.decided_by == "alice"
    assert row.note == "accepted with the high-confidence batch"
    ctx = bm.context(db, ws, pos(db, ws, "QUAA101"))
    assert ctx["asset_bindings"][0]["status"] == "confirmed" and ctx["asset_bindings"][0]["asset"]["name"] == "MAG-ACC-QF01"


def test_confirmed_bindings_survive_later_syncs_and_rejections_stick(ring, db):
    ws = ring["ws"]
    sync.apply(db, ws, "dafne-accumulator-v2", "alice", {"accept_high_confidence": True, "options": opts(ring),
                                                         "reject": [{"component": "QUAA103",
                                                                     "asset": ring["uid"]["a-qf03"]}]})
    db.commit()
    again = by_comp(sync.preview(db, ws, "dafne-accumulator-v2", opts(ring)))
    assert again["QUAA101"]["status"] == "confirmed" and again["QUAA101"]["diff"] == "unchanged"
    assert again["QUAA103"]["status"] == "unmatched"                           # never proposed again
    # The asset is renamed in the hub: the binding stays and the difference is reported.
    a = db.get(Asset, ring["uid"]["a-qf01"])
    a.name = "MAG-ACC-QF01-R"
    db.commit()
    p = by_comp(sync.preview(db, ws, "dafne-accumulator-v2", opts(ring)))["QUAA101"]
    assert p["status"] == "confirmed" and p["diff"] == "changed" and "renamed" in p["notes"][0]


def test_a_replaced_unit_is_a_swap_and_the_physics_position_keeps_its_identity(ring, db):
    ws = ring["ws"]
    k = pos(db, ws, "KCKA101")
    out = sync.apply(db, ws, "dafne-accumulator-v2", "alice",
                     {"accept": [{"component": "KCKA101", "asset": ring["uid"]["a-kck-new"]}], "options": opts(ring)})
    db.commit()
    assert out["confirmed"][0]["asset"] == "KCK-NEW" and not out["problems"]
    assert pos(db, ws, "KCKA101") == k
    eq = bm.equipment(db, ws, k)
    assert [i["asset"]["name"] for i in eq["installed"]] == ["KCK-NEW"]
    assert {h["asset"]["name"] for h in eq["history"]} == {"KCK-OLD", "KCK-NEW"}


def test_a_diagnostic_binds_its_pickup_and_reaches_the_electronics_through_the_hub(ring, db):
    ws = ring["ws"]
    sync.apply(db, ws, "dafne-accumulator-v2", "alice",
               {"accept": [{"component": "BPSA101", "asset": ring["uid"]["a-pu-bpsa101"]}], "options": opts(ring)})
    db.commit()
    ctl = bm.controls(db, ws, pos(db, ws, "BPSA101"))
    assert [u["name"] for u in ctl["units"]] == ["BPM-BPSA101"]
    assert [e["name"] for e in ctl["connected_electronics"]] == ["LIBERA-BPSA101"]
    obs = {o["name"] for o in bm.observables_of(db, ws, pos(db, ws, "BPSA101"))}
    assert obs == {"beam.position.x", "beam.position.y"}


def test_other_relations_bind_a_support_without_claiming_it_implements(ring, db):
    ws = ring["ws"]
    out = sync.apply(db, ws, "dafne-accumulator-v2", "alice", {"accept": [
        {"component": "QUAA102", "asset": ring["uid"]["a-gir01"], "relation": "mounted_on"},
        # QUAA101 is on GIRDER_01 in the model: the girder is what binds to the physical support
        {"component": "QUAA101", "asset": ring["uid"]["a-gir01"], "relation": "mounted_on"}]})
    db.commit()
    assert [c["component"] for c in out["confirmed"]] == ["QUAA102"] and out["confirmed"][0]["relation"] == "mounted_on"
    assert "GIRDER_01" in out["problems"][0]
    rel = db.scalar(select(Relation).where(Relation.from_asset_uid == pos(db, ws, "QUAA102"),
                                           Relation.relation_type == "mounted on"))
    assert rel is not None and rel.to_asset_uid == ring["uid"]["a-gir01"]
    assert not bm.equipment(db, ws, pos(db, ws, "QUAA102"))["installed"]       # no installation for mounted_on


def test_auto_acceptance_happens_only_when_configured_and_says_so(ring, db, monkeypatch):
    ws = ring["ws"]
    assert sync.auto_after_import(db, ws, "dafne-accumulator-v2") is None    # off by default
    monkeypatch.setenv("ARGUS_BEAM_ASSET_SYNC_AUTO", "accept_high_confidence")
    out = sync.auto_after_import(db, ws, "dafne-accumulator-v2")
    db.commit()
    assert out["confirmed"] and all(c["authority"] == "auto_accepted" for c in out["confirmed"])
    auto = {b.component_id for b in db.scalars(select(BeamAssetBinding).where(
        BeamAssetBinding.workspace_id == ws, BeamAssetBinding.authority == "auto_accepted"))}
    # without naming rules from the person, the convention match stays a proposal; nothing weak was accepted
    assert "QUAA103" not in auto and "BLWA101" not in auto and "BPSA103" not in auto


# --------------------------------------------------------------------------- the API

def test_the_sync_api(ring):
    h, ws = ring["h"], ring["ws"]
    base = "/v1/beam-models/dafne-accumulator-v2"
    prev = client.post(f"{base}/asset-sync/preview", headers=h, json=opts(ring))
    assert prev.status_code == 200 and prev.json()["summary"]["ambiguous"] >= 1
    st = client.get(f"{base}/asset-sync/status?filter=magnets", headers=h).json()
    assert st["proposals"] and all(p["family"] == "magnet" for p in st["proposals"])
    assert st["groups"]["vacuum"] >= 3 and st["summary"]["model_components"] > 30
    done = client.post(f"{base}/asset-sync/apply", headers=h, json={"accept_high_confidence": True, "options": opts(ring)})
    assert done.status_code == 200 and done.json()["summary"]["confirmed"] >= 10
    confirmed = client.get(f"{base}/asset-bindings?status=confirmed", headers=h).json()
    q = next(b for b in confirmed if b["component"] == "QUAA101")
    assert q["authority"] == "human_confirmed" and q["source"]["matcher"] == "beamline_asset_matcher"
    assert q["target"]["namespace"] == "kh" and q["asset"]["name"] == "MAG-ACC-QF01"
    # the v2 export carries the confirmed bindings, with provenance, and no copy of the asset's own data
    doc = client.get("/v1/beam-model/models/dafne-accumulator-v2/export", headers=h).json()
    assert doc["schema_version"] == "argus.beam-model/2"
    b = next(x for x in doc["external_bindings"] if x["component"] == "QUAA101")
    assert b["status"] == "confirmed" and b["authority"] == "human_confirmed" and set(b["target"]) == {"namespace", "id", "name"}
    assert client.post("/v1/beam-models/nope/asset-sync/preview", headers=h, json={}).status_code == 404


def test_the_v2_model_queries(ring, db):
    h, ws = ring["h"], ring["ws"]
    assert bm.import_canonical(db, ws, load("aperture.beam.json"), "person", trusted=True)["state"] == "published"
    db.commit()
    r = client.get("/v1/beam-models/test-aperture/aperture", headers=h,
                   params={"path": "line", "from": "Q1", "to": "Q2", "dataset": "design"}).json()
    assert r["limit_y"]["component"] == "COL1" and r["limit_x"]["component"] == "VLV1"
    scraped = client.get("/v1/beam-models/test-aperture/aperture", headers=h,
                         params={"path": "line", "state": "SCP1:IN"}).json()
    assert scraped["limit_x"]["component"] == "SCP1"
    al = client.get("/v1/beam-models/dafne-accumulator-v2/components/GIRDER_01/alignment", headers=h).json()
    assert set(al["moves_with_it"]) >= {"QUAA101", "SXTA101", "BPSA101"}
    doc = client.get("/v1/beam-models/dafne-accumulator-v2/document", headers=h).json()
    assert "TOPOLOGY" in doc["validation"]["levels"] and doc["document"]["definitions"]
    assert client.get("/v1/beam-model/schema", headers=h).json()["title"].endswith("(argus.beam-model/2)")


def test_ledger_records_for_new_component_kinds_and_shared_paths(ring, db):
    ws = ring["ws"]
    v = db.get(Asset, pos(db, ws, "VLVA101"))
    assert v.type == "Vacuum Element" and v.attributes["element_kind"] == "gate_valve"
    assert v.attributes["component_family"] == "vacuum"
    g = db.get(Asset, pos(db, ws, "GIRDER_01"))
    assert g.type == "Support Element"
    mounted = db.scalar(select(Relation).where(Relation.from_asset_uid == pos(db, ws, "QUAA101"),
                                               Relation.relation_type == "mounted on"))
    assert mounted.to_asset_uid == g.uid
    assert bm.import_canonical(db, ws, load("collider_ir.beam.json"), "person", trusted=True)["state"] == "published"
    db.commit()
    ip = db.get(Asset, next(u for u, i in bm.model_ids(db, ws, "test-collider-ir", "element").items() if i == "IP1"))
    placed = {r.to_asset_uid for r in db.scalars(select(Relation).where(Relation.from_asset_uid == ip.uid,
                                                                          Relation.relation_type == "placed on"))}
    assert len(placed) == 2
    for p in placed:
        assert "IP1" in [n["name"] for n in bm.path_graph(db, ws, p)["nodes"]]


def test_a_v1_edit_of_a_v2_model_keeps_what_v1_cannot_say(ring, db):
    ws = ring["ws"]
    v1 = bm.export_canonical(db, ws, "dafne-accumulator-v2", "1")
    assert v1["format"] == "argus.beam-model/1"
    v1["elements"][0]["name"] = "Injection septum"                  # an editor's change
    bm.import_canonical(db, ws, v1, "person", trusted=True)
    db.commit()
    doc = bm.export_canonical(db, ws, "dafne-accumulator-v2", "2")
    comps = {c["id"]: c for c in doc["components"]}
    assert comps["SEPA101"]["name"] == "Injection septum"
    assert comps["VLVA101"]["type"] == "gate_valve" and comps["VLVA101"]["boundaries"]
    assert comps["QUAA101"]["definition"] == "QUA1" and comps["QUAA101"]["mounted_on"] == "GIRDER_01"
    assert "GIRDER_01" in comps and doc["definitions"]


def test_what_the_editor_needs_and_an_edited_v2_model_round_trips(ring, db):
    h = ring["h"]
    voc = client.get("/v1/beam-model/vocabulary", headers=h).json()
    assert "gate_valve" in voc["families"]["vacuum"] and "aperture_limiting" in voc["capabilities"]
    assert voc["states"]["gate_valve"]["OPEN"] == {"beam_passes": True} and "circle" in voc["shapes"]
    v1 = json.loads((FX / "linac.json").read_text())
    up = client.post("/v1/beam-model/upgrade", headers=h, json=v1).json()
    assert up["schema_version"] == "argus.beam-model/2" and up["components"]
    # The editor loads v2, changes it and saves it whole: a component placed on a second path, a branch, a boundary.
    doc = client.get("/v1/beam-model/models/dafne-accumulator-v2/export?format=2", headers=h).json()
    doc["paths"].append({"id": "spur", "topology": "open", "placements": ["DMPT101x"], "system": "dafne-accumulator"})
    doc["components"].append({"id": "DMPT101x", "type": "beam_dump", "material": {"material": "graphite"}})
    doc["paths"][1]["placements"].append({"component": "QUAT101", "reversed": True})     # passed again, backwards
    doc["connections"].append({"kind": "branch", "from": {"path": "extraction-line", "component": "BPST101"},
                               "to": {"path": "spur"}})
    q = next(c for c in doc["components"] if c["id"] == "QUAA102")
    q["boundaries"] = [{"profile": {"shape": "circle", "radius": 0.021}}]
    saved = client.post("/v1/beam-model/import", headers=h, json=doc)
    assert saved.status_code == 200, saved.text
    back = client.get("/v1/beam-model/models/dafne-accumulator-v2/export", headers=h).json()
    assert back["schema_version"] == "argus.beam-model/2" and back["definitions"]               # nothing lost
    assert next(c for c in back["components"] if c["id"] == "QUAA102")["boundaries"][0]["profile"]["radius"] == 0.021
    assert any(c["to"]["path"] == "spur" for c in back["connections"])
    ext = next(p for p in back["paths"] if p["id"] == "extraction-line")
    assert {"component": "QUAT101", "reversed": True} in ext["placements"]
