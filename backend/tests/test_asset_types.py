"""The object catalogue.

What is worth testing is what could be wrong without anybody noticing: a key
spelled differently from the one tickets use (so "everything about the vacuum
system" quietly stops being answerable), a control-plane key the importer
writes that no type declares, a reference pointing at a type that is not
there, and a seeder that duplicates or overwrites what a workspace already
holds.
"""
import re
import secrets
import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.import_job import ImportJob
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import asset_types as at
from app.services.attribute_validation import check_attributes, effective_attributes
from app.services.document_types import base_attributes as document_attributes
from app.services.epik8s_import import _Importer
from app.services.ticket_types import base_attributes as ticket_attributes
from tests.test_epik8s_import import VALUES_TEMPLATE

pytestmark = pytest.mark.usefixtures("_schema")


@pytest.fixture(scope="module")
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def workspace(db):
    ws = f"cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Catalogue"))
    db.commit()
    return ws


# Every type the EPIK8s import writes objects of.
IMPORTER_TYPES = ("Facility", "Control Configuration", "IOC Template", "IOC", "Control Device",
                  "Access Point", "Control Network", "Control Service", "Storage Mount", "Serial Line")


def keys_of(name):
    return {a["key"] for a in at.BY_NAME[name].attributes}


def effective_keys(db, ws, name):
    schema = db.get(Schema, at.type_uid(ws, name))
    return {a["key"] for a in effective_attributes(db, schema)}


# --- the shape --------------------------------------------------------------

def test_the_catalogue_is_the_size_the_design_says():
    # 153 in the 1.x catalogue, and the four IT types (firewall, Wi-Fi access point, storage, patch panel)
    # the it package added when the catalogue was split into core-objects, it and accelerator: 157. Since
    # 1.35.26 the accelerator package stands on core-records, safety, vacuum-cryo and optics-alignment too, so
    # its catalogue gains their new types (3 + 12 + 11 + 17) and it 1.1.0's four (peripheral, software product,
    # version, licence); the types moved into those packages are counted once, as before.
    assert len(at.CATALOGUE) == 204
    assert sum(t.abstract for t in at.CATALOGUE) == 22
    assert max(at.depth(t.name) for t in at.CATALOGUE) == 6


def test_names_are_unique_and_so_are_their_uids():
    names = [t.name for t in at.CATALOGUE]
    assert len(names) == len(set(names))
    slugs = [at.type_uid("ws", n) for n in names]
    assert len(slugs) == len(set(slugs))


def test_parents_come_before_children_so_a_copy_can_resolve_them():
    seen = set()
    for spec in at.CATALOGUE:
        assert spec.parent is None or spec.parent in seen, spec.name
        seen.add(spec.name)


def test_every_reference_names_a_type_that_exists():
    for spec in at.CATALOGUE:
        for attr in spec.attributes:
            if attr["type"] == "reference":
                assert attr["referenceType"] in at.BY_NAME, (spec.name, attr["key"])


def test_a_pattern_is_anchored_or_it_matches_a_substring():
    for spec in at.CATALOGUE:
        for attr in spec.attributes:
            if attr.get("regex"):
                assert attr["regex"].startswith("^") and attr["regex"].endswith("$"), attr["key"]
                re.compile(attr["regex"])


def test_no_type_declares_the_same_key_twice():
    for spec in at.CATALOGUE:
        keys = [a["key"] for a in spec.attributes]
        assert len(keys) == len(set(keys)), spec.name


def test_only_the_root_and_the_six_branches_sit_directly_under_it():
    assert {t.name for t in at.CATALOGUE if t.parent == "Item"} == {
        "Engineered Item", "Catalog Item", "Control Item", "Engineering Record", "Location", "IT Record"}


# --- keys other parts of the hub already depend on --------------------------

def test_the_keys_shared_with_tickets_and_documents_are_spelled_the_same():
    item = {a["key"]: a for a in at.BY_NAME["Item"].attributes}
    for attr in ticket_attributes() + document_attributes():
        key = attr["key"]
        if key in ("argus_system", "argus_subsystem", "argus_facility", "argus_keywords"):
            assert key in item
            assert item[key]["type"] == attr["type"]
            assert item[key]["indexed"] == attr["indexed"]
            assert item[key]["multiValue"] == attr["multiValue"]
    assert {"argus_system", "argus_subsystem", "argus_facility", "argus_keywords"} <= set(item)


def test_the_keys_photo_identification_writes_are_declared():
    # asset_vision fills these four on a new object, unprefixed.
    assert "description" in keys_of("Item")
    assert {"manufacturer", "model", "serial"} <= keys_of("Asset")


def test_every_enumeration_option_has_a_unique_id():
    for spec in at.CATALOGUE:
        for attr in spec.attributes:
            if attr["type"] == "enumeration":
                ids = [o["id"] for o in attr["options"]]
                assert ids and len(ids) == len(set(ids)), (spec.name, attr["key"])


def test_the_source_options_include_the_ones_the_importers_write():
    ids = {o["id"] for o in next(a for a in at.BY_NAME["Item"].attributes
                                  if a["key"] == "argus_source")["options"]}
    assert {"epik8s", "epik8s-devices", "pbs"} <= ids


# --- seeding ------------------------------------------------------------------

def test_seeding_creates_the_whole_tree(db, workspace):
    result = at.ensure_asset_types(db, workspace)
    db.commit()
    assert len(result.created) == len(at.CATALOGUE) and not result.adopted and not result.duplicates
    rows = db.query(Schema).filter(Schema.workspace_id == workspace).all()
    assert len(rows) == len(at.CATALOGUE)
    by_name = {s.name: s for s in rows}
    assert by_name["Ion Pump"].parent_schema_uid == at.type_uid(workspace, "Vacuum Pump")
    assert by_name["Vacuum Pump"].parent_schema_uid == at.type_uid(workspace, "Asset")
    assert by_name["Item"].parent_schema_uid is None
    assert by_name["Vacuum Pump"].is_concrete is False and by_name["Ion Pump"].is_concrete is True
    assert all(s.applies_to == "objects" for s in rows)


def test_seeding_twice_changes_nothing(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    again = at.ensure_asset_types(db, workspace)
    db.commit()
    assert not again.created and not again.adopted and not again.extended
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == len(at.CATALOGUE)


def test_a_leaf_inherits_what_the_ancestors_declare(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    ion_pump = effective_keys(db, workspace, "Ion Pump")
    assert {"pumping_speed", "serial", "manufacturer", "pbs_code", "argus_system",
            "argus_lifecycle", "description"} <= ion_pump
    # and nothing from another branch
    assert "gradient" not in ion_pump and "pv" not in ion_pump


def test_a_reference_is_bound_to_the_type_in_this_workspace(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    schema = db.get(Schema, at.type_uid(workspace, "Asset"))
    located = next(a for a in schema.attributes if a["key"] == "argus_location")
    assert located["referenceSchemaUid"] == at.type_uid(workspace, "Location")
    assert located["includeChildren"] is True


def test_seeding_adds_what_is_missing_and_never_overwrites(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    uid = at.type_uid(workspace, "Ion Pump")
    schema = db.get(Schema, uid)
    edited = [dict(a) for a in schema.attributes]
    edited[0]["name"] = "Pumping speed, as this beamline writes it"
    schema.attributes = edited[:2]          # one edited, one removed
    db.commit()
    again = at.ensure_asset_types(db, workspace)
    db.commit()
    db.expire_all()
    after = db.get(Schema, uid).attributes
    assert after[0]["name"] == "Pumping speed, as this beamline writes it"
    assert {a["key"] for a in after} == keys_of("Ion Pump")
    assert again.extended == ["Ion Pump"]


def test_a_type_an_importer_made_is_adopted_not_duplicated(db, workspace):
    # uids are primary keys across the whole installation, so they carry the
    # workspace here as the real ones should.
    ioc_uid = f"epik8s-{workspace}-ioc"
    db.add(Schema(uid=ioc_uid, workspace_id=workspace, name="IOC",
                  applies_to="objects", metadata_json={"source": "epik8s"}, attributes=[]))
    db.add(Schema(uid=f"epik8s-{workspace}-power-supply", workspace_id=workspace,
                  name="Power Supply", applies_to="objects", attributes=[]))
    db.commit()
    result = at.ensure_asset_types(db, workspace)
    db.commit()
    assert sorted(result.adopted) == ["IOC", "Power Supply"]
    assert result.uids["IOC"] == ioc_uid
    rows = db.query(Schema).filter(Schema.workspace_id == workspace).all()
    assert len(rows) == len(at.CATALOGUE) and sum(1 for s in rows if s.name == "IOC") == 1
    ioc = db.get(Schema, ioc_uid)
    assert ioc.parent_schema_uid == at.type_uid(workspace, "Control Item")
    assert {a["key"] for a in ioc.attributes} == keys_of("IOC")
    # a child reaches its adopted parent by the adopted uid, not by a new one
    assert db.get(Schema, at.type_uid(workspace, "Camera")).parent_schema_uid == \
        at.type_uid(workspace, "Asset")


def test_somebody_elses_type_of_the_same_name_is_left_alone_and_reported(db, workspace):
    db.add(Schema(uid=f"{workspace}:mine", workspace_id=workspace, name="Camera",
                  applies_to="objects", parent_schema_uid=None,
                  attributes=[{"key": "lens_mount", "name": "Lens mount", "type": "string"}]))
    db.commit()
    result = at.ensure_asset_types(db, workspace)
    db.commit()
    assert result.duplicates == ["Camera"]
    mine = db.get(Schema, f"{workspace}:mine")
    assert mine.parent_schema_uid is None
    assert [a["key"] for a in mine.attributes] == ["lens_mount"]


# --- the catalogue has to describe what the importers actually store ---------

def run_import(db, ws):
    beamline = f"t{secrets.token_hex(3)}"
    values = yaml.safe_load(VALUES_TEMPLATE.replace("BEAMLINE", beamline))
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, "test@main:deploy/values.yaml")
    importer.ensure_types()
    importer.run(values, True)
    db.commit()
    return importer


def test_the_importer_adopts_the_typed_types_when_they_are_seeded_first(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    run_import(db, workspace)
    for name in IMPORTER_TYPES:
        found = db.query(Schema).filter(Schema.workspace_id == workspace, Schema.name == name).all()
        assert len(found) == 1, name
        assert found[0].uid == at.type_uid(workspace, name)


def test_every_key_the_importer_writes_is_declared_by_the_type_it_writes_to(db, workspace):
    from app.models.asset import Asset

    at.ensure_asset_types(db, workspace)
    db.commit()
    run_import(db, workspace)
    declared = {name: effective_keys(db, workspace, name) for name in IMPORTER_TYPES}
    undeclared = {}
    for asset in db.query(Asset).filter(Asset.workspace_id == workspace):
        missing = set(asset.attributes) - declared[asset.type]
        if missing:
            undeclared.setdefault(asset.type, set()).update(missing)
    assert not undeclared, undeclared


def test_seeded_after_the_importer_the_result_is_the_same(db, workspace):
    run_import(db, workspace)              # makes its own empty, epik8s-... types
    result = at.ensure_asset_types(db, workspace)
    db.commit()
    assert set(result.adopted) == set(IMPORTER_TYPES)
    for name in IMPORTER_TYPES:
        assert db.query(Schema).filter(Schema.workspace_id == workspace,
                                       Schema.name == name).count() == 1


# --- the rules that reach an object ---------------------------------------------

def test_a_real_pbs_code_passes_and_a_wrong_one_does_not(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    schema = db.get(Schema, at.type_uid(workspace, "RF Load"))
    from app.models.asset import Asset
    for code in ("INJ-A-ACC-SB3M-001", "INJ-A-ACC-SB1.5M-003", "MHX-R-RFX-XBND-003",
                 "MHX3-R-RF-LOAD-001"):
        assert not check_attributes(db, schema, {"pbs_code": code}, workspace, Asset,
                                    skip_unique=True), code
    assert check_attributes(db, schema, {"pbs_code": "not a code"}, workspace, Asset,
                            skip_unique=True)


def test_an_enumeration_rejects_a_value_it_does_not_list(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    schema = db.get(Schema, at.type_uid(workspace, "Ion Pump"))
    from app.models.asset import Asset
    assert not check_attributes(db, schema, {"argus_lifecycle": "In service"}, workspace, Asset,
                                skip_unique=True)
    assert check_attributes(db, schema, {"argus_lifecycle": "Very much alive"}, workspace, Asset,
                            skip_unique=True)


# --- through the REST API, as a beamline would use it -------------------------

client = TestClient(app)


@pytest.fixture()
def seeded(db, workspace):
    at.ensure_asset_types(db, workspace)
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=workspace, token_hash=hash_token(raw)))
    db.commit()
    return workspace, {"Authorization": f"Bearer {raw}"}


def make(ws, headers, type_name, prefix, attributes=None, name=None):
    uid = f"{prefix}-{secrets.token_hex(4)}"
    resp = client.post("/v1/assets", headers=headers, json={
        "uid": uid, "schema_uid": at.type_uid(ws, type_name),
        "key": f"{prefix.upper()}-{secrets.randbelow(10**7) + 10**6}",
        "name": name or type_name, "type": type_name, "attributes": attributes or {}})
    return uid, resp


def test_the_seeded_types_are_listed_and_an_object_of_one_can_be_made(seeded):
    ws, headers = seeded
    listed = client.get("/v1/schemas", headers=headers).json()
    assert len([s for s in listed if s["workspace_id"] == ws]) == len(at.CATALOGUE)
    _, resp = make(ws, headers, "Ion Pump", "pump", {
        "serial": "IPC-1234", "manufacturer": "Agilent", "pumping_speed": 55.0,
        "argus_lifecycle": "In service", "pbs_code": "INJ-A-VAC-PUMP-001"})
    assert resp.status_code == 201, resp.text


def test_an_object_of_a_seeded_type_is_held_to_the_types_rules(seeded):
    ws, headers = seeded
    _, bad_enum = make(ws, headers, "Ion Pump", "pump", {"argus_lifecycle": "Very much alive"})
    assert bad_enum.status_code == 422
    _, bad_code = make(ws, headers, "Ion Pump", "pump", {"pbs_code": "not a code"})
    assert bad_code.status_code == 422


def test_a_location_reference_accepts_a_rack_and_refuses_a_pump(seeded):
    ws, headers = seeded
    rack, made = make(ws, headers, "Rack", "rack")
    assert made.status_code == 201
    pump, _ = make(ws, headers, "Ion Pump", "pump")
    # Rack is a Location, and `Located in` accepts any Location descendant.
    _, ok = make(ws, headers, "Ion Pump", "pump", {"argus_location": rack})
    assert ok.status_code == 201, ok.text
    _, wrong = make(ws, headers, "Ion Pump", "pump", {"argus_location": pump})
    assert wrong.status_code == 422


def test_a_screen_station_is_composed_of_its_parts(seeded):
    ws, headers = seeded
    station, _ = make(ws, headers, "Screen Station", "flg",
                      {"screen_type": "YAG:Ce", "calibration_um_per_px": 16.67,
                       "insertion_positions": ["IN", "OUT"]})
    camera, _ = make(ws, headers, "Camera", "cam", {"interface": "GigE"})
    actuator, _ = make(ws, headers, "Actuator", "act", {"n_positions": 2})
    for part in (camera, actuator):
        resp = client.post("/v1/relations", headers=headers, json={
            "from_asset_uid": station, "to_asset_uid": part, "relation_type": "composed of"})
        assert resp.status_code == 201, resp.text
    edges = [r for r in client.get("/v1/relations", headers=headers).json()
             if r["from_asset_uid"] == station]
    assert {(e["to_asset_uid"], e["relation_type"]) for e in edges} == {
        (camera, "composed of"), (actuator, "composed of")}


# --- two sets: shared, and one machine's own ------------------------------------

def test_the_two_sets_partition_the_catalogue():
    assert set(at.GLOBAL_TYPES) | set(at.BEAMLINE_TYPES) == {t.name for t in at.CATALOGUE}
    assert not set(at.GLOBAL_TYPES) & set(at.BEAMLINE_TYPES)
    # the it package's four new types are shared equipment, and so are the 47 the domain packages add (1.35.26)
    assert (len(at.GLOBAL_TYPES), len(at.BEAMLINE_TYPES)) == (135, 69)


def test_a_machines_structure_and_control_are_its_own_and_the_rest_is_shared():
    beamline_roots = {"Functional Element", "Control Item", "Engineering Record"}
    for name in at.BEAMLINE_TYPES:
        cur = name
        while cur not in beamline_roots:
            cur = at.BY_NAME[cur].parent
    for name in ("Asset", "Ion Pump", "Camera", "Product Model", "Vendor", "Location", "Rack",
                 "Engineered Item", "Item"):
        assert name in at.GLOBAL_TYPES, name
    for name in ("Facility", "Quadrupole", "Screen Station", "IOC", "Control Device",
                 "Access Point", "Machine Module", "RF Station"):
        assert name in at.BEAMLINE_TYPES, name


def test_what_a_machine_costs_is_not_readable_from_another_machines_workspace():
    """A procurement record carries a price, and the objects of a global type are
    readable everywhere. The engineering records are the machine's own for that reason."""
    for name in ("Engineering Record", "Procurement Record", "Utility Requirement", "Work Package"):
        assert name in at.BEAMLINE_TYPES, name


def test_no_shared_type_depends_on_a_beamline_type():
    """A global type that named a beamline one would be unusable from any workspace
    that has not seeded that beamline's set."""
    for name in at.GLOBAL_TYPES:
        spec = at.BY_NAME[name]
        assert spec.parent is None or spec.parent in at.GLOBAL_TYPES, name
        for attr in spec.attributes:
            if attr["type"] == "reference":
                assert attr["referenceType"] in at.GLOBAL_TYPES, (name, attr["key"])


@pytest.fixture()
def catalogue(db):
    ws = f"cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Catalogue"))
    db.commit()
    result = at.ensure_asset_types(db, ws, scope="global")
    db.commit()
    return ws, result


def test_the_global_set_is_created_in_the_catalogue_and_shared(db, catalogue):
    ws, result = catalogue
    rows = db.query(Schema).filter(Schema.workspace_id == ws).all()
    assert len(result.created) == len(rows) == len(at.GLOBAL_TYPES)
    assert all(r.is_global for r in rows)
    assert {r.name for r in rows} == set(at.GLOBAL_TYPES)


def test_a_beamline_type_the_catalogue_shares_is_used_from_there_not_copied(db, catalogue):
    """sparc got a second control branch beside accelerator-infn's shared one, its IOCs on one copy and
    its Access Points on the other. A type the catalogue shares is the beamline's to use, not to copy."""
    ws, result = catalogue
    control = Schema(uid=f"{ws}:shared:control-item", workspace_id=ws, name="Control Item", applies_to="objects",
                     is_global=True, is_concrete=False, parent_schema_uid=result.uids["Item"])
    ioc = Schema(uid=f"{ws}:shared:ioc", workspace_id=ws, name="IOC", applies_to="objects", is_global=True,
                 parent_schema_uid=control.uid)
    db.add_all([control, ioc])
    bl = f"bl-{secrets.token_hex(4)}"
    db.add(Workspace(id=bl, name="Beamline"))
    db.commit()
    try:
        seeded = at.ensure_asset_types(db, bl, scope="beamline", catalogue_workspace_id=ws)
        db.commit()
        own = {s.name: s for s in db.query(Schema).filter(Schema.workspace_id == bl)}
        assert set(seeded.reused) == {"Control Item", "IOC"} and not {"Control Item", "IOC"} & set(own)
        assert own["Control Device"].parent_schema_uid == control.uid      # the rest of the branch hangs from it
        assert seeded.uids["IOC"] == ioc.uid
        # Seeding again changes nothing.
        again = at.ensure_asset_types(db, bl, scope="beamline", catalogue_workspace_id=ws)
        assert not again.created and set(again.reused) == {"Control Item", "IOC"}
    finally:
        # Shared types are seen by every workspace: these two would turn up in other tests.
        db.rollback()
        db.query(Schema).filter(Schema.workspace_id == bl).delete()
        db.query(Workspace).filter(Workspace.id == bl).delete()
        db.query(Schema).filter(Schema.uid == ioc.uid).delete()
        db.query(Schema).filter(Schema.uid == control.uid).delete()
        db.commit()


# Every attribute key tools/epik8s-devices `push` can write on a Control Device. The same
# list is asserted there against what `push` really writes: if a key is added on either
# side, one of the two tests fails, instead of the hub quietly storing a key no type declares.
CLI_PUSHES = {
    "beamline", "pv", "pv_prefix", "ioc", "system", "function", "zones", "address", "port", "channel",
    "axis", "settings", "argus_facility", "argus_source", "argus_source_ref", "device_class",
    "element", "vendor", "model_code", "argus_keywords",
}


def test_every_key_the_cli_pushes_is_declared_by_control_device(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    assert CLI_PUSHES <= effective_keys(db, workspace, "Control Device")


def test_a_pv_can_repeat_because_the_configuration_repeats_it():
    """SPARC configures two PVs on two IOCs each. A unique rule would make the hub
    refuse every later edit of those four devices."""
    pv = next(a for a in at.BY_NAME["Control Device"].attributes if a["key"] == "pv")
    assert not pv["unique"] and pv["indexed"]


def test_the_beamline_set_needs_the_global_one_to_hang_from(db, workspace):
    with pytest.raises(ValueError, match="say which workspace"):
        at.ensure_asset_types(db, workspace, scope="beamline")
    with pytest.raises(ValueError, match="cannot be its own catalogue"):
        at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=workspace)
    empty = f"cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=empty, name="Empty"))
    db.commit()
    with pytest.raises(at.CatalogueMissing, match="Seed it first"):
        at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=empty)
    db.rollback()
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == 0   # nothing half-written


def test_the_beamline_set_hangs_from_the_global_one(db, catalogue, workspace):
    cat, _ = catalogue
    result = at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    rows = {r.name: r for r in db.query(Schema).filter(Schema.workspace_id == workspace)}
    assert len(result.created) == len(rows) == len(at.BEAMLINE_TYPES) and set(rows) == set(at.BEAMLINE_TYPES)
    assert not any(r.is_global for r in rows.values())            # a machine's own
    # a beamline type reaches its parent and its references in the catalogue workspace
    assert rows["Functional Element"].parent_schema_uid == at.type_uid(cat, "Engineered Item")
    assert rows["Control Item"].parent_schema_uid == at.type_uid(cat, "Item")
    assert rows["Quadrupole"].parent_schema_uid == at.type_uid(workspace, "Beam Element")
    isolated = next(a for a in rows["Vacuum Sector"].attributes if a["key"] == "isolated_by")
    assert isolated["referenceSchemaUid"] == at.type_uid(cat, "Vacuum Valve")
    # every type is usable from here, by name
    assert set(result.uids) >= {t.name for t in at.CATALOGUE}
    assert result.uids["Ion Pump"] == at.type_uid(cat, "Ion Pump")
    assert result.uids["IOC"] == at.type_uid(workspace, "IOC")


def test_a_beamline_type_inherits_from_its_shared_ancestors(db, catalogue, workspace):
    cat, _ = catalogue
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    keys = {a["key"] for a in effective_attributes(db, db.get(Schema, at.type_uid(workspace, "Quadrupole")))}
    assert {"gradient", "lattice_name",          # its own and its beamline parent's
            "pbs_code", "argus_system", "description"} <= keys      # from the global ancestors


def test_seeding_the_beamline_set_twice_changes_nothing(db, catalogue, workspace):
    cat, _ = catalogue
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    again = at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    assert not again.created and not again.extended and not again.adopted


def test_a_workspace_seeded_in_full_can_become_the_catalogue(db, workspace):
    at.ensure_asset_types(db, workspace)                        # scope "all": nothing shared yet
    db.commit()
    assert not db.query(Schema).filter(Schema.workspace_id == workspace, Schema.is_global).count()
    result = at.ensure_asset_types(db, workspace, scope="global")
    db.commit()
    assert not result.created
    assert db.query(Schema).filter(Schema.workspace_id == workspace, Schema.is_global).count() == len(at.GLOBAL_TYPES)


def test_the_importers_find_a_type_wherever_it_is(db, catalogue, workspace):
    cat, _ = catalogue
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    uids = at.resolve_type_uids(db, workspace)
    assert uids["Ion Pump"] == at.type_uid(cat, "Ion Pump")       # global, from the catalogue
    assert uids["IOC"] == at.type_uid(workspace, "IOC")           # its own
    # a workspace that has an own type of the same name prefers it
    other = f"cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=other, name="Other"))
    db.flush()
    db.add(Schema(uid=f"{other}:mine", workspace_id=other, name="Ion Pump", applies_to="objects",
                  attributes=[]))
    db.commit()
    assert at.resolve_type_uids(db, other)["Ion Pump"] == f"{other}:mine"


# --- a workspace seeded before the two types were renamed ---------------------------

def _as_it_was_before_the_rename(db, ws):
    """Recreate what an earlier seeding left: `Equipment Item` and `Place` under their
    own uids, with their children pointing at them."""
    for new, old in (("Asset", "Equipment Item"), ("Location", "Place")):
        current = db.get(Schema, at.type_uid(ws, new))
        legacy = at.type_uid(ws, old)
        db.add(Schema(uid=legacy, workspace_id=ws, name=old, description=current.description,
                      applies_to="objects", is_concrete=False,
                      parent_schema_uid=current.parent_schema_uid,
                      attributes=current.attributes, metadata_json={"source": "argus"}))
        db.flush()
        db.query(Schema).filter(Schema.parent_schema_uid == current.uid).update(
            {Schema.parent_schema_uid: legacy}, synchronize_session=False)
        db.delete(current)
        db.flush()
    schema = db.get(Schema, at.type_uid(ws, "Asset")) or db.get(Schema, at.type_uid(ws, "Equipment Item"))
    fixed = []
    for a in schema.attributes:
        a = dict(a)
        if a["key"] == "argus_location":
            a["referenceType"], a["referenceSchemaUid"] = "Place", at.type_uid(ws, "Place")
        fixed.append(a)
    schema.attributes = fixed
    db.commit()


def test_a_workspace_seeded_under_the_old_names_is_carried_across_in_place(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    _as_it_was_before_the_rename(db, workspace)
    assert db.get(Schema, at.type_uid(workspace, "Equipment Item")) is not None

    result = at.ensure_asset_types(db, workspace)
    db.commit()
    db.expire_all()

    assert sorted(result.renamed) == ["Asset", "Location"] and not result.created
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == len(at.CATALOGUE)
    asset = db.get(Schema, at.type_uid(workspace, "Equipment Item"))    # same row, same uid
    assert asset.name == "Asset"
    assert db.get(Schema, at.type_uid(workspace, "Place")).name == "Location"
    assert not db.query(Schema).filter(Schema.workspace_id == workspace,
                                       Schema.name.in_(["Equipment Item", "Place"])).count()
    # what pointed at the old row still does
    assert db.get(Schema, at.type_uid(workspace, "Camera")).parent_schema_uid == asset.uid
    located = next(a for a in asset.attributes if a["key"] == "argus_location")
    assert located["referenceType"] == "Location"                       # the display name follows
    assert located["referenceSchemaUid"] == at.type_uid(workspace, "Place")


def test_a_stale_catalogue_workspace_is_named_not_worked_around(db, workspace):
    cat = f"cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=cat, name="Old catalogue"))
    db.commit()
    at.ensure_asset_types(db, cat)                       # everything, in one workspace
    at.ensure_asset_types(db, cat, scope="global")
    db.commit()
    _as_it_was_before_the_rename(db, cat)
    with pytest.raises(at.CatalogueMissing, match="seed it again"):
        at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)


# --- what "global" means to the people using a beamline --------------------------------

def test_a_shared_type_is_usable_everywhere_but_its_objects_stay_where_they_are_unless_flagged(db, catalogue):
    """Types are shared, objects are not. A beamline's cameras are its own; a product model or a
    vendor is what is flagged global, and only that is seen elsewhere."""
    cat, _ = catalogue
    sparc, btf = f"bl-{secrets.token_hex(4)}", f"bl-{secrets.token_hex(4)}"
    headers = {}
    for ws in (sparc, btf):
        db.add(Workspace(id=ws, name=ws))
        db.commit()
        at.ensure_asset_types(db, ws, scope="beamline", catalogue_workspace_id=cat)
        raw = secrets.token_urlsafe(16)
        db.add(ApiToken(workspace_id=ws, token_hash=hash_token(raw)))
        db.commit()
        headers[ws] = {"Authorization": f"Bearer {raw}"}

    def make_in(ws, type_uid, type_name, prefix, **extra):
        uid = f"{prefix}-{secrets.token_hex(4)}"
        resp = client.post("/v1/assets", headers=headers[ws], json={
            "uid": uid, "schema_uid": type_uid, "key": f"{prefix.upper()}-{secrets.randbelow(10**7) + 10**6}",
            "name": type_name, "type": type_name, "attributes": {}, **extra})
        assert resp.status_code == 201, resp.text
        return uid

    pump = make_in(sparc, at.type_uid(cat, "Ion Pump"), "Ion Pump", "pump")            # a shared type, not flagged
    model = make_in(sparc, at.type_uid(cat, "Ion Pump"), "Ion Pump", "mdl", is_global=True)   # the same type, flagged
    facility = make_in(sparc, at.type_uid(sparc, "Facility"), "Facility", "fac")         # SPARC's own type

    def seen_from(ws):
        return {a["uid"] for a in client.get("/v1/assets", headers=headers[ws]).json()}

    assert pump not in seen_from(btf) and facility not in seen_from(btf)     # of a shared type is not enough
    assert model in seen_from(btf)                                           # flagged: seen elsewhere
    assert {pump, model, facility} <= seen_from(sparc)                       # and everything is seen at home
    # seen, not editable: the owning workspace is the only one that can change it
    assert client.get(f"/v1/assets/{pump}", headers=headers[btf]).status_code == 404
    assert client.put(f"/v1/assets/{model}", headers=headers[btf], json={"name": "x"}).status_code == 404
    assert client.put(f"/v1/assets/{model}", headers=headers[sparc], json={"name": "x"}).status_code == 200


def test_an_object_made_in_a_global_workspace_is_global_unless_it_says_otherwise(db, catalogue):
    cat, _ = catalogue
    workspace = db.get(Workspace, cat)
    workspace.is_global = True
    db.commit()
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=cat, token_hash=hash_token(raw)))
    db.commit()
    headers = {"Authorization": f"Bearer {raw}"}

    def make(prefix, **extra):
        uid = f"{prefix}-{secrets.token_hex(4)}"
        resp = client.post("/v1/assets", headers=headers, json={
            "uid": uid, "schema_uid": at.type_uid(cat, "Ion Pump"), "key": f"{prefix.upper()}-{secrets.randbelow(10**7) + 10**6}",
            "name": "x", "type": "Ion Pump", "attributes": {}, **extra})
        assert resp.status_code == 201, resp.text
        return client.get(f"/v1/assets/{uid}", headers=headers).json()["is_global"]

    assert make("a") is True                       # made in a global workspace
    assert make("b", is_global=False) is False     # unless it says otherwise


def test_a_workspace_knows_which_catalogue_it_hangs_from(db, catalogue, workspace):
    cat, _ = catalogue
    assert at.catalogue_of(db, workspace) is None                 # nothing seeded yet
    assert at.catalogue_of(db, cat) is None                       # a catalogue hangs from nothing
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    assert at.catalogue_of(db, workspace) == cat


def test_seeding_in_full_a_workspace_that_hangs_from_a_catalogue_is_refused(db, catalogue, workspace):
    """Otherwise the shared types would be copied into it: the copies this design
    exists to avoid."""
    cat, _ = catalogue
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    for scope in ("all", "global"):
        with pytest.raises(ValueError, match="already hangs from the catalogue"):
            at.ensure_asset_types(db, workspace, scope=scope)
    db.rollback()
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == len(at.BEAMLINE_TYPES)



# --- the IT model --------------------------------------------------------------------------

def test_the_it_types_form_a_tree_under_asset_and_the_registry_records_sit_apart():
    def parent(name):
        return at.BY_NAME[name].parent
    assert parent("IT Equipment") == "Asset"
    for name in ("Switch", "Router", "Serial Converter", "Media Converter"):
        assert parent(name) == "Network Device"
    assert parent("Network Device") == parent("Computing Node") == "IT Equipment"
    assert parent("Server") == parent("Workstation") == "Computing Node"
    assert parent("Network Segment") == parent("Address Record") == "IT Record"
    assert parent("IT Record") == "Item"
    assert all(at.BY_NAME[n].abstract for n in ("IT Equipment", "IT Record"))
    # concrete since it 1.1.0: what GLPI does not classify further is a plain network device or computing node
    assert not any(at.BY_NAME[n].abstract for n in ("Network Device", "Computing Node"))


def test_it_equipment_and_records_are_shared_and_a_serial_line_is_a_beamlines_own():
    for name in ("IT Equipment", "Switch", "Serial Converter", "Server", "Workstation",
                 "IT Record", "Network Segment", "Address Record"):
        assert at.scope_of(name) == "global", name
    assert at.scope_of("Serial Line") == "beamline"


def test_a_converter_is_a_network_device_with_the_addressing_every_it_box_has(db, catalogue):
    cat, _ = catalogue
    keys = effective_keys(db, cat, "Serial Converter")
    assert {"hostname", "fqdn", "ip", "mac", "n_serial_ports", "tcp_port_base"} <= keys
    assert {"is_virtual", "cpu"} <= effective_keys(db, cat, "Server")
    assert {"workstation_role", "console_group", "os"} <= effective_keys(db, cat, "Workstation")


def test_an_access_point_says_what_kind_of_endpoint_it_is_and_how_that_was_read(db, workspace):
    at.ensure_asset_types(db, workspace)
    db.commit()
    assert {"endpoint_kind", "endpoint_kind_source"} <= effective_keys(db, workspace, "Access Point")
    assert {"tcp_port", "line_kind", "baud"} <= effective_keys(db, workspace, "Serial Line")


def test_seeding_again_moves_a_type_whose_place_in_the_tree_changed(db, workspace):
    """Network Device used to hang from Asset. A workspace seeded before must follow the release."""
    at.ensure_asset_types(db, workspace, scope="all")
    db.commit()
    device = db.get(Schema, at.type_uid(workspace, "Network Device"))
    device.parent_schema_uid = at.type_uid(workspace, "Asset")      # the old shape
    device.is_concrete = False                                        # abstract before it 1.1.0
    db.commit()
    result = at.ensure_asset_types(db, workspace, scope="all")
    db.commit()
    db.refresh(device)
    assert device.parent_schema_uid == at.type_uid(workspace, "IT Equipment") and device.is_concrete
    assert "Network Device" in result.extended


def test_cables_are_classified_by_what_they_carry_and_a_line_is_not_one_of_them():
    by = {t.name: t for t in at.CATALOGUE}
    assert by["Cable Run"].abstract
    kids = {t.name for t in at.CATALOGUE if t.parent == "Cable Run"}
    assert kids == {"Ethernet Cable", "Serial Cable", "Fibre Cable", "Power Cable", "HV Cable",
                    "RF Cable", "Signal Cable"}
    assert kids <= set(at.GLOBAL_TYPES)
    assert by["Serial Line"].parent == "Control Item"



def test_every_type_gets_a_default_icon_once_and_a_chosen_one_stays(tmp_path, monkeypatch):
    """Tabler icons, and four drawn for ARGUS; a type without its own takes its nearest ancestor's."""
    from app.models.icon import Icon
    from app.services import catalogue_icons
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    assert catalogue_icons.icon_for("Ion Pump") == "tabler/propeller"           # from Vacuum Pump
    assert catalogue_icons.icon_for("Quadrupole") == "argus/quadrupole"
    for icon in set(catalogue_icons.ICONS.values()):
        assert (catalogue_icons.ICON_DIR / f"{icon}.svg").exists(), icon
    assert all(catalogue_icons.icon_for(t.name) for t in at.CATALOGUE)
    workspace = f"icons-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=workspace, name=workspace))
    db.flush()
    result = at.ensure_asset_types(db, workspace)
    assert len(result.iconed) == len(at.CATALOGUE)
    schemas = {s.name: s for s in db.query(Schema).filter(Schema.workspace_id == workspace)}
    quad = db.get(Icon, schemas["Quadrupole"].icon_uid)
    assert quad.filename == "argus-quadrupole.svg" and quad.mime_type == "image/svg+xml"
    assert open(quad.storage_path, "rb").read().startswith(b"<svg")
    assert schemas["Ion Pump"].icon_uid == schemas["Turbo Pump"].icon_uid              # one icon, shared
    mine = Icon(uid=str(uuid.uuid4()), workspace_id=workspace, name="mine", filename="mine.png",
                storage_path=str(tmp_path / "mine"), is_global=False)
    db.add(mine)
    schemas["Camera"].icon_uid = mine.uid
    db.flush()
    again = at.ensure_asset_types(db, workspace)
    assert again.iconed == []                                                      # nothing to fill
    assert db.get(Schema, schemas["Camera"].uid).icon_uid == mine.uid              # a chosen icon stays
    assert db.query(Icon).filter(Icon.workspace_id == workspace, Icon.filename.like("argus-%")).count() == \
        len(set(catalogue_icons.icon_for(t.name) for t in at.CATALOGUE))
    db.rollback()
    db.close()
