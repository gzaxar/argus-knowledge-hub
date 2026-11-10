"""The beam model (docs/beam-model.md): a simulator-independent physics model linked to the facility.

Three canonical fixtures — a closed ring with an extraction branch, an open linac and a laser line that
splits — go through one model. What is checked: the import (validation, provenance, idempotence, retiring
what a model no longer lists), topology (order, a ring's closure, branches that need no `s`), the physics
positions staying while the hardware installed at them changes, diagnostics observing several observables
through signals that are identities and never values, datasets holding what depends on the optics, and the
queries ARGUS exists to answer, through the service and the API.
"""
import copy
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.ledger import engine, service
from app.main import app
from app.models.asset import Asset, Relation
from app.models.beam_model import BeamModelValue
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import beam_model as bm
from app.services.asset_types import ensure_asset_types

FIXTURES = Path(__file__).parent / "fixtures" / "beam_model"
client = TestClient(app)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture()
def world():
    t = secrets.token_hex(4)
    ws = f"bm-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Beam model"))
    db.flush()
    ensure_asset_types(db, ws)
    admin = User(id=str(uuid.uuid4()), email=f"bm-{t}@argus.test", is_admin=True)
    db.add(admin)
    engine.activate_policy(db)                       # a hub that already has an authority policy
    reports = {f: bm.import_canonical(db, ws, load(f), "test") for f in
               ("dafne_accumulator.json", "linac.json", "laser_transport.json")}
    # A new source waits for governance: its claims take effect when a policy covering it is activated.
    assert all(r["awaiting_policy"] for r in reports.values())
    engine.activate_policy(db)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"ws": ws, "h": {"X-Workspace-Id": ws}, "reports": reports, "admin": admin}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def el(db, ws: str, model_name: str) -> Asset:
    return next(a for a in db.scalars(select(Asset).where(Asset.workspace_id == ws))
                if (a.attributes or {}).get("model_name") == model_name)


def path(db, ws: str, name: str) -> Asset:
    return db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Beam Path", Asset.name == name))


def names(rows) -> list[str]:
    return [r["name"] for r in rows]


# --------------------------------------------------------------------------- import

def test_three_kinds_of_machine_import_into_one_model(world, db):
    r = world["reports"]
    assert all(x["state"] == "published" for x in r.values())
    assert r["dafne_accumulator.json"]["elements"] == 28 and r["dafne_accumulator.json"]["values"] == 24
    ws = world["ws"]
    kinds = {a.type for a in db.scalars(select(Asset).where(Asset.workspace_id == ws))}
    assert {"Beam System", "Particle Beam", "Photon Beam", "Beam Path", "Septum", "Kicker", "Beam Position Monitor",
            "Screen Station", "Beam Source", "Beam Dump", "Mirror", "Lens", "Beam Splitter", "Generic Monitor",
            "Generic Beam Element", "Observable", "Model Dataset", "RF Cavity"} <= kinds
    q = el(db, ws, "QUAA101")
    assert q.type == "Quadrupole" and q.attributes["element_kind"] == "quadrupole"
    assert q.attributes["native_type"] == "QUADRUPOLE" and q.attributes["native_source"] == "madx"
    assert {"focusing", "powered"} <= set(q.attributes["capabilities"])
    # The optics are not on the element: they are the dataset's.
    assert "k1" not in q.attributes and "s_position" not in q.attributes
    photon = db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Photon Beam"))
    assert photon.attributes["wavelength"] == 800 and "species" not in photon.attributes


def test_the_import_keeps_its_provenance_and_is_idempotent_and_retires_what_is_gone(world, db):
    ws = world["ws"]
    q = el(db, ws, "QUAA101")
    from app.models.ledger import Claim
    claim = db.scalar(select(Claim).where(Claim.predicate == "exists", Claim.source_ref.like("%:element:QUAA101")))
    assert claim.rule_id == bm.RULE and claim.method == "stated"
    again = bm.import_canonical(db, ws, load("linac.json"), "test")
    db.commit()
    assert again["state"] in ("published", "historical", "unchanged") or again["revision"]
    smaller = load("linac.json")
    smaller["paths"][0]["elements"].remove("ACC02")
    smaller["elements"] = [e for e in smaller["elements"] if e["id"] != "ACC02"]
    bm.import_canonical(db, ws, smaller, "test")
    db.commit()
    # Found by its stable key: a retired record's facts no longer project.
    gone = db.get(Asset, next(u for u, i in bm.model_ids(db, ws, "linac-demo", "element").items() if i == "ACC02"))
    assert gone.record_status == "Retired"
    assert names(bm.neighbours(db, ws, el(db, ws, "QUA01").uid, "downstream")) == ["BPM01"]
    assert q.uid == el(db, ws, "QUAA101").uid


@pytest.mark.parametrize("mutate, problem", [
    (lambda m: m["elements"].__setitem__(0, {**m["elements"][0], "type": "warp_drive"}), "unknown element type"),
    (lambda m: m["paths"][1]["elements"].append("QUAA101"), "is on paths"),
    (lambda m: m["paths"][0]["branches"].append({"at": "SEPA102", "to_path": "nowhere"}), "unknown or empty path"),
    (lambda m: m["paths"][0].__setitem__("topology", "spiral"), "open or closed"),
    (lambda m: m["elements"][4].__setitem__("observes", ["beam.flavour"]), "not among the observables"),
])
def test_a_model_that_says_something_impossible_is_refused_with_the_reason(mutate, problem):
    m = copy.deepcopy(load("dafne_accumulator.json"))
    mutate(m)
    with pytest.raises(bm.BeamModelError) as e:
        bm.validate(m)
    assert problem in str(e.value)


# --------------------------------------------------------------------------- topology

def test_an_open_path_is_in_beam_order(world, db):
    g = bm.path_graph(db, world["ws"], path(db, world["ws"], "Linac").uid)
    assert g["topology"] == "open"
    assert [n["name"] for n in g["nodes"]] == ["GUN01", "BUN01", "ACC01", "QUA01", "BPM01", "ACC02", "DIP01",
                                              "SCR01", "DMP01"]
    assert [n["s"] for n in g["nodes"]] == sorted(n["s"] for n in g["nodes"])


def test_a_closed_path_has_no_end(world, db):
    ws = world["ws"]
    ring = bm.path_graph(db, ws, path(db, ws, "Accumulator ring").uid)
    assert ring["topology"] == "closed" and ring["length"] == 32.56 and len(ring["nodes"]) == 24
    assert ring["nodes"][0]["name"] == "SEPA101"                               # the reference, s = 0 side
    assert {"from": ring["nodes"][-1]["uid"], "to": ring["nodes"][0]["uid"], "relation": "closes to"} in ring["edges"]
    # Downstream of the last element is the first: round the ring, not off its end.
    assert names(bm.neighbours(db, ws, el(db, ws, "CHVA102").uid, "downstream")) == ["SEPA101"]
    assert names(bm.neighbours(db, ws, el(db, ws, "SEPA101").uid, "upstream")) == ["CHVA102"]


def test_a_branch_is_an_edge_not_a_coordinate(world, db):
    ws = world["ws"]
    down = bm.neighbours(db, ws, el(db, ws, "BSP01").uid, "downstream")
    assert {(d["name"], d["via"]) for d in down} == {("Interaction point", "upstream of"), ("Leak camera", "branches to")}
    main = bm.path_graph(db, ws, path(db, ws, "Transport to the interaction point").uid)
    assert main["branches_out"][0]["to_path"]["name"] == "Diagnostic leg"
    leg = bm.path_graph(db, ws, path(db, ws, "Diagnostic leg").uid)
    assert leg["branches_in"] and leg["nodes"][0].get("s") is None          # the camera has no s: none needed
    # Upstream of the first element of the leg is the splitter, across the branch.
    assert names(bm.neighbours(db, ws, el(db, ws, "CAM01").uid, "upstream")) == ["BSP01"]
    # The ring's extraction septum leads both on round the ring and out into the extraction line.
    out = {d["name"] for d in bm.neighbours(db, ws, el(db, ws, "SEPA102").uid, "downstream")}
    assert out == {"QUAA104", "QUAT101"}


def test_what_lies_between_two_elements(world, db):
    ws = world["ws"]
    assert names(bm.between(db, ws, el(db, ws, "QUAA101").uid, el(db, ws, "BPSA101").uid)) == ["SXTA101"]
    assert names(bm.between(db, ws, el(db, ws, "BPSA101").uid, el(db, ws, "QUAA101").uid)) == ["SXTA101"]
    assert bm.between(db, ws, el(db, ws, "GUN01").uid, el(db, ws, "LSR01").uid) is None   # other machines


# --------------------------------------------------------------------------- diagnostics and observables

def test_which_diagnostics_observe_the_horizontal_orbit(world, db):
    ws = world["ws"]
    ring = path(db, ws, "Accumulator ring").uid
    assert names(bm.diagnostics(db, ws, ring, "beam.position.x")) == ["BPSA101", "BPSA102", "BPSA103", "BPSA104",
                                                                       "BPSA105"]
    assert names(bm.diagnostics(db, ws, None, "optical.profile")) == ["Leak camera"]


def test_correctors_upstream_acting_on_the_horizontal_plane(world, db):
    ws = world["ws"]
    near = bm.correctors_upstream(db, ws, el(db, ws, "BPSA102").uid, "x")
    # Nearest first; going upstream round the ring it reaches the horizontal correctors and the kickers.
    assert names(near)[0] == "CHHA101" and "CHVA101" not in names(near)
    assert {"KCKA101", "CHHA102"} <= set(names(near)) and all(n["plane_known"] for n in near)
    assert names(bm.correctors_upstream(db, ws, el(db, ws, "BPSA102").uid, "y"))[0] == "CHVA102"


def test_one_physical_diagnostic_exposes_several_observables_through_signal_identities(world, db):
    ws = world["ws"]
    bpm = el(db, ws, "BPM01")
    types = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}
    pickup = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["Other Equipment"], key=f"{ws}:PICKUP-7",
                   name="Stripline pickup 7", type="Other Equipment", attributes={"serial": "SP-7"})
    electronics = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["Digitizer"], key=f"{ws}:LIB-3",
                        name="Libera 3", type="Digitizer", attributes={})
    device = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["Control Device"], key=f"{ws}:DEV-BPM01",
                   name="BPM01", type="Control Device", attributes={"pv": "LINAC:BPM01"})
    ioc = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["IOC"], key=f"{ws}:IOC-BPM",
                name="ioc-bpm", type="IOC", attributes={})
    db.add_all([pickup, electronics, device, ioc])
    db.flush()
    db.add_all([Relation(workspace_id=ws, from_asset_uid=pickup.uid, to_asset_uid=electronics.uid, relation_type="connected to"),
                Relation(workspace_id=ws, from_asset_uid=device.uid, to_asset_uid=electronics.uid, relation_type="acts on"),
                Relation(workspace_id=ws, from_asset_uid=device.uid, to_asset_uid=ioc.uid, relation_type="provided by")])
    service.new_installation_claims(db, ws, "test", bpm.uid, pickup.uid, {"kind": "date", "nominal": "2025-01-01T00:00:00+00:00", "precision": "instant"})
    inst = db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Installation"))
    service.confirm_installation(db, ws, "test", inst.uid)
    for plane in ("x", "y"):
        bm.ensure_signal(db, ws, "test", name=f"BPM01 {plane.upper()}", address=f"LINAC:BPM01:{plane.upper()}",
                         role="measurement", device_uid=device.uid, for_uid=bpm.uid, measures=f"beam.position.{plane}",
                         unit="mm")
    db.commit()
    obs = bm.observables_of(db, ws, bpm.uid)
    assert {o["name"]: [s["address"] for s in o["measured_by"]] for o in obs} == {
        "beam.position.x": ["LINAC:BPM01:X"], "beam.position.y": ["LINAC:BPM01:Y"]}
    ctl = bm.controls(db, ws, bpm.uid)
    assert names(ctl["units"]) == ["Stripline pickup 7"] and names(ctl["connected_electronics"]) == ["Libera 3"]
    assert {s["address"] for s in ctl["signals"]} == {"LINAC:BPM01:X", "LINAC:BPM01:Y"}
    # Signals are identities: nothing of a reading is stored.
    sig = db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Control Signal"))
    assert set(sig.attributes) <= {"address", "role", "signal_system", "unit", "quantity", "argus_source",
                                   "argus_source_ref"}


# --------------------------------------------------------------------------- positions, hardware and datasets

def test_the_position_stays_while_the_hardware_installed_there_changes(world, db):
    ws = world["ws"]
    q = el(db, ws, "QUAA101")
    types = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}
    old = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["Magnet Assembly"], key=f"{ws}:MAG-1",
                name="QUAA101", type="Magnet Assembly", attributes={"serial": "Q-0001"})
    new = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=types["Magnet Assembly"], key=f"{ws}:MAG-2",
                name="Spare quadrupole Q-0007", type="Magnet Assembly", attributes={"serial": "Q-0007"})
    db.add_all([old, new])
    db.commit()
    # A name match is only ever a proposal.
    report = bm.propose_bindings(db, ws)
    db.commit()
    assert report["proposed"] >= 1
    proposed = [b for b in bm.bindings(db, ws) if b["position"]["uid"] == q.uid]
    assert [b["state"] for b in proposed] == ["proposed"] and proposed[0]["proposed_by"] == bm.BIND_RULE
    assert bm.equipment(db, ws, q.uid)["installed"] == []
    service.confirm_installation(db, ws, "test", proposed[0]["installation_uid"],
                                 valid_from={"kind": "date", "nominal": "2025-01-01T00:00:00+00:00", "precision": "instant"})
    db.commit()
    assert names(i["asset"] for i in bm.equipment(db, ws, q.uid)["installed"]) == ["QUAA101"]
    service.swap(db, ws, "test", q.uid, new.uid, {"kind": "date", "nominal": "2026-03-01T00:00:00+00:00", "precision": "instant"},
                 reason="Failure")
    db.commit()
    assert names(i["asset"] for i in bm.equipment(db, ws, q.uid)["installed"]) == ["Spare quadrupole Q-0007"]
    last_year = bm.equipment(db, ws, q.uid, "2025-06-01T00:00:00+00:00")["installed"]
    assert names(i["asset"] for i in last_year) == ["QUAA101"]
    assert [b["state"] for b in bm.bindings(db, ws) if b["position"]["uid"] == q.uid] == ["historical", "confirmed"]
    assert el(db, ws, "QUAA101").uid == q.uid                                # the same position throughout


def test_optics_belong_to_a_dataset_not_to_hardware(world, db):
    ws = world["ws"]
    q = el(db, ws, "QUAA101")
    ctx = bm.context(db, ws, q.uid)
    assert ctx["physics"]["physics"]["k1"] == 4.30926
    assert ctx["physics"]["native"]["parameters"]["K1"] == 4.30926 and ctx["physics"]["native"]["source"] == "madx"
    assert ctx["path"]["name"] == "Accumulator ring"
    bpm = el(db, ws, "BPSA101")
    design = bm.context(db, ws, bpm.uid)["physics"]
    assert {"beta_x", "beta_y", "dx"} <= set(design["optics"]) and design["geometry"]["x"] is not None
    datasets = db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Model Dataset")).all()
    assert {d.attributes.get("dataset_kind") for d in datasets} == {"design"}
    view = bm.dataset_view(db, ws, next(d.uid for d in datasets if d.name == "Design optics 2026"))
    assert view["attributes"]["simulator"] == "madx" and len(view["values"]) == 24
    assert [v["s"] for v in view["values"]] == sorted(v["s"] for v in view["values"])
    # The linac's element-level values went into the model's own dataset, not lost.
    assert db.scalar(select(BeamModelValue).where(BeamModelValue.subject_uid == el(db, ws, "QUA01").uid)).physics["k1"] == 8.2


# --------------------------------------------------------------------------- the API

def test_the_api_answers_the_argus_questions(world, db):
    ws, h = world["ws"], world["h"]
    ring = path(db, ws, "Accumulator ring").uid
    bpm = el(db, ws, "BPSA101").uid
    quad = el(db, ws, "QUAA101").uid
    systems = client.get("/v1/beam-systems", headers=h).json()
    assert {s["name"] for s in systems} == {"DAΦNE Accumulator", "Electron linac", "Laser transport"}
    graph = client.get(f"/v1/beam-paths/{ring}/graph", headers=h).json()
    assert graph["topology"] == "closed" and len(graph["nodes"]) == 24
    assert [x["name"] for x in client.get(f"/v1/beam-elements/{bpm}/upstream", headers=h).json()] == ["SXTA101"]
    assert client.get(f"/v1/beam-elements/{quad}/between/{bpm}", headers=h).json()[0]["name"] == "SXTA101"
    diag = client.get("/v1/diagnostics", params={"path": ring, "observable": "beam.position.x"}, headers=h).json()
    assert len(diag) == 5
    obs = client.get("/v1/observables/beam.position.x", headers=h).json()
    assert len(obs["diagnostics"]) >= 5
    ctx = client.get(f"/v1/beam-elements/{quad}/context", headers=h).json()
    assert ctx["physics"]["physics"]["k1"] == 4.30926 and ctx["equipment"]["installed"] == []
    assert client.get(f"/v1/beam-elements/{quad}/correctors", params={"plane": "x"}, headers=h).status_code == 200
    datasets = client.get("/v1/model-datasets", params={"path": ring}, headers=h).json()
    assert len(datasets) == 1 and client.get(f"/v1/model-datasets/{datasets[0]['uid']}", headers=h).json()["values"]
    assert client.get("/v1/model-bindings", headers=h).json() == []
    bad = client.post("/v1/beam-model/import", headers=h, json={"format": "argus.beam-model/1", "model": {"id": "x"},
                                                                 "systems": [], "paths": [], "elements": [
                                                                     {"id": "A", "type": "warp_drive"}]})
    assert bad.status_code == 422 and "unknown element type" in json.dumps(bad.json())
    assert client.get(f"/v1/beam-elements/{ring}", headers=h).status_code == 404   # a path is not an element


def _fresh_workspace(db) -> str:
    ws = f"bm-copy-{secrets.token_hex(3)}"
    db.add(Workspace(id=ws, name="Copy"))
    db.flush()
    ensure_asset_types(db, ws)
    db.commit()
    return ws


def _drop(db, ws):
    from app.ledger.audit import allow_purge
    db.rollback()
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()


def test_an_exported_model_imports_into_another_hub_as_the_same_model(world, db):
    ws = world["ws"]
    assert {m["model_id"] for m in bm.list_models(db, ws)} == {"dafne-accumulator", "linac-demo", "laser-transport"}
    first = bm.export_canonical(db, ws, "dafne-accumulator")
    assert first["model"]["version"] == "2026.1" and first["model"]["simulator"] == "madx"
    ring = next(p for p in first["paths"] if p["id"] == "accumulator-ring")
    assert ring["topology"] == "closed" and ring["reference"] == "SEPA101" and len(ring["elements"]) == 24
    assert ring["branches"] == [{"at": "SEPA102", "to_path": "extraction-line"}]
    values = first["datasets"][0]["values"]["QUAA101"]
    assert values["physics"]["k1"] == 4.30926 and values["native"]["parameters"]["K1"] == 4.30926
    other = _fresh_workspace(db)
    try:
        report = bm.import_canonical(db, other, first, "test", trusted=True)
        db.commit()
        assert report["awaiting_policy"] is False                         # a person's import takes effect at once
        again = bm.export_canonical(db, other, "dafne-accumulator")
        assert json.dumps(again, sort_keys=True) == json.dumps(first, sort_keys=True)
    finally:
        _drop(db, other)


def test_several_models_go_in_and_out_together_or_not_at_all(world, db):
    ws, h = world["ws"], world["h"]
    bundle = client.get("/v1/beam-model/export", headers=h).json()
    assert bundle["format"] == bm.BUNDLE_FORMAT and len(bundle["models"]) == 3
    one = client.get("/v1/beam-model/models/linac-demo/export", headers=h).json()
    assert one["model"]["id"] == "linac-demo"
    assert client.get("/v1/beam-model/models/nope/export", headers=h).status_code == 404
    other = _fresh_workspace(db)
    try:
        oh = {"X-Workspace-Id": other}
        broken = copy.deepcopy(bundle)
        broken["models"][1]["elements"][0]["type"] = "warp_drive"
        checked = client.post("/v1/beam-model/validate", headers=oh, json=broken).json()["models"]
        assert [c["ok"] for c in checked] == [True, False, True] and checked[0]["summary"]["elements"] > 0
        refused = client.post("/v1/beam-model/import", headers=oh, json=broken)
        assert refused.status_code == 422
        assert client.get("/v1/beam-model/models", headers=oh).json() == []            # nothing was written
        done = client.post("/v1/beam-model/import", headers=oh, json=bundle)
        assert done.status_code == 200 and len(done.json()["models"]) == 3
        assert not any(r["awaiting_policy"] for r in done.json()["models"])            # a signed-in person brought them
        assert {m["model_id"] for m in client.get("/v1/beam-model/models", headers=oh).json()} == \
            {"dafne-accumulator", "linac-demo", "laser-transport"}
    finally:
        _drop(db, other)


def test_a_workspace_without_the_beam_model_types_is_told_to_seed_them(db):
    ws = f"bm-bare-{secrets.token_hex(3)}"
    db.add(Workspace(id=ws, name="Bare"))
    db.flush()
    with pytest.raises(bm.BeamModelError) as e:
        bm.import_canonical(db, ws, load("linac.json"))
    assert "seed_asset_types.py" in str(e.value) and "Beam System" in str(e.value)


def test_the_relations_are_classified_and_registered():
    from app.ledger import registry
    from app.services import causal_model
    for rel in ("branches to", "closes to", "observes", "signal of", "signal for", "starts at", "beam of", "models",
                "connected to", "upstream of", "part of", "measures"):
        assert rel in causal_model.SEMANTICS, rel
    assert causal_model.SEMANTICS["closes to"].layer == "beam"
    assert causal_model.SEMANTICS["observes"].flows == "none"                # knowing is not depending
    assert registry.CARDINALITY["closes to"] == (1, 1)
    assert {"Septum", "Beam Splitter", "Generic Monitor"} <= registry.BEAM_ELEMENTS
    assert {"Septum", "Generic Monitor", "Lens"} <= engine.INSTALLABLE and "Drift" not in engine.INSTALLABLE


def _now():
    return datetime.now(timezone.utc)


def test_a_model_is_removed_whole_and_comes_back_when_imported_again(world, db):
    ws, h = world["ws"], world["h"]
    from app.models.beam_model import BeamModelDocument
    linac = [a.uid for a in db.scalars(select(Asset).where(Asset.workspace_id == ws))
             if (a.attributes or {}).get("model_id") == "linac-demo"]
    assert linac
    r = client.delete("/v1/beam-model/models/linac-demo", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["retired"] == len(linac)
    db.expire_all()
    assert "linac-demo" not in {m["model_id"] for m in bm.list_models(db, ws)}
    assert {m["model_id"] for m in bm.list_models(db, ws)} == {"dafne-accumulator", "laser-transport"}, \
        "the other models are untouched"
    assert all(db.get(Asset, u).record_status == "Retired" for u in linac), "retired, history kept"
    assert not db.scalars(select(BeamModelDocument).where(BeamModelDocument.workspace_id == ws,
                                                          BeamModelDocument.model_id == "linac-demo")).first()
    assert not db.scalars(select(BeamModelValue).where(BeamModelValue.dataset_uid.in_(linac))).first()
    assert client.get("/v1/beam-model/models/linac-demo/export", headers=h).status_code == 404
    assert client.delete("/v1/beam-model/models/linac-demo", headers=h).status_code in (200, 404)

    bm.import_canonical(db, ws, load("linac.json"), "test")
    db.commit()
    db.expire_all()
    assert "linac-demo" in {m["model_id"] for m in bm.list_models(db, ws)}
    back = [a.uid for a in db.scalars(select(Asset).where(Asset.workspace_id == ws))
            if (a.attributes or {}).get("model_id") == "linac-demo" and a.record_status != "Retired"]
    assert set(back) == set(linac), "the same records, not copies"


def test_removing_a_model_that_is_not_there_says_so(world):
    assert client.delete("/v1/beam-model/models/no-such-model", headers=world["h"]).status_code == 404
