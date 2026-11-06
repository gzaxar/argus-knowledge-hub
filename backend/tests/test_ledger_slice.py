"""The S1 vertical slice (asset-model-revision §13, §14): one configuration-derived
position, one inventory asset, a confirmed Installation, a re-import, a swap, a
historical query, a retraction with retirement, and conflicting confirmations —
through the fact ledger end to end. Test names carry the plan's acceptance ids.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import hash_token
from app.db import Base, SessionLocal, engine as db_engine
from app.ledger import engine, service, temporal
from app.ledger.engine import InvariantError
from app.ledger.policy import ClaimContext, Policy, PolicyError, Vocabulary, validate
from app.main import app
from app.models.api_token import ApiToken
from app.models.asset import Asset, Relation
from app.models.issue import Issue
from app.models.ledger import (Claim, Conflict, Decision, FactState, JobRun, RevisionEvent, StatusEvent,
                               StreamHead)
from app.models.workspace import Workspace

client = TestClient(app)
T0 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(db_engine)
    yield


def values_yaml(fac, oid, devices=("GUNSIP00", "GUNSIP01", "GUNSIP02"), zones=("LINAC", "GUN"), extra=()):
    lines = [f"beamline: {fac}", "epicsConfiguration:", "  iocs:", "    - name: vac-gunvpc", "      devgroup: vac",
             "      template: agilent-vac", f"      zones: [{', '.join(zones)}]", "      devices:"]
    for i, d in enumerate(devices):
        asset = f', asset: "https://servicedesk.example/ObjectSchema.jspa?id=32&objectId={oid}"' \
            if d == "GUNSIP01" else ""
        lines.append(f"        - {{name: {d}, channel: {145 + i}{asset}}}")
    for d in extra:
        lines.append(f"        - {{name: {d}, channel: 900}}")
    return "\n".join(lines).encode()


def insight_json(fac, oid1, oid2, location="Rack B12"):
    return json.dumps({"objects": [
        {"objectId": oid1, "type": "Ion Pump", "key": f"{fac}INV-84321", "name": "Ion pump 84321",
         "attributes": {"serial": "84321", "argus_location": location}},
        {"objectId": oid2, "type": "Ion Pump", "key": f"{fac}INV-90001", "name": "Ion pump 90001",
         "attributes": {"serial": "90001", "argus_location": "Storage"}},
    ]}).encode()


class Slice:
    def __init__(self):
        self.fac = f"S{secrets.token_hex(3).upper()}"
        self.ws = f"slice-{secrets.token_hex(3)}"
        self.inv = f"inv-{secrets.token_hex(3)}"
        self.oid1, self.oid2 = str(secrets.randbelow(10 ** 9)), str(secrets.randbelow(10 ** 9))
        self.config = f"epik8s:{self.fac}#values.yaml@main"
        self.insight = f"insight:{self.fac}:schema=44"
        db = SessionLocal()
        db.add_all([Workspace(id=self.ws, name="Slice"), Workspace(id=self.inv, name="Inventory")])
        db.flush()
        engine.register_stream(db, self.config, self.ws, "epik8s", facility=self.fac,
                               may_create=["IOC", "Control Device", "Equipment Position"])
        engine.register_stream(db, self.insight, self.inv, "insight", may_create=["Ion Pump"])
        engine.activate_policy(db)
        raw = secrets.token_urlsafe(12)
        db.add(ApiToken(workspace_id=self.ws, token_hash=hash_token(raw)))
        db.commit()
        db.close()
        self.headers = {"Authorization": f"Bearer {raw}"}

    def config_rev(self, db, rev="r1", at=T0, **kw):
        return engine.ingest(db, self.config, revision=rev, content=values_yaml(self.fac, self.oid1, **kw),
                             observed_at=at, parser="epik8s-slice")

    def inventory(self, db, rev="i1", at=T0, **kw):
        return engine.ingest(db, self.insight, revision=rev, content=insight_json(self.fac, self.oid1, self.oid2, **kw),
                             observed_at=at, parser="insight-fixture")

    def rec(self, db, key) -> Asset:
        return db.scalar(select(Asset).where(Asset.key == key))

    def pos(self, db, name="GUNSIP01"):
        return self.rec(db, f"{self.fac}:POS:{name}")

    def dev(self, db, name="GUNSIP01"):
        return self.rec(db, f"{self.fac}-DEV-vac-gunvpc-{name}")

    def unit(self, db, serial="84321"):
        return self.rec(db, f"{self.fac}INV-{serial}")


@pytest.fixture()
def s():
    return Slice()


def proposed_installation(db, s):
    views = engine.installations(db, position_uid=s.pos(db).uid)
    return [v for v in views if v["status"] == "Proposed"]


def setup_confirmed(db, s):
    s.config_rev(db)
    s.inventory(db)
    [prop] = proposed_installation(db, s)
    service.confirm_installation(db, s.ws, "operator", prop["uid"])
    db.commit()
    return prop["uid"]


# --------------------------------------------------------------------------- A1–A6

def test_A1_a_configuration_makes_control_records_and_an_inferred_position(s):
    db = SessionLocal()
    result = s.config_rev(db)
    db.commit()
    assert result["state"] == "published" and result["appeared"] > 0
    assert s.dev(db).record_status == "Active"
    pos = s.pos(db)
    assert pos.type == "Equipment Position" and pos.record_status == "Active"
    assert pos.attributes["position_class"] == "Ion Pump"
    # No physical asset is ever made from a configuration (§4.2).
    assert db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == s.ws,
                                                                  Asset.type == "Ion Pump")) == 0
    ev = db.scalar(select(StatusEvent).where(StatusEvent.subject_uid == pos.uid, StatusEvent.predicate == "exists"))
    assert ev.to_status == "accepted" and ev.cause.startswith("revision:")
    zones = s.dev(db).attributes["zones"]
    assert zones == ["GUN", "LINAC"]
    db.close()


def test_A2_A3_inventory_resolves_to_a_proposal_that_a_person_confirms(s):
    db = SessionLocal()
    s.config_rev(db)
    s.inventory(db)
    db.commit()
    unit = s.unit(db)
    assert unit.workspace_id == s.inv and unit.attributes["serial"] == "84321"
    [prop] = proposed_installation(db, s)
    assert prop["asset_uid"] == unit.uid
    inst = db.get(Asset, prop["uid"])
    assert inst.key.startswith("INS-") and len(inst.key) == 30 and inst.workspace_id == s.ws
    # Not realized yet: a proposal is not a fact about the machine.
    assert not db.scalar(select(Relation).where(Relation.from_asset_uid == s.pos(db).uid,
                                                Relation.relation_type == "realized by"))
    service.confirm_installation(db, s.ws, "operator", inst.uid)
    db.commit()
    db.refresh(inst)
    assert inst.attributes["installation_status"] == "Confirmed"
    edge = db.scalar(select(Relation).where(Relation.from_asset_uid == s.pos(db).uid,
                                            Relation.relation_type == "realized by"))
    assert edge.to_asset_uid == unit.uid and edge.derivation == "derived"
    [now_] = engine.installations_at(db, engine.now(), position_uid=s.pos(db).uid)
    assert now_["certainty"] == "definite"
    db.close()


def test_A4_identical_bytes_skip_parsing_and_write_nothing(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    events = db.scalar(select(func.count()).select_from(StatusEvent))
    claims = db.scalar(select(func.count()).select_from(Claim))
    again = s.config_rev(db, rev="r1-again", at=T0 + timedelta(hours=1))
    db.commit()
    assert again["parse_skipped"] and again["appeared"] == again["disappeared"] == 0
    assert db.scalar(select(func.count()).select_from(Claim)) == claims
    assert db.scalar(select(func.count()).select_from(StatusEvent)) == events
    last = db.scalar(select(JobRun).where(JobRun.stage == "parse", JobRun.scope == s.config)
                     .order_by(JobRun.id.desc()).limit(1))
    assert last.status == "skipped"
    db.close()


def test_A5_resolution_reruns_when_the_inventory_arrives_even_if_the_config_did_not_change(s):
    db = SessionLocal()
    s.config_rev(db)
    db.commit()
    assert proposed_installation(db, s) == []
    s.inventory(db)
    s.config_rev(db, rev="r1-again", at=T0 + timedelta(hours=1))
    db.commit()
    assert len(proposed_installation(db, s)) == 1
    runs = list(db.scalars(select(JobRun).where(JobRun.stage == "resolve", JobRun.scope == s.ws)))
    assert any(r.status == "ran" and r.counts.get("proposals") == 1 for r in runs)
    db.close()


def test_A6_a_confirmed_edit_survives_reimport_and_a_disagreeing_source_is_flagged(s):
    db = SessionLocal()
    s.config_rev(db)
    db.commit()
    dev = s.dev(db)
    service.edit_value(db, s.ws, "operator", dev.uid, "attr:description", "controller in rack C3")
    service.edit_value(db, s.ws, "operator", dev.uid, "attr:channel", 999)
    db.commit()
    s.config_rev(db, rev="r1b", at=T0 + timedelta(hours=1))
    db.commit()
    db.refresh(dev)
    assert dev.attributes["description"] == "controller in rack C3"
    assert dev.attributes["channel"] == 999
    kinds = {c.conflict_type: c.severity for c in db.scalars(select(Conflict).where(Conflict.subject_uid == dev.uid))}
    assert kinds == {"source_vs_confirmed": "non-blocking"}
    db.close()


# --------------------------------------------------------------------------- A7–A10 installations over time

def test_A7_A8_a_swap_moves_the_derived_edge_and_history_answers_either_side(s):
    db = SessionLocal()
    first = setup_confirmed(db, s)
    pos, new_unit = s.pos(db), s.unit(db, "90001")
    t = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    result = service.swap(db, s.ws, "operator", pos.uid, new_unit.uid, temporal.instant(t), "Failure")
    db.commit()
    assert result["ended"] == [first]
    old = db.get(Asset, first)
    assert old.attributes["removal_reason"] == "Failure"
    # The swap does not move the unit's location; that is inventory's fact.
    assert s.unit(db).attributes["argus_location"] == "Rack B12"
    [before] = engine.installations_at(db, t - timedelta(seconds=1), position_uid=pos.uid)
    [after] = engine.installations_at(db, t, position_uid=pos.uid)
    assert before["asset_uid"] == s.unit(db).uid and after["asset_uid"] == new_unit.uid
    edge = db.scalar(select(Relation).where(Relation.from_asset_uid == pos.uid,
                                            Relation.relation_type == "realized by"))
    assert edge.to_asset_uid == new_unit.uid
    db.close()


def test_A9_a_unit_cannot_be_in_two_places_and_the_attempt_is_audited(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    t = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    service.swap(db, s.ws, "operator", s.pos(db).uid, s.unit(db, "90001").uid, temporal.instant(t))
    db.commit()
    other_pos, unit = s.pos(db, "GUNSIP02"), s.unit(db, "90001")
    db.close()
    resp = client.post("/v1/installations/swap", headers=s.headers, json={
        "position_uid": other_pos.uid, "new_asset_uid": unit.uid, "at": (t + timedelta(days=1)).isoformat()})
    assert resp.status_code == 409 and resp.json()["detail"]["invariant"] == "I-INS-1"
    db = SessionLocal()
    assert db.scalar(select(Decision).where(Decision.workspace_id == s.ws, Decision.kind == "batch_rejected"))
    assert engine.installations(db, position_uid=other_pos.uid) == []
    db.close()


def test_A10_backdating_needs_the_neighbour_corrected_in_the_same_batch(s):
    db = SessionLocal()
    first = setup_confirmed(db, s)
    pos = s.pos(db)
    t = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    second = service.swap(db, s.ws, "operator", pos.uid, s.unit(db, "90001").uid, temporal.instant(t))["installation_uid"]
    db.commit()
    earlier = temporal.instant(t - timedelta(hours=2))
    alone = [service.confirm_value(second, "attr:valid_from", earlier)]
    with pytest.raises(InvariantError) as exc:
        engine.apply_decisions(db, s.ws, "operator", alone)
    assert exc.value.code == "I-INS-2"
    db.rollback()
    ended = service._active(db, first, "attr:valid_until")
    engine.apply_decisions(db, s.ws, "operator", [
        service.confirm_value(second, "attr:valid_from", earlier),
        service.confirm_value(first, "attr:valid_until", earlier, replaces=ended)])
    db.commit()
    [then] = engine.installations_at(db, t - timedelta(hours=1), position_uid=pos.uid)
    assert then["uid"] == second
    db.close()


# --------------------------------------------------------------------------- A11–A13 confirmation

def test_A11_A12_A13_confirmations_are_sticky_and_replaced_only_explicitly(s):
    db = SessionLocal()
    s.inventory(db)
    db.commit()
    unit = s.unit(db)
    [b13] = engine.apply_decisions(db, s.inv, "alice", [service.confirm_value(unit.uid, "attr:argus_location", "Rack B13")])
    engine.apply_decisions(db, s.inv, "bob", [service.confirm_value(unit.uid, "attr:argus_location", "Rack B14")])
    db.commit()
    db.refresh(unit)
    assert unit.attributes["argus_location"] == "Rack B13"
    blocking = db.scalar(select(Conflict).where(Conflict.subject_uid == unit.uid,
                                                Conflict.conflict_type == "confirmed_vs_confirmed"))
    assert blocking.severity == "blocking"

    b14 = service._active(db, unit.uid, "attr:argus_location")
    engine.apply_decisions(db, s.inv, "carol", [service.confirm_value(unit.uid, "attr:argus_location", "Rack B14",
                                                                      replaces=b14)])
    db.commit()
    db.refresh(unit)
    assert unit.attributes["argus_location"] == "Rack B14"
    assert not db.scalar(select(Conflict).where(Conflict.subject_uid == unit.uid,
                                                Conflict.conflict_type == "confirmed_vs_confirmed"))
    assert db.scalar(select(func.count()).select_from(Decision).where(Decision.subject_uid == unit.uid)) == 3

    s.inventory(db, rev="i2", at=T0 + timedelta(days=1), location="Rack B12")
    db.commit()
    db.refresh(unit)
    assert unit.attributes["argus_location"] == "Rack B14"
    types = {c.conflict_type for c in db.scalars(select(Conflict).where(Conflict.subject_uid == unit.uid))}
    assert types == {"source_vs_confirmed"}
    db.close()


# --------------------------------------------------------------------------- A14–A16 retraction and replay

def test_A14_a_revision_retiring_a_ticketed_record_is_held_and_retires_nothing_until_approved(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    dev2 = s.dev(db, "GUNSIP02")
    db.add(Issue(uid=f"tk-{secrets.token_hex(4)}", workspace_id=s.ws, title="GUNSIP02 readback", state="new",
                 asset_uid=dev2.uid))
    db.commit()
    r2 = s.config_rev(db, rev="r2", at=T0 + timedelta(days=2), devices=("GUNSIP00", "GUNSIP01"))
    db.commit()
    assert r2["state"] == "held"
    assert s.dev(db, "GUNSIP02").record_status == "Active"
    engine.approve_revision(db, r2["revision_id"], "reviewer")
    db.commit()
    assert s.dev(db, "GUNSIP02").record_status == "Retired"
    assert s.pos(db, "GUNSIP02").record_status == "Retired"
    assert s.pos(db).record_status == "Active"
    assert db.scalar(select(Issue).where(Issue.asset_uid == dev2.uid)) is not None
    db.close()


def test_A14b_a_position_the_hardware_still_occupies_is_flagged_not_retired(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    r2 = s.config_rev(db, rev="r2", at=T0 + timedelta(days=2), devices=("GUNSIP00", "GUNSIP02"))
    db.commit()
    if r2["state"] == "held":
        engine.approve_revision(db, r2["revision_id"], "reviewer")
        db.commit()
    pos = s.pos(db)
    assert pos.record_status == "Active"
    assert db.scalar(select(Conflict).where(Conflict.subject_uid == pos.uid,
                                            Conflict.conflict_type == "retirement_blocked"))
    db.close()


def test_A15_a_rejected_inference_is_not_proposed_again(s):
    db = SessionLocal()
    s.config_rev(db)
    db.commit()
    pos0 = s.pos(db, "GUNSIP00")
    claim = db.scalar(select(Claim).where(Claim.source_ref == f"infer:{s.fac}:pos:GUNSIP00",
                                          Claim.predicate == "exists"))
    engine.apply_decisions(db, s.ws, "reviewer", [{"kind": "reject", "target": {"claim_id": claim.claim_id,
                                                                                  "scope": "fingerprint"}}])
    db.commit()
    assert s.pos(db, "GUNSIP00").record_status == "Retired"
    s.config_rev(db, rev="r1b", at=T0 + timedelta(hours=1))
    s.config_rev(db, rev="r2", at=T0 + timedelta(hours=2), zones=("LINAC",))
    db.commit()
    assert s.pos(db, "GUNSIP00").record_status == "Retired"
    state = db.scalar(select(FactState).where(FactState.subject_uid == pos0.uid, FactState.predicate == "exists"))
    assert state.status == "rejected"
    db.close()


def test_A16_projections_rebuild_identically_and_a_policy_change_is_the_cause_of_what_it_changes(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    service.edit_value(db, s.ws, "operator", s.dev(db).uid, "attr:channel", 999)
    db.commit()
    before = engine.snapshot(db, s.ws)
    engine.rebuild(db, s.ws)
    db.commit()
    assert engine.snapshot(db, s.ws) == before

    body = json.loads(json.dumps(engine.DEFAULT_POLICY))
    body["policy_version"] = f"slice-test-{secrets.token_hex(2)}"
    body["rules"].append({"id": "distrust-this-config", "match": {"source_instance": s.config}, "rank": "ignored"})
    row = engine.activate_policy(db, body, "governance")
    db.commit()
    dev = s.dev(db, "GUNSIP00")
    assert dev.record_status == "Retired"
    ev = db.scalar(select(StatusEvent).where(StatusEvent.subject_uid == dev.uid, StatusEvent.predicate == "exists")
                   .order_by(StatusEvent.seq.desc()).limit(1))
    assert ev.cause == f"policy:{row.version}" and ev.to_status == "ignored"
    engine.activate_policy(db, None, "governance")   # restore the default for the next tests
    db.commit()
    db.close()


# --------------------------------------------------------------------------- A24–A26 held revisions

def many(prefix, n):
    return tuple(f"{prefix}{i:02d}" for i in range(n))


def test_A24_a_held_revision_that_a_later_one_undoes_is_never_projected(s):
    db = SessionLocal()
    full = many("DEV", 24)
    s.config_rev(db, devices=full)
    db.commit()
    events = db.scalar(select(func.count()).select_from(StatusEvent))
    r2 = s.config_rev(db, rev="r2", at=T0 + timedelta(hours=1), devices=full[:12])
    assert r2["state"] == "held" and r2["disappeared"] > 0
    r3 = s.config_rev(db, rev="r3", at=T0 + timedelta(hours=2), devices=full)
    db.commit()
    assert r3["state"] == "published"
    assert engine.revision_state(db, r2["revision_id"]) == "superseded"
    assert db.scalar(select(func.count()).select_from(StatusEvent)) == events
    head = db.get(StreamHead, s.config)
    assert head.parsed_head == head.published_head == r3["revision_id"]
    db.close()


def test_A25_approving_the_latest_supersedes_the_earlier_and_approving_the_earlier_reguards_the_latest(s):
    db = SessionLocal()
    full = many("DEV", 24)
    s.config_rev(db, devices=full)
    r2 = s.config_rev(db, rev="r2", at=T0 + timedelta(hours=1), devices=full[:12])
    r3 = s.config_rev(db, rev="r3", at=T0 + timedelta(hours=2), devices=full[:10])
    db.commit()
    assert r2["state"] == r3["state"] == "held"
    engine.approve_revision(db, r2["revision_id"], "reviewer")
    db.commit()
    # r3 drops only 2 of r2's 12 subjects: it now passes the guard and publishes.
    assert engine.revision_state(db, r3["revision_id"]) == "published"
    db.close()

    s2 = Slice()
    db = SessionLocal()
    s2.config_rev(db, devices=full)
    a = s2.config_rev(db, rev="r2", at=T0 + timedelta(hours=1), devices=full[:12])
    b = s2.config_rev(db, rev="r3", at=T0 + timedelta(hours=2), devices=full[:12])
    engine.approve_revision(db, b["revision_id"], "reviewer")
    db.commit()
    assert engine.revision_state(db, a["revision_id"]) == "superseded"
    assert db.get(StreamHead, s2.config).published_head == b["revision_id"]
    db.close()


def test_A26_a_rejected_revision_rejects_no_facts_and_rewind_applies_the_net_transition(s):
    db = SessionLocal()
    full = many("DEV", 24)
    r1 = s.config_rev(db, devices=full)
    r2 = s.config_rev(db, rev="r2", at=T0 + timedelta(hours=1), devices=full[:12])
    engine.reject_revision(db, r2["revision_id"], "reviewer")
    r4 = s.config_rev(db, rev="r4", at=T0 + timedelta(hours=2), devices=full, extra=("NEWDEV",))
    db.commit()
    assert engine.revision_state(db, r2["revision_id"]) == "rejected"
    assert r4["state"] == "published" and s.dev(db, "NEWDEV").record_status == "Active"
    engine.rewind(db, s.config, r1["revision_id"], "reviewer")
    db.commit()
    assert s.dev(db, "NEWDEV").record_status == "Retired"
    assert db.scalar(select(RevisionEvent).where(RevisionEvent.revision_id == r1["revision_id"],
                                                 RevisionEvent.kind == "rewound_to"))
    db.close()


# --------------------------------------------------------------------------- A27–A28 negative facts

def test_A27_a_confirmed_absence_holds_until_retracted_and_a_member_can_be_restored(s):
    db = SessionLocal()
    s.config_rev(db)
    db.commit()
    dev = s.dev(db)
    service.set_member(db, s.ws, "operator", dev.uid, "attr:zones", "GUN", present=False)
    db.commit()
    db.refresh(dev)
    assert dev.attributes["zones"] == ["LINAC"]
    assert db.scalar(select(Conflict).where(Conflict.subject_uid == dev.uid,
                                            Conflict.conflict_type == "source_vs_confirmed"))
    s.config_rev(db, rev="r1b", at=T0 + timedelta(hours=1))
    db.commit()
    db.refresh(dev)
    assert dev.attributes["zones"] == ["LINAC"]
    absence = service._active(db, dev.uid, "attr:zones", json.dumps("GUN"))
    engine.apply_decisions(db, s.ws, "operator", [{"kind": "retract", "target": {"decisions": absence}}])
    db.commit()
    db.refresh(dev)
    assert dev.attributes["zones"] == ["GUN", "LINAC"]
    service.set_member(db, s.ws, "operator", dev.uid, "attr:zones", "GUN", present=True)
    s.config_rev(db, rev="r2", at=T0 + timedelta(hours=2), zones=("LINAC",))
    db.commit()
    db.refresh(dev)
    assert dev.attributes["zones"] == ["GUN", "LINAC"]
    db.close()


def test_A28_rejecting_one_claim_does_not_remove_a_member_another_source_states(s):
    db = SessionLocal()
    s.config_rev(db)
    branch = f"epik8s:{s.fac}#values.yaml@test"
    engine.register_stream(db, branch, s.ws, "epik8s", facility=s.fac)
    engine.activate_policy(db)
    engine.ingest(db, branch, revision="b1", content=values_yaml(s.fac, s.oid1), observed_at=T0,
                  parser="epik8s-slice")
    db.commit()
    dev = s.dev(db)
    gun = db.scalar(select(Claim).where(Claim.stream_id == s.config, Claim.source_ref.like("%GUNSIP01"),
                                        Claim.predicate == "attr:zones", Claim.member == json.dumps("GUN")))
    engine.apply_decisions(db, s.ws, "reviewer", [{"kind": "reject", "target": {"claim_id": gun.claim_id}}])
    db.commit()
    db.refresh(dev)
    assert "GUN" in dev.attributes["zones"]
    db.close()


# --------------------------------------------------------------------------- A29 policy

VOCAB = Vocabulary(types={"Control Device": ("Control Device", "Control Item", "Item"),
                          "Control Item": ("Control Item", "Item"), "Item": ("Item",),
                          "Equipment": ("Equipment", "Item")},
                   workspaces=["sparc"], facilities=["SPARC"], domains=[],
                   streams={"epik8s:btf#values.yaml@test": "epik8s", "epik8s:btf#values.yaml@main": "epik8s",
                            "insight:44": "insight"},
                   rules=["infer.vac.sip/1"])


def ctx(**kw):
    base = dict(predicate="attr:pv", object_type="Control Device", type_lineage=VOCAB.types["Control Device"],
                owner_workspace="sparc", facility="SPARC", domain=None, source_kind="epik8s",
                source_instance="epik8s:btf#values.yaml@test", rule=None, method="stated")
    return ClaimContext(**{**base, **kw})


def test_A29_a_source_instance_rule_beats_a_deep_generic_one():
    policy = Policy({"rules": [
        {"id": "control-device-pv", "match": {"predicate": "attr:pv", "object_type": "Control Device",
                                              "source_kind": "epik8s"}, "rank": "authoritative"},
        {"id": "btf-test-branch", "match": {"source_instance": "epik8s:btf#values.yaml@test"}, "rank": "advisory"},
    ]}, VOCAB.depths())
    assert policy.select(ctx()).rule_id == "btf-test-branch"
    assert policy.select(ctx(source_instance="epik8s:btf#values.yaml@main")).rule_id == "control-device-pv"


def test_A29_the_validator_rejects_ambiguous_unreachable_and_dominant_rules():
    ambiguous = {"rules": [
        {"id": "a", "match": {"source_kind": "epik8s"}, "rank": "authoritative"},
        {"id": "b", "match": {"source_kind": "epik8s"}, "rank": "advisory"}]}
    unreachable = {"rules": [
        {"id": "wide", "match": {"source_instance": "epik8s:btf#values.yaml@main"}, "rank": "authoritative"},
        {"id": "dead", "match": {"source_kind": "epik8s", "source_instance": "epik8s:btf#values.yaml@main"},
         "rank": "advisory", "priority": -1}]}
    dominant = {"protected": [{"predicate": ["attr:serial"], "owners": ["insight", "person"]}],
                "rules": [{"id": "facility-serials", "match": {"facility": "SPARC", "predicate": "attr:serial"},
                           "rank": "authoritative"}]}
    for body, word in ((ambiguous, "ambiguous"), (unreachable, "unreachable"), (dominant, "dominant")):
        with pytest.raises(PolicyError) as exc:
            validate(Policy(body, VOCAB.depths()), VOCAB)
        assert any(word in e for e in exc.value.errors), exc.value.errors
    justified = json.loads(json.dumps(dominant))
    justified["rules"][0]["allow_dominant"] = "the facility's own serial register, agreed with Inventory"
    assert validate(Policy(justified, VOCAB.depths()), VOCAB)["errors"] == []


def test_A29_a_new_stream_stays_ineffective_until_the_policy_is_validated_again(s):
    db = SessionLocal()
    s.config_rev(db)
    other = f"epik8s:{s.fac}#other.yaml@main"
    engine.register_stream(db, other, s.ws, "epik8s", facility=s.fac, may_create=["Control Device", "IOC"])
    engine.ingest(db, other, revision="o1", content=values_yaml(s.fac, s.oid1, devices=("GUNSIP00", "LONELY01")),
                  observed_at=T0, parser="epik8s-slice")
    db.commit()
    lonely = s.dev(db, "LONELY01")
    assert lonely.record_status == "Provisional"
    engine.activate_policy(db)
    db.commit()
    db.refresh(lonely)
    assert lonely.record_status == "Active"
    db.close()


# --------------------------------------------------------------------------- A30 time

def test_A30_uncertain_precision_is_classified_not_guessed():
    month_end = temporal.interval(temporal.instant("2025-01-01T00:00:00Z"), temporal.instant("2026-03-01", "month"))
    starts_mid = temporal.interval(temporal.instant("2026-03-15T08:00:00Z"), None)
    handover_a = temporal.interval(temporal.instant("2025-01-01T00:00:00Z"), temporal.instant("2026-03-03T09:00:00Z"))
    handover_b = temporal.interval(temporal.instant("2026-03-03T09:00:00Z"), None)
    both_open = temporal.interval({"kind": "before_records", "bound": "2025-06-01T00:00:00Z"}, None)
    ended_by = temporal.interval(temporal.instant("2024-05-02", "day"),
                                 {"kind": "unknown_past", "bound": "2025-02-10T00:00:00Z"})
    assert temporal.overlap(month_end, starts_mid) == "possible"
    assert temporal.overlap(handover_a, handover_b) == "none"
    assert temporal.overlap(both_open, temporal.interval(temporal.instant("2025-01-01", "month"), None)) == "definite"
    assert temporal.overlap(ended_by, temporal.interval(temporal.instant("2025-03-01", "day"), None)) == "none"
    assert temporal.covers(month_end, temporal.parse_instant("2026-03-20T00:00:00Z")) == "possible"
    with pytest.raises(temporal.TemporalError):
        temporal.validate(temporal.interval(temporal.instant("2026-05-01"), temporal.instant("2026-04-01")))


def test_A30_a_possible_overlap_is_accepted_for_review_and_a_definite_one_fails(s):
    db = SessionLocal()
    s.config_rev(db)
    s.inventory(db)
    db.commit()
    pos = s.pos(db, "GUNSIP02")
    a = service.new_installation_claims(db, s.ws, "operator", pos.uid, s.unit(db).uid,
                                        temporal.instant("2025-01-01T00:00:00Z"),
                                        temporal.instant("2026-03-01", "month"))
    engine.apply_decisions(db, s.ws, "operator", [service.confirm_value(a, "exists", "present")])
    b = service.new_installation_claims(db, s.ws, "operator", pos.uid, s.unit(db, "90001").uid,
                                        temporal.instant("2026-03-15T08:00:00Z"))
    engine.apply_decisions(db, s.ws, "operator", [service.confirm_value(b, "exists", "present")])
    db.commit()
    assert db.scalar(select(Conflict).where(Conflict.subject_uid == b, Conflict.conflict_type == "possible_overlap"))
    assert db.get(Asset, b).attributes["temporal_uncertain"] is True
    c = service.new_installation_claims(db, s.ws, "operator", pos.uid, s.unit(db).uid,
                                        temporal.instant("2026-04-01T00:00:00Z"))
    with pytest.raises(InvariantError):
        engine.apply_decisions(db, s.ws, "operator", [service.confirm_value(c, "exists", "present")])
    db.rollback()
    db.close()


# --------------------------------------------------------------------------- API

def test_the_review_queue_and_provenance_are_served(s):
    db = SessionLocal()
    s.config_rev(db)
    s.inventory(db)
    db.commit()
    pos_uid = s.pos(db).uid
    db.close()
    review = client.get("/v1/ledger/review", headers=s.headers).json()
    assert review["counts"]["installation_proposals"] == 1
    assert review["installation_proposals"][0]["position"]["uid"] == pos_uid
    facts = client.get(f"/v1/ledger/records/{pos_uid}/facts", headers=s.headers).json()
    exists = next(f for f in facts["facts"] if f["predicate"] == "exists")
    c = exists["contributors"][0]
    assert c["method"] == "inferred" and c["rule_id"] == "infer.vac.sip/1" and c["status"] == "accepted"
    assert c["evidence"]["name_token"] == "SIP"
    history = client.get(f"/v1/installations?position_uid={pos_uid}", headers=s.headers).json()
    assert history[0]["status"] == "Proposed"
    assert client.post(f"/v1/installations/{history[0]['uid']}/confirm", headers=s.headers, json={}).status_code == 200
    history = client.get(f"/v1/installations?position_uid={pos_uid}", headers=s.headers).json()
    assert history[0]["status"] == "Confirmed" and history[0]["temporal_state"] == "Current"


def test_an_edge_the_ledger_maintains_cannot_be_removed_by_hand(s):
    db = SessionLocal()
    setup_confirmed(db, s)
    edge = db.scalar(select(Relation).where(Relation.from_asset_uid == s.pos(db).uid,
                                            Relation.relation_type == "realized by"))
    db.close()
    resp = client.delete(f"/v1/relations/{edge.id}", headers=s.headers)
    assert resp.status_code == 409
