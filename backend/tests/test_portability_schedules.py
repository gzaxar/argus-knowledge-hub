"""Periodic Git exports: a published export repeated at an interval, as increments on the last publication,
skipped when nothing changed, keeping new dependencies as external references by themselves, waiting for a
person only when its analysis needs one for something else, and switched off after repeated failures. Setting one follows the rules for approving the export itself."""
from datetime import timedelta

import uuid

import pytest
from sqlalchemy.orm import Session

from app.ledger import service as ledger_service
from app.models.document import DocumentRelation
from app.models.portability import PortabilityEvent, PortabilityExport, PortabilitySchedule
from app.portability import schedules, service
from app.portability.service import ServiceError
from tests.test_portability import dbs, env, populate, run_export  # noqa: F401 — fixtures


def _schedule(eng, env, export_id, **kw):
    with Session(eng) as db:
        exp = db.get(PortabilityExport, export_id)
        sched = schedules.create(db, exp, kw.pop("actor", "carol@example.org"), every_minutes=kw.pop("every", 60),
                                 admin=True, fresh_auth=kw.pop("fresh_auth", True), cfg=env.cfg("src"), **kw)
        db.commit()
        return sched.id


def _run(eng, env, sid):
    with Session(eng) as db:
        return schedules.run_now(eng, db, db.get(PortabilitySchedule, sid), env.cfg("src"))


def _edit(eng, s, value):
    with Session(eng) as db:
        ledger_service.edit_value(db, s.inv, "rossi@example.org", s.unit, "attr:argus_location", value)
        db.commit()


def test_a_schedule_publishes_increments_on_its_last_publication_and_skips_when_nothing_changed(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"])

    assert _run(src, env, sid)["outcome"] == "unchanged"

    _edit(src, s, "Rack D4")
    out = _run(src, env, sid)
    assert out["outcome"] == "published", out["message"]
    with Session(src) as db:
        inc = db.get(PortabilityExport, out["export"])
        assert inc.mode == "incremental" and inc.base_export_id == first["id"] and inc.state == "published"
        assert inc.git["previous_tag"] == first["git"]["tag"]
        assert inc.requested_by.startswith(f"schedule {sid}") and "standing approval" in inc.approved_by
        sched = db.get(PortabilitySchedule, sid)
        assert sched.last_published_export_id == inc.id and sched.runs == 2 and sched.running_since is None
        assert sched.next_run_at > schedules.now() + timedelta(minutes=55)

    _edit(src, s, "Rack D5")
    out2 = _run(src, env, sid)
    with Session(src) as db:
        assert db.get(PortabilityExport, out2["export"]).base_export_id == inc.id        # the chain goes on
        kinds = [e.kind for e in db.query(PortabilityEvent).filter_by(subject_kind="schedule", subject_id=sid)]
    assert kinds == ["schedule_set", "schedule_run", "schedule_run", "schedule_run"]
    assert _run(src, env, sid)["outcome"] == "unchanged"


def test_a_complete_chain_repeats_the_export_as_it_was(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"], chain="complete", skip_unchanged=False)
    out = _run(src, env, sid)
    assert out["outcome"] == "published", out["message"]
    with Session(src) as db:
        exp = db.get(PortabilityExport, out["export"])
        assert exp.mode == "workspace" and exp.base_export_id is None and exp.workspaces == first["workspaces"]


def _refer_to_a_missing_record(eng, s):
    """A document of the exported workspace now names a record that is not on this installation."""
    with Session(eng) as db:
        db.add(DocumentRelation(workspace_id=s.inv, from_document_uid=s.doc, to_type="asset",
                                to_uid=str(uuid.uuid4()), relation_type="references"))
        db.commit()


def test_a_new_dependency_does_not_stop_a_run_it_stays_an_external_reference(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"], skip_unchanged=False)
    _refer_to_a_missing_record(src, s)
    out = _run(src, env, sid)
    assert out["outcome"] == "published", out["message"]
    with Session(src) as db:
        exp = db.get(PortabilityExport, out["export"])
        assert exp.decisions["document_relation:missing"] == "external_reference"
        assert "standing approval" in exp.approved_by
        sched = db.get(PortabilitySchedule, sid)
        assert sched.decisions["document_relation:missing"] == "external_reference"   # kept for later runs
        kinds = [e.kind for e in db.query(PortabilityEvent).filter_by(subject_kind="schedule", subject_id=sid)]
    assert "schedule_outcomes" in kinds


def test_an_export_a_run_left_waiting_is_carried_on_by_the_next_one(dbs, env):
    """Exports stopped by a run before automatic outcomes existed are not left waiting for ever."""
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"], skip_unchanged=False)
    _refer_to_a_missing_record(src, s)
    with Session(src) as db:
        sched = db.get(PortabilitySchedule, sid)
        exp = service.create_export(db, schedules.actor_of(sched), mode="incremental", workspaces=list(sched.workspaces),
                                    classifications=[], destination=dict(sched.destination),
                                    decisions=dict(sched.decisions), base_export_id=first["id"], cfg=env.cfg("src"))
        service.analyse_export(db, exp, schedules.actor_of(sched), env.cfg("src"))
        assert not exp.analysis["ready"] and exp.state == "awaiting_approval"
        sched.last_export_id = exp.id
        waiting = exp.id
        db.commit()
    out = _run(src, env, sid)
    assert out["outcome"] == "published" and out["export"] == waiting, out["message"]


def test_a_run_whose_analysis_needs_a_person_waits_for_one(dbs, env, monkeypatch):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"], skip_unchanged=False)
    real = service.analyse_export

    def needs_a_person(db, exp, actor, cfg=None):
        out = real(db, exp, actor, cfg)
        out.analysis = {**out.analysis, "ready": False, "warnings": ["1 dependencies need an outcome"]}
        return out
    monkeypatch.setattr(service, "analyse_export", needs_a_person)
    out = _run(src, env, sid)
    assert out["outcome"] == "waiting" and "needs a person" in out["message"]
    again = _run(src, env, sid)                          # no second export while the first one waits
    assert again["outcome"] == "waiting" and again["export"] == out["export"]
    with Session(src) as db:
        assert db.get(PortabilityExport, out["export"]).state == "awaiting_approval"


def test_three_failures_in_a_row_switch_it_off(dbs, env, monkeypatch):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"], skip_unchanged=False)

    def broken(*a, **k):
        raise ServiceError("the signing key is unreadable", "no_signing_key", 409)
    monkeypatch.setattr(service, "generate_export", broken)
    for _ in range(3):
        assert _run(src, env, sid)["outcome"] == "failed"
    with Session(src) as db:
        sched = db.get(PortabilitySchedule, sid)
        assert not sched.enabled and "switched off" in sched.last_message and sched.failures == 3
        schedules.change(db, sched, "carol@example.org", enabled=True)
        assert sched.enabled and sched.failures == 0
        db.commit()


def test_only_due_schedules_run_and_a_claimed_one_is_never_run_twice(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    sid = _schedule(src, env, first["id"])
    assert schedules.run_due(src, env.cfg("src")) == []                     # not due for an hour
    with Session(src) as db:
        db.get(PortabilitySchedule, sid).next_run_at = schedules.now() - timedelta(minutes=1)
        db.commit()
        assert schedules.claim(db, sid)
        assert not schedules.claim(db, sid, force=True)                     # another runner has it
    assert schedules.run_due(src, env.cfg("src")) == []
    with Session(src) as db:
        db.get(PortabilitySchedule, sid).running_since = None
        db.commit()
    [out] = schedules.run_due(src, env.cfg("src"))
    assert out["outcome"] == "unchanged"


def test_setting_one_follows_the_rules_for_approving_the_export(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    unpublished, _ = run_export(src, env, s, publish=False)
    with pytest.raises(ServiceError, match="published to a Git repository"):
        _schedule(src, env, unpublished["id"])
    restricted, _ = run_export(src, env, s, classifications=["costs"], repository="escrow-restricted")
    with pytest.raises(ServiceError, match="restricted classes"):
        _schedule(src, env, restricted["id"])
    full, _ = run_export(src, env, s, mode="full")                           # high risk
    with pytest.raises(ServiceError, match="recent sign-in"):
        _schedule(src, env, full["id"], fresh_auth=False)
    with pytest.raises(ServiceError, match="other than its requester"):
        _schedule(src, env, full["id"], actor="alice@example.org")
    with pytest.raises(ServiceError, match="between an hour"):
        _schedule(src, env, full["id"], every=10)
    sid = _schedule(src, env, full["id"])
    with pytest.raises(ServiceError, match="already has a schedule"):
        _schedule(src, env, full["id"])
    with Session(src) as db:
        assert db.get(PortabilitySchedule, sid).mode == "full"
        with pytest.raises(ServiceError, match="administrator"):
            schedules.create(db, db.get(PortabilityExport, full["id"]), "x@example.org", every_minutes=60,
                             admin=False, fresh_auth=True, cfg=env.cfg("src"))


def test_the_api_lets_administrators_set_change_run_and_remove_a_schedule(env, monkeypatch):
    import secrets
    import time
    import uuid

    from fastapi.testclient import TestClient

    from app.auth import OidcIdentity, get_identity
    from app.db import SessionLocal
    from app.ledger import engine as ledger
    from app.main import app
    from app.models.asset import Asset
    from app.models.user import User
    from app.models.workspace import Workspace
    monkeypatch.setenv("ARGUS_PORTABILITY_ROOT", str(env.tmp / "api"))
    monkeypatch.setenv("ARGUS_PORTABILITY_POLICY", "strict")
    monkeypatch.setenv("ARGUS_PORTABILITY_REPOSITORIES", f"escrow={env.repo}")
    monkeypatch.setenv("ARGUS_PORTABILITY_ARTIFACT_STORES", f"vault={env.store.root}")
    monkeypatch.setenv("ARGUS_PORTABILITY_SIGNING_KEY", str(env.signer.key_path))
    monkeypatch.setenv("ARGUS_PORTABILITY_TRUSTED_KEYS", str(env.allowed))
    ws = f"sched-{secrets.token_hex(3)}"
    db = SessionLocal()
    alice = User(id=f"a-{ws}", email=f"alice-{ws}@example.org", is_admin=True)
    eve = User(id=f"e-{ws}", email=f"eve-{ws}@example.org", is_admin=False)
    db.add_all([Workspace(id=ws, name="Scheduled"), alice, eve])
    db.flush()
    pump = ledger.ensure_type(db, ws, "Ion Pump")
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=ws, key=f"{ws}-1", name="Pump", type="Ion Pump",
                 schema_uid=pump.uid, attributes={}))
    db.commit()
    for u in (alice, eve):
        db.refresh(u)
        db.expunge(u)
    db.close()
    client = TestClient(app)
    person = lambda u: (lambda: OidcIdentity(user=u, claims={"auth_time": time.time()}))  # noqa: E731
    try:
        app.dependency_overrides[get_identity] = person(alice)
        exp = client.post("/v1/portability/exports", json={
            "mode": "workspace", "workspaces": [ws], "repository": "escrow", "artifact_store": "vault",
            # icons other tests gave the shared type are opaque images
            "decisions": {"opaque_blobs": "approve_opaque"}}).json()
        for step in ("approve", "generate", "publish-git"):
            r = client.post(f"/v1/portability/exports/{exp['id']}/{step}")
            assert r.status_code == 200, r.text
        app.dependency_overrides[get_identity] = person(eve)
        assert client.post("/v1/portability/schedules", json={"export_id": exp["id"]}).status_code == 403
        assert client.get("/v1/portability/schedules").status_code == 403
        app.dependency_overrides[get_identity] = person(alice)
        r = client.post("/v1/portability/schedules", json={"export_id": exp["id"], "every_minutes": 1440})
        assert r.status_code == 201, r.text
        sched = r.json()
        assert sched["repository"] == "escrow" and sched["enabled"] and sched["chain"] == "incremental"
        r = client.put(f"/v1/portability/schedules/{sched['id']}", json={"every_minutes": 360, "skip_unchanged": False})
        assert r.json()["every_minutes"] == 360 and not r.json()["skip_unchanged"]
        job = client.post(f"/v1/portability/schedules/{sched['id']}/run").json()["job"]
        for _ in range(120):
            job = client.get(f"/v1/portability/jobs/{job['id']}").json()
            if job["state"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert job["state"] == "completed", job
        [listed] = [s for s in client.get("/v1/portability/schedules").json() if s["id"] == sched["id"]]
        assert listed["last_outcome"] == "published" and listed["runs"] == 1
        assert client.delete(f"/v1/portability/schedules/{sched['id']}").status_code == 204
        assert all(s["id"] != sched["id"] for s in client.get("/v1/portability/schedules").json())
    finally:
        app.dependency_overrides.pop(get_identity, None)
