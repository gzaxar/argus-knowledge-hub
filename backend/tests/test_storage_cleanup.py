"""Freeing room in the portability area (services/storage_cleanup.py): the export repository copy compacted, or
dropped when the remote has all of it; old bundle uploads and left-overs removed; nothing else touched."""
import os
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, TokenScope, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.user import User
from app.services import storage_cleanup

client = TestClient(app)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def area(tmp_path, monkeypatch):
    root = tmp_path / "portability"
    monkeypatch.setenv("ARGUS_PORTABILITY_ROOT", str(root))
    monkeypatch.delenv("ARGUS_BUNDLES_DIR", raising=False)
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    work = root / "work" / "abc123"
    work.parent.mkdir(parents=True)
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    for i in range(30):                                       # what nightly exports leave: loose objects
        (work / f"f{i}.txt").write_text(f"export {i}\n" * 2000)
        git("add", "-A", cwd=work)
        git("commit", "-q", "-m", f"export {i}", cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)
    old = time.time() - 10 * 86400
    for d in ("bundles/imports/old", "bundles/imports/new", "staging/old", "quarantine/new"):
        (root / d).mkdir(parents=True)
        (root / d / "file.bin").write_bytes(b"x" * 5000)
    for d in ("bundles/imports/old", "staging/old"):
        os.utime(root / d, (old, old))
    return {"root": root, "work": work}


def test_it_says_what_is_there_and_what_each_cleanup_frees(area):
    p = storage_cleanup.preview()
    acts = {a["id"]: a for a in p["actions"]}
    assert acts["compact:work/abc123"]["available"] and acts["compact:work/abc123"]["frees_up_to"] > 0
    assert acts["drop:work/abc123"]["available"]                              # in sync with the remote
    assert acts["bundle_imports"]["count"] == 1 and acts["leftovers"]["count"] == 1      # only the old ones
    assert {h["part"] for h in p["holds"]} >= {"work", "bundles"}


def test_compacting_loses_nothing_and_old_files_go(area):
    loose_before = storage_cleanup.preview()["repositories"][0]["loose_bytes"]
    out = storage_cleanup.run(["compact:work/abc123", "bundle_imports", "leftovers"])
    assert all(a["done"] for a in out["actions"])
    assert storage_cleanup.preview()["repositories"][0]["loose_bytes"] < loose_before
    assert git("log", "--oneline", cwd=area["work"]).stdout.count("export") == 30          # history intact
    assert not (area["root"] / "bundles/imports/old").exists() and (area["root"] / "bundles/imports/new").exists()
    assert not (area["root"] / "staging/old").exists() and (area["root"] / "quarantine/new").exists()


def test_a_copy_with_work_the_remote_lacks_is_never_dropped(area):
    (area["work"] / "local.txt").write_text("not pushed")
    git("add", "-A", cwd=area["work"])
    git("commit", "-q", "-m", "local only", cwd=area["work"])
    acts = {a["id"]: a for a in storage_cleanup.preview()["actions"]}
    assert not acts["drop:work/abc123"]["available"] and "not pushed" in acts["drop:work/abc123"]["note"]
    assert storage_cleanup.run(["drop:work/abc123"])["actions"][0]["done"] is False
    assert area["work"].exists()
    git("push", "-q", "origin", "HEAD:main", cwd=area["work"])
    assert storage_cleanup.run(["drop:work/abc123"])["actions"][0]["done"] is True       # once pushed, it may go
    assert not area["work"].exists()


def test_only_an_administrator_signed_in_frees_room(area):
    db = SessionLocal()
    admin = User(id=str(uuid.uuid4()), email=f"admin-{uuid.uuid4().hex[:6]}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin, token=TokenScope(
            kind="personal", scopes=frozenset({"read", "admin", "delete"})))
        r = client.post("/v1/admin/statistics/storage/cleanup", json={"actions": ["bundle_imports"]})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "person_only"
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
        assert client.get("/v1/admin/statistics/storage/cleanup").status_code == 200
        r = client.post("/v1/admin/statistics/storage/cleanup", json={"actions": ["bundle_imports"]})
        assert r.status_code == 200 and r.json()["actions"][0]["done"] is True
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db = SessionLocal()
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()
