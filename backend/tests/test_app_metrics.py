"""The application's numbers for Prometheus (services/app_metrics.py): aggregates by workspace, never a person."""
import secrets
from datetime import datetime, timedelta, timezone

from prometheus_client import generate_latest

from app.db import SessionLocal
from app.models.issue import Issue
from app.models.usage import UsageLLM, UsagePresence
from app.models.workspace import Workspace
from app.services import app_metrics, metrics


def test_the_numbers_are_aggregates_by_workspace_and_window(monkeypatch):
    # Read now: another test's scrape may have left a copy the collector would otherwise serve for a minute.
    monkeypatch.setenv("ARGUS_APP_METRICS_SECONDS", "0")
    t = secrets.token_hex(4)
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    ws = f"metrics-{t}"
    db.add(Workspace(id=ws, name="Metrics"))
    db.flush()
    db.add_all([Issue(uid=f"i1-{t}", workspace_id=ws, title="Open one", state="new", attributes={}, labels=[]),
                Issue(uid=f"i2-{t}", workspace_id=ws, title="Done", state="closed", attributes={}, labels=[],
                      closed_at=now),
                UsagePresence(bucket=now - timedelta(hours=2), client="web", person=f"secret-person-{t}"),
                UsageLLM(day=now.date(), workspace_id=ws, model="m", purpose="chat", calls=3, failures=1,
                         prompt_tokens=100, completion_tokens=20, estimated_calls=0, ms_total=0)])
    db.commit()
    try:
        by_name = {name: dict((tuple(v), value) for v, value in rows) for name, _, _, rows in app_metrics.gather(db)}
        assert by_name["argus_records"][(ws, "tickets")] == 2
        assert by_name["argus_tickets_open"][(ws, "new")] == 1 and (ws, "closed") not in by_name["argus_tickets_open"]
        assert by_name["argus_records_created"][(ws, "tickets", "1d")] == 2
        assert by_name["argus_llm_tokens"][(ws, "m", "7d", "prompt")] == 100
        assert by_name["argus_llm_failures"][(ws, "m", "1d")] == 1
        assert by_name["argus_active_people"][("1d", "all")] >= 1
        text = generate_latest(metrics.REGISTRY).decode()
        assert "argus_app_metrics_up 1.0" in text and f'argus_tickets_open{{state="new",workspace="{ws}"}} 1.0' in text
        assert "secret-person" not in text, "no person in any label"
    finally:
        db.rollback()
        db.query(UsageLLM).filter(UsageLLM.workspace_id == ws).delete()
        db.query(UsagePresence).filter(UsagePresence.person == f"secret-person-{t}").delete()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        db.delete(db.get(Workspace, ws))
        db.commit()
        db.close()
