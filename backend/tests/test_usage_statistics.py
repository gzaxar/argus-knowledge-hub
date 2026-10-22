"""Usage statistics and Ask ARGUS feedback: counted without saying by whom.

Requests are counted by client, workspace and function; people only as a keyed hash; the model's calls with
their tokens. An answer is rated once; one rated down becomes an "Argus Knowledge" ticket for the person who
looks after Ask ARGUS, and nothing kept with the rating names who asked.
"""
import secrets
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.ask_conversation import AskConversation, AskMessage
from app.models.issue import Issue
from app.models.membership import Membership
from app.models.usage import AskFeedback, UsageLLM, UsagePresence, UsageRequest
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ask_feedback, usage

client = TestClient(app)


@pytest.fixture()
def world(monkeypatch):
    t = secrets.token_hex(4)
    ws = f"stats-{t}"
    feedback_ws = f"fb-{t}"
    monkeypatch.setenv("ARGUS_FEEDBACK_WORKSPACE", feedback_ws)
    monkeypatch.setenv("ARGUS_FEEDBACK_ASSIGNEE", f"keeper-{t}@argus.test")
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Stats"))
    people = {n: User(id=str(uuid.uuid4()), email=f"{n}-{t}@argus.test", name=n.title(), is_admin=(n != "eve"))
              for n in ("ann", "keeper", "eve")}
    db.add_all(people.values())
    db.flush()
    db.add(Membership(workspace_id=ws, user_id=people["eve"].id, can_read=True))
    db.commit()
    for p in people.values():
        db.refresh(p)
        db.expunge(p)
    db.close()
    yield {"ws": ws, "fb": feedback_ws, **people, "h": {"X-Workspace-Id": ws}}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in (ws, feedback_ws):
        if db.get(Workspace, w) is not None:
            db.delete(db.get(Workspace, w))
    db.execute(delete(AskFeedback).where(AskFeedback.workspace_id == ws))
    db.execute(delete(UsageRequest).where(UsageRequest.workspace_id == ws))
    db.execute(delete(UsageLLM).where(UsageLLM.workspace_id == ws))
    db.commit()
    db.close()


def as_(person):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)


def _conversation(w, owner, answers=("The pump is IP-02.",)):
    db = SessionLocal()
    cid = str(uuid.uuid4())
    c = AskConversation(id=cid, workspace_id=w["ws"], owner=owner, title="pumps")
    db.add(c)
    db.flush()
    seq = 0
    for a in answers:
        db.add(AskMessage(id=str(uuid.uuid4()), conversation_id=cid, seq=seq, role="user", content=f"Q{seq}: which pump?"))
        db.add(AskMessage(id=str(uuid.uuid4()), conversation_id=cid, seq=seq + 1, role="assistant", content=a,
                          model="qwen3", stopped="answered", seconds=3.2,
                          steps=[{"tool": "search_records", "arguments": {"query": "pump"}, "result": "SECRET ROWS",
                                  "error": None, "seconds": 0.4}]))
        seq += 2
    db.commit()
    db.close()
    return cid


def test_requests_are_counted_by_client_workspace_and_function(world):
    w = world
    as_(w["ann"])
    client.get("/v1/me", headers=w["h"])
    client.get("/v1/me", headers={**w["h"], "X-ARGUS-Client": "flutter/1.35.37/android"})
    client.get("/v1/me", headers={**w["h"], "User-Agent": "Mozilla/5.0"})
    usage.flush()
    db = SessionLocal()
    rows = {r.client: r.count for r in db.scalars(select(UsageRequest).where(
        UsageRequest.workspace_id == w["ws"], UsageRequest.function == "GET /v1/me", UsageRequest.day == date.today()))}
    db.close()
    assert rows == {"api": 1, "app": 1, "web": 1}


def test_people_are_counted_as_a_keyed_hash_never_by_id(world):
    w = world
    holder = usage.begin({"user-agent": "Mozilla/5.0"}, "/v1/assets")
    usage.note_user(w["eve"].id)
    usage.end(holder, "GET /v1/assets", 200)
    usage.flush()
    db = SessionLocal()
    mine = usage.person(db, w["eve"].id)
    rows = list(db.scalars(select(UsagePresence).where(UsagePresence.person == mine)))
    assert rows and rows[0].client == "web"
    assert not db.scalar(select(func.count()).select_from(UsagePresence).where(UsagePresence.person == w["eve"].id))
    db.execute(delete(UsagePresence).where(UsagePresence.person == mine))
    db.commit()
    db.close()


def test_the_models_tokens_are_counted_or_estimated(world):
    w = world
    usage.begin({"x-workspace-id": w["ws"]}, "/v1/ai/chat")
    usage.note_llm("qwen3", "chat", prompt_tokens=100, completion_tokens=20, seconds=1.5)
    usage.note_llm("qwen3", "chat", prompt_text="x" * 400, completion_text="y" * 40)
    usage.flush()
    db = SessionLocal()
    row = db.get(UsageLLM, (datetime.now(timezone.utc).date(), w["ws"], "qwen3", "chat"))
    db.close()
    assert (row.calls, row.prompt_tokens, row.completion_tokens, row.estimated_calls) == (2, 200, 30, 1)


def test_an_answer_rated_down_becomes_an_argus_knowledge_ticket_without_its_asker(world):
    w = world
    as_(w["eve"])
    cid = _conversation(w, owner=w["eve"].email)
    r = client.post(f"/v1/ai/conversations/{cid}/feedback", headers=w["h"],
                    json={"rating": "down", "comment": "It named the wrong pump."})
    assert r.status_code == 200, r.text
    assert r.json() == {"rating": "down", "reported": True}

    again = client.post(f"/v1/ai/conversations/{cid}/feedback", headers=w["h"], json={"rating": "up"})
    assert again.status_code == 409                                   # once

    db = SessionLocal()
    fb = db.scalar(select(AskFeedback).where(AskFeedback.workspace_id == w["ws"]))
    assert fb.question.startswith("Q0") and fb.answer == "The pump is IP-02." and fb.model == "qwen3"
    assert fb.tools == [{"tool": "search_records", "arguments": {"query": "pump"}, "error": None, "seconds": 0.4}]
    kept = " ".join(str(getattr(fb, c.name)) for c in AskFeedback.__table__.columns)
    assert w["eve"].email not in kept and w["eve"].id not in kept and cid not in kept and "SECRET ROWS" not in kept

    ticket = db.get(Issue, fb.ticket_uid)
    assert ticket.workspace_id == w["fb"] and ticket.assignee == w["keeper"].id
    assert ticket.schema_uid.endswith(":argus-knowledge") and "wrong pump" in ticket.description
    assert w["eve"].email not in ticket.description and ticket.created_by is None
    feedback_ws = db.get(Workspace, w["fb"])
    assert not feedback_ws.default_can_read_tickets
    assert db.scalar(select(Membership).where(Membership.workspace_id == w["fb"],
                                              Membership.user_id == w["keeper"].id)).can_read_tickets
    db.close()


def test_an_answer_rated_up_is_counted_with_no_ticket_and_only_by_its_asker(world):
    w = world
    cid = _conversation(w, owner=w["eve"].email, answers=("one", "two"))
    as_(w["ann"])
    assert client.post(f"/v1/ai/conversations/{cid}/feedback", headers=w["h"],
                       json={"rating": "up"}).status_code == 404          # not hers
    as_(w["eve"])
    r = client.post(f"/v1/ai/conversations/{cid}/feedback", headers=w["h"], json={"rating": "up", "answer_index": 0})
    assert r.json() == {"rating": "up", "reported": False}
    detail = client.get(f"/v1/ai/conversations/{cid}", headers=w["h"]).json()
    assert [m.get("rating") for m in detail["messages"] if m["role"] == "assistant"] == ["up", None]


def test_the_statistics_are_for_administrators(world):
    w = world
    as_(w["eve"])
    assert client.get("/v1/admin/statistics").status_code == 403
    as_(w["ann"])
    client.get("/v1/me", headers=w["h"])
    r = client.get("/v1/admin/statistics?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["requests_per_day"]) == 7 and body["requests_per_day"][-1]["api"] >= 1
    assert any(x["workspace"] == w["ws"] for x in body["workspaces"])
    assert {"top", "slowest", "failing", "by_client"} <= set(body["functions"])
    assert body["feedback"]["workspace"] == w["fb"]


def test_the_assignee_can_be_set_in_the_installation_settings(world):
    from app.models.app_setting import AppSetting
    db = SessionLocal()
    assert ask_feedback.assignee_email(db) == world["keeper"].email
    row = db.get(AppSetting, ask_feedback.SETTING) or AppSetting(key=ask_feedback.SETTING, value={})
    previous = dict(row.value or {})
    row.value = {"assignee": "someone@else.test"}
    db.add(row)
    db.flush()
    assert ask_feedback.assignee_email(db) == "someone@else.test"
    db.rollback()
    assert previous.get("assignee") is None or ask_feedback.assignee_email(db) == previous["assignee"]
    db.close()


def test_sizes_are_read_as_kubernetes_quantities():
    from app.services.storage import parse_size
    assert parse_size("15Gi") == 15 * 2 ** 30 and parse_size("500M") == 500 * 10 ** 6
    assert parse_size("1024") == 1024 and parse_size("") is None and parse_size("lots") is None


def test_what_is_left_is_whichever_runs_out_first():
    from app.services.storage import available
    assert available(4, planned=10, disk_free=100) == 6           # the planned room
    assert available(4, planned=10, disk_free=2) == 2             # the disk under a volume that does not enforce it
    assert available(12, planned=10, disk_free=None) == 0
    assert available(4, planned=None, disk_free=None) is None


def test_storage_is_measured_kept_per_day_and_projected(world, tmp_path, monkeypatch):
    from app.models.usage import UsageStorage
    from app.services import storage
    files = tmp_path / "attachments"
    (files / "ws" / "a").mkdir(parents=True)
    (files / "ws" / "a" / "one.bin").write_bytes(b"x" * 3000)
    (files / "two.bin").write_bytes(b"y" * 1000)
    monkeypatch.setenv("ATTACHMENTS_DIR", str(files))
    monkeypatch.setenv("ARGUS_PORTABILITY_ROOT", str(tmp_path / "none"))
    monkeypatch.setenv("ARGUS_STORAGE_ATTACHMENTS_SIZE", "10K")
    monkeypatch.setenv("ARGUS_STORAGE_DATABASE_SIZE", "10Gi")
    db = SessionLocal()
    try:
        out = storage.report(db, date.today(), refresh=True)
        areas = {a["area"]: a for a in out["areas"]}
        a = areas["attachments"]
        assert (a["used_bytes"], a["files"], a["planned_bytes"]) == (4000, 2, 10_000)
        assert a["available_bytes"] == min(6000, a["disk_free_bytes"])
        assert areas["database"]["used_bytes"] > 0 and areas["database"]["planned_bytes"] == 10 * 2 ** 30
        assert areas["portability"]["used_bytes"] == 0
        row = db.get(UsageStorage, (datetime.now(timezone.utc).date(), "attachments"))
        assert row.used_bytes == 4000                                  # today's measurement, for the trend
        assert out["trend"][-1]["attachments"] == 4000
        assert out["attachment_growth"][-1]["day"] == date.today().isoformat()
        assert out["largest_tables"]
    finally:
        db.execute(delete(UsageStorage).where(UsageStorage.day == datetime.now(timezone.utc).date()))
        db.commit()
        db.close()
