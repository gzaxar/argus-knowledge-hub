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


def _newer(tmp_path):
    """accelerator 1.1.0: one change of each kind."""
    root = tmp_path / "packages"
    shutil.copytree(loader.packages_dir(), root)
    acc = root / "accelerator"
    manifest = yaml.safe_load((acc / "package.yaml").read_text())
    manifest["version"] = "1.1.0"
    (acc / "package.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    data = yaml.safe_load((acc / ACC).read_text())
    types = {t["name"]: t for t in data["object_types"]["types"]}
    # additive: a new type, a new attribute, a new option
    data["object_types"]["types"].append({"name": "Turbo Pump Controller", "parent": "Vacuum Controller",
                                          "description": "Drives a turbomolecular pump."})
    types["Vacuum Gauge"].setdefault("attributes", []).append({"key": "gauge_range", "name": "Range", "type": "string"})
    data["option_sets"]["band"].append({"id": "w_band", "value": "W-band"})
    # definition: a label and a description
    rack = types["Rack"]
    for a in rack["attributes"]:
        if a["key"] == "power_feed":
            a["name"] = "Power feed (PDU)"
    types["Vacuum Gauge"]["description"] = "Measures pressure in a vacuum sector."
    # breaking: a rename, a removal, tighter validation, a type removed
    for a in rack["attributes"]:
        if a["key"] == "rack_units":
            a["key"], a["renamed_from"] = "height_units", "rack_units"
        if a["key"] == "position":
            a["regex"] = "^[A-Z][0-9]{2}$"
    rack["attributes"] = [a for a in rack["attributes"] if a["key"] != "cooling"]
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
    rack_type = db.get(Schema, asset_types.type_uid(ws, "Rack"))
    rack = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=rack_type.uid, key=f"{ws}-RACK-1", name="Rack 1",
                 type="Rack", attributes={"rack_units": 42, "position": "row A, slot 1", "cooling": "air"})
    db.add(rack)
    # A local edit: this workspace dropped the Rack's power feed field itself.
    rack_type.attributes = [a for a in rack_type.attributes if a["key"] != "power_feed"]
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
    assert step.action == "upgrade" and step.from_version == "1.0.0" and step.version == "1.1.0"
    r = step.result
    by_id = {c["id"]: c for c in r["changes"]}
    assert by_id["object_types/Turbo Pump Controller/added"]["category"] == "additive"
    assert by_id["object_types/Vacuum Gauge/attributes/gauge_range/added"]["category"] == "additive"
    assert by_id["object_types/RF Station/attributes/band/options/w_band/added"]["category"] == "additive"
    assert by_id["object_types/Vacuum Gauge/description"]["category"] == "definition"
    assert set(r["needs_decision"]) >= {"object_types/Rack/attributes/height_units/renamed",
                                        "object_types/Rack/attributes/cooling/removed",
                                        "object_types/Rack/attributes/position/tightened",
                                        "object_types/Wire Scanner/removed"}
    tightened = by_id["object_types/Rack/attributes/position/tightened"]
    assert tightened["records"] == 1 and tightened["violations"] == 1      # "row A, slot 1" fails the pattern
    assert by_id["object_types/Rack/attributes/cooling/removed"]["records"] == 1
    relabel = by_id["object_types/Rack/attributes/power_feed/relabelled"]
    assert relabel["conflict"] == "the workspace removed this attribute itself"


def test_an_upgrade_without_a_migration_plan_changes_nothing(world):
    db = SessionLocal()
    with pytest.raises(installer.PackageProblem, match="needs a migration plan"):
        installer.install(db, world["ws"], ["accelerator"])
    db.rollback()
    assert installer.installed(db, world["ws"])["accelerator"].version == "1.0.0"
    assert db.get(Schema, asset_types.type_uid(world["ws"], "Turbo Pump Controller")) is None
    db.close()


def test_applying_a_change_that_would_leave_records_invalid_is_refused(world):
    db = SessionLocal()
    plan = {"object_types/Rack/attributes/height_units/renamed": "apply",
            "object_types/Rack/attributes/cooling/removed": "keep",
            "object_types/Rack/attributes/position/tightened": "apply",
            "object_types/Wire Scanner/removed": "keep"}
    with pytest.raises(installer.PackageProblem, match="1 record"):
        installer.install(db, world["ws"], ["accelerator"], decisions=plan)
    db.rollback()
    assert installer.installed(db, world["ws"])["accelerator"].version == "1.0.0"
    db.close()


def test_an_upgrade_with_its_plan_applies_it_keeps_local_edits_and_records_every_decision(world):
    ws = world["ws"]
    db = SessionLocal()
    plan = {"object_types/Rack/attributes/height_units/renamed": "apply",
            "object_types/Rack/attributes/cooling/removed": "keep",
            "object_types/Rack/attributes/position/tightened": "keep",
            "object_types/Wire Scanner/removed": "apply"}
    done = installer.install(db, ws, ["accelerator"], decisions=plan, actor="tester")
    db.commit()
    assert _steps(done)["accelerator"].action == "upgrade"
    row = installer.installed(db, ws)["accelerator"]
    assert row.version == "1.1.0" and row.checksum == loader.available()["accelerator"].checksum

    rack_type = db.get(Schema, asset_types.type_uid(ws, "Rack"))
    keys = {a["key"]: a for a in rack_type.attributes}
    assert "height_units" in keys and "rack_units" not in keys                  # renamed…
    assert db.get(Asset, world["rack"]).attributes["height_units"] == 42        # …and the value moved with it
    assert "cooling" in keys                                                     # kept, as decided
    assert "regex" not in keys["position"]                                       # kept: no pattern imposed
    assert "power_feed" not in keys, "a field the workspace removed is not added back"
    gauge = db.get(Schema, asset_types.type_uid(ws, "Vacuum Gauge"))
    assert "gauge_range" in {a["key"] for a in gauge.attributes}
    assert gauge.description == "Measures pressure in a vacuum sector."
    band = next(a for a in db.get(Schema, asset_types.type_uid(ws, "RF Station")).attributes if a["key"] == "band")
    assert "w_band" in {o["id"] for o in band["options"]}
    new_type = db.get(Schema, asset_types.type_uid(ws, "Turbo Pump Controller"))
    assert new_type is not None and new_type.parent_schema_uid == asset_types.type_uid(ws, "Vacuum Controller")
    storage = db.get(Schema, asset_types.type_uid(ws, "Wire Scanner"))
    assert storage.is_concrete is False and storage.metadata_json["withdrawn"] is True

    [step] = [h for h in installer.history(db, ws) if h.action == "upgrade"]
    assert (step.from_version, step.to_version, step.actor) == ("1.0.0", "1.1.0", "tester")
    assert step.result["decisions"] == plan
    assert step.result["outcome"]["object_types/Rack/attributes/cooling/removed"] == "kept as the workspace has it"
    assert "object_types/Rack/attributes/power_feed/relabelled" in step.result["conflicts"]

    again = installer.install(db, ws, ["accelerator"])
    assert {s.action for s in again.steps} == {"unchanged"}
    db.close()
