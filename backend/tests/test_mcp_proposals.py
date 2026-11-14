"""Proposals through MCP (docs/mcp-proposals.md): an assistant proposes a record, a relation, a ticket and a draft
document; nothing changes until a person applies them in the Review queue; a token may not decide, and may not
propose what it could not do by hand."""
import json
import secrets
import uuid

from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity, hash_token
from app.db import SessionLocal
from app.main import app
from app.models.api_token import ApiToken
from app.models.asset import Asset, Relation
from app.models.document import Document, DocumentRelation
from app.models.issue import Issue
from app.models.membership import Membership
from app.models.user import User
from app.models.workspace import Workspace
from app.services.asset_types import ensure_asset_types
from tests.test_mcp import rpc

client = TestClient(app)


def _world(scopes=None):
    t = secrets.token_hex(3)
    ws = f"mcpp-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Proposals"))
    db.flush()
    ensure_asset_types(db, ws)
    raw = secrets.token_urlsafe(16)
    token = ApiToken(workspace_id=ws, token_hash=hash_token(raw), label="claude-desktop")
    if scopes is not None:
        token.scopes = scopes
    db.add(token)
    person = User(id=str(uuid.uuid4()), email=f"p-{t}@argus.test", name=f"Reviewer {t}")
    db.add(person)
    db.flush()
    db.add(Membership(workspace_id=ws, user_id=person.id, can_read=True, can_create=True, can_modify=True,
                      can_delete=True, can_read_tickets=True, can_create_tickets=True, can_modify_tickets=True,
                      can_read_documents=True, can_create_documents=True, can_modify_documents=True))
    from app.ledger import engine
    camera = Asset(uid=f"cam-{t}", workspace_id=ws, schema_uid=engine.ensure_type(db, ws, "Camera").uid,
                   key=f"CAM-{t}", name="Camera 1", type="Camera", attributes={}, record_status="Active")
    db.add(camera)
    cam_key, cam_uid = camera.key, camera.uid
    db.commit()
    db.refresh(person)
    db.expunge(person)
    db.close()
    return ws, raw, person, cam_key, cam_uid


def call(raw, name, args):
    body = rpc(raw, "tools/call", {"name": name, "arguments": args}).json()["result"]
    return body["isError"], body["content"][0]["text"]


def test_an_assistant_proposes_and_a_person_applies():
    ws, raw, person, cam_key, cam_uid = _world()
    listed = {t["name"]: t for t in rpc(raw, "tools/list").json()["result"]["tools"]}
    assert listed["propose_document"]["annotations"]["readOnlyHint"] is False
    assert listed["propose_document"]["annotations"]["destructiveHint"] is False
    assert "propose_ioc_pull_request" not in listed
    assert "a proposal waits for a person" in rpc(raw, "initialize").json()["result"]["instructions"]

    err, text = call(raw, "propose_create_record", {"type": "Camera", "name": "Camera 2", "reason": "the second one"})
    assert not err, text
    made = json.loads(text)
    assert made["ref"] == "new:1" and made["review"].endswith("/review") and "nothing has changed" in made["status"]
    err, text = call(raw, "propose_relation", {"from": "new:1", "relation_type": "associated with", "to": cam_key})
    assert not err, text
    err, text = call(raw, "propose_ticket", {"title": "Camera 1 drops frames", "object": cam_key, "priority": "high"})
    assert not err, text
    err, text = call(raw, "propose_document", {"title": "Replacing a camera", "type": "Procedure",
                                                "body": "# Replacing a camera\n\n1. Power off.", "describes": [cam_key]})
    assert err and "no document type 'Procedure'" in text                 # refused, with the reason
    err, text = call(raw, "propose_document", {"title": "Replacing a camera",
                                                "body": "# Replacing a camera\n\n1. Power off.", "describes": [cam_key]})
    assert not err, text

    db = SessionLocal()
    assert db.query(Asset).filter(Asset.workspace_id == ws, Asset.name == "Camera 2").count() == 0   # nothing yet
    db.close()
    h = {"X-Workspace-Id": ws, "Authorization": f"Bearer {raw}"}
    waiting = client.get("/v1/proposals", headers=h).json()
    assert [w["kind"] for w in waiting] == ["create", "relate", "ticket", "document"]
    assert waiting[0]["conversation"]["from"] == "token claude-desktop" and waiting[0]["reason"] == "the second one"
    # A token may propose, never decide.
    assert client.post("/v1/proposals/apply", headers=h, json={"ids": [waiting[0]["id"]]}).status_code == 403

    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)
    try:
        done = client.post("/v1/proposals/apply", headers={"X-Workspace-Id": ws},
                           json={"ids": [w["id"] for w in waiting[:2]] + [waiting[3]["id"]]})
        assert done.status_code == 200, done.text
        assert {d["kind"]: d["status"] for d in done.json()} == {"create": "applied", "relate": "applied",
                                                                 "document": "applied"}, done.json()
        gone = client.post("/v1/proposals/discard", headers={"X-Workspace-Id": ws}, json={"ids": [waiting[2]["id"]]})
        assert gone.json()[0]["status"] == "discarded"
        assert client.get("/v1/proposals", headers={"X-Workspace-Id": ws}).json() == []
    finally:
        app.dependency_overrides.pop(get_identity, None)

    db = SessionLocal()
    new = db.query(Asset).filter(Asset.workspace_id == ws, Asset.name == "Camera 2").one()
    assert db.query(Relation).filter(Relation.from_asset_uid == new.uid, Relation.to_asset_uid == cam_uid).count() == 1
    doc = db.query(Document).filter(Document.workspace_id == ws, Document.title == "Replacing a camera").one()
    assert db.query(DocumentRelation).filter(DocumentRelation.from_document_uid == doc.uid,
                                             DocumentRelation.to_uid == cam_uid).count() == 1
    assert db.query(Issue).filter(Issue.workspace_id == ws).count() == 0          # the discarded ticket
    db.close()
    # The day's proposals are not an Ask conversation of anybody's.
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)
    try:
        assert client.get("/v1/ai/conversations", headers={"X-Workspace-Id": ws}).json() == []
    finally:
        app.dependency_overrides.pop(get_identity, None)


def test_a_token_may_not_propose_what_it_could_not_do():
    ws, raw, _person, cam_key, _uid = _world(scopes=["read"])
    err, text = call(raw, "propose_ticket", {"title": "Anything", "object": cam_key})
    assert err and "may not create tickets" in text
    db = SessionLocal()
    assert db.get(Workspace, ws) is not None
    db.close()
