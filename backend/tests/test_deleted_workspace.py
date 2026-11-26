"""A page that chose a workspace since deleted: an administrator, permitted everywhere, is told it no longer
exists (404) instead of the request failing later on what refers to it — Ask's conversation, mid-answer."""
import secrets
import uuid

from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.user import User


def test_an_administrator_asking_in_a_deleted_workspace_is_told_it_no_longer_exists():
    db = SessionLocal()
    admin = User(id=str(uuid.uuid4()), email=f"admin-{secrets.token_hex(3)}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    try:
        gone = f"gone-{secrets.token_hex(3)}"
        r = TestClient(app).post("/v1/ai/chat", headers={"X-Workspace-Id": gone}, json={"question": "Hello?"})
        assert r.status_code == 404 and "no longer exists" in r.json()["detail"], r.text
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()
