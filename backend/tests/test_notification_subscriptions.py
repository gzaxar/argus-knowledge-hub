"""What a person asked to hear about in a workspace: new tickets, new and published documents, new equipment —
never what they did themselves, never what they may not read; and, for the phone, everything unread across
their workspaces."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_types

client = TestClient(app)
FULL = dict(can_read=True, can_create=True, can_modify=True, can_read_tickets=True, can_create_tickets=True,
            can_modify_tickets=True, can_read_documents=True, can_create_documents=True, can_modify_documents=True,
            can_approve_documents=True)


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    ws, other = f"sub-{t}", f"sub-other-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=ws, name="Linac"), Workspace(id=other, name="Ring")])
    db.flush()
    types = asset_types.ensure_asset_types(db, ws).uids
    people = {}
    for name in ("ann", "bob", "cid"):
        u = User(id=str(uuid.uuid4()), email=f"{name}-{t}@argus.test", name=name, is_admin=False)
        db.add(u)
        db.flush()
        people[name] = u
    db.add(Membership(workspace_id=ws, user_id=people["ann"].id, **FULL))
    db.add(Membership(workspace_id=ws, user_id=people["bob"].id, **FULL))
    db.add(Membership(workspace_id=other, user_id=people["bob"].id, **FULL))
    db.add(Membership(workspace_id=ws, user_id=people["cid"].id,          # reads equipment, not documents
                      **{**FULL, "can_read_documents": False}))
    db.commit()
    for u in people.values():
        db.refresh(u)
        db.expunge(u)
    db.close()
    yield {"ws": ws, "other": other, "types": types, **people}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in (ws, other):
        db.delete(db.get(Workspace, w))
    db.commit()                                     # their records first: a revision names its author
    for u in people.values():
        db.delete(db.get(User, u.id))
    db.commit()
    db.close()


def as_(user):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user)


def titles(w, who, workspace=None):
    as_(w[who])
    return [n["title"] for n in client.get("/v1/notifications/everywhere").json()
            if workspace is None or n["workspace_id"] == workspace]


def test_subscribers_hear_about_new_things_and_the_author_does_not(world):
    w = world
    for who in ("ann", "bob", "cid"):
        as_(w[who])
        assert client.put(f"/v1/notifications/subscriptions/{w['ws']}",
                          json={"tickets": True, "documents": True, "assets": True}).status_code == 200
    as_(w["ann"])
    h = {"X-Workspace-Id": w["ws"]}
    assert client.post("/v1/issues", headers=h, json={"uid": str(uuid.uuid4()), "title": "Gauge reads zero"}).status_code in (200, 201)
    doc = str(uuid.uuid4())
    assert client.post("/v1/documents", headers=h, json={"uid": doc, "title": "Bake-out", "body_markdown": "Heat"}).status_code == 201
    r = client.post("/v1/assets", headers=h, json={"uid": str(uuid.uuid4()), "schema_uid": w["types"]["Ion Pump"],
                                                   "key": f"{w['ws']}-IP-9", "name": "Ion pump 9", "attributes": {}})
    assert r.status_code == 201, r.text

    bob = titles(w, "bob")
    assert "New ticket: Gauge reads zero" in bob and any(t.startswith("New document:") for t in bob)
    assert any(t.startswith("New equipment: Ion pump 9") for t in bob)
    assert titles(w, "ann") == [], "not what you did yourself"
    cid = titles(w, "cid")
    assert not any(t.startswith("New document") for t in cid), "not what you may not read"
    assert any(t.startswith("New equipment") for t in cid)


def test_unsubscribed_hears_nothing_and_the_list_covers_every_workspace(world):
    w = world
    as_(w["bob"])
    subs = {s["workspace_id"]: s for s in client.get("/v1/notifications/subscriptions").json()}
    assert {w["ws"], w["other"]} <= set(subs) and subs[w["ws"]]["tickets"] is False
    assert subs[w["other"]]["workspace_name"] == "Ring"
    as_(w["ann"])
    client.post("/v1/issues", headers={"X-Workspace-Id": w["ws"]}, json={"uid": str(uuid.uuid4()), "title": "Quiet"})
    assert titles(w, "bob") == []


def test_a_workspace_one_cannot_open_cannot_be_subscribed_to(world):
    w = world
    as_(w["ann"])
    assert client.put(f"/v1/notifications/subscriptions/{w['other']}", json={"tickets": True}).status_code == 404


def test_the_phone_asks_for_what_is_new_since_it_last_looked(world):
    w = world
    as_(w["bob"])
    client.put(f"/v1/notifications/subscriptions/{w['ws']}", json={"tickets": True})
    as_(w["ann"])
    for title in ("First", "Second"):
        client.post("/v1/issues", headers={"X-Workspace-Id": w["ws"]}, json={"uid": str(uuid.uuid4()), "title": title})
    as_(w["bob"])
    rows = client.get("/v1/notifications/everywhere").json()
    assert [r["title"] for r in rows] == ["New ticket: First", "New ticket: Second"]
    assert rows[0]["workspace_name"] == "Linac" and rows[0]["issue_uid"]
    later = client.get("/v1/notifications/everywhere", params={"after": rows[0]["id"]}).json()
    assert [r["title"] for r in later] == ["New ticket: Second"]


def test_a_reader_of_documents_only_hears_about_new_documents(world):
    """The phone's list keeps a workspace's news for anyone who may read some kind of record there, documents
    included: a person whose role reads only documents is told about the new ones they subscribed to."""
    w = world
    t = secrets.token_hex(3)
    db = SessionLocal()
    dee = User(id=str(uuid.uuid4()), email=f"dee-{t}@argus.test", name="dee", is_admin=False)
    db.add(dee)
    db.flush()
    db.add(Membership(workspace_id=w["ws"], user_id=dee.id, can_read=False, can_read_tickets=False,
                      can_read_documents=True))
    db.commit()
    db.refresh(dee)
    db.expunge(dee)
    db.close()
    try:
        as_(dee)
        assert w["ws"] in {s["workspace_id"] for s in client.get("/v1/notifications/subscriptions").json()}
        assert client.put(f"/v1/notifications/subscriptions/{w['ws']}", json={"documents": True}).status_code == 200
        as_(w["ann"])
        assert client.post("/v1/documents", headers={"X-Workspace-Id": w["ws"]},
                           json={"uid": str(uuid.uuid4()), "title": "Interlock test"}).status_code == 201
        as_(dee)
        news = [n["title"] for n in client.get("/v1/notifications/everywhere").json()]
        assert any(t.startswith("New document:") and "Interlock test" in t for t in news), news
    finally:
        db = SessionLocal()
        from app.models.workflow import Notification, NotificationSubscription
        db.query(Notification).filter(Notification.recipient == dee.id).delete()
        db.query(NotificationSubscription).filter(NotificationSubscription.user_id == dee.id).delete()
        db.query(Membership).filter(Membership.user_id == dee.id).delete()
        db.delete(db.get(User, dee.id))
        db.commit()
        db.close()
