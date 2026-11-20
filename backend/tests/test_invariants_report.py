"""The data invariants as a report (I-MIG-4): a clean migrated workspace
passes; each kind of violation written around the ledger is found."""
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ledger import engine, invariants, temporal
from app.main import app
from app.models.asset import Asset, Relation
from app.models.issue import Issue
from tests.test_legacy_migration import Legacy, outcomes

client = TestClient(app)
NOW = datetime.now(timezone.utc)


def migrated():
    L = Legacy()
    plan = client.post("/v1/migration/plans", headers=L.headers, json={}).json()
    item = outcomes(plan)["vac:SIP04"]["item"]
    client.post(f"/v1/migration/plans/{plan['id']}/items/{item}/override", headers=L.headers,
                json={"outcome": "M-POS", "reason": "duplicate"})
    applied = client.post(f"/v1/migration/plans/{plan['id']}/apply", headers=L.headers).json()
    return L, {r["legacy_key"].split(":AST:")[1]: r["applied"] for r in applied["rows"]}


def record(db, ws, type_, attrs=None, key=None):
    a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=engine.ensure_type(db, ws, type_).uid,
              key=key or f"T-{uuid.uuid4().hex[:10]}", name=type_, type=type_, attributes=attrs or {})
    db.add(a)
    db.flush()
    return a


def test_a_migrated_workspace_satisfies_every_invariant():
    L, _done = migrated()
    rep = client.get("/v1/ledger/invariants/report", headers=L.headers).json()
    assert rep["ok"], rep["failing"]
    assert set(rep["invariants"]) >= {"I-INS-1", "I-AP-1", "I-PORT-1", "I-TKT-3", "uniqueness"}
    assert "note" in rep["invariants"]["I-INS-7"]


def test_each_violation_written_around_the_ledger_is_found():
    L, done = migrated()
    db = SessionLocal()
    unit = done["vac:SIP02"]["equipment"]
    other_position = done["vac:SIP03"]["position"]
    # I-INS-1: the same unit Confirmed at a second position for the same time.
    twin = record(db, L.ws, "Installation", {"installation_status": "Confirmed",
                                             "valid_from": temporal.instant("2020-01-01", "day")})
    db.add_all([Relation(workspace_id=L.ws, from_asset_uid=twin.uid, to_asset_uid=other_position,
                         relation_type="installed at", derivation="ledger"),
                Relation(workspace_id=L.ws, from_asset_uid=twin.uid, to_asset_uid=unit,
                         relation_type="installation of", derivation="ledger")])
    # I-INS-4: installed at something that is not a position.
    wrong = record(db, L.ws, "Installation", {"installation_status": "Proposed"})
    pump = record(db, L.ws, "Ion Pump")
    db.add_all([Relation(workspace_id=L.ws, from_asset_uid=wrong.uid, to_asset_uid=pump.uid,
                         relation_type="installed at", derivation="ledger"),
                Relation(workspace_id=L.ws, from_asset_uid=wrong.uid, to_asset_uid=unit,
                         relation_type="installation of", derivation="ledger")])
    # I-AP-1: two Active Access Points for one address.
    for _ in range(2):
        record(db, L.ws, "Access Point", {"address": "10.0.0.7"})
    # Uniqueness: one serial on two live records of the same make.
    record(db, L.ws, "Ion Pump", {"serial": f"DUP-{L.fac}", "manufacturer": "Agilent"})
    record(db, L.ws, "Ion Pump", {"serial": f"DUP-{L.fac}", "manufacturer": "agilent"})
    # I-TKT-1: a ticket with no subject link.
    db.add(Issue(uid=str(uuid.uuid4()), workspace_id=L.ws, asset_uid=pump.uid, title="Trip", description="",
                 state="new", attributes={}, labels=[], version=1, created_at=NOW, updated_at=NOW))
    db.commit()
    rep = invariants.report(db, [L.ws])
    db.close()
    assert not rep["ok"]
    assert {"I-INS-1", "I-INS-4", "I-AP-1", "uniqueness", "I-TKT-1"} <= set(rep["failing"]), rep["failing"]
    assert rep["invariants"]["I-AP-1"]["examples"][0]["address"] == "10.0.0.7"


def test_the_report_runs_in_a_read_only_snapshot_and_still_finds_a_missing_derived_link():
    """An export takes the report inside its read-only snapshot. I-TKT-3 used to rewrite the links in a savepoint
    and failed there ("cannot execute DELETE in a read-only transaction"), losing the whole report."""
    from sqlalchemy import delete, func, select, text

    from app.ledger import tickets
    from app.models.ledger import TicketLink

    L, done = migrated()
    db = SessionLocal()
    issue = Issue(uid=str(uuid.uuid4()), workspace_id=L.ws, asset_uid=done["vac:SIP02"]["position"],
                  title="Vacuum trip", description="", state="new", attributes={}, labels=[], version=1,
                  created_at=NOW, updated_at=NOW)
    db.add(issue)
    db.flush()
    tickets.derive_for_ticket(db, issue)
    db.commit()
    derived = db.scalar(select(func.count()).select_from(TicketLink).where(
        TicketLink.ticket_uid == issue.uid, TicketLink.origin == "derived"))
    assert derived, "the position's installed unit is involved"
    before = db.scalar(select(func.count()).select_from(TicketLink).where(TicketLink.workspace_id == L.ws))

    def read_only_report():
        s = SessionLocal()
        try:
            s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return invariants.report(s, [L.ws])
        finally:
            s.rollback()
            s.close()

    rep = read_only_report()
    assert "I-TKT-3" not in rep["failing"], rep["invariants"]["I-TKT-3"]

    # A derived link removed around the ledger is still found from the read-only snapshot.
    db.execute(delete(TicketLink).where(TicketLink.ticket_uid == issue.uid, TicketLink.origin == "derived"))
    db.commit()
    rep = read_only_report()
    assert "I-TKT-3" in rep["failing"]
    assert db.scalar(select(func.count()).select_from(TicketLink).where(
        TicketLink.workspace_id == L.ws)) == before - derived   # the report wrote nothing back
    db.close()
