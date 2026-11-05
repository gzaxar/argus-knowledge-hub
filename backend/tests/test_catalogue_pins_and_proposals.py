"""A catalogue release pinned from Administration (app/catalogue/pins.py) and a model proposed to Git from its record
(app/catalogue/proposals.py): the stored pin read over the lock while newer, checked before it is kept; the pull
request's files written in place and checked; and the install that links the record it came from."""
import base64
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.catalogue import install as inst
from app.catalogue import pins, proposals
from app.catalogue.loader import load_tree
from app.catalogue.sources import _over, describe, effective, releases
from app.db import SessionLocal
from app.ledger import service as ledger
from app.models.asset import Asset
from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation, CataloguePin, CatalogueProposal
from app.models.package import WorkspacePackage
from app.models.user import User
from app.models.workspace import Workspace
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**GIT_ENV, "HOME": str(repo)}).stdout.strip()


def manifest(cid: str, version: str, contents: str) -> dict:
    out = {"id": cid, "version": version, "name": cid.title(), "domain": "catalogue", "owner": "INFN ARGUS",
           "license": "CC0-1.0", "contents": [contents], "requires": {"packages": {"core-objects": ">=2.1,<3"}}}
    if cid != "vendors":
        out["requires"]["collections"] = {"vendors": ">=0.2,<1"}
    return out


AGILENT = {"id": "agilent", "name": "Agilent Technologies", "aliases": ["Agilent"]}
XGS = {"id": "agilent/xgs-600", "vendor": "agilent", "model_code": "XGS-600", "name": "XGS-600 Gauge Controller",
       "device_class": "vacuum"}
TPS = {"id": "agilent/tps-compact", "vendor": "agilent", "model_code": "TPS-compact", "name": "TPS-compact",
       "device_class": "vacuum"}


def files(vendors_version="0.2.0", vacuum_version="0.1.0", models=(XGS,)) -> dict:
    return {"collections/vendors/collection.yaml": manifest("vendors", vendors_version, "vendors.yaml"),
            "collections/vendors/vendors.yaml": {"vendors": [AGILENT]},
            "collections/vacuum/collection.yaml": manifest("vacuum", vacuum_version, "models.yaml"),
            "collections/vacuum/models.yaml": {"models": list(models)}}


def commit(repo: Path, content: dict, tag=None, annotated=False) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        git(repo, "init", "-q", "-b", "main")
    for rel, data in content.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(yaml.safe_dump(data, sort_keys=False))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c", "--allow-empty")
    if tag:
        git(repo, "tag", *(["-a", "-m", tag] if annotated else []), tag)
    return git(repo, "rev-parse", "HEAD")


# --------------------------------------------------------------------------- the stored pin

def test_a_stored_pin_is_read_only_while_newer_than_the_lock():
    lock = {"id": "argus", "kind": "argus-collections", "repo": "r", "ref": "v0.2.0", "commit": "a" * 40}
    assert _over(lock, {"ref": "v0.3.0", "commit": "b" * 40})["commit"] == "b" * 40
    assert _over(lock, {"ref": "v0.2.0", "commit": "b" * 40}) is lock            # an ARGUS release caught up
    assert _over(lock, {"ref": "v0.1.0", "commit": "b" * 40}) is lock
    assert _over(lock, {"ref": "main", "commit": "b" * 40}) is lock
    branch = {**lock, "ref": "infn"}
    assert _over(branch, {"ref": "v9.0.0", "commit": "b" * 40}) is branch         # a branch moves only with ARGUS


def test_releases_are_the_tags_newest_first_with_their_commits(tmp_path):
    repo = tmp_path / "argus"
    a = commit(repo, files(), "v0.1.0")
    b = commit(repo, files(vacuum_version="0.1.1", models=(XGS, TPS)), "v0.10.0", annotated=True)
    git(repo, "tag", "not-a-release")
    assert releases({"id": "argus", "repo": str(repo)}) == [{"tag": "v0.10.0", "commit": b},
                                                            {"tag": "v0.1.0", "commit": a}]


@pytest.fixture()
def installation(tmp_path, monkeypatch):
    """A catalogue directory whose lock pins a local repository at v0.1.0, and a source id no other test uses."""
    sid = f"argus-{secrets.token_hex(3)}"
    repo = tmp_path / "argus"
    first = commit(repo, files(), "v0.1.0")
    cat = tmp_path / "catalogue"
    cat.mkdir()
    (cat / "sources.lock.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": sid, "kind": "argus-collections", "repo": str(repo), "ref": "v0.1.0", "commit": first}]}))
    monkeypatch.setenv("ARGUS_CATALOGUE_DIR", str(cat))
    monkeypatch.setenv("ARGUS_CATALOGUE_CACHE", str(tmp_path / "cache"))
    yield {"sid": sid, "repo": repo, "first": first}
    with SessionLocal() as db:
        db.execute(CataloguePin.__table__.delete().where(CataloguePin.source_id == sid))
        db.commit()


def test_a_newer_release_is_checked_pinned_read_and_unpinned(installation):
    sid, repo = installation["sid"], installation["repo"]
    second = commit(repo, files(vacuum_version="0.1.1", models=(XGS, TPS)), "v0.2.0")
    assert [r["tag"] for r in pins.available(sid)["releases"]] == ["v0.2.0"]
    with SessionLocal() as db:
        out = pins.pin(db, sid, "v0.2.0", "maintainer@infn.it")
        db.commit()
    assert out["commit"] == second and out["previous_ref"] == "v0.1.0"
    assert {"id": "vacuum", "version": "0.1.1"} in out["collections"]
    assert effective()[0]["commit"] == second
    shown = describe()[0]
    assert shown["ref"] == "v0.2.0" and shown["shipped_ref"] == "v0.1.0" and shown["pinned_in"] == "administration"
    assert shown["pinned_by"] == "maintainer@infn.it"
    assert "agilent/tps-compact" in {m.id for c in load_tree().values() for m in c.models}

    with SessionLocal() as db:
        assert pins.unpin(db, sid)["ref"] == "v0.1.0"
        db.commit()
    assert effective()[0]["commit"] == installation["first"] and describe()[0]["pinned_in"] == "lock"


def test_a_release_that_breaks_the_catalogue_or_is_not_newer_is_not_pinned(installation):
    sid, repo = installation["sid"], installation["repo"]
    commit(repo, files(vacuum_version="0.1.1", models=(TPS,)), "v0.2.0")            # XGS-600 dropped
    with SessionLocal() as db:
        with pytest.raises(pins.PinProblem) as e:
            pins.pin(db, sid, "v0.2.0", "m")
        assert any("agilent/xgs-600" in d and "no longer in the collection" in d for d in e.value.details)
        with pytest.raises(pins.PinProblem):
            pins.pin(db, sid, "v0.1.0", "m")                                      # the lock's own: unpin instead
        with pytest.raises(pins.PinProblem, match="no release v0.9.0"):
            pins.pin(db, sid, "v0.9.0", "m")
        assert db.get(CataloguePin, sid) is None
    assert effective()[0]["commit"] == installation["first"]


# --------------------------------------------------------------------------- a model proposed to Git

class FakeGitHub(proposals.GitHub):
    """The catalogue repository: `main` and the release tags, as {ref: {path: text}}."""

    def __init__(self, refs: dict):
        super().__init__("infn-argus/argus-catalogue")
        self.refs = refs
        self.opened = []
        self.state = "open"

    def default_branch(self):
        return "main"

    def read(self, path, ref):
        return self.refs.get(ref, {}).get(path)

    def latest_release(self):
        return max((r for r in self.refs if r.startswith("v")), default=None)

    def open_pull_request(self, base, branch, title, body, files, message):
        self.opened.append({"base": base, "branch": branch, "title": title, "body": body, "files": files})
        return {"number": 7, "url": "https://github.com/infn-argus/argus-catalogue/pull/7"}

    def pull_state(self, number):
        return self.state


def as_text(content: dict) -> dict:
    return {p: yaml.safe_dump(d, sort_keys=False) for p, d in content.items()}


@pytest.fixture()
def cat(tmp_path, monkeypatch):
    """A catalogue workspace whose collections are folders (no lock), and the same files on GitHub."""
    t = secrets.token_hex(3)
    ws = f"catp-{t}"
    root = tmp_path / "collections"
    for rel, text in as_text(files()).items():
        f = root / rel[len("collections/"):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    monkeypatch.setenv("ARGUS_CATALOGUE_DIR", str(root))
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Catalogue"))
    db.flush()
    ensure_asset_types(db, ws)
    db.add(WorkspacePackage(workspace_id=ws, package_id="core-objects", version="2.1.0", checksum="x"))
    actor = User(id=str(uuid.uuid4()), email=f"m-{t}@argus.test", is_admin=True)
    db.add(actor)
    db.commit()
    model_schema, vendor_schema = cm.catalogue_types(db, ws)
    from app.services import asset_keys

    def make(schema, name, **attrs):
        uid = str(uuid.uuid4())
        ledger.create_record(db, ws, actor.id, uid=uid, schema_uid=schema.uid,
                             key=asset_keys.allocate(db, ws, schema), name=name, type_name=schema.name,
                             attributes=attrs, is_global=True)
        db.commit()
        return db.get(Asset, uid)

    vendor = make(vendor_schema, "Keysight", website="https://www.keysight.com")
    model = make(model_schema, "Keysight 34465A", vendor="Keysight", vendor_ref=vendor.uid, model_code="34465A",
                 device_class="multimeter")
    gh = FakeGitHub({"main": as_text(files()), "v0.1.0": as_text(files())})
    yield {"db": db, "ws": ws, "actor": actor.id, "vendor": vendor, "model": model, "gh": gh, "root": tmp_path,
           "make": make, "model_schema": model_schema}
    db.rollback()
    for table in (CatalogueProposal, CatalogueEntry, CatalogueInstallation):
        db.execute(table.__table__.delete().where(table.workspace_id == ws))
    db.commit()
    db.close()


BODY = {"collection": {"id": "test-measurement", "name": "Test and measurement", "domain": "catalogue"},
        "source": {"kind": "datasheet", "ref": "https://www.keysight.com/34465A-datasheet.pdf"}}


def test_the_draft_reads_the_record_and_finds_a_new_vendor(cat):
    d = proposals.draft(cat["db"], cat["ws"], cat["model"].uid)
    assert d["entry"] == {"id": "keysight/34465a", "vendor": "keysight", "model_code": "34465A",
                          "name": "Keysight 34465A", "device_class": "multimeter"}
    assert d["vendor"]["new"] and d["vendor"]["entry"] == {"id": "keysight", "name": "Keysight",
                                                           "website": "https://www.keysight.com"}
    assert [c["id"] for c in d["collections"]] == ["vacuum"]
    assert "multimeter" in d["device_classes"]


def test_the_files_put_the_entry_in_place_and_raise_versions_once(cat):
    body = {**BODY, "record_uid": cat["model"].uid, "vendor": {"name": "Keysight Technologies", "aliases": ["Keysight"]},
            "entry": {"name": "Truevolt 34465A 6½-digit Digital Multimeter"}}
    built = proposals.build(cat["db"], cat["ws"], body, cat["gh"])
    f = built["files"]
    assert set(f) == {"collections/vendors/vendors.yaml", "collections/vendors/collection.yaml",
                      "collections/test-measurement/collection.yaml", "collections/test-measurement/models.yaml"}
    vendors = yaml.safe_load(f["collections/vendors/vendors.yaml"])["vendors"]
    assert [v["id"] for v in vendors] == ["agilent", "keysight"]
    assert vendors[1]["name"] == "Keysight Technologies" and vendors[1]["aliases"] == ["Keysight"]
    assert yaml.safe_load(f["collections/vendors/collection.yaml"])["version"] == "0.2.1"
    new = yaml.safe_load(f["collections/test-measurement/collection.yaml"])
    assert new["version"] == "0.1.0" and new["requires"]["collections"] == {"vendors": ">=0.2,<1"}
    entry = yaml.safe_load(f["collections/test-measurement/models.yaml"])["models"][0]
    assert entry["id"] == "keysight/34465a" and entry["name"].startswith("Truevolt")
    assert entry["sources"][0]["kind"] == "datasheet" and "checked" in entry["sources"][0]
    assert "checked: 20" in f["collections/test-measurement/models.yaml"]           # a date, not a quoted string

    # Raised already since the last release (another proposal merged): not raised again.
    cat["gh"].refs["main"]["collections/vendors/collection.yaml"] = yaml.safe_dump(manifest("vendors", "0.2.1", "vendors.yaml"))
    again = proposals.build(cat["db"], cat["ws"], body, cat["gh"])
    assert "collections/vendors/collection.yaml" not in again["files"]


def test_an_existing_collection_gets_the_entry_by_id_and_a_known_vendor_is_not_proposed(cat):
    model = cat["make"](cat["model_schema"], "Agilent IPCmini", vendor="Agilent", model_code="IPCmini",
                        device_class="ion pump controller")
    built = proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": model.uid, "collection": {"id": "vacuum"}},
                            cat["gh"])
    assert set(built["files"]) == {"collections/vacuum/models.yaml", "collections/vacuum/collection.yaml"}
    assert [m["id"] for m in yaml.safe_load(built["files"]["collections/vacuum/models.yaml"])["models"]] == \
        ["agilent/ipcmini", "agilent/xgs-600"]
    assert not built["vendor"]["new"] and built["vendor"]["id"] == "agilent"


def test_a_vendor_only_the_netbox_library_has_is_proposed_to_vendors_under_its_id(cat):
    lib = cat["root"] / "collections" / "it-devices"
    lib.mkdir()
    (lib / "collection.yaml").write_text(yaml.safe_dump({**manifest("it-devices", "0.2.0", "vendors.yaml"),
                                                         "origin": "netbox"}, sort_keys=False))
    (lib / "vendors.yaml").write_text(yaml.safe_dump({"vendors": [
        {"id": "keysight", "name": "Keysight", "website": "https://www.keysight.com"}]}))
    d = proposals.draft(cat["db"], cat["ws"], cat["model"].uid)
    assert d["vendor"]["new"] and d["vendor"]["id"] == "keysight"
    built = proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": cat["model"].uid,
                                                   "collection": {"id": "vacuum"}}, cat["gh"])
    assert [v["id"] for v in yaml.safe_load(built["files"]["collections/vendors/vendors.yaml"])["vendors"]] == \
        ["agilent", "keysight"]
    assert {m["id"]: m["vendor"] for m in yaml.safe_load(built["files"]["collections/vacuum/models.yaml"])["models"]} \
        == {"agilent/xgs-600": "agilent", "keysight/34465a": "keysight"}


def test_a_model_the_netbox_library_defines_is_linked_not_proposed(cat):
    lib = cat["root"] / "collections" / "it-devices"
    lib.mkdir()
    (lib / "collection.yaml").write_text(yaml.safe_dump({**manifest("it-devices", "0.2.0", "vendors.yaml"),
                                                         "contents": ["vendors.yaml", "models/keysight.yaml"],
                                                         "origin": "netbox"}, sort_keys=False))
    (lib / "vendors.yaml").write_text(yaml.safe_dump({"vendors": [{"id": "keysight", "name": "Keysight"}]}))
    (lib / "models").mkdir()
    (lib / "models" / "keysight.yaml").write_text(yaml.safe_dump({"models": [
        {"id": "keysight/truevolt-34465", "vendor": "keysight", "model_code": "34465-A", "name": "Truevolt"}]}))
    with pytest.raises(proposals.ProposalProblem, match="NetBox library as keysight/truevolt-34465"):
        proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": cat["model"].uid,
                                               "collection": {"id": "vacuum"}}, cat["gh"])


def test_a_model_the_catalogue_has_or_an_unchecked_one_is_refused(cat):
    same = cat["make"](cat["model_schema"], "XGS 600", vendor="Agilent Technologies", model_code="XGS600")
    with pytest.raises(proposals.ProposalProblem, match="agilent/xgs-600 in vacuum is the same model"):
        proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": same.uid, "collection": {"id": "vacuum"}},
                        cat["gh"])
    with pytest.raises(proposals.ProposalProblem, match="where the values can be checked"):
        proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": cat["model"].uid, "source": {"kind": "datasheet"}},
                        cat["gh"])
    with pytest.raises(proposals.ProposalProblem, match="validator refuses"):
        proposals.build(cat["db"], cat["ws"], {**BODY, "record_uid": cat["model"].uid,
                                               "entry": {"device_class": "gadget"}}, cat["gh"])


def test_proposed_then_installed_links_the_record_it_came_from(cat):
    db, ws = cat["db"], cat["ws"]
    out = proposals.propose(db, ws, {**BODY, "record_uid": cat["model"].uid,
                                     "vendor": {"name": "Keysight Technologies"}}, "m@infn.it", cat["gh"])
    db.commit()
    assert out["state"] == "open" and out["number"] == 7 and out["catalogue_id"] == "keysight/34465a"
    opened = cat["gh"].opened[0]
    assert opened["title"] == "Add Keysight Technologies 34465A (keysight/34465a)" and "m@infn.it" in opened["body"]
    with pytest.raises(proposals.ProposalProblem, match="proposed already"):
        proposals.draft(db, ws, cat["model"].uid)

    cat["gh"].state = "merged"
    proposals.refresh(db, ws, cat["gh"])
    assert proposals.listing(db, ws)[0]["state"] == "merged"

    # The release as merged: what the pull request wrote.
    root = cat["root"] / "release"
    for rel, text in {**cat["gh"].refs["main"], **opened["files"]}.items():
        f = root / rel[len("collections/"):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    tree = load_tree(root)
    result = inst.install(db, ws, ["vendors", "test-measurement"], actor=cat["actor"], tree=tree)
    db.commit()
    by_id = {i["catalogue_id"]: i for r in result["releases"] for i in r["items"]}
    assert by_id["keysight/34465a"]["category"] == "link" and by_id["keysight/34465a"]["record_uid"] == cat["model"].uid
    assert by_id["keysight"]["record_uid"] == cat["vendor"].uid
    assert db.get(Asset, cat["vendor"].uid).name == "Keysight Technologies"        # the reviewed value
    row = db.scalar(select(CatalogueEntry).where(CatalogueEntry.record_uid == cat["model"].uid))
    assert row.catalogue_id == "keysight/34465a"
    assert proposals.listing(db, ws)[0]["state"] == "installed"


def test_the_repository_is_the_github_one_the_lock_pins(monkeypatch):
    monkeypatch.delenv("ARGUS_CATALOGUE_REPO", raising=False)
    monkeypatch.setattr("app.catalogue.sources.effective", lambda *a, **k: [
        {"id": "argus", "kind": "argus-collections", "repo": "https://github.com/infn-argus/argus-catalogue.git"}])
    assert proposals.repository() == "infn-argus/argus-catalogue"
    monkeypatch.setenv("ARGUS_CATALOGUE_REPO", "Other/Repo")
    assert proposals.repository() == "other/repo"
