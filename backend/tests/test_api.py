import secrets

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.workspace import Workspace

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def token():
    db = SessionLocal()
    workspace_id = f"test-{secrets.token_hex(4)}"
    db.add(Workspace(id=workspace_id, name="Test"))
    db.flush()
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=workspace_id, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    return raw


def auth(raw_token: str) -> dict:
    return {"Authorization": f"Bearer {raw_token}"}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_requires_auth():
    assert client.get("/v1/schemas").status_code == 401
    assert client.get("/v1/schemas", headers=auth("bogus")).status_code == 401


def test_schema_crud(token):
    created = client.post(
        "/v1/schemas",
        json={"uid": "s-1", "name": "Magnet", "metadata": {"a": 1}},
        headers=auth(token),
    )
    assert created.status_code == 201
    assert created.json()["metadata"] == {"a": 1}

    dup = client.post(
        "/v1/schemas", json={"uid": "s-1", "name": "dup"}, headers=auth(token)
    )
    assert dup.status_code == 409

    fetched = client.get("/v1/schemas/s-1", headers=auth(token))
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Magnet"

    # Deleting a type takes every record of it: never with a token (docs/dangerous-actions.md).
    deleted = client.delete("/v1/schemas/s-1", headers={**auth(token), "X-Confirm-Workspace": "Test"})
    assert deleted.status_code == 403 and deleted.json()["detail"]["code"] == "person_only"
    assert client.get("/v1/schemas/s-1", headers=auth(token)).status_code == 200


def test_asset_and_sync(token):
    client.post(
        "/v1/schemas", json={"uid": "s-2", "name": "Pump"}, headers=auth(token)
    )
    created = client.post(
        "/v1/assets",
        json={
            "uid": "a-1",
            "schema_uid": "s-2",
            "key": f"PUMP-{secrets.token_hex(3)}",
            "name": "Pump 1",
            "type": "Pump",
            "attributes": {"flow": 3.5},
        },
        headers=auth(token),
    )
    assert created.status_code == 201

    synced = client.get(
        "/v1/sync", params={"since": "1970-01-01T00:00:00Z"}, headers=auth(token)
    )
    assert synced.status_code == 200
    body = synced.json()
    assert any(a["uid"] == "a-1" for a in body["assets"])
    assert any(s["uid"] == "s-2" for s in body["schemas"])


def test_workspace_isolation(token):
    client.post("/v1/schemas", json={"uid": "s-3", "name": "Iso"}, headers=auth(token))

    db = SessionLocal()
    other_ws = f"other-{secrets.token_hex(4)}"
    db.add(Workspace(id=other_ws, name="Other"))
    db.flush()
    other_raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=other_ws, token_hash=hash_token(other_raw)))
    db.commit()
    db.close()

    resp = client.get("/v1/schemas/s-3", headers=auth(other_raw))
    assert resp.status_code == 404


def _document(token: str, code: str, title: str, type_uid: str | None = None) -> str:
    uid = f"doc-{secrets.token_hex(4)}"
    resp = client.post(
        "/v1/documents",
        json={"uid": uid, "code": code, "title": title, "document_type_uid": type_uid},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return uid


def test_documents_move_between_types_in_one_call(token):
    """Typing a library is a sorting job done in hindsight, over dozens of
    documents at a time — one at a time through the edit form is the reason
    an import's guesses never get corrected."""
    suffix = secrets.token_hex(4)
    for name in ("Note", "Procedure"):
        client.post(
            "/v1/schemas",
            json={"uid": f"{name.lower()}-{suffix}", "name": name, "applies_to": "documents"},
            headers=auth(token),
        )
    note_uid, procedure_uid = f"note-{suffix}", f"procedure-{suffix}"

    docs = [
        _document(token, f"D1-{suffix}", "Vacuum recovery", note_uid),
        _document(token, f"D2-{suffix}", "Camera replacement", note_uid),
    ]

    resp = client.post(
        "/v1/documents/retype",
        json={"uids": docs + ["not-a-document"], "document_type_uid": procedure_uid},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved"] == 2
    # A uid that isn't here is reported, not silently counted as moved.
    assert body["not_found"] == ["not-a-document"]

    for uid in docs:
        got = client.get(f"/v1/documents/{uid}", headers=auth(token)).json()
        assert got["document_type_uid"] == procedure_uid


def test_documents_cannot_be_moved_onto_an_object_type(token):
    suffix = secrets.token_hex(4)
    client.post(
        "/v1/schemas",
        json={"uid": f"cam-{suffix}", "name": "Cameras"},
        headers=auth(token),
    )
    uid = _document(token, f"D3-{suffix}", "A note")

    resp = client.post(
        "/v1/documents/retype",
        json={"uids": [uid], "document_type_uid": f"cam-{suffix}"},
        headers=auth(token),
    )
    assert resp.status_code == 422


def test_a_new_document_is_given_a_code(token):
    """Inventing a code nobody has used is the database's job, and it is the
    first field on the form — asking for it stops people before they start."""
    suffix = secrets.token_hex(4)
    client.post(
        "/v1/schemas",
        json={"uid": f"proc-{suffix}", "name": "Procedure", "applies_to": "documents"},
        headers=auth(token),
    )
    resp = client.post(
        "/v1/documents",
        json={
            "uid": f"d1-{suffix}",
            "title": "Vacuum recovery",
            "document_type_uid": f"proc-{suffix}",
        },
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    first = resp.json()["code"]
    assert first.startswith("PROC-"), first

    # The next one does not collide with it.
    resp = client.post(
        "/v1/documents",
        json={
            "uid": f"d2-{suffix}",
            "title": "Camera replacement",
            "document_type_uid": f"proc-{suffix}",
        },
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"] != first


def test_a_typed_code_is_kept(token):
    """A real controlled-document number is the one that matters."""
    suffix = secrets.token_hex(4)
    resp = client.post(
        "/v1/documents",
        json={"uid": f"d3-{suffix}", "code": f"LNF-VAC-{suffix}", "title": "Numbered"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"] == f"LNF-VAC-{suffix}"


def test_an_untyped_document_still_gets_a_code(token):
    suffix = secrets.token_hex(4)
    resp = client.post(
        "/v1/documents",
        json={"uid": f"d4-{suffix}", "title": "No type at all"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"].startswith("DOC-")


def test_a_code_already_in_use_is_refused_by_name(token):
    suffix = secrets.token_hex(4)
    client.post(
        "/v1/documents",
        json={"uid": f"d5-{suffix}", "code": f"DUP-{suffix}", "title": "First"},
        headers=auth(token),
    )
    resp = client.post(
        "/v1/documents",
        json={"uid": f"d6-{suffix}", "code": f"DUP-{suffix}", "title": "Second"},
        headers=auth(token),
    )
    assert resp.status_code == 409
    assert f"DUP-{suffix}" in resp.json()["detail"]
