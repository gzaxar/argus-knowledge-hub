"""Template packages: the format and its validation, the defaults extracted into them (installing them writes
exactly what seeding wrote before), and the installer with its version record."""
import json
import secrets
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.package import PackageInstallation, WorkspacePackage
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import available, load, validate
from app.packages import install as installer
from app.packages.__main__ import main as cli
from app.services import asset_types
from tests.package_parity import FIXTURES, seed_every_way

client = TestClient(app)


# --------------------------------------------------------------------------- the format

def test_the_packages_that_ship_are_valid_and_report_what_they_hold(capsys):
    shipped = available()
    assert {"core-facility", "accelerator"} <= set(shipped)
    for p in shipped.values():
        assert validate(p) == [], p.id
    assert shipped["accelerator"].depends == {"core-facility": ">=1.0,<2"}
    assert shipped["accelerator"].summary()["object_types"] == len(asset_types.CATALOGUE)
    assert cli(["validate"]) == 0
    assert "✓ accelerator" in capsys.readouterr().out


def _package(tmp_path: Path, files: dict) -> Path:
    root = tmp_path / "broken-pkg"
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def test_a_broken_package_is_reported_precisely(tmp_path, capsys):
    root = _package(tmp_path, {
        "package.yaml": "id: broken-pkg\nversion: one\nowner: ''\ndepends: {accelerator: '>=2.0', nowhere: '*'}\n"
                        "contents: [types.yaml, ../escape.yaml]\ncoordinates: [41.8, 12.6]\n",
        "types.yaml": "object_types:\n  types:\n"
                      "    - {name: Pump Station, parent: Plant Item, behaviors: [teleport], map_layer: pumps, latitude: 41.8,\n"
                      "       attributes: [{key: flow, type: number}, {key: flow, type: float},\n"
                      "                    {key: site, type: reference, reference: Nowhere}, {key: mode, type: enumeration}]}\n"
                      "    - {name: Asset}\n    - {name: Plant Item, parent: Item}\n"
                      "workflows:\n  - {id: wf, initial: open, states: [{key: open, category: started}],"
                      " transitions: [{from: open, to: gone}]}\n"})
    problems = {(p.where, p.message) for p in validate(load(root))}
    expected = [
        ("coordinates", "unknown key in the manifest"),                      # no site data in a package
        ("contents › ../escape.yaml", "must be a .yaml file inside the package"),
        ("version", "'one' is not a version (e.g. 1.0.0)"),
        ("owner", "say who answers for the package"),
        ("depends › accelerator", "needs accelerator >=2.0, this installation has 1.0.0"),
        ("depends › nowhere", "no such package"),
        ("types[0] › latitude", "unknown key"),
        ("Pump Station", "parent 'Plant Item' is defined later: list parents before children"),
        ("Pump Station › flow", "duplicate attribute key"),
        ("Pump Station › site", "refers to 'Nowhere', which no package here defines"),
        ("Pump Station › mode", "an enumeration needs options or an option_set"),
        ("Pump Station", "no map layer 'pumps'"),
        ("Asset", "already defined by accelerator"),
        ("wf › transitions[0]", "to 'gone' is not a state"),
    ]
    for item in expected:
        assert item in problems, item
    assert any(w == "Pump Station" and m.startswith("unsupported behaviour 'teleport'") for w, m in problems)
    assert cli(["validate", str(root)]) == 1
    assert "✗ broken-pkg" in capsys.readouterr().out


def test_a_package_that_is_not_yaml_says_where(tmp_path):
    root = _package(tmp_path, {"package.yaml": "id: broken-pkg\nversion: 1.0.0\nowner: x\ncontents: [a.yaml]\n",
                               "a.yaml": "object_types: {types: [ {name: A\n"})
    [problem] = validate(load(root))
    assert problem.file == "a.yaml" and problem.message.startswith("not valid YAML") and "line" in problem.where


def test_a_package_cannot_run_code(tmp_path):
    root = _package(tmp_path, {"package.yaml": "id: broken-pkg\nversion: 1.0.0\nowner: x\ncontents: [a.yaml]\n",
                               "a.yaml": "object_types: !!python/object/apply:os.system ['true']\n"})
    assert any("not valid YAML" in p.message for p in validate(load(root)))


# --------------------------------------------------------------------------- parity with seeding before packages

def _by_installer(db, kind, workspace_id, catalogue_id):
    if kind == "core":
        installer.install(db, workspace_id, ["core-facility"])
    elif kind == "accelerator":
        installer.install(db, workspace_id, ["accelerator"])
    elif kind == "catalogue":
        installer.install(db, workspace_id, ["accelerator"], scope="global")
    else:
        installer.install(db, workspace_id, ["accelerator"], catalogue_workspace_id=catalogue_id)


def test_installing_the_packages_writes_exactly_what_seeding_wrote_before_them():
    """The record in fixtures/package_parity was made from the Python definitions, before they moved to YAML."""
    before = json.loads((FIXTURES / "seeding.json").read_text())
    assert seed_every_way(_by_installer) == before


# --------------------------------------------------------------------------- the installer and the record

@pytest.fixture()
def ws():
    w = f"pkg-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=w, name=w))
    db.commit()
    db.close()
    yield w
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for row in db.scalars(select(Workspace).where(Workspace.id.like(f"{w}%"))):
        db.delete(row)
    db.commit()
    db.close()


def _count(db, model, workspace_id):
    return db.scalar(select(func.count()).select_from(model).where(model.workspace_id == workspace_id))


def test_a_workspace_records_exactly_which_versions_it_uses_and_reapplying_changes_nothing(ws):
    db = SessionLocal()
    plan = installer.install(db, ws, ["accelerator"], actor="tester")
    db.commit()
    assert [(s.package_id, s.action, s.requested) for s in plan.steps] == [
        ("core-facility", "install", False), ("accelerator", "install", True)]
    rows = installer.installed(db, ws)
    shipped = available()
    for pid in ("core-facility", "accelerator"):
        assert (rows[pid].version, rows[pid].checksum) == (shipped[pid].version, shipped[pid].checksum)
    assert rows["accelerator"].options == {"scope": "all"}
    created = plan.steps[1].result["created"]
    assert "Item" in created and len(created) == len(asset_types.CATALOGUE)

    schemas, history = _count(db, Schema, ws), len(installer.history(db, ws))
    again = installer.install(db, ws, ["accelerator", "core-facility"], actor="tester")
    db.commit()
    assert {s.action for s in again.steps} == {"unchanged"} and not again.changes
    assert _count(db, Schema, ws) == schemas and len(installer.history(db, ws)) == history
    db.close()


def test_a_preview_keeps_nothing_and_an_install_that_fails_applies_nothing(ws):
    db = SessionLocal()
    plan = installer.plan(db, ws, ["accelerator"])
    db.rollback()
    assert plan.changes and len(plan.steps[1].result["created"]) == len(asset_types.CATALOGUE)
    assert _count(db, Schema, ws) == 0 and _count(db, WorkspacePackage, ws) == 0

    # Hanging from a "catalogue" that holds none of the shared types: the accelerator step fails, and the core
    # package that came before it in the same install is not kept either.
    with pytest.raises(installer.PackageProblem, match="cannot be its own catalogue"):
        installer.install(db, ws, ["accelerator"], catalogue_workspace_id=ws)
    db.rollback()
    empty = f"{ws}-empty"
    db.add(Workspace(id=empty, name=empty))
    db.commit()
    with pytest.raises(installer.PackageProblem, match="does not hold the global types"):
        installer.install(db, ws, ["accelerator"], catalogue_workspace_id=empty)
    db.rollback()
    assert _count(db, Schema, ws) == 0 and _count(db, WorkspacePackage, ws) == 0
    assert _count(db, PackageInstallation, ws) == 0
    db.close()


def test_a_package_changed_without_a_new_version_is_refused(ws, tmp_path, monkeypatch):
    db = SessionLocal()
    installer.install(db, ws, ["core-facility"])
    db.commit()
    copy = tmp_path / "packages"
    shutil.copytree(available()["core-facility"].path.parent, copy)
    with open(copy / "core-facility" / "workflows.yaml", "a") as f:
        f.write("# edited\n")
    monkeypatch.setenv("ARGUS_PACKAGES_DIR", str(copy))
    from app.packages import loader
    loader.reload()
    try:
        with pytest.raises(installer.PackageProblem, match="must raise its version"):
            installer.install(db, ws, ["core-facility"])
    finally:
        monkeypatch.delenv("ARGUS_PACKAGES_DIR")
        loader.reload()
        db.rollback()
        db.close()


def test_a_workspace_made_before_packages_is_recorded_once_from_what_it_has(ws):
    db = SessionLocal()
    from app.routers.workspaces import seed_default_global_values, seed_default_ticket_types
    seed_default_global_values(db, ws)
    seed_default_ticket_types(db, ws)
    asset_types.ensure_asset_types(db, ws, scope=asset_types.SCOPE_GLOBAL)
    db.commit()
    installer.detect(db)
    db.commit()
    rows = installer.installed(db, ws)
    assert rows["core-facility"].version == "1.0.0" and rows["accelerator"].options == {"scope": "global"}
    assert {h.action for h in installer.history(db, ws)} == {"detected"}
    installer.detect(db)
    db.commit()
    assert len(installer.history(db, ws)) == 2
    db.close()


def test_an_import_that_seeds_the_catalogue_keeps_the_record_exact(ws):
    db = SessionLocal()
    catalogue = f"{ws}-catalogue"
    db.add(Workspace(id=catalogue, name=catalogue))
    db.flush()
    asset_types.ensure_asset_types(db, catalogue, scope=asset_types.SCOPE_GLOBAL)
    asset_types.ensure_for_import(db, ws, catalogue_workspace_id=catalogue)
    db.commit()
    [step] = [h for h in installer.history(db, ws) if h.package_id == "accelerator"]
    assert step.action == "seeded" and step.to_version == available()["accelerator"].version
    assert installer.installed(db, ws)["accelerator"].options == {"scope": "beamline", "catalogue_workspace_id": catalogue}
    db.close()


# --------------------------------------------------------------------------- the API

def _admin():
    db = SessionLocal()
    u = User(id=str(uuid.uuid4()), email=f"pkg-{secrets.token_hex(3)}@argus.test", name="admin", is_admin=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    db.close()
    return u


def test_a_workspace_is_made_from_the_chosen_packages_and_says_which_it_uses():
    admin = _admin()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    wid = f"pkg-api-{secrets.token_hex(3)}"
    try:
        listed = {p["id"]: p for p in client.get("/v1/packages").json()}
        assert listed["accelerator"]["installable"] and listed["accelerator"]["problems"] == []
        assert listed["accelerator"]["contents"]["object_types"] == len(asset_types.CATALOGUE)
        resolved = client.post("/v1/packages/resolve", json={"packages": ["accelerator"]}).json()
        assert [(p["id"], p["requested"]) for p in resolved] == [("core-facility", True), ("accelerator", True)]
        assert client.post("/v1/packages/resolve", json={"packages": ["nowhere"]}).status_code == 422

        r = client.post("/v1/workspaces", json={"name": "Packages test", "id": wid, "packages": ["accelerator"]})
        assert r.status_code == 201, r.text
        mine = client.get(f"/v1/workspaces/{wid}/packages").json()
        assert [(p["package_id"], p["version"]) for p in mine["packages"]] == [
            ("accelerator", "1.0.0"), ("core-facility", "1.0.0")]
        assert all(len(p["checksum"]) == 64 and not p["upgrade_available"] for p in mine["packages"])
        assert [h["action"] for h in mine["history"]] == ["install", "install"]

        preview = client.post(f"/v1/workspaces/{wid}/packages/preview", json={"packages": ["accelerator"]}).json()
        assert preview["changes"] is False
        done = client.post(f"/v1/workspaces/{wid}/packages/install", json={"packages": ["accelerator"]}).json()
        assert {s["action"] for s in done["steps"]} == {"unchanged"} and len(done["history"]) == 2
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db = SessionLocal()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        w = db.get(Workspace, wid)
        if w is not None:
            db.delete(w)
            db.commit()
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()
