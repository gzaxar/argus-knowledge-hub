"""Issue #18: a link to a file (/v1/attachments/{uid}) sent to someone who may read it opened a blank page — a
browser carries no sign-in to the API. Opened in a browser, it now goes to the web app's page for the file, which
signs the person in and reads the file in its own workspace, whichever one they are working in."""
import secrets
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.attachment import Attachment
from app.models.role import Role, RoleBinding
from app.models.user import User
from app.models.workspace import Workspace

client = TestClient(app)


def test_a_file_link_opens_in_the_app_and_says_where_to_read_it(tmp_path, monkeypatch):
    btf, own = f"att-{secrets.token_hex(3)}", f"att-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add_all([Workspace(id=btf, name="BTF"), Workspace(id=own, name="Own")])
    reader = User(id=f"reader-{btf}", email=f"reader@{btf}.example", name="Reader")
    stranger = User(id=f"stranger-{btf}", email=f"stranger@{btf}.example", name="Stranger")
    db.add_all([reader, stranger])
    db.flush()
    role = Role(id=f"{btf}-reader", name="Reader", permissions={"objects": ["read"]})
    db.add(role)
    db.flush()
    now = datetime.now(timezone.utc)
    for ws, who in ((btf, reader), (own, reader), (own, stranger)):
        db.add(RoleBinding(workspace_id=ws, subject_type="user", subject_id=who.id, role_id=role.id, created_at=now))
    stored = tmp_path / "layout.png"
    stored.write_bytes(b"\x89PNG\r\n\x1a\nlayout")
    uid = str(uuid.uuid4())
    db.add(Attachment(uid=uid, workspace_id=btf, filename="layout_elettroni.png", mime_type="image/png",
                      file_size=stored.stat().st_size, storage_path=str(stored)))
    db.commit()
    reader_id, stranger_id = reader.id, stranger.id
    db.refresh(reader)
    db.refresh(stranger)
    db.expunge(reader)
    db.expunge(stranger)
    try:
        # A browser opening the link, signed in to nothing: to the app's page for the file.
        monkeypatch.setenv("ARGUS_WEB_URL", "https://argus.example")
        r = client.get(f"/v1/attachments/{uid}", headers={"Accept": "text/html,application/xhtml+xml"},
                       follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"https://argus.example/attachments/{uid}"
        # The app itself, signed in, still reads the file there.
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=reader)
        about = client.get(f"/v1/attachments/{uid}/about", headers={"X-Workspace-Id": own})
        assert about.status_code == 200, (about.text, about.headers.get("x-argus-api-version"))
        assert about.json()["workspace_id"] == btf and about.json()["filename"] == "layout_elettroni.png"
        got = client.get(f"/v1/attachments/{uid}", headers={"X-Workspace-Id": btf, "Accept": "text/html",
                                                            "Authorization": "Bearer the-apps-own"})
        assert got.status_code == 200 and got.content.startswith(b"\x89PNG")              # signed in: the file
        # Someone who may not read BTF learns nothing, not even that it exists.
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=stranger)
        hidden = client.get(f"/v1/attachments/{uid}/about", headers={"X-Workspace-Id": own})
        missing = client.get(f"/v1/attachments/{uuid.uuid4()}/about", headers={"X-Workspace-Id": own})
        assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    finally:
        app.dependency_overrides.pop(get_identity, None)
        ids = (reader_id, stranger_id)
        db.close()
        db = SessionLocal()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        db.query(Attachment).filter(Attachment.uid == uid).delete()
        for who in ids:
            db.query(RoleBinding).filter(RoleBinding.subject_id == who).delete()
        db.query(Role).filter(Role.id == f"{btf}-reader").delete()
        for ws in (btf, own):
            db.delete(db.get(Workspace, ws))
        db.query(User).filter(User.id.in_(ids)).delete()
        db.commit()
        db.close()
