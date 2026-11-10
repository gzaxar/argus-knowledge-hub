"""Controlled documents (§19 item 4) and access reviews (§19 item 1)."""
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.api_token import ApiToken
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.group import Group, GroupMember
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.services import access_review, document_control
from tests.test_ledger_transition import token

client = TestClient(app)


@pytest.fixture()
def ws():
    ws = f"doc-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Documents"))
    db.flush()
    headers = token(db, ws)
    db.commit()
    db.close()
    return ws, headers


def published(headers, title="Bake-out procedure", retention="5y"):
    uid = str(uuid.uuid4())
    doc = client.post("/v1/documents", headers=headers, json={"uid": uid, "title": title, "body_markdown": "Steps",
                                                                "retention_class": retention})
    assert doc.status_code == 201, doc.text
    rev = client.get(f"/v1/documents/{uid}/revisions", headers=headers).json()[0]["uid"]
    for step in ("submit", "approve", "publish"):
        r = client.post(f"/v1/documents/{uid}/revisions/{rev}/{step}", headers=headers, json={"comment": "ok"})
        assert r.status_code == 200, (step, r.text)
    return uid


def test_a_released_document_is_kept_for_its_retention_and_can_only_be_retired(ws):
    _ws, headers = ws
    draft = client.post("/v1/documents", headers=headers, json={"uid": str(uuid.uuid4()), "title": "Draft"}).json()
    assert client.delete(f"/v1/documents/{draft['uid']}", headers=headers).status_code == 204   # never released

    uid = published(headers)
    retention = client.get(f"/v1/documents/{uid}/retention", headers=headers).json()
    assert retention["class"] == "5y" and not retention["deletable"] and retention["retain_until"]
    refused = client.delete(f"/v1/documents/{uid}", headers=headers)
    assert refused.status_code == 409 and refused.json()["detail"]["invariant"] == "retention"
    assert client.post("/v1/documents/bulk-delete", headers=headers, json={"uids": [uid]}).status_code == 409
    # Shortening a released document's retention would release it early.
    assert client.put(f"/v1/documents/{uid}/retention", headers=headers,
                      json={"retention_class": "none"}).status_code == 409
    assert client.put(f"/v1/documents/{uid}/retention", headers=headers,
                      json={"retention_class": "permanent"}).json()["permanent"]
    retired = client.post(f"/v1/documents/{uid}/retire", headers=headers, json={"reason": "obsolete"}).json()
    assert retired["retired_at"] is not None
    assert client.delete(f"/v1/documents/{uid}", headers=headers).status_code == 409


def test_the_author_of_a_revision_cannot_approve_it():
    rev = DocumentRevision(uid="r", document_uid="d", revision_number=1, authored_by="rossi")
    with pytest.raises(document_control.ControlError):
        document_control.assert_not_author(rev, "rossi")
    document_control.assert_not_author(rev, "bianchi")


def test_a_document_superseded_by_another_retires_and_points_to_it(ws):
    workspace, headers = ws
    old, new = published(headers, "Bake-out procedure v1"), published(headers, "Bake-out procedure v2")
    draft = client.post("/v1/documents", headers=headers, json={"uid": str(uuid.uuid4()), "title": "v3"}).json()
    assert client.post(f"/v1/documents/{old}/supersede", headers=headers,
                       json={"by_document_uid": draft["uid"], "reason": "not released"}).status_code == 409
    resp = client.post(f"/v1/documents/{old}/supersede", headers=headers,
                       json={"by_document_uid": new, "reason": "replaced by v2"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["superseded_by_uid"] == new and resp.json()["current_revision_uid"] is None
    db = SessionLocal()
    assert db.query(DocumentRelation).filter_by(from_document_uid=new, to_uid=old, relation_type="supersedes").count() == 1
    db.close()
    assert client.post(f"/v1/documents/{old}/supersede", headers=headers,
                       json={"by_document_uid": new, "reason": "again"}).status_code == 409


def test_an_attachment_proves_it_is_unchanged(ws, tmp_path):
    workspace, headers = ws
    f = tmp_path / "wiring.pdf"
    f.write_bytes(b"%PDF wiring diagram")
    db = SessionLocal()
    att = Attachment(uid=str(uuid.uuid4()), workspace_id=workspace, filename="wiring.pdf", file_size=19,
                     storage_path=str(f))
    db.add(att)
    db.commit()
    uid = att.uid
    db.close()
    assert client.get(f"/v1/attachments/{uid}/verify", headers=headers).json()["ok"]
    f.write_bytes(b"%PDF something else")
    check = client.get(f"/v1/attachments/{uid}/verify", headers=headers).json()
    assert not check["ok"] and not check["missing"]


def test_an_access_review_captures_every_grant_and_needs_two_distinct_signers(ws):
    workspace, headers = ws
    db = SessionLocal()
    access_review.install_templates(db)
    alice = User(id=f"alice-{workspace}", email=f"alice@{workspace}.example", name="Alice")
    bob = User(id=f"bob-{workspace}", email=f"bob@{workspace}.example", name="Bob")
    carol = User(id=f"carol-{workspace}", email=f"carol@{workspace}.example", name="Carol")
    group = Group(uid=f"g-{workspace}", name="Service desk")
    db.add_all([alice, bob, carol, group])
    db.flush()
    db.add(GroupMember(group_uid=group.uid, user_id=bob.id))
    now = datetime.now(timezone.utc)
    db.add(RoleBinding(workspace_id=workspace, subject_type="user", subject_id=alice.id,
                       role_id="argus-safety-investigator", created_at=now))
    db.add(RoleBinding(workspace_id=workspace, subject_type="group", subject_id=group.uid,
                       role_id="argus-service-desk-agent", created_at=now))
    db.add(ApiToken(workspace_id=workspace, token_hash=secrets.token_hex(16), label="procurement sync",
                    restricted_grants=["costs"]))
    db.commit()

    first = client.post("/v1/access-reviews", headers=headers, json={"required_signers": 2}).json()
    people = {p["email"]: p for p in first["snapshot"]["people"]}
    assert people[alice.email]["permissions"]["restricted"] == ["safety_investigation", "security_incident"]
    assert people[bob.email]["roles"] == [f"Service desk agent (via group {group.name})"]   # named, not by uid
    assert any(t["restricted_grants"] == ["costs"] for t in first["snapshot"]["tokens"])
    sign = lambda rid, who: client.post(f"/v1/access-reviews/{rid}/sign", headers=headers, json={"signer": who})
    assert sign(first["id"], "owner-a").json()["completed_at"] is None
    assert sign(first["id"], "owner-a").status_code == 409                 # each owner signs once

    db.add(RoleBinding(workspace_id=workspace, subject_type="user", subject_id=carol.id,
                       role_id="argus-auditor", created_at=now))
    db.commit()
    assert sign(first["id"], "owner-b").status_code == 409                 # access moved since
    second = client.post("/v1/access-reviews", headers=headers, json={}).json()
    assert f"user:{carol.email}" in second["changes"]["added"]
    sign(second["id"], "owner-a")
    done = sign(second["id"], "owner-b").json()
    assert done["completed_at"] is not None and len(done["signatures"]) == 2
    db.close()


def test_a_shared_document_is_read_with_its_files_in_every_workspace_and_changed_only_in_its_own(ws, tmp_path):
    owner, headers = ws
    reader = f"doc-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=reader, name="Elsewhere"))
    db.flush()
    elsewhere = token(db, reader)
    db.commit()
    uid = published(headers, "Shared vacuum rules")
    rev = client.get(f"/v1/documents/{uid}/current", headers=headers).json()["uid"]
    picture = tmp_path / "valve.png"
    picture.write_bytes(b"png")
    att = Attachment(uid=str(uuid.uuid4()), workspace_id=owner, document_revision_uid=rev, filename="valve.png",
                     mime_type="image/png", storage_path=str(picture), file_size=3)
    db.add(att)
    db.commit()
    att_uid = att.uid
    db.close()

    def seen_elsewhere():
        return [d["uid"] for d in client.get("/v1/documents", headers=elsewhere).json()]

    assert uid not in seen_elsewhere()
    assert client.get(f"/v1/attachments/{att_uid}", headers=elsewhere).status_code == 404

    assert client.put(f"/v1/documents/{uid}", headers=headers, json={"is_global": True}).status_code == 200
    assert uid in seen_elsewhere()
    assert client.get(f"/v1/documents/{uid}/current", headers=elsewhere).json()["uid"] == rev
    got = client.get(f"/v1/attachments/{att_uid}", headers=elsewhere)
    assert got.status_code == 200 and got.content == b"png", "its pictures open where it is shared"
    assert client.put(f"/v1/documents/{uid}", headers=elsewhere, json={"title": "Mine now"}).status_code == 404
    assert client.delete(f"/v1/attachments/{att_uid}", headers=elsewhere).status_code == 404

    db = SessionLocal()                                   # (the API refuses to make a shared document riservato)
    db.get(Document, uid).confidentiality = "riservato"
    db.commit()
    db.close()
    assert uid not in seen_elsewhere(), "riservato is never shared"
    assert client.get(f"/v1/attachments/{att_uid}", headers=elsewhere).status_code == 404
