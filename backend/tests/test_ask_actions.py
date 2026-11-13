"""Changes Ask ARGUS proposes: checked when proposed, nothing changed until the person applies them, then
applied through the forms' code, in order, each standing or failing on its own.

The case is the one that asked for it: ELI's screen stations, which inference did not make, each composed of
the camera and the motor axis the configuration names after it.
"""
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset, Relation
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_types as at

client = TestClient(app)


@pytest.fixture()
def world():
    t = secrets.token_hex(4)
    ws = f"act-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Actions"))
    db.flush()
    at.ensure_asset_types(db, ws)
    keys = {}
    for kind, key in (("Camera", f"{ws.upper()}:SCN01:CAM01"), ("Motor Axis", f"{ws.upper()}:SCN01:MOT01")):
        schema = db.query(Schema).filter(Schema.workspace_id == ws, Schema.name == kind).one()
        db.add(Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=schema.uid, key=key, name=key, type=kind))
        keys[kind] = key
    db.add(LLMConfig(workspace_id=ws, base_url="https://gateway.example/v1", model="m", enabled=True,
                     last_check_ok=True))
    person = User(id=str(uuid.uuid4()), email=f"ann-{t}@argus.test", is_admin=True)
    db.add(person)
    db.commit()
    db.refresh(person)
    db.expunge(person)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)
    yield {"ws": ws, "h": {"X-Workspace-Id": ws}, "camera": keys["Camera"], "motor": keys["Motor Axis"]}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.query(LLMConfig).filter(LLMConfig.workspace_id == ws).delete()
    db.commit()
    db.close()


def scripted(monkeypatch, turns):
    sent = []

    def fake(endpoint, messages, tools=None, max_tokens=1200):
        sent.append({"messages": [dict(m) for m in messages], "tools": [t["function"]["name"] for t in tools or []]})
        yield from turns.pop(0)

    monkeypatch.setattr("app.services.ask.converse_stream", fake)
    return sent


def call(name, arguments):
    c = {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
    return [("message", {"role": "assistant", "content": "", "tool_calls": [c]})]


def answer(text):
    return [("content", text), ("message", {"role": "assistant", "content": text})]


def events(resp):
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def test_proposed_changes_wait_for_the_person_and_then_are_applied(world, monkeypatch):
    w = world
    sent = scripted(monkeypatch, [
        call("propose_create_record", {"type": "screen station", "name": "SCN01", "reason": "camera and motor"}),
        call("propose_relation", {"from": "new:1", "relation_type": "composed of", "to": w["camera"]}),
        call("propose_relation", {"from": "new:1", "relation_type": "composed of", "to": w["motor"]}),
        call("propose_create_record", {"type": "Flux Capacitor", "name": "X"}),           # refused: no such type
        answer("Proposed SCN01 with its camera and motor; apply them to make the changes."),
    ])
    resp = client.post("/v1/ai/chat", headers=w["h"], json={"question": "Create the screen SCN01 and link it"})
    evs = events(resp)
    assert "propose_create_record" in sent[0]["tools"]                     # offered: this person may create
    proposals = [e["action"] for e in evs if e["type"] == "proposal"]
    assert [p["number"] for p in proposals] == [1, 2, 3] and all(p["status"] == "proposed" for p in proposals)
    refused = [e for e in evs if e["type"] == "step" and e["error"]]
    assert len(refused) == 1 and "Flux Capacitor" in refused[0]["error"]
    # The model is told a proposal changes nothing, and how to refer to the record still to be made.
    assert json.loads(next(e for e in evs if e["type"] == "step")["result"])["ref"] == "new:1"
    cid = evs[0]["id"]

    db = SessionLocal()
    assert db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.type == "Screen Station").count() == 0
    db.close()

    listed = client.get(f"/v1/ai/conversations/{cid}/actions", headers=w["h"]).json()
    assert [a["status"] for a in listed] == ["proposed"] * 3
    applied = client.post(f"/v1/ai/conversations/{cid}/actions/apply", headers=w["h"],
                          json={"ids": [a["id"] for a in listed]}).json()
    assert [a["status"] for a in applied] == ["applied"] * 3, applied

    db = SessionLocal()
    station = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.type == "Screen Station").one()
    assert station.name == "SCN01" and applied[0]["result"]["key"] == station.key
    parts = {db.get(Asset, r.to_asset_uid).key for r in db.query(Relation).filter(
        Relation.from_asset_uid == station.uid, Relation.relation_type == "composed of")}
    assert parts == {w["camera"], w["motor"]}
    db.close()

    # The next turn knows what became of them.
    sent = scripted(monkeypatch, [answer("Done.")])
    client.post("/v1/ai/chat", headers=w["h"], json={"question": "Is it done?", "conversation_id": cid})
    note = next(m["content"] for m in sent[0]["messages"] if m["role"] == "system" and "proposed earlier" in m["content"])
    assert "A1" in note and "applied" in note and station.key in note


def test_a_ticket_is_proposed_on_an_object_and_opened_only_when_applied(world, monkeypatch):
    from app.models.issue import Issue
    w = world
    db = SessionLocal()
    db.add(Schema(uid=f"{w['ws']}:change", workspace_id=w["ws"], name="Change", applies_to="tickets"))
    db.commit()
    db.close()
    sent = scripted(monkeypatch, [
        call("propose_ticket", {"title": "Replace the camera", "type": "Rocket", "object": w["camera"]}),
        call("propose_ticket", {"title": "Replace the camera", "type": "Change", "object": w["camera"],
                                "priority": "medium", "due_date": "2026-12-15"}),
        answer("Proposed a change; apply it to open the ticket."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "Open a change next month"}))
    assert "propose_ticket" in sent[0]["tools"]
    assert "Today is" in sent[0]["messages"][0]["content"], "next month is counted from today"
    refused = next(e for e in evs if e["type"] == "step" and e["error"])
    assert "Rocket" in refused["error"] and "Change" in refused["error"]       # told which types there are
    proposal = next(e["action"] for e in evs if e["type"] == "proposal")
    assert proposal["kind"] == "ticket" and "Change" in proposal["summary"] and w["camera"] in proposal["summary"]
    db = SessionLocal()
    assert db.query(Issue).filter(Issue.workspace_id == w["ws"]).count() == 0     # nothing until applied
    db.close()
    cid = evs[0]["id"]
    applied = client.post(f"/v1/ai/conversations/{cid}/actions/apply", headers=w["h"],
                          json={"ids": [proposal["id"]]}).json()
    assert applied[0]["status"] == "applied", applied
    db = SessionLocal()
    issue = db.get(Issue, applied[0]["result"]["uid"])
    camera = db.query(Asset).filter(Asset.key == w["camera"]).one()
    assert issue.title == "Replace the camera" and issue.asset_uid == camera.uid and issue.priority == "medium"
    assert issue.schema_uid == f"{w['ws']}:change" and issue.due_date.date().isoformat() == "2026-12-15"
    db.close()


def test_a_relation_to_a_record_whose_creation_failed_fails_with_it(world, monkeypatch):
    w = world
    taken = f"{w['ws'].upper()}:TAKEN"
    scripted(monkeypatch, [
        call("propose_create_record", {"type": "Screen Station", "name": "SCN02", "key": taken}),
        call("propose_relation", {"from": "new:1", "relation_type": "composed of", "to": w["camera"]}),
        answer("Proposed."),
    ])
    cid = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "SCN02"}))[0]["id"]
    # Somebody takes the key between the proposal and its application.
    db = SessionLocal()
    schema = db.query(Schema).filter(Schema.workspace_id == w["ws"], Schema.name == "Camera").one()
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=schema.uid, key=taken, name="x",
                 type="Camera"))
    db.commit()
    db.close()
    ids = [a["id"] for a in client.get(f"/v1/ai/conversations/{cid}/actions", headers=w["h"]).json()]
    out = client.post(f"/v1/ai/conversations/{cid}/actions/apply", headers=w["h"], json={"ids": ids}).json()
    assert [a["status"] for a in out] == ["failed", "failed"]
    assert "taken" in out[0]["error"] and "new:1" in out[1]["error"]


def test_a_discarded_proposal_is_never_applied(world, monkeypatch):
    w = world
    scripted(monkeypatch, [
        call("propose_update_record", {"record": w["camera"], "name": "Renamed"}),
        answer("Proposed."),
    ])
    cid = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "rename"}))[0]["id"]
    ids = [a["id"] for a in client.get(f"/v1/ai/conversations/{cid}/actions", headers=w["h"]).json()]
    assert client.post(f"/v1/ai/conversations/{cid}/actions/discard", headers=w["h"],
                       json={"ids": ids}).json()[0]["status"] == "discarded"
    assert client.post(f"/v1/ai/conversations/{cid}/actions/apply", headers=w["h"],
                       json={"ids": ids}).json()[0]["status"] == "discarded"
    db = SessionLocal()
    assert db.query(Asset).filter(Asset.key == w["camera"]).one().name == w["camera"]
    db.close()


def test_a_relation_the_rules_forbid_is_refused_when_proposed(world, monkeypatch):
    w = world
    scripted(monkeypatch, [
        call("propose_relation", {"from": w["camera"], "relation_type": "installed at", "to": w["motor"]}),
        answer("Could not."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "relate"}))
    step = next(e for e in evs if e["type"] == "step")
    assert step["error"] and "cannot start at type Camera" in step["error"]
    assert not [e for e in evs if e["type"] == "proposal"]


def test_a_reference_takes_the_record_its_value_names_and_is_checked_when_proposed(world, monkeypatch):
    """Issue #16: a unit's Located in was proposed as the room's name ("Stanza 118") and failed only when applied
    (“must reference an object of the correct type”). A reference now takes the record its value names — its
    key, uid or exact name — and a value no record answers is refused when proposed, with the reason."""
    w = world
    db = SessionLocal()
    area = db.query(Schema).filter(Schema.workspace_id == w["ws"], Schema.name == "Area").one()
    room = Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=area.uid, key=f"{w['ws'].upper()}-ARE-0001",
                 name="Stanza 118", type="Area")
    db.add(room)
    db.commit()
    room_uid, room_key = room.uid, room.key
    db.close()
    scripted(monkeypatch, [
        call("propose_update_record", {"record": w["camera"], "attributes": {"argus_location": "Stanza 999"}}),
        call("propose_update_record", {"record": w["camera"], "attributes": {"argus_location": w["motor"]}}),
        call("propose_update_record", {"record": w["camera"], "attributes": {"argus_location": "Stanza 118"}}),
        answer("Proposed: the camera is in Stanza 118."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "The camera is in Stanza 118"}))
    refused = [e["error"] for e in evs if e["type"] == "step" and e["error"]]
    assert len(refused) == 2
    assert "takes a record, not text" in refused[0] and "'Stanza 999'" in refused[0]
    assert "takes a Location" in refused[1] and w["motor"] in refused[1]                 # a record of another kind
    proposal = next(e["action"] for e in evs if e["type"] == "proposal")
    assert f"argus_location → {room_key} (Stanza 118)" in proposal["summary"]           # the room, not its uid
    applied = client.post(f"/v1/ai/conversations/{evs[0]['id']}/actions/apply", headers=w["h"],
                          json={"ids": [proposal["id"]]}).json()
    assert applied[0]["status"] == "applied", applied
    db = SessionLocal()
    camera = db.query(Asset).filter(Asset.key == w["camera"]).one()
    assert camera.attributes["argus_location"] == room_uid
    db.close()


def test_a_record_still_to_be_created_is_not_written_into_a_text_value(world, monkeypatch):
    """A Product Model proposed with vendor = "new:1" (the vendor proposed just before) kept the text "new:1",
    then went to the catalogue as a vendor called new:1. A new:N in a text value is refused when proposed."""
    w = world
    scripted(monkeypatch, [
        call("propose_update_record", {"record": w["camera"], "attributes": {"description": "new:1"}}),
        answer("I cannot write that."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "Its vendor is the new one"}))
    refused = [e["error"] for e in evs if e["type"] == "step" and e["error"]]
    assert len(refused) == 1 and "is text: write the name itself, not new:1" in refused[0]


def test_a_reference_to_a_record_still_to_be_created_says_how_to_set_it_later(world, monkeypatch):
    w = world
    scripted(monkeypatch, [
        call("propose_update_record", {"record": w["camera"], "attributes": {"argus_location": "new:3"}}),
        answer("Set it once the room exists."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "It is in the new room"}))
    refused = [e["error"] for e in evs if e["type"] == "step" and e["error"]]
    assert len(refused) == 1 and "not created yet" in refused[0] and "propose_update_record" in refused[0]
