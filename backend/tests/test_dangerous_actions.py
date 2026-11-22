"""Dangerous actions (docs/dangerous-actions.md): deleting a workspace, making it global, deleting a type with its
records and deleting the orphaned objects are done only by a person signed in who typed the workspace's name —
refused without it or with another name, refused with any API token (robot or personal, even with the admin
scope), and offered by no MCP tool."""
import secrets
import uuid
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, TokenScope, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services.mcp_tools import catalogue
from tests.test_ledger_transition import token

client = TestClient(app)
NAME = "Hall B — ground floor"          # not plain ASCII: sent percent-encoded


@pytest.fixture
def w():
    t = secrets.token_hex(3)
    db = SessionLocal()
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    ws = Workspace(id=f"danger-{t}", name=NAME)
    db.add_all([admin, ws])
    db.flush()
    db.add(Schema(uid=f"magnet-{t}", workspace_id=ws.id, name="Magnet"))
    robot = token(db, ws.id)
    db.commit()
    admin_id = admin.id
    db.expunge(admin)
    yield {"db": db, "ws": ws.id, "type": f"magnet-{t}", "admin": admin, "robot": robot}
    db.close()
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    if db.get(Workspace, f"danger-{t}") is not None:
        db.delete(db.get(Workspace, f"danger-{t}"))
    db.delete(db.get(User, admin_id))
    db.commit()
    db.close()


def as_person(user, scope=None):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user, token=scope)


def typed(name=NAME):
    return {"X-Confirm-Workspace": quote(name)}


def actions(w):
    return [
        ("delete", f"/v1/workspaces/{w['ws']}", None, {}),
        ("put", f"/v1/workspaces/{w['ws']}", {"is_global": True}, {}),
        ("delete", f"/v1/schemas/{w['type']}", None, {"X-Workspace-Id": w["ws"]}),
        ("post", f"/v1/workspaces/{w['ws']}/cleanup", {"delete_orphaned_objects": True}, {}),
    ]


def send(method, url, body, headers):
    kw = {"headers": headers} | ({"json": body} if body is not None else {})
    return getattr(client, method)(url, **kw)


def test_each_dangerous_action_needs_the_workspace_name_typed_by_a_person(w):
    as_person(w["admin"])
    for method, url, body, headers in actions(w):
        for sent in ({}, typed("Hall B"), typed("danger")):
            r = send(method, url, body, {**headers, **sent})
            assert r.status_code == 428, (url, sent, r.text)
            assert r.json()["detail"]["code"] == "confirm_workspace_name" and r.json()["detail"]["workspace"] == NAME

    db = SessionLocal()
    assert db.get(Workspace, w["ws"]).is_global is False and db.get(Schema, w["type"]) is not None
    db.close()

    # With the name: done, in the order that leaves the workspace to delete last.
    for method, url, body, headers in actions(w)[1:] + actions(w)[:1]:
        r = send(method, url, body, {**headers, **typed()})
        assert r.status_code in (200, 204), (url, r.text)
    db = SessionLocal()
    assert db.get(Workspace, w["ws"]) is None
    db.close()


def test_no_token_does_them_and_no_mcp_tool_offers_them(w):
    for method, url, body, headers in actions(w):
        r = send(method, url, body, {**headers, **w["robot"], **typed()})
        assert r.status_code == 403, (url, r.text)          # the administrators' ones are refused even sooner
    r = send("delete", f"/v1/schemas/{w['type']}", None, {"X-Workspace-Id": w["ws"], **w["robot"], **typed()})
    assert r.json()["detail"]["code"] == "person_only" and "MCP" in r.json()["detail"]["error"]

    # A personal token of an administrator, given every scope: still not a person signed in.
    as_person(w["admin"], TokenScope(kind="personal", scopes=frozenset({"read", "create", "modify", "delete",
                                                                         "approve", "admin"})))
    for method, url, body, headers in actions(w):
        r = send(method, url, body, {**headers, **typed()})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "person_only", (url, r.text)

    db = SessionLocal()
    assert db.get(Workspace, w["ws"]) is not None and db.get(Schema, w["type"]) is not None
    db.close()

    names = {t["name"] for t in catalogue()}
    assert not any(n.startswith(("delete", "remove", "purge", "cleanup")) or "global" in n for n in names), names


def test_a_workspace_made_again_with_the_same_id_numbers_its_records_from_one(w):
    """Its key counters go with the deleted workspace: they have no foreign key to cascade from."""
    from sqlalchemy import text
    db = w["db"]
    db.execute(text("INSERT INTO asset_key_counters (workspace_id, scope, next_value) VALUES (:w, 'X-IP-#', 7)"),
               {"w": w["ws"]})
    db.commit()
    as_person(w["admin"])
    assert client.delete(f"/v1/workspaces/{w['ws']}", headers=typed()).status_code in (200, 204)
    left = db.execute(text("SELECT count(*) FROM asset_key_counters WHERE workspace_id = :w"), {"w": w["ws"]}).scalar()
    assert left == 0
