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
    assert shipped["accelerator"].depends == {"core-objects": ">=2.0,<3", "it": ">=1.1,<2", "safety": ">=1.0,<2",
                                              "vacuum-cryo": ">=1.0,<2", "optics-alignment": ">=1.0,<2"}
    from app.packages import defaults
    assert sum(shipped[p].summary()["object_types"] for p in defaults.closure("accelerator")) == \
        len(asset_types.CATALOGUE)
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
        "package.yaml": "id: broken-pkg\nversion: one\nowner: ''\ndepends: {accelerator: '>=9.0', nowhere: '*'}\n"
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
        ("depends › accelerator", f"needs accelerator >=9.0, this installation has {available()['accelerator'].version}"),
        ("depends › nowhere", "no such package"),
        ("types[0] › latitude", "unknown key"),
        ("Pump Station", "parent 'Plant Item' is defined later: list parents before children"),
        ("Pump Station › flow", "duplicate attribute key"),
        ("Pump Station › site", "refers to 'Nowhere', which no package here defines"),
        ("Pump Station › mode", "an enumeration needs options or an option_set"),
        ("Pump Station", "no map layer 'pumps'"),
        ("Asset", "already defined by core-objects"),
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

def _chain() -> list[str]:
    """What installing the accelerator installs, in order: it and every package it stands on."""
    return [p.id for p, _requested in installer.resolve(["accelerator"])]


def _by_installer(db, kind, workspace_id, catalogue_id):
    if kind == "core":
        installer.install(db, workspace_id, ["core-facility"])
    elif kind == "accelerator":
        installer.install(db, workspace_id, ["accelerator"])
    elif kind == "catalogue":
        installer.install(db, workspace_id, ["accelerator"], scope="global")
    else:
        installer.install(db, workspace_id, ["accelerator"], catalogue_workspace_id=catalogue_id)


# Types the it package added beyond the 1.x catalogue (an accelerator workspace gets them with it).
NEW_IN_IT = {"Firewall", "Wireless Access Point", "Storage System", "Patch Panel"}
# What 1.35.26 added on the way to the domain packages: the core vocabulary made neutral (the beam options
# kept, now added by the accelerator package), the GLPI provenance fields, two IT types made concrete.
NEUTRAL_OPTIONS = {"service_down", "service_degraded", "no_impact", "mission_critical", "degrades_service", "glpi"}
GLPI_FIELDS = {"glpi_url", "glpi_unmapped"}
# The beam's own options: a workspace without the accelerator package no longer has them.
BEAM_OPTIONS = {"beam_down", "beam_degraded", "no_beam_impact", "beam_critical", "degrades"}
MADE_CONCRETE = {"Network Device", "Computing Node"}


def _new_names() -> set:
    """Types and kinds the accelerator now brings that the catalogue before packages did not have: those of the
    packages it stands on since 1.35.26 (but the types that moved into them), and the new IT ones."""
    from app.packages import defaults
    shipped = available()
    before = json.loads((FIXTURES / "seeding.json").read_text())
    had = {s["name"] for part in before.values() for s in part["schemas"]}
    out = set(NEW_IN_IT)
    for pid in defaults.closure("accelerator"):
        p = shipped[pid]
        out |= {t["name"] for t in (p.section("object_types") or {}).get("types") or []} - had
        for area in ("ticket_types", "document_types"):
            out |= {k["name"] for k in (p.section(area) or {}).get("kinds") or []} - had
    return out


def _as_before(schema: dict) -> dict:
    """A schema with what 1.35.26 added taken out again."""
    s = json.loads(json.dumps(schema))
    if s.get("metadata"):
        s["metadata"] = {k: v for k, v in s["metadata"].items() if k not in ("locatable", "map_layer")}
    attrs = []
    for a in s.get("attributes") or []:
        if a.get("key") in GLPI_FIELDS:
            continue
        if a.get("key") in ("argus_impact", "argus_criticality", "argus_source") and a.get("options"):
            a["options"] = sorted((o for o in a["options"] if o.get("id") not in NEUTRAL_OPTIONS),
                                  key=lambda o: o["id"])
        attrs.append(a)
    s["attributes"] = attrs
    if s["name"] in MADE_CONCRETE:
        s["is_concrete"] = False
    return s


def _sorted_options(schema: dict, beam: bool = True) -> dict:
    s = json.loads(json.dumps(schema))
    for a in s.get("attributes") or []:
        if a.get("key") in ("argus_impact", "argus_criticality", "argus_source") and a.get("options"):
            a["options"] = sorted((o for o in a["options"] if beam or o["id"] not in BEAM_OPTIONS),
                                  key=lambda o: o["id"])
    if s.get("metadata"):
        s["metadata"] = {k: v for k, v in s["metadata"].items() if k not in ("locatable", "map_layer")}
    return s


def test_installing_the_packages_writes_exactly_what_seeding_wrote_before_them():
    """The record in fixtures/package_parity was made from the Python definitions, before they moved to YAML.
    Since then: the catalogue was split into core-objects, it and accelerator (same types, same uids); it
    gained four IT types; core-objects 1.1.0 map placement; and 1.35.26 made the core vocabulary neutral (the
    beam options kept, with their ids and labels, by the accelerator package), added the GLPI provenance
    fields, made two IT types concrete, and brought the types of the packages the accelerator now stands on
    (safety, vacuum-cryo, optics-alignment, core-records). Nothing else changed: no type, field or option a
    workspace had is gone or different."""
    before = json.loads((FIXTURES / "seeding.json").read_text())
    now = seed_every_way(_by_installer)
    allowed_new = _new_names()
    placed = {s["name"] for part in now.values() for s in part["schemas"]
              if (s.get("metadata") or {}).get("locatable")}
    assert {"Asset", "Location"} <= placed
    for part, then in before.items():
        old = {s["uid"]: s for s in then["schemas"]}
        new = {s["uid"]: s for s in now[part]["schemas"]}
        assert not set(old) - set(new), f"{part}: types gone"
        added = {new[u]["name"] for u in set(new) - set(old)}
        assert added <= allowed_new, f"{part}: unexpected new types {sorted(added - allowed_new)}"
        for uid in old:
            beam = part != "{core}"            # the core-only workspace: neutral, no beam vocabulary
            assert _as_before(new[uid]) == _sorted_options(old[uid], beam), f"{part}: {old[uid]['name']} changed"
        assert now[part]["global_values"] == then["global_values"]
    impact = next(a for s in now["{core}"]["schemas"] if s["name"] == "Ticket" for a in s["attributes"]
                  if a["key"] == "argus_impact")
    assert {o["id"] for o in impact["options"]} == {"service_down", "service_degraded", "no_impact", "safety",
                                                   "unknown"}, "a workspace without the accelerator: neutral"
    beam = next(a for s in now["{accelerator}"]["schemas"] if s["name"] == "Ticket" for a in s["attributes"]
                if a["key"] == "argus_impact")
    assert {"beam_down", "beam_degraded", "no_beam_impact"} <= {o["id"] for o in beam["options"]}


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
    chain = _chain()
    assert [(s.package_id, s.action, s.requested) for s in plan.steps] == [
        (pid, "install", pid == "accelerator") for pid in chain]
    assert chain[0] == "core-facility" and chain[-1] == "accelerator"
    rows = installer.installed(db, ws)
    shipped = available()
    for pid in chain:
        assert (rows[pid].version, rows[pid].checksum) == (shipped[pid].version, shipped[pid].checksum)
    assert rows["accelerator"].options == {"scope": "all"}
    created = [n for st in plan.steps[1:] for n in st.result["created"]]
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
    assert plan.changes and sum(len(st.result["created"]) for st in plan.steps[1:]) == len(asset_types.CATALOGUE)
    assert _count(db, Schema, ws) == 0 and _count(db, WorkspacePackage, ws) == 0

    # Hanging from a "catalogue" that holds none of the shared types: the accelerator step fails, and the core
    # package that came before it in the same install is not kept either.
    with pytest.raises(installer.PackageProblem, match="cannot be its own catalogue"):
        installer.install(db, ws, ["accelerator"], catalogue_workspace_id=ws)
    db.rollback()
    empty = f"{ws}-empty"
    db.add(Workspace(id=empty, name=empty))
    db.commit()
    # A catalogue with no recorded packages is checked type by type, and says which are missing.
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
    assert rows["core-facility"].version == available()["core-facility"].version
    catalogues = [pid for pid in _chain() if pid != "core-facility"]
    assert {pid: rows[pid].options for pid in catalogues} == {pid: {"scope": "global"} for pid in catalogues}
    assert {h.action for h in installer.history(db, ws)} == {"detected"}
    installer.detect(db)
    db.commit()
    assert len(installer.history(db, ws)) == len(_chain())        # each package of the chain: once
    db.close()


def test_an_import_requires_the_packages_it_needs_and_installs_none(ws):
    from app.packages.requirements import MissingPrerequisite, require
    from app.services.document_types import ensure_document_kinds
    from app.services.ticket_types import ensure_ticket_kinds
    db = SessionLocal()
    with pytest.raises(MissingPrerequisite, match="Install accelerator first"):
        require(db, ws, "accelerator-catalogue")
    with pytest.raises(MissingPrerequisite, match="Install core-facility first"):
        ensure_ticket_kinds(db, ws, {"Incident"})
    with pytest.raises(MissingPrerequisite):
        ensure_document_kinds(db, ws)
    assert _count(db, Schema, ws) == 0 and _count(db, WorkspacePackage, ws) == 0
    db.rollback()

    installer.install(db, ws, ["core-facility"])
    db.commit()
    base = db.get(Schema, f"{ws}:argus-ticket")
    base.attributes = [a for a in base.attributes if a["key"] != "argus_votes"]   # a local edit
    db.commit()
    kinds = ensure_ticket_kinds(db, ws, {"Incident", "Task"})
    db.commit()
    assert set(kinds) == {"Incident", "Task"} and db.get(Schema, kinds["Incident"]).parent_schema_uid == base.uid
    assert "argus_votes" not in {a["key"] for a in db.get(Schema, f"{ws}:argus-ticket").attributes}, \
        "an import does not rewrite the base type's fields"
    db.close()


def test_a_workspace_given_the_catalogue_before_the_record_is_recognised_not_reinstalled(ws):
    from app.packages.requirements import require
    db = SessionLocal()
    asset_types.ensure_asset_types(db, ws)
    db.commit()
    schemas = _count(db, Schema, ws)
    require(db, ws, "accelerator-catalogue")
    db.commit()
    from app.packages import defaults
    assert [(h.package_id, h.action) for h in installer.history(db, ws)] == [
        (pid, "detected") for pid in defaults.ordered() if pid in _chain() and pid != "core-facility"]
    assert _count(db, Schema, ws) == schemas
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
        assert listed["accelerator"]["contents"]["object_types"] == len(asset_types.specs_of("accelerator"))
        resolved = client.post("/v1/packages/resolve", json={"packages": ["accelerator"]}).json()
        assert [(p["id"], p["requested"]) for p in resolved] == [
            (pid, pid in ("core-facility", "accelerator")) for pid in _chain()]
        assert client.post("/v1/packages/resolve", json={"packages": ["nowhere"]}).status_code == 422

        r = client.post("/v1/workspaces", json={"name": "Packages test", "id": wid, "packages": ["accelerator"]})
        assert r.status_code == 201, r.text
        mine = client.get(f"/v1/workspaces/{wid}/packages").json()
        shipped = available()
        assert [(p["package_id"], p["version"]) for p in mine["packages"]] == [
            (pid, shipped[pid].version) for pid in sorted(_chain())]
        assert all(len(p["checksum"]) == 64 and not p["upgrade_available"] for p in mine["packages"])
        assert [h["action"] for h in mine["history"]] == ["install"] * len(_chain())

        preview = client.post(f"/v1/workspaces/{wid}/packages/preview", json={"packages": ["accelerator"]}).json()
        assert preview["changes"] is False
        done = client.post(f"/v1/workspaces/{wid}/packages/install", json={"packages": ["accelerator"]}).json()
        assert {s["action"] for s in done["steps"]} == {"unchanged"} and len(done["history"]) == len(_chain())
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
