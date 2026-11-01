"""Where a type comes from (app/packages/origin.py): a package at the version its workspace has, an import, or
made in its workspace — given by the type list and a type's page."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import install as installer
from app.packages.loader import available


@pytest.fixture()
def ws():
    t = secrets.token_hex(3)
    w = f"origin-{t}"
    db = SessionLocal()
    db.add(Workspace(id=w, name=w))
    db.flush()
    installer.install(db, w, ["core-objects"])
    db.add_all([Schema(uid=f"{w}:jira-motors", workspace_id=w, name="Motors", applies_to="objects", attributes=[],
                       metadata_json={"source": "jira"}),
                Schema(uid=f"{w}:gpu", workspace_id=w, name="GPU Server", applies_to="objects", attributes=[],
                       metadata_json={})])
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield w
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, w))
    db.delete(db.get(User, admin.id))
    db.commit()
    db.close()


def test_the_type_list_says_where_each_type_comes_from(ws):
    client = TestClient(app)
    types = {(t["name"], t["workspace_id"]): t for t in client.get("/v1/schemas", headers={"X-Workspace-Id": ws}).json()}
    pump = types[("Rack", ws)]
    version = available()["core-objects"].version
    assert pump["origin"] == {"kind": "package", "package": "core-objects", "version": version,
                              "package_name": available()["core-objects"].name}
    assert types[("Ticket", ws)]["origin"]["package"] == "core-facility"
    assert types[("Motors", ws)]["origin"] == {"kind": "import", "source": "jira"}
    assert types[("GPU Server", ws)]["origin"] == {"kind": "local"}
    one = client.get(f"/v1/schemas/{pump['uid']}", headers={"X-Workspace-Id": ws}).json()
    assert one["origin"]["package"] == "core-objects"
