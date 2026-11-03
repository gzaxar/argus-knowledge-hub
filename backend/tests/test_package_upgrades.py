"""Moving a workspace to a newer package version: a preview that says what changes and what it touches, safe
changes applied by themselves, breaking ones only by an explicit migration plan, local edits kept, every
decision recorded."""
import secrets
import shutil
import uuid

import pytest
import yaml
from sqlalchemy import select

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.packages import install as installer
from app.packages import loader
from app.packages.validate import validate
from app.services import asset_types

ACC = "object_types.yaml"


def _versions():
    """The version that ships, and the newer one these tests make from it."""
    from packaging.version import Version
    shipped = Version(loader.available()["accelerator"].version)
    return str(shipped), f"{shipped.major}.{shipped.minor + 1}.0"


FROM, TO = _versions()


def _newer(tmp_path):
    """The next accelerator version: one change of each kind."""
    root = tmp_path / "packages"
    shutil.copytree(loader.packages_dir(), root)
    acc = root / "accelerator"
    manifest = yaml.safe_load((acc / "package.yaml").read_text())
    manifest["version"] = TO
    (acc / "package.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    data = yaml.safe_load((acc / ACC).read_text())
    types = {t["name"]: t for t in data["object_types"]["types"]}
    # additive: a new type, a new attribute, a new option
    data["object_types"]["types"].append({"name": "Turbo Pump Controller", "parent": "Vacuum Controller",
                                          "description": "Drives a turbomolecular pump."})
    types["Camera"].setdefault("attributes", []).append({"key": "frame_rate", "name": "Frame rate", "type": "string"})
    data["option_sets"]["band"].append({"id": "w_band", "value": "W-band"})
    # definition: a label and a description
    mount = types["Storage Mount"]
    for a in mount["attributes"]:
        if a["key"] == "export_path":
            a["name"] = "Export path (on the server)"
    types["Camera"]["description"] = "Takes images of a screen or a beam."
    # breaking: a rename, a removal, tighter validation, a type removed
    for a in mount["attributes"]:
        if a["key"] == "size_gb":
            a["key"], a["renamed_from"] = "capacity_gb", "size_gb"
        if a["key"] == "mount_path":
            a["regex"] = "^/[a-z0-9/_-]*$"
    mount["attributes"] = [a for a in mount["attributes"] if a["key"] != "server"]
    data["object_types"]["types"] = [t for t in data["object_types"]["types"] if t["name"] != "Wire Scanner"]
    (acc / ACC).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return root


@pytest.fixture()
def world(tmp_path, monkeypatch):
    ws = f"upg-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()
    installer.install(db, ws, ["accelerator"])
    mount_type = db.get(Schema, asset_types.type_uid(ws, "Storage Mount"))
    rack = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=mount_type.uid, key=f"{ws}-MNT-1", name="Data mount",
                 type="Storage Mount", attributes={"size_gb": 42, "mount_path": "data/raw", "server": "nas1"})
    db.add(rack)
    # A local edit: this workspace dropped the mount's export path field itself.
    mount_type.attributes = [a for a in mount_type.attributes if a["key"] != "export_path"]
    db.commit()
    rack_uid = rack.uid
    db.close()
    monkeypatch.setenv("ARGUS_PACKAGES_DIR", str(_newer(tmp_path)))
    loader.reload()
    yield {"ws": ws, "rack": rack_uid}
    monkeypatch.delenv("ARGUS_PACKAGES_DIR")
    loader.reload()
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


def _steps(plan):
    return {s.package_id: s for s in plan.steps}


def test_a_preview_says_what_changes_what_needs_a_decision_and_what_it_touches(world):
    assert validate(loader.available()["accelerator"]) == []
    db = SessionLocal()
    plan = installer.plan(db, world["ws"], ["accelerator"])
    db.rollback()
    step = _steps(plan)["accelerator"]
    assert step.action == "upgrade" and step.from_version == FROM and step.version == TO
    r = step.result
    by_id = {c["id"]: c for c in r["changes"]}
    assert by_id["object_types/Turbo Pump Controller/added"]["category"] == "additive"
    assert by_id["object_types/Camera/attributes/frame_rate/added"]["category"] == "additive"
    assert by_id["object_types/RF Station/attributes/band/options/w_band/added"]["category"] == "additive"
    assert by_id["object_types/Camera/description"]["category"] == "definition"
    assert set(r["needs_decision"]) >= {"object_types/Storage Mount/attributes/capacity_gb/renamed",
                                        "object_types/Storage Mount/attributes/server/removed",
                                        "object_types/Storage Mount/attributes/mount_path/tightened",
                                        "object_types/Wire Scanner/removed"}
    tightened = by_id["object_types/Storage Mount/attributes/mount_path/tightened"]
    assert tightened["records"] == 1 and tightened["violations"] == 1      # "data/raw" fails the pattern
    assert by_id["object_types/Storage Mount/attributes/server/removed"]["records"] == 1
    relabel = by_id["object_types/Storage Mount/attributes/export_path/relabelled"]
    assert relabel["conflict"] == "the workspace removed this attribute itself"


def test_an_upgrade_without_a_migration_plan_changes_nothing(world):
    db = SessionLocal()
    with pytest.raises(installer.PackageProblem, match="needs a migration plan"):
        installer.install(db, world["ws"], ["accelerator"])
    db.rollback()
    assert installer.installed(db, world["ws"])["accelerator"].version == FROM
    assert db.get(Schema, asset_types.type_uid(world["ws"], "Turbo Pump Controller")) is None
    db.close()


def test_applying_a_change_that_would_leave_records_invalid_is_refused(world):
    db = SessionLocal()
    plan = {"object_types/Storage Mount/attributes/capacity_gb/renamed": "apply",
            "object_types/Storage Mount/attributes/server/removed": "keep",
            "object_types/Storage Mount/attributes/mount_path/tightened": "apply",
            "object_types/Wire Scanner/removed": "keep"}
    with pytest.raises(installer.PackageProblem, match="1 record"):
        installer.install(db, world["ws"], ["accelerator"], decisions=plan)
    db.rollback()
    assert installer.installed(db, world["ws"])["accelerator"].version == FROM
    db.close()


def test_an_upgrade_with_its_plan_applies_it_keeps_local_edits_and_records_every_decision(world):
    ws = world["ws"]
    db = SessionLocal()
    plan = {"object_types/Storage Mount/attributes/capacity_gb/renamed": "apply",
            "object_types/Storage Mount/attributes/server/removed": "keep",
            "object_types/Storage Mount/attributes/mount_path/tightened": "keep",
            "object_types/Wire Scanner/removed": "apply"}
    done = installer.install(db, ws, ["accelerator"], decisions=plan, actor="tester")
    db.commit()
    assert _steps(done)["accelerator"].action == "upgrade"
    row = installer.installed(db, ws)["accelerator"]
    assert row.version == TO and row.checksum == loader.available()["accelerator"].checksum

    mount_type = db.get(Schema, asset_types.type_uid(ws, "Storage Mount"))
    keys = {a["key"]: a for a in mount_type.attributes}
    assert "capacity_gb" in keys and "size_gb" not in keys                      # renamed…
    assert db.get(Asset, world["rack"]).attributes["capacity_gb"] == 42         # …and the value moved with it
    assert "server" in keys                                                      # kept, as decided
    assert "regex" not in keys["mount_path"]                                     # kept: no pattern imposed
    assert "export_path" not in keys, "a field the workspace removed is not added back"
    camera = db.get(Schema, asset_types.type_uid(ws, "Camera"))
    assert "frame_rate" in {a["key"] for a in camera.attributes}
    assert camera.description == "Takes images of a screen or a beam."
    band = next(a for a in db.get(Schema, asset_types.type_uid(ws, "RF Station")).attributes if a["key"] == "band")
    assert "w_band" in {o["id"] for o in band["options"]}
    new_type = db.get(Schema, asset_types.type_uid(ws, "Turbo Pump Controller"))
    assert new_type is not None and new_type.parent_schema_uid == asset_types.type_uid(ws, "Vacuum Controller")
    storage = db.get(Schema, asset_types.type_uid(ws, "Wire Scanner"))
    assert storage.is_concrete is False and storage.metadata_json["withdrawn"] is True

    [step] = [h for h in installer.history(db, ws) if h.action == "upgrade"]
    assert (step.from_version, step.to_version, step.actor) == (FROM, TO, "tester")
    assert step.result["decisions"] == plan
    assert step.result["outcome"]["object_types/Storage Mount/attributes/server/removed"] == "kept as the workspace has it"
    assert "object_types/Storage Mount/attributes/export_path/relabelled" in step.result["conflicts"]

    again = installer.install(db, ws, ["accelerator"])
    assert {s.action for s in again.steps} == {"unchanged"}
    db.close()


# --------------------------------------------------------------------------- going back

PLAN = {"object_types/Storage Mount/attributes/capacity_gb/renamed": "apply",
        "object_types/Storage Mount/attributes/server/removed": "keep",
        "object_types/Storage Mount/attributes/mount_path/tightened": "keep",
        "object_types/Wire Scanner/removed": "apply"}


def test_a_workspace_goes_back_to_the_version_it_had_with_a_plan_and_a_record(world):
    from app.packages import revert
    ws = world["ws"]
    db = SessionLocal()
    old_checksum = installer.installed(db, ws)["accelerator"].checksum
    assert revert.targets(db, ws, "accelerator") == []                  # nothing earlier yet
    installer.install(db, ws, ["accelerator"], decisions=PLAN, actor="tester")
    db.commit()
    [target] = revert.targets(db, ws, "accelerator")
    assert target == {"version": FROM, "checksum": old_checksum}

    preview = revert.run(db, ws, "accelerator", old_checksum, keep=False)
    db.rollback()
    r = preview.steps[0].result
    assert preview.steps[0].action == "revert" and preview.steps[0].from_version == TO
    assert "object_types/Turbo Pump Controller/removed" in r["needs_decision"]
    assert "object_types/Storage Mount/attributes/size_gb/renamed" in r["needs_decision"]   # renamed back
    with pytest.raises(installer.PackageProblem, match="needs a migration plan"):
        revert.run(db, ws, "accelerator", old_checksum, keep=True)
    db.rollback()

    decide = {c: "apply" for c in r["needs_decision"]}
    revert.run(db, ws, "accelerator", old_checksum, decisions=decide, actor="tester", keep=True)
    db.commit()
    db.expire_all()
    row = installer.installed(db, ws)["accelerator"]
    assert (row.version, row.checksum) == (FROM, old_checksum)
    keys = {a["key"] for a in db.get(Schema, asset_types.type_uid(ws, "Storage Mount")).attributes}
    assert "size_gb" in keys and "capacity_gb" not in keys
    assert db.get(Asset, world["rack"]).attributes["size_gb"] == 42      # the value moved back with it
    scanner = db.get(Schema, asset_types.type_uid(ws, "Wire Scanner"))
    assert scanner.is_concrete and "withdrawn" not in (scanner.metadata_json or {})   # offered again
    turbo = db.get(Schema, asset_types.type_uid(ws, "Turbo Pump Controller"))
    assert turbo is None or turbo.is_concrete is False
    [step] = [h for h in installer.history(db, ws) if h.action == "revert"]
    assert (step.from_version, step.to_version, step.actor) == (TO, FROM, "tester")

    # The newer version is an upgrade again.
    assert {s.action for s in installer.plan(db, ws, ["accelerator"]).steps if s.package_id == "accelerator"} == {"upgrade"}
    db.rollback()
    db.close()


def test_a_revert_to_a_version_the_workspace_never_had_is_refused(world):
    from app.packages import revert
    db = SessionLocal()
    with pytest.raises(installer.PackageProblem, match="not an earlier version"):
        revert.run(db, world["ws"], "accelerator", "0" * 64, keep=False)
    db.close()


def test_a_revert_another_package_needs_the_newer_version_of_is_refused(world):
    from app.models.package import PackageSnapshot
    from app.packages import revert
    ws = world["ws"]
    db = SessionLocal()
    installer.install(db, ws, ["accelerator"], decisions=PLAN)
    db.commit()
    [target] = revert.targets(db, ws, "accelerator")
    # A package here that needs the newer accelerator.
    snap = db.scalar(select(PackageSnapshot).where(PackageSnapshot.package_id == "core-objects",
                                                   PackageSnapshot.checksum == installer.installed(db, ws)["core-objects"].checksum))
    dependent = installer.installed(db, ws)["core-objects"]
    original = dict(snap.manifest)
    snap.manifest = {**original, "depends": {"accelerator": f">={TO}"}}
    db.flush()
    try:
        assert revert.blockers(db, ws, "accelerator", FROM) == [f"core-objects {dependent.version} needs accelerator >={TO}"]
        with pytest.raises(installer.PackageProblem, match="cannot go back"):
            revert.run(db, ws, "accelerator", target["checksum"], keep=False)
    finally:
        db.rollback()
        db.close()


def test_administrators_see_every_workspace_and_upgrade_where_no_decision_is_needed(world):
    from fastapi.testclient import TestClient
    from app.auth import OidcIdentity, get_identity
    from app.main import app
    from app.models.user import User
    db = SessionLocal()
    admin = User(id=str(uuid.uuid4()), email=f"admin-{secrets.token_hex(3)}@argus.test", is_admin=True)
    plain = User(id=str(uuid.uuid4()), email=f"user-{secrets.token_hex(3)}@argus.test", is_admin=False)
    db.add_all([admin, plain])
    db.commit()
    db.refresh(admin)
    db.refresh(plain)
    db.expunge_all()
    db.close()
    client = TestClient(app)
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=plain)
        assert client.get("/v1/admin/packages").status_code == 403
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
        every = client.get("/v1/admin/packages").json()
        mine = next(w for w in every["workspaces"] if w["id"] == world["ws"])
        acc = next(p for p in mine["packages"] if p["package_id"] == "accelerator")
        assert acc["upgrade_available"] and acc["shipped_version"] == TO and acc["revert_to"] == []
        assert world["ws"] in next(p for p in every["packages"] if p["id"] == "accelerator")["behind"]

        body = {"workspaces": [world["ws"]]}
        preview = client.post("/v1/admin/packages/accelerator/upgrade-everywhere/preview", json=body).json()
        [entry] = preview["workspaces"]
        assert entry["status"] == "needs_decisions" and entry["decisions"] >= 4
        done = client.post("/v1/admin/packages/accelerator/upgrade-everywhere", json=body).json()
        assert done["workspaces"][0]["status"] == "needs_decisions"       # left for its own page
        db = SessionLocal()
        assert installer.installed(db, world["ws"])["accelerator"].version == FROM
        db.close()

        # Upgraded with its plan on its own page, it can be taken back from the same API.
        r = client.post(f"/v1/workspaces/{world['ws']}/packages/install",
                        json={"packages": ["accelerator"], "decisions": PLAN})
        assert r.status_code == 200, r.text
        rows = client.get(f"/v1/workspaces/{world['ws']}/packages").json()["packages"]
        [target] = next(p for p in rows if p["package_id"] == "accelerator")["revert_to"]
        r = client.post(f"/v1/workspaces/{world['ws']}/packages/revert/preview",
                        json={"package_id": "accelerator", "checksum": target["checksum"]})
        assert r.status_code == 200 and r.json()["steps"][0]["action"] == "revert"
        decide = {c: "keep" for c in r.json()["steps"][0]["result"]["needs_decision"]}
        r = client.post(f"/v1/workspaces/{world['ws']}/packages/revert",
                        json={"package_id": "accelerator", "checksum": target["checksum"], "decisions": decide})
        assert r.status_code == 200, r.text
        assert r.json()["history"][-1]["action"] == "revert"
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db = SessionLocal()
        for u in (admin, plain):
            db.delete(db.get(User, u.id))
        db.commit()
        db.close()


def test_core_objects_2_2_rewords_by_itself_and_keeps_a_workspaces_own_label(tmp_path, monkeypatch):
    """2.2.0 relabels (Product model, the "as recorded" fields, PBS area), describes and groups them: definition
    changes, applied with no decision — except where the workspace changed a field itself."""
    root = tmp_path / "packages"
    shutil.copytree(loader.packages_dir(), root)
    co = root / "core-objects"
    manifest = yaml.safe_load((co / "package.yaml").read_text())
    manifest["version"] = "2.1.0"
    (co / "package.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    data = yaml.safe_load((co / "object_types.yaml").read_text())
    from tests.package_parity import before_2_2
    for t in data["object_types"]["types"]:
        for a in t.get("attributes") or []:
            back = before_2_2({"key": a["key"], "name": a["name"], **({"description": a["description"]} if "description" in a else {}),
                               **({"group": a["group"]} if "group" in a else {})})
            a["name"] = back["name"]
            for k in ("description", "group"):
                if k in back:
                    a[k] = back[k]
                else:
                    a.pop(k, None)
    (co / "object_types.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    monkeypatch.setenv("ARGUS_PACKAGES_DIR", str(root))
    loader.reload()
    ws = f"wording-{secrets.token_hex(3)}"
    db = SessionLocal()
    try:
        db.add(Workspace(id=ws, name=ws))
        db.flush()
        installer.install(db, ws, ["core-objects"])
        asset = db.get(Schema, asset_types.type_uid(ws, "Asset"))
        attrs = {a["key"]: a for a in asset.attributes}
        assert attrs["product_model"]["name"] == "Instance of" and "group" not in attrs["manufacturer"]
        # The workspace renamed one field itself.
        asset.attributes = [{**a, "name": "Costruttore"} if a["key"] == "manufacturer" else a for a in asset.attributes]
        db.commit()
        monkeypatch.delenv("ARGUS_PACKAGES_DIR")
        loader.reload()
        plan = installer.plan(db, ws, ["core-objects"])
        db.rollback()
        step = next(s for s in plan.steps if s.package_id == "core-objects")
        assert step.action == "upgrade" and step.result["needs_decision"] == []
        installer.install(db, ws, ["core-objects"], actor="t")
        db.commit()
        db.expire_all()
        attrs = {a["key"]: a for a in db.get(Schema, asset_types.type_uid(ws, "Asset")).attributes}
        assert attrs["product_model"]["name"] == "Product model" and "catalogue" in attrs["product_model"]["description"]
        assert attrs["model"]["name"] == "Model (as recorded)" and attrs["model"]["group"] == "recorded"
        assert attrs["manufacturer"]["name"] == "Costruttore"                   # its own label kept
        pbs = {a["key"]: a for a in db.get(Schema, asset_types.type_uid(ws, "Engineered Item")).attributes}
        assert pbs["pbs_area"]["name"] == "PBS area" and pbs["pbs_code"]["group"] == "PBS"
    finally:
        db.rollback()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        w = db.get(Workspace, ws)
        if w is not None:
            db.delete(w)
        db.commit()
        db.close()
        loader.reload()
