"""Reading a product-breakdown workbook as equipment.

The tests worth having are about a workbook that is still being filled in: a
number written as words, a range in a column that expects one value, a code the
import has never heard of. Each has to end as something a person can see, not
as a number nobody meant.
"""
import io
import os
import secrets

import openpyxl
import pytest

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset, Relation
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import asset_types as at
from app.services.attribute_validation import check_attributes
from app.services.pbs_import import import_pbs, parse_modules, read_workbook

REAL = os.path.join(os.path.dirname(__file__), "..", "..", "docs",
                    "2026-06-11 - EuPRAXIA PBS_ver2.xlsx")

HEADERS = [
    "DESCRIPTION", "ID", "COMPONENT\nID", "WBS\nCODE", "AREA/ZONE", "SYSTEM", "FAMILY", "TYPE",
    "SEQUENTIAL \nNUMBER", "PBS-CODE", "MODULES", "STATUS\nD= da definire\nS= in studio",
    "UNIT COST(€)", "NUM. OF UNITS", "COMMENTS",
    "ELECTRICAL PHASES (3P+N, 1P+N)", "WATER TEMPERATURE SETPOINT REGULATION MIN-MAX (°C)",
    "WATER FLOW RATE (l/min)", "MAX ACCEPTABLE TEMPERATURE IN (°C)", "RH STABILITY [%]",
    "DO NOT COMPILE FROM HERE", "TOTAL COST(€)", "SUPPLIER", "RUP",
]


def row(**v):
    """A component row, by header keyword; anything not given is empty."""
    keys = {"name": 0, "id": 1, "comp": 2, "wbs": 3, "area": 4, "system": 5, "family": 6,
            "type": 7, "seq": 8, "code": 9, "modules": 10, "status": 11, "cost": 12,
            "units": 13, "comments": 14, "phases": 15, "setpoint": 16, "flow": 17,
            "maxtemp": 18, "rh": 19, "total": 21, "supplier": 22, "rup": 23}
    out = [None] * len(HEADERS)
    for k, val in v.items():
        out[keys[k]] = val
    return out


def workbook(rows, wp=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "UTILITY RF"
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    wbs = wb.create_sheet("WBS CODE")
    wbs.append(["WBS CODE", "DESCRIZIONE"])
    wbs.append(["WP-04", "Radiofrequency"])
    zone = wb.create_sheet("SYSTEM ZONE")
    for r in (["SYSTEM ZONE", "DESCRIZIONE"], ["INJ", "Injector"], ["LEL", "Low Energy Linac"],
              ["ID_COMPONENT", "DESCRIPTION"], ["RFG", "RF GUN"]):
        zone.append(r)
    area = wb.create_sheet("AREA")
    for r in (["MODULO", "DESCRIZIONE"], ["MHX3", "Modulator Hall X-Band 3"], ["LNT", "Linac Tunnel"]):
        area.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


GOOD = [
    row(name="SBAND 3M LA002", id=39, comp="SB3", wbs="WP-04", area="INJ", system="A",
        family="ACC", type="SB3M", seq="001", code="INJ-A-ACC-SB3M-001",
        modules="INJ-LA-002", status="D", cost=150000, units=1, total=150000,
        flow="4,2  (l/m oppure l/h)????????", maxtemp="35+/-0,1", setpoint=25),
    row(name="COUPLER", id=80, comp="BDC", wbs="WP-04", area="MHX3", system="I", family="WGS",
        type="BDC", seq=1, code="MHX3-I-WGS-BDC-001",
        modules="X-BAND STATION 3 LEL-LA-002", status="A", cost=10000, units=1, total=10000),
    row(name="LOAD", id=81, comp="RFL", wbs="WP-04", area="MHX3", system="R", family="RF",
        type="LOAD", seq="001", code="MHX3-R-RF-LOAD-001",
        modules="X-BAND STATION 3 LEL-LA-002", status="A", cost=8000, units=1, total=8000),
]


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def bare(db):
    """A workspace with no object catalogue."""
    ws = f"pbs-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="PBS"))
    db.commit()
    return ws


@pytest.fixture()
def workspace(db, bare):
    """A workspace with the accelerator catalogue installed, self-contained: what a PBS import needs."""
    from app.packages.install import install
    install(db, bare, ["accelerator"])
    db.commit()
    return bare


@pytest.fixture()
def facility():
    # Keys are unique across the installation, so each test has a facility of its own.
    return f"F{secrets.token_hex(3).upper()}"


def assets(db, ws):
    return {a.key: a for a in db.query(Asset).filter(Asset.workspace_id == ws)}


def edges(db, ws):
    by_uid = {a.uid: a.key for a in db.query(Asset).filter(Asset.workspace_id == ws)}
    return {(by_uid[r.from_asset_uid], r.relation_type, by_uid[r.to_asset_uid])
            for r in db.query(Relation).filter(Relation.workspace_id == ws)}


# --- the station and module in one cell ----------------------------------------

@pytest.mark.parametrize("text,station,modules", [
    ("X-BAND STATION 3 LEL-LA-002", "X-BAND STATION 3", ["LEL-LA-002"]),
    ("S-BAND STATION 1 INJ-LA002/003", "S-BAND STATION 1", ["INJ-LA-002", "INJ-LA-003"]),
    ("S-BAND STATION INJ-LA-001", "S-BAND STATION", ["INJ-LA-001"]),
    ("INJ-LA-004", None, ["INJ-LA-004"]),
    (None, None, []),
])
def test_a_station_and_a_module_are_read_out_of_one_label(text, station, modules):
    assert parse_modules(text) == (station, modules)


# --- reading what is written ---------------------------------------------------

def test_a_number_written_as_words_is_kept_as_words_and_reported():
    book = read_workbook(workbook(GOOD))
    util = book.components[0].utility
    assert util["water_flow_l_min"] == 4.2               # the decimal comma is read
    assert util["water_max_acceptable_temp_c"] == 35.0
    notes = " | ".join(book.components[0].notes)
    assert "'4,2  (l/m oppure l/h)????????'" in notes and "'35+/-0,1'" in notes
    assert any("AF" in w or "R2" in w or "WATER FLOW RATE" in w for w in book.warnings)


def test_a_range_is_not_read_as_its_first_number():
    book = read_workbook(workbook([row(code="INJ-A-ACC-SB3M-001", rh="50-88", comp="SB3")]))
    assert "relative_humidity_pct" not in book.components[0].utility
    assert "rh_stability_pct" not in book.components[0].utility
    assert any("range" in w for w in book.warnings)
    assert any("'50-88'" in n for n in book.components[0].notes)


def test_a_setpoint_column_holds_a_setpoint_or_a_range():
    one = read_workbook(workbook([row(code="INJ-A-ACC-SB3M-001", setpoint=25, comp="SB3")]))
    assert one.components[0].utility == {"water_temp_setpoint_c": 25.0}
    two = read_workbook(workbook([row(code="INJ-A-ACC-SB3M-001", setpoint="20-30", comp="SB3")]))
    assert two.components[0].utility == {"water_temp_setpoint_min_c": 20.0,
                                         "water_temp_setpoint_max_c": 30.0}


def test_a_value_the_column_cannot_hold_is_reported_not_stored():
    book = read_workbook(workbook([row(code="INJ-A-ACC-SB3M-001", phases=129, comp="SB3")]))
    assert "electrical_phases" not in book.components[0].utility
    assert any("129" in n for n in book.components[0].notes)


def test_codes_are_kept_as_written_and_status_is_read():
    book = read_workbook(workbook(GOOD))
    first, second = book.components[0].component, book.components[1].component
    assert first["pbs_sequential"] == "001" and second["pbs_sequential"] == "001"   # int 1 -> "001"
    assert first["design_status"] == "Defined" and second["design_status"] == "Approved"
    assert first["sequence_index"] == 39


def test_the_legend_sheets_are_read():
    book = read_workbook(workbook(GOOD))
    assert book.work_packages == {"WP-04": "Radiofrequency"}
    assert book.zones == {"INJ": "Injector", "LEL": "Low Energy Linac"}   # not the component codes
    assert book.areas == {"MHX3": "Modulator Hall X-Band 3", "LNT": "Linac Tunnel"}


# --- writing it ------------------------------------------------------------------

def test_a_row_becomes_an_object_of_the_type_its_component_code_names(db, workspace, facility):
    result = import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    objs = assets(db, workspace)
    assert objs[f"{facility}:INJ-A-ACC-SB3M-001"].type == "Accelerating Structure"
    assert objs[f"{facility}:MHX3-I-WGS-BDC-001"].type == "Directional Coupler"
    assert objs[f"{facility}:MHX3-R-RF-LOAD-001"].type == "RF Load"
    assert result.counts["components"] == 3 and result.counts["procurement_records"] == 3
    assert result.counts["utility_requirements"] == 1     # only the row that said anything


def test_a_component_is_linked_to_what_the_workbook_says_about_it(db, workspace, facility):
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    e = edges(db, workspace)
    coupler = f"{facility}:MHX3-I-WGS-BDC-001"
    assert (coupler, "assigned to", f"{facility}:WP:WP-04") in e
    assert (coupler, "part of", f"{facility}:AREA:MHX3") in e          # an area
    assert (f"{facility}:INJ-A-ACC-SB3M-001", "part of", f"{facility}:SEC:INJ") in e   # a zone
    assert (coupler, "part of", f"{facility}:MOD:LEL-LA-002") in e
    assert (coupler, "procured under", f"{coupler}:PROC") in e
    assert (f"{facility}:INJ-A-ACC-SB3M-001", "requires",
            f"{facility}:INJ-A-ACC-SB3M-001:UTIL") in e


def test_a_shared_label_becomes_a_station_composed_of_its_parts(db, workspace, facility):
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    station = f"{facility}:STN:x-band-station-3"
    e = edges(db, workspace)
    assert (station, "composed of", f"{facility}:MHX3-I-WGS-BDC-001") in e
    assert (station, "composed of", f"{facility}:MHX3-R-RF-LOAD-001") in e
    assert (station, "part of", f"{facility}:MOD:LEL-LA-002") in e
    obj = assets(db, workspace)[station]
    assert obj.type == "RF Station"
    assert obj.attributes["band"] == "X-band" and obj.attributes["station_number"] == 3


def test_a_code_the_import_does_not_know_is_not_guessed_at(db, workspace, facility):
    book = read_workbook(workbook([row(name="WIDGET", comp="ZZZ", code="INJ-A-ZZZ-ZZZZ-001",
                                       area="INJ", wbs="WP-04")]))
    result = import_pbs(db, workspace, book, facility, "x.xlsx")
    assert assets(db, workspace)[f"{facility}:INJ-A-ZZZ-ZZZZ-001"].type == "Engineered Item"
    assert any("'ZZZ'" in w for w in result.warnings)


def test_an_area_in_no_legend_gets_no_edge_and_a_warning(db, workspace, facility):
    book = read_workbook(workbook([row(comp="RFG", code="NOW-A-RF-GUN-001", area="NOWHERE")]))
    result = import_pbs(db, workspace, book, facility, "x.xlsx")
    obj = f"{facility}:NOW-A-RF-GUN-001"
    assert not [e for e in edges(db, workspace) if e[0] == obj and e[1] == "part of"]
    assert any("NOWHERE" in w for w in result.warnings)


def test_running_it_twice_changes_nothing(db, workspace, facility):
    first = import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    n_assets, n_edges = len(assets(db, workspace)), len(edges(db, workspace))
    second = import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    assert first.counts["relations"] > 0 and second.counts.get("relations", 0) == 0
    assert (len(assets(db, workspace)), len(edges(db, workspace))) == (n_assets, n_edges)


def test_a_dry_run_writes_nothing(db, workspace, facility):
    types = db.query(Schema).filter(Schema.workspace_id == workspace).count()
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx", dry_run=True)
    db.expire_all()
    assert not assets(db, workspace) and not edges(db, workspace)
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == types


def test_a_re_read_leaves_what_a_person_has_since_decided(db, workspace, facility):
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    obj = assets(db, workspace)[f"{facility}:INJ-A-ACC-SB3M-001"]
    obj.attributes = {**obj.attributes, "argus_lifecycle": "In service", "serial": "SN-1"}
    db.commit()
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    db.expire_all()
    again = assets(db, workspace)[f"{facility}:INJ-A-ACC-SB3M-001"]
    assert again.attributes["argus_lifecycle"] == "In service"     # outranks the workbook
    assert again.attributes["serial"] == "SN-1"                    # not the workbook's to erase
    assert again.attributes["pbs_code"] == "INJ-A-ACC-SB3M-001"


def test_a_key_that_belongs_to_another_workspace_is_named_not_clobbered(db, facility):
    a, b = f"pbs-{secrets.token_hex(4)}", f"pbs-{secrets.token_hex(4)}"
    db.add_all([Workspace(id=a, name="A"), Workspace(id=b, name="B")])
    db.commit()
    from app.packages.install import install
    for w in (a, b):
        install(db, w, ["accelerator"])
    db.commit()
    import_pbs(db, a, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    with pytest.raises(ValueError, match="already exists in workspace"):
        import_pbs(db, b, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    db.rollback()


def test_everything_it_writes_is_declared_and_valid_under_the_catalogue(db, workspace, facility):
    """The catalogue has to describe what the importer stores — and hold it to
    the catalogue's own rules, so a later edit through the API does not fail on
    a value the importer itself wrote."""
    import_pbs(db, workspace, read_workbook(workbook(GOOD + [
        row(name="S1.5", comp="SB1.5", code="INJ-A-ACC-SB1.5M-003", area="INJ", wbs="WP-04")])),
        facility, "x.xlsx")
    for obj in assets(db, workspace).values():
        schema = db.get(Schema, obj.schema_uid)
        from app.services.attribute_validation import effective_attributes
        declared = {a["key"] for a in effective_attributes(db, schema)}
        assert not set(obj.attributes) - declared, (obj.key, set(obj.attributes) - declared)
        assert not check_attributes(db, schema, obj.attributes, workspace, Asset,
                                    exclude_uid=obj.uid, skip_unique=True, skip_reference=True), obj.key


# --- the real workbook, when it is there --------------------------------------------

@pytest.mark.skipif(not os.path.exists(REAL), reason="the EuPRAXIA workbook is not in docs/")
def test_the_real_workbook_reads_and_imports(db, workspace, facility):
    book = read_workbook(REAL)
    assert len(book.components) == 179
    assert len(book.work_packages) == 13 and len(book.zones) == 6 and len(book.areas) == 20
    result = import_pbs(db, workspace, book, facility, "EuPRAXIA PBS_ver2.xlsx")
    assert result.counts["components"] == 179 and result.counts["stations"] == 11
    e = edges(db, workspace)
    station = f"{facility}:STN:x-band-station-3"
    assert len([x for x in e if x[0] == station and x[1] == "composed of"]) == 15
    # Every component code in the file is one the import knows.
    assert not any("not one this import knows" in w for w in result.warnings)
    # Nothing in the file may be silently promoted to a number it never was.
    for obj in assets(db, workspace).values():
        schema = db.get(Schema, obj.schema_uid)
        assert not check_attributes(db, schema, obj.attributes, workspace, Asset,
                                    exclude_uid=obj.uid, skip_unique=True, skip_reference=True), obj.key


def test_with_a_shared_catalogue_only_the_beamlines_own_types_are_made_here(db, bare, facility):
    from app.packages.install import install
    from app.services import asset_types as at
    workspace = bare
    cat = f"pbs-cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=cat, name="Catalogue"))
    db.commit()
    install(db, cat, ["accelerator"], scope="global")
    install(db, workspace, ["accelerator"], catalogue_workspace_id=cat)
    db.commit()

    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx",
               catalogue_workspace_id=cat)
    made_here = {s.name for s in db.query(Schema).filter(Schema.workspace_id == workspace, Schema.applies_to == "objects")}
    assert made_here == set(at.BEAMLINE_TYPES)                    # no copy of the shared ones

    objs = assets(db, workspace)
    coupler = objs[f"{facility}:MHX3-I-WGS-BDC-001"]             # a shared type
    structure = objs[f"{facility}:INJ-A-ACC-SB3M-001"]           # this beamline's own
    assert coupler.schema_uid == at.type_uid(cat, "Directional Coupler")
    assert structure.schema_uid == at.type_uid(workspace, "Accelerating Structure")
    assert objs[f"{facility}:WP:WP-04"].schema_uid == at.type_uid(workspace, "Work Package")   # money stays here
    assert objs[f"{facility}:MHX3-I-WGS-BDC-001:PROC"].schema_uid == at.type_uid(workspace, "Procurement Record")
    assert objs[f"{facility}:AREA:MHX3"].schema_uid == at.type_uid(cat, "Area")


def test_an_import_into_a_workspace_without_the_catalogue_is_refused_and_writes_nothing(db, bare, facility):
    from app.packages.requirements import MissingPrerequisite
    with pytest.raises(MissingPrerequisite, match="Install accelerator first"):
        import_pbs(db, bare, read_workbook(workbook(GOOD)), facility, "x.xlsx")
    db.rollback()
    assert db.query(Schema).filter(Schema.workspace_id == bare).count() == 0
    assert not assets(db, bare)


def test_a_beamline_workspace_keeps_using_its_catalogue_without_being_told(db, bare, facility):
    from app.services import asset_types as at
    workspace = bare
    cat = f"pbs-cat-{secrets.token_hex(4)}"
    db.add(Workspace(id=cat, name="Catalogue"))
    db.commit()
    at.ensure_asset_types(db, cat, scope="global")
    at.ensure_asset_types(db, workspace, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    import_pbs(db, workspace, read_workbook(workbook(GOOD)), facility, "x.xlsx")   # no catalogue given
    assert db.query(Schema).filter(Schema.workspace_id == workspace).count() == len(at.BEAMLINE_TYPES)
