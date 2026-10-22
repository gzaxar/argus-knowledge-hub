"""Ask ARGUS as a chat: the answer streamed as it is worked out, kept as a conversation that a follow-up
continues, and each conversation its author's alone.

The model is scripted: what is tested is the stream (the lookups as they run, the text as it is written,
a <think> block left out), what is saved, and what a follow-up sends the model.
"""
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ask import _ThinkFilter

client = TestClient(app)


@pytest.fixture()
def chat_world():
    t = secrets.token_hex(4)
    ws = f"chat-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Chat"))
    db.flush()
    db.add(Schema(uid=f"{ws}:cam", workspace_id=ws, name="Camera", applies_to="objects"))
    db.flush()
    db.add(Asset(uid=f"{ws}-cam", workspace_id=ws, schema_uid=f"{ws}:cam", key=f"{ws.upper()}:CAM01",
                 name="FI4-B-CAM-VIS-001", type="Camera"))
    db.add(LLMConfig(workspace_id=ws, base_url="https://gateway.example/v1", model="m", enabled=True,
                     last_check_ok=True))
    people = [User(id=str(uuid.uuid4()), email=f"{n}-{t}@argus.test", is_admin=True) for n in ("ann", "bob")]
    db.add_all(people)
    db.commit()
    for p in people:
        db.refresh(p)
        db.expunge(p)
    db.close()
    yield {"ws": ws, "ann": people[0], "bob": people[1], "h": {"X-Workspace-Id": ws}}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.query(LLMConfig).filter(LLMConfig.workspace_id == ws).delete()
    db.commit()
    db.close()


def as_(person):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)


def scripted_stream(monkeypatch, turns):
    """A model that streams these turns in order; each turn is a list of (kind, value) pieces, the last
    being the assembled message. Records the messages it was sent."""
    sent = []

    def fake(endpoint, messages, tools=None, max_tokens=1200):
        sent.append([dict(m) for m in messages])
        yield from turns.pop(0)

    monkeypatch.setattr("app.services.ask.converse_stream", fake)
    return sent


def lookup(name, arguments):
    call = {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
    return [("reasoning", "I should search."), ("message", {"role": "assistant", "content": "", "tool_calls": [call]})]


def answer(*pieces):
    return [("content", p) for p in pieces] + [("message", {"role": "assistant", "content": "".join(pieces)})]


def events(resp):
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def test_a_turn_streams_its_lookups_and_its_answer_and_is_kept(chat_world, monkeypatch):
    w = chat_world
    as_(w["ann"])
    scripted_stream(monkeypatch, [
        lookup("search_objects", {"query": "camera"}),
        answer("<think>which one", "?</think>One camera: ", f"`{w['ws'].upper()}:CAM01`."),
    ])
    resp = client.post("/v1/ai/chat", headers=w["h"], json={"question": "What cameras?"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    evs = events(resp)
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "conversation" and kinds[-1] == "done"
    assert kinds.index("thinking") < kinds.index("step_start") < kinds.index("step") < kinds.index("text")
    step = next(e for e in evs if e["type"] == "step")
    assert step["tool"] == "search_objects" and step["summary"] == "1 found"
    written = "".join(e["text"] for e in evs if e["type"] == "text")
    assert written == f"One camera: `{w['ws'].upper()}:CAM01`."            # the <think> block is not shown
    cid = evs[0]["id"]
    saved = client.get(f"/v1/ai/conversations/{cid}", headers=w["h"]).json()
    assert saved["title"] == "What cameras?"
    assert [(m["role"], m["content"]) for m in saved["messages"]] == [
        ("user", "What cameras?"), ("assistant", f"One camera: `{w['ws'].upper()}:CAM01`.")]
    assert saved["messages"][1]["steps"][0]["tool"] == "search_objects"
    assert saved["messages"][1]["stopped"] == "answered"


def test_a_follow_up_is_answered_with_the_earlier_turns(chat_world, monkeypatch):
    w = chat_world
    as_(w["ann"])
    sent = scripted_stream(monkeypatch, [answer("There is one camera."), answer("It is FI4-B-CAM-VIS-001.")])
    first = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "How many cameras?"}))
    cid = first[0]["id"]
    second = events(client.post("/v1/ai/chat", headers=w["h"],
                                json={"question": "Which one?", "conversation_id": cid}))
    assert second[0]["id"] == cid
    roles = [(m["role"], m["content"]) for m in sent[1] if m["role"] != "system"]
    assert roles == [("user", "How many cameras?"), ("assistant", "There is one camera."), ("user", "Which one?")]
    listed = client.get("/v1/ai/conversations", headers=w["h"]).json()
    assert [c["id"] for c in listed] == [cid]
    assert len(client.get(f"/v1/ai/conversations/{cid}", headers=w["h"]).json()["messages"]) == 4


def test_a_conversation_is_its_authors_alone(chat_world, monkeypatch):
    w = chat_world
    as_(w["ann"])
    scripted_stream(monkeypatch, [answer("One camera.")])
    cid = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "Cameras?"}))[0]["id"]
    as_(w["bob"])
    assert client.get("/v1/ai/conversations", headers=w["h"]).json() == []
    assert client.get(f"/v1/ai/conversations/{cid}", headers=w["h"]).status_code == 404
    assert client.post("/v1/ai/chat", headers=w["h"],
                       json={"question": "and?", "conversation_id": cid}).status_code == 404
    assert client.delete(f"/v1/ai/conversations/{cid}", headers=w["h"]).status_code == 404
    as_(w["ann"])
    assert client.delete(f"/v1/ai/conversations/{cid}", headers=w["h"]).status_code == 204
    assert client.get("/v1/ai/conversations", headers=w["h"]).json() == []


def test_a_think_tag_split_across_pieces_is_still_left_out():
    f = _ThinkFilter()
    assert "".join(f.feed(p) for p in ["Hello <thi", "nk>secret</th", "ink> world"]) == "Hello  world"
    f = _ThinkFilter()
    assert "".join(f.feed(p) for p in ["a < b", " and c"]) + f.pending == "a < b and c"


def test_a_spoken_turn_asks_for_a_short_answer_and_one_clarifying_question(chat_world, monkeypatch):
    w = chat_world
    as_(w["ann"])
    sent = scripted_stream(monkeypatch, [answer("One camera."), answer("Which camera?")])
    client.post("/v1/ai/chat", headers=w["h"], json={"question": "What cameras?", "voice": True})
    system = sent[0][0]["content"]
    assert "spoken" in system and "exactly one" in system and "clarifying question" in system
    client.post("/v1/ai/chat", headers=w["h"], json={"question": "And the other?"})
    assert "spoken" not in sent[1][0]["content"], "only a spoken turn is asked for it"
