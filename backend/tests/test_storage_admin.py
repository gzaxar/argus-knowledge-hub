"""Administration → Storage (routers/storage.py): each area's planned room — an administrator's setting, else the
deployment's, else the default (portability 10 GiB); the files of exports and imports that are over freed at any age;
and a workspace's own share, for its administrators."""
import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, TokenScope, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.app_setting import AppSetting
from app.models.attachment import Attachment
from app.models.portability import PortabilityImport
from app.models.user import User
from app.models.workspace import Workspace
from app.services import storage, storage_cleanup

client = TestClient(app)


@pytest.fixture
def people():
    db = SessionLocal()
    t = uuid.uuid4().hex[:6]
    out = {"admin": User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True),
           "eve": User(id=str(uuid.uuid4()), email=f"eve-{t}@argus.test", is_admin=False)}
    db.add_all(out.values())
    saved = db.get(AppSetting, storage.PLANNED_SETTING)
    saved = dict(saved.value) if saved is not None else None
    db.commit()
    for u in out.values():
        db.refresh(u)
        db.expunge(u)
    db.close()
    yield out
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    row = db.get(AppSetting, storage.PLANNED_SETTING)
    if saved is None and row is not None:
        db.delete(row)
    elif saved is not None:
        row.value = saved
    for u in out.values():
        db.delete(db.get(User, u.id))
    db.commit()
    db.close()


def as_(user, token=False):
    app.dependency_overrides[get_identity] = (
        (lambda: OidcIdentity(user=user, token=TokenScope(kind="personal", scopes=frozenset({"read", "admin"}))))
        if token else (lambda: OidcIdentity(user=user)))


def test_the_planned_room_is_the_setting_else_the_deployments_else_ten_gib(people, monkeypatch):
    monkeypatch.delenv("ARGUS_STORAGE_PORTABILITY_SIZE", raising=False)
    monkeypatch.setenv("ARGUS_STORAGE_ATTACHMENTS_SIZE", "15Gi")
    as_(people["admin"])
    client.put("/v1/admin/storage/settings", json={"planned": {"portability": None, "attachments": None}})
    view = client.get("/v1/admin/storage/settings").json()["planned"]
    assert view["portability"]["planned_bytes"] == 10 * 2 ** 30 and view["portability"]["source"] == "default"
    assert view["attachments"]["planned_bytes"] == 15 * 2 ** 30 and view["attachments"]["source"] == "deployment"
    monkeypatch.setenv("ARGUS_STORAGE_PORTABILITY_SIZE", "5Gi")
    assert client.get("/v1/admin/storage/settings").json()["planned"]["portability"]["planned_bytes"] == 5 * 2 ** 30

    r = client.put("/v1/admin/storage/settings", json={"planned": {"portability": 20 * 2 ** 30}})
    assert r.status_code == 200
    assert r.json()["planned"]["portability"] == {"planned_bytes": 20 * 2 ** 30, "setting_bytes": 20 * 2 ** 30,
                                                  "deployment_bytes": 5 * 2 ** 30, "default_bytes": 10 * 2 ** 30,
                                                  "source": "setting"}
    report = client.get("/v1/admin/storage").json()
    assert {a["area"]: a["planned_bytes"] for a in report["areas"]}["portability"] == 20 * 2 ** 30   # measured again
    r = client.put("/v1/admin/storage/settings", json={"planned": {"portability": None}})
    assert r.json()["planned"]["portability"]["source"] == "deployment"
    assert client.put("/v1/admin/storage/settings", json={"planned": {"nowhere": 2 ** 30}}).status_code == 422
    assert client.put("/v1/admin/storage/settings", json={"planned": {"portability": 12}}).status_code == 422


def test_only_an_administrator_signed_in_sets_the_planned_room(people):
    as_(people["eve"])
    assert client.get("/v1/admin/storage").status_code == 403
    assert client.put("/v1/admin/storage/settings", json={"planned": {"portability": 2 ** 31}}).status_code == 403
    as_(people["admin"], token=True)
    assert client.get("/v1/admin/storage/settings").status_code == 200       # reading, with a token, is fine
    assert client.put("/v1/admin/storage/settings", json={"planned": {"portability": 2 ** 31}}).status_code == 403


def test_the_files_of_imports_that_are_over_go_at_any_age_and_no_others(people, tmp_path, monkeypatch):
    root = tmp_path / "portability"
    monkeypatch.setenv("ARGUS_PORTABILITY_ROOT", str(root))
    monkeypatch.delenv("ARGUS_BUNDLES_DIR", raising=False)
    t = uuid.uuid4().hex[:6]
    imports = {"invalid": "invalid", "discarded": "discarded", "failed": "failed", "held": "invalid"}
    db = SessionLocal()
    for name, state in imports.items():
        q = root / "quarantine" / f"imp-{name}-{t}"
        q.mkdir(parents=True)
        (q / "archive.bin").write_bytes(b"x" * 4000)
        db.add(PortabilityImport(id=f"imp-{name}-{t}", mode="clone", state=state, requested_by="a@argus.test",
                                 quarantine_dir=str(q), legal_hold=(name == "held")))
    db.commit()
    try:
        action = {a["id"]: a for a in storage_cleanup.preview(db)["actions"]}["finished"]
        assert action["available"] and action["frees_up_to"] >= 8000   # today's, not a week old
        as_(people["admin"])
        r = client.post("/v1/admin/statistics/storage/cleanup", json={"actions": ["finished"]})
        assert r.status_code == 200 and r.json()["actions"][0]["done"] is True
        assert not (root / "quarantine" / f"imp-invalid-{t}").exists()
        assert not (root / "quarantine" / f"imp-discarded-{t}").exists()
        assert (root / "quarantine" / f"imp-failed-{t}").exists()       # it can resume
        assert (root / "quarantine" / f"imp-held-{t}").exists()         # a legal hold keeps it
        db.expire_all()
        assert db.get(PortabilityImport, f"imp-invalid-{t}").purged_at is not None
        assert db.get(PortabilityImport, f"imp-failed-{t}").purged_at is None
    finally:
        db.rollback()
        for name in imports:
            db.delete(db.get(PortabilityImport, f"imp-{name}-{t}"))
        db.commit()
        db.close()


def test_a_workspace_shows_its_own_share_to_its_administrators(people, tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_BUNDLES_DIR", str(tmp_path / "bundles"))
    t = uuid.uuid4().hex[:6]
    ws, other = f"st-{t}", f"so-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=ws, name="Storage"), Workspace(id=other, name="Other")])
    db.flush()
    db.add_all([Attachment(uid=str(uuid.uuid4()), workspace_id=ws, filename="big.pdf", file_size=9000,
                           mime_type="application/pdf", storage_path="x"),
                Attachment(uid=str(uuid.uuid4()), workspace_id=other, filename="o.bin", file_size=1000,
                           storage_path="y")])
    db.commit()
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    for bid, w in ((mine, ws), (theirs, other)):
        d = tmp_path / "bundles" / "exports" / bid / "bundle"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"workspace": {"id": w}, "created_at": date.today().isoformat()}))
    try:
        as_(people["eve"])
        assert client.get(f"/v1/workspaces/{ws}/storage").status_code == 403
        as_(people["admin"])
        out = client.get(f"/v1/workspaces/{ws}/storage").json()
        assert (out["attachments"]["files"], out["attachments"]["bytes"]) == (1, 9000)
        assert out["attachments"]["largest"][0]["filename"] == "big.pdf"
        assert [b["id"] for b in out["bundles"]] == [mine]
        assert client.delete(f"/v1/workspaces/{ws}/storage/bundles/{theirs}").status_code == 404   # not this one's
        as_(people["admin"], token=True)
        assert client.delete(f"/v1/workspaces/{ws}/storage/bundles/{mine}").status_code == 403
        as_(people["admin"])
        assert client.delete(f"/v1/workspaces/{ws}/storage/bundles/{mine}").status_code == 200
        assert not (tmp_path / "bundles" / "exports" / mine).exists()
        assert (tmp_path / "bundles" / "exports" / theirs).exists()
    finally:
        from app.ledger.audit import allow_purge
        db.rollback()
        allow_purge(db)
        for a in db.query(Attachment).filter(Attachment.workspace_id.in_([ws, other])):
            db.delete(a)
        db.delete(db.get(Workspace, ws))
        db.delete(db.get(Workspace, other))
        db.commit()
        db.close()
