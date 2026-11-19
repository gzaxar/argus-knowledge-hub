"""Run in ARGUS's normal migrated test-database environment."""
import secrets
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db import SessionLocal
from app.auth import hash_token
from app.models.api_token import ApiToken
from app.models.document import DocumentRelation
from app.models.workspace import Workspace
from tests.test_ledger_transition import token

client = TestClient(app)
NAV = "/v1/document-navigation"


@pytest.fixture()
def workspace():
    uid = f"nav-{secrets.token_hex(4)}"
    db = SessionLocal(); db.add(Workspace(id=uid, name="Navigation test")); db.flush()
    headers = token(db, uid); db.commit(); db.close()
    return uid, headers


def new_doc(headers, title="Document", **values):
    response = client.post("/v1/documents", headers=headers, json={"uid": str(uuid.uuid4()), "title": title, **values})
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def folder(headers, name="Subsystems", parent_uid=None):
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": name, "parent_uid": parent_uid})
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def graph(headers):
    response = client.get(NAV, headers=headers); assert response.status_code == 200, response.text
    return {n["id"]: n["parent_id"] for n in response.json()["nodes"]}


def test_imported_children_follow_the_parent_into_a_folder(workspace):
    ws, headers = workspace
    a, b = new_doc(headers, "WP02"), new_doc(headers, "How-to")
    response = client.post(f"/v1/documents/{b}/relations", headers=headers, json={"to_type": "document", "to_uid": a, "relation_type": "child_of"})
    assert response.status_code == 201
    f = folder(headers)
    assert client.put(f"{NAV}/documents/{a}/location", headers=headers, json={"folder_uid": f}).status_code == 200
    result = graph(headers)
    assert result[f"d:{a}"] == f"f:{f}" and result[f"d:{b}"] == f"d:{a}"
    db = SessionLocal()
    assert len(db.scalars(select(DocumentRelation).where(DocumentRelation.workspace_id == ws)).all()) == 1
    db.close()


def test_child_creation_and_navigation_are_atomic(workspace):
    _, headers = workspace
    parent = new_doc(headers, "Parent")
    child = new_doc(headers, "Child", navigation_parent_document_uid=parent)
    assert graph(headers)[f"d:{child}"] == f"d:{parent}"
    bad_uid = str(uuid.uuid4())
    response = client.post("/v1/documents", headers=headers, json={"uid": bad_uid, "title": "Invalid child", "navigation_folder_uid": "missing"})
    assert response.status_code == 422
    assert client.get(f"/v1/documents/{bad_uid}", headers=headers).status_code == 404


def test_new_document_can_be_created_directly_in_a_folder(workspace):
    _, headers = workspace
    f = folder(headers)
    uid = new_doc(headers, navigation_folder_uid=f)
    assert graph(headers)[f"d:{uid}"] == f"f:{f}"
    preview = client.get(f"{NAV}/documents/{uid}/preview", headers=headers).json()
    assert preview["revision"]["state"] == "draft"


def test_document_and_folder_cycles_are_refused(workspace):
    _, headers = workspace
    a = new_doc(headers); b = new_doc(headers, navigation_parent_document_uid=a)
    assert client.put(f"{NAV}/documents/{a}/location", headers=headers, json={"parent_document_uid": b}).status_code == 422
    f = folder(headers); g = folder(headers, "Child folder", f)
    assert client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "Subsystems", "parent_uid": g}).status_code == 422


def test_delete_folder_requires_it_to_be_empty(workspace):
    _, headers = workspace
    f = folder(headers); doc = new_doc(headers, navigation_folder_uid=f)
    assert client.delete(f"{NAV}/folders/{f}", headers=headers).status_code == 409
    assert client.put(f"{NAV}/documents/{doc}/location", headers=headers, json={}).status_code == 200
    assert client.delete(f"{NAV}/folders/{f}", headers=headers).status_code == 204
    assert client.get(f"/v1/documents/{doc}", headers=headers).status_code == 200


def test_manual_location_can_be_reset_to_the_imported_parent(workspace):
    _, headers = workspace
    a, b = new_doc(headers), new_doc(headers)
    client.post(f"/v1/documents/{b}/relations", headers=headers, json={"to_type": "document", "to_uid": a, "relation_type": "child_of"})
    client.put(f"{NAV}/documents/{b}/location", headers=headers, json={})
    assert graph(headers)[f"d:{b}"] == "group:unfiled"
    assert client.delete(f"{NAV}/documents/{b}/location", headers=headers).status_code == 204
    assert graph(headers)[f"d:{b}"] == f"d:{a}"


def test_read_only_tokens_cannot_write_or_see_confidential_documents(workspace):
    ws, headers = workspace
    hidden = new_doc(headers, "Private", confidentiality="riservato")
    db = SessionLocal(); raw = secrets.token_urlsafe(20)
    db.add(ApiToken(workspace_id=ws, token_hash=hash_token(raw), scopes=["read"], resources=["documents"]))
    db.commit(); db.close(); reader = {"Authorization": f"Bearer {raw}"}
    result = client.get(NAV, headers=reader); assert result.status_code == 200
    assert hidden not in {d["uid"] for d in result.json()["documents"]}
    assert client.get(f"{NAV}/documents/{hidden}/preview", headers=reader).status_code == 404
    assert client.post(f"{NAV}/folders", headers=reader, json={"name": "Refused"}).status_code == 403


def test_shared_preview_does_not_return_a_foreign_draft(workspace):
    _, headers = workspace
    shared = new_doc(headers, "Shared", is_global=True, body_markdown="Draft content")
    other = f"other-{secrets.token_hex(4)}"; db = SessionLocal()
    db.add(Workspace(id=other, name="Other")); db.flush(); other_headers = token(db, other); db.commit(); db.close()
    result = client.get(f"{NAV}/documents/{shared}/preview", headers=other_headers)
    assert result.status_code == 200 and result.json()["revision"] is None and result.json()["revisions"] == []
    assert client.put(f"{NAV}/documents/{shared}/location", headers=other_headers, json={}).status_code == 404


def test_folder_names_are_unique_per_parent_ignoring_case(workspace):
    _, headers = workspace
    folder(headers, "Subsystems")
    assert client.post(f"{NAV}/folders", headers=headers, json={"name": " subsystems "}).status_code == 422


def test_preview_defaults_to_draft_without_changing_publication(workspace):
    _, headers = workspace
    uid = new_doc(headers, "Controlled", body_markdown="Released body")
    rev = client.get(f"/v1/documents/{uid}/revisions", headers=headers).json()[0]["uid"]
    for action in ("submit", "approve", "publish"):
        response = client.post(f"/v1/documents/{uid}/revisions/{rev}/{action}", headers=headers, json={"comment": "ok"})
        assert response.status_code == 200, response.text
    draft = client.post(f"/v1/documents/{uid}/revisions", headers=headers, json={"body_markdown": "Draft body"})
    assert draft.status_code == 201, draft.text
    result = client.get(f"{NAV}/documents/{uid}/preview", headers=headers).json()
    assert result["revision"]["state"] == "draft" and result["revision"]["body_markdown"] == "Draft body"
    assert result["document"]["current_revision_uid"] == rev
    published = client.get(f"{NAV}/documents/{uid}/preview", headers=headers, params={"revision_uid": rev}).json()
    assert published["revision"]["body_markdown"] == "Released body"


def test_folder_can_be_created_and_moved_between_document_folder_and_root(workspace):
    _, headers = workspace
    parent = new_doc(headers, "WP04 - Controls")
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": "EPIK8s", "parent_document_uid": parent})
    assert response.status_code == 201, response.text
    f = response.json()["uid"]
    assert response.json()["parent_uid"] is None
    assert response.json()["parent_document_uid"] == parent
    assert graph(headers)[f"f:{f}"] == f"d:{parent}"
    child = new_doc(headers, "Manual", navigation_folder_uid=f)
    before = client.get(f"{NAV}/documents/{child}/preview", headers=headers).json()
    parent_folder = folder(headers, "Other folder")
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "EPIK8s", "parent_uid": parent_folder})
    assert response.status_code == 200, response.text
    assert response.json()["parent_document_uid"] is None
    assert graph(headers)[f"f:{f}"] == f"f:{parent_folder}"
    assert graph(headers)[f"d:{child}"] == f"f:{f}"
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "EPIK8s", "parent_document_uid": parent})
    assert response.status_code == 200, response.text
    assert response.json()["parent_uid"] is None
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "EPIK8s"})
    assert response.status_code == 200, response.text
    assert graph(headers)[f"f:{f}"] is None
    after = client.get(f"{NAV}/documents/{child}/preview", headers=headers).json()
    assert after["revision"] == before["revision"]
    assert after["document"] == before["document"]


def test_folder_refuses_two_parents_missing_parents_and_mixed_cycles(workspace):
    _, headers = workspace
    parent = new_doc(headers, "Parent")
    f = folder(headers)
    for body, status in [
        ({"name": "Both", "parent_uid": f, "parent_document_uid": parent}, 422),
        ({"name": "Missing", "parent_document_uid": str(uuid.uuid4())}, 404),
    ]:
        response = client.post(f"{NAV}/folders", headers=headers, json=body)
        assert response.status_code == status, response.text
    child = new_doc(headers, "Inside", navigation_folder_uid=f)
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "Cycle", "parent_document_uid": child})
    assert response.status_code == 422, response.text
    assert graph(headers)[f"f:{f}"] is None
    assert graph(headers)[f"d:{child}"] == f"f:{f}"
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "Folder", "parent_document_uid": parent})
    assert response.status_code == 200, response.text
    response = client.put(f"{NAV}/documents/{parent}/location", headers=headers, json={"folder_uid": f})
    assert response.status_code == 422, response.text
    assert graph(headers)[f"f:{f}"] == f"d:{parent}"


def test_folder_name_uniqueness_is_scoped_to_the_exact_parent(workspace):
    _, headers = workspace
    a, b = new_doc(headers, "A"), new_doc(headers, "B")
    folder(headers, "Manuals")
    for parent in (a, b):
        response = client.post(f"{NAV}/folders", headers=headers, json={"name": "Manuals", "parent_document_uid": parent})
        assert response.status_code == 201, response.text
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": " manuals ", "parent_document_uid": a})
    assert response.status_code == 422, response.text


def test_folder_refuses_a_document_parent_from_another_workspace(workspace):
    _, headers = workspace
    other = f"nav-parent-{secrets.token_hex(4)}"
    db = SessionLocal(); db.add(Workspace(id=other, name="Other")); db.flush()
    other_headers = token(db, other); db.commit(); db.close()
    foreign = new_doc(other_headers, "Foreign", is_global=True)
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": "Refused", "parent_document_uid": foreign})
    assert response.status_code == 404, response.text
    f = folder(headers)
    response = client.put(f"{NAV}/folders/{f}", headers=headers, json={"name": "Refused", "parent_document_uid": foreign})
    assert response.status_code == 404, response.text
    assert graph(headers)[f"f:{f}"] is None


def test_hidden_parent_is_refused_and_not_disclosed_in_folder_snapshot(workspace):
    ws, headers = workspace
    parent = new_doc(headers, "Private parent", confidentiality="riservato")
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": "Workspace folder", "parent_document_uid": parent})
    assert response.status_code == 201, response.text
    f = response.json()["uid"]
    raw = secrets.token_urlsafe(20)
    db = SessionLocal()
    db.add(ApiToken(workspace_id=ws, token_hash=hash_token(raw), scopes=["read", "create", "modify"], resources=["documents"]))
    db.commit(); db.close()
    limited = {"Authorization": f"Bearer {raw}"}
    result = client.get(NAV, headers=limited)
    assert result.status_code == 200, result.text
    assert parent not in result.text
    item = next(row for row in result.json()["folders"] if row["uid"] == f)
    assert item["parent_document_uid"] is None
    assert graph(limited)[f"f:{f}"] is None
    response = client.post(f"{NAV}/folders", headers=limited, json={"name": "Refused", "parent_document_uid": parent})
    assert response.status_code == 404, response.text
    response = client.put(f"{NAV}/folders/{f}", headers=limited, json={"name": "Refused", "parent_document_uid": parent})
    assert response.status_code == 404, response.text


def test_deleting_document_parent_keeps_its_folders_and_contents(workspace):
    _, headers = workspace
    parent = new_doc(headers, "Disposable parent")
    response = client.post(f"{NAV}/folders", headers=headers, json={"name": "Kept", "parent_document_uid": parent})
    assert response.status_code == 201, response.text
    f = response.json()["uid"]
    child = new_doc(headers, "Kept document", navigation_folder_uid=f)
    assert client.delete(f"/v1/documents/{parent}", headers=headers).status_code == 204
    snapshot = client.get(NAV, headers=headers).json()
    row = next(row for row in snapshot["folders"] if row["uid"] == f)
    assert row["parent_document_uid"] is None
    assert graph(headers)[f"f:{f}"] is None
    assert graph(headers)[f"d:{child}"] == f"f:{f}"
    assert client.get(f"/v1/documents/{child}", headers=headers).status_code == 200
    assert client.delete(f"{NAV}/folders/{f}", headers=headers).status_code == 409


def test_database_rejects_a_folder_with_both_parent_types(workspace):
    from sqlalchemy.exc import IntegrityError
    from app.models.document_navigation import DocumentFolder
    ws, headers = workspace
    parent = new_doc(headers, "Parent")
    f = folder(headers)
    db = SessionLocal()
    try:
        db.add(DocumentFolder(uid=str(uuid.uuid4()), workspace_id=ws, name="Invalid", parent_uid=f, parent_document_uid=parent))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    finally:
        db.close()
