"""The EPIK8s import with `infer_elements`: what the channels are for.

The point is the trade. The inference makes objects the file never states, so each
must say it is inferred and why, must never overwrite what a person has since entered,
and must not exist at all unless asked for.
"""
import secrets

import pytest
import yaml

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset, Relation
from app.models.import_job import ImportJob
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import asset_types as at
from app.services.attribute_validation import effective_attributes
from app.services.epik8s_import import _Importer

CONFIG = """
beamline: BEAMLINE
iocDefaults:
  agilent-vac: {devgroup: vac, devtype: ipcmini, devfunc: ion, asset: "https://servicedesk.infn.it/x?objectId=129491"}
  caenels: {devgroup: mag, devtype: histar}
  adcamera: {devgroup: cam, devtype: camera}
  libera-sppp: {devgroup: bpm, devtype: libera-spp}
  libera-llrf: {devgroup: rf, devtype: llrf}
  ppt: {devgroup: modulator}
epicsConfiguration:
  iocs:
    vac-gunvpc:
      iocprefix: SPARC:VAC
      iocroot: GUNVPC
      template: agilent-vac
      iocparam: [{name: server, value: scsparcsipmxa001.lnf.infn.it}, {name: port, value: 4003}]
      devices: [{name: GUNSIP01, channel: 146}, {name: GUNNEG01, channel: 148}]
    histar:
      iocprefix: SPARC:MAG:HISTAR
      template: caenels
      zones: LINAC
      ps: {current: {max: 30}}
      devices:
        - {name: GUNQUA01, ip: 192.168.0.28}
        - {name: AC1VCR01, ip: 192.168.0.24}
    cameras:
      iocprefix: SPARC:CAM
      template: adcamera
      devices:
        - {name: AC101, devtype: Basler-scA640-70gm, id: 192.168.110.26, asset: "https://servicedesk.infn.it/y?objectId=145351"}
        - {name: SIM01, devtype: camerasim}
    ac1bpm01:
      iocprefix: AC1BPM01
      template: libera-sppp
      host: bdsparcac1bpm001.lnf.infn.it
      zones: [LINAC]
    llrfs01:
      iocprefix: SPARC:LLRF1
      template: libera-llrf
      host: plsparcllrfs001.lnf.infn.it
      devices: [{name: ad1, channel: 3}, {name: ad2, channel: 4}]
    ppt-mod1:
      iocprefix: SPARC:MOD1
      template: ppt
    tml-ch1:
      iocprefix: SPARC:MOT:TML
      template: motor
      devgroup: mot
      devices: [{name: C1M1V, axid: 1}]
"""


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
def tag():
    return f"T{secrets.token_hex(3)}".upper()


@pytest.fixture()
def split(db):
    """A catalogue workspace and a beamline hanging from it: how the hub is really used."""
    cat, ws = f"inf-cat-{secrets.token_hex(4)}", f"inf-{secrets.token_hex(4)}"
    db.add_all([Workspace(id=cat, name="Catalogue"), Workspace(id=ws, name="Beamline")])
    db.commit()
    at.ensure_asset_types(db, cat, scope="global")
    at.ensure_asset_types(db, ws, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    yield cat, ws
    # Leave nothing behind: every other test searches the whole database, and a hundred
    # cameras from these imports would push the fixtures of the ones that look for one.
    db.rollback()
    for workspace in (ws, cat):
        db.query(Relation).filter(Relation.workspace_id == workspace).delete()
        db.query(Asset).filter(Asset.workspace_id == workspace).delete()
        db.query(ImportJob).filter(ImportJob.workspace_id == workspace).delete()
        db.query(Schema).filter(Schema.workspace_id == workspace).delete()
        db.query(Workspace).filter(Workspace.id == workspace).delete()
    db.commit()


def run(db, ws, tag, infer=True, text=CONFIG):
    values = yaml.safe_load(text.replace("BEAMLINE", tag))
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, "test@main:deploy/values.yaml", infer_elements=infer)
    importer.ensure_types()
    importer.run(values, True)
    db.commit()
    return importer


def objects(db, ws):
    return {a.key: a for a in db.query(Asset).filter(Asset.workspace_id == ws)}


def edges(db, ws):
    names = {a.uid: a.key for a in db.query(Asset).filter(Asset.workspace_id == ws)}
    return {(names[r.from_asset_uid], r.relation_type, names[r.to_asset_uid])
            for r in db.query(Relation).filter(Relation.workspace_id == ws)}


def of_type(db, ws, name):
    return sorted(k for k, a in objects(db, ws).items() if a.type == name)


# --- off by default -------------------------------------------------------------------------------------

def test_nothing_is_inferred_unless_asked_for(db, split, tag):
    _, ws = split
    importer = run(db, ws, tag, infer=False)
    types = {a.type for a in objects(db, ws).values()}
    assert not types & {"Ion Pump", "Power Supply", "Camera", "Quadrupole", "Digitizer"}
    assert importer.counts["inferred_assets"] == 0 and not importer.not_inferred


# --- what is made ----------------------------------------------------------------------------------------

def test_the_channels_become_the_things_they_drive(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    assert of_type(db, ws, "Ion Pump") == [f"{tag}-AST-vac-gunvpc-GUNSIP01"]
    assert of_type(db, ws, "NEG Cartridge") == [f"{tag}-AST-vac-gunvpc-GUNNEG01"]
    assert of_type(db, ws, "Power Supply") == [f"{tag}-AST-histar-AC1VCR01", f"{tag}-AST-histar-GUNQUA01"]
    assert of_type(db, ws, "Camera") == [f"{tag}-AST-cameras-AC101"]        # the simulator is not one
    assert of_type(db, ws, "Quadrupole") == [f"{tag}-ELM-GUNQUA01"]
    assert of_type(db, ws, "Corrector") == [f"{tag}-ELM-AC1VCR01"]


def test_an_ioc_that_is_one_unit_is_one_asset_whatever_channels_it_lists(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    assert of_type(db, ws, "Low-Level RF Unit") == [f"{tag}-AST-llrfs01"]     # ad1 and ad2 are its channels
    assert of_type(db, ws, "Modulator") == [f"{tag}-AST-ppt-mod1"]
    assert of_type(db, ws, "Digitizer") == [f"{tag}-AST-ac1bpm01"]
    assert of_type(db, ws, "Beam Position Monitor") == [f"{tag}-ELM-AC1BPM01"]


def test_what_a_channel_drives_is_linked_from_the_channel(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    e = edges(db, ws)
    assert (f"{tag}-DEV-vac-gunvpc-GUNSIP01", "acts on", f"{tag}-AST-vac-gunvpc-GUNSIP01") in e
    assert (f"{tag}-DEV-histar-GUNQUA01", "acts on", f"{tag}-AST-histar-GUNQUA01") in e
    # a supply powers its magnet
    assert (f"{tag}-AST-histar-GUNQUA01", "powers", f"{tag}-ELM-GUNQUA01") in e
    # a unit is driven by its IOC; a BPM element is realised by its electronics
    assert (f"{tag}-IOC-llrfs01", "drives", f"{tag}-AST-llrfs01") in e
    assert (f"{tag}-IOC-ac1bpm01", "drives", f"{tag}-AST-ac1bpm01") in e
    assert (f"{tag}-ELM-AC1BPM01", "realized by", f"{tag}-AST-ac1bpm01") in e


def test_what_the_file_says_about_a_supply_and_a_camera_is_kept(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    objs = objects(db, ws)
    psu = objs[f"{tag}-AST-histar-GUNQUA01"].attributes
    assert psu["current_max"] == 30.0 and psu["manufacturer"] == "CAEN ELS" and psu["model"] == "Hi-Star"
    cam = objs[f"{tag}-AST-cameras-AC101"].attributes
    assert (cam["manufacturer"], cam["model"]) == ("Basler", "scA640-70gm")
    assert cam["inventory_url"].endswith("objectId=145351")                  # the device's own `asset:` link
    element = objs[f"{tag}-ELM-AC1VCR01"].attributes
    assert element["plane"] == "V" and element["zone"] == ["LINAC"] and element["lattice_name"] == "AC1VCR01"


def test_every_inferred_object_says_it_is_and_why(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    inferred = [a for a in objects(db, ws).values() if "-AST-" in a.key or "-ELM-" in a.key]
    assert inferred
    for obj in inferred:
        assert obj.attributes["argus_keywords"] == ["inferred"], obj.key
        assert "Inferred by the control-configuration import" in obj.attributes["description"]
        assert obj.attributes["argus_facility"] == tag and obj.attributes["argus_source"] == "epik8s"
    assert "channel GUNSIP01" in objects(db, ws)[f"{tag}-AST-vac-gunvpc-GUNSIP01"].attributes["description"]


def test_what_no_rule_covers_is_counted_and_not_guessed_at(db, split, tag):
    _, ws = split
    importer = run(db, ws, tag)
    # the simulated camera: deliberately not hardware
    assert importer.not_inferred == {"cam/adcamera": 1}
    assert not [k for k in objects(db, ws) if "SIM01" in k and ":AST:" in k]
    assert not [k for k in objects(db, ws) if "SIM01" in k and ":AST:" in k]


def test_the_counts_say_what_was_inferred(db, split, tag):
    _, ws = split
    counts = run(db, ws, tag).counts
    assert counts["inferred_assets"] == 9 and counts["inferred_elements"] == 3
    assert counts["inferred Power Supply"] == 2 and counts["inferred Quadrupole"] == 1
    assert counts["inferred Motor Axis"] == 1


# --- the types ---------------------------------------------------------------------------------------------

def test_assets_are_of_the_shared_types_and_elements_of_the_beamlines_own(db, split, tag):
    cat, ws = split
    run(db, ws, tag)
    objs = objects(db, ws)
    assert objs[f"{tag}-AST-vac-gunvpc-GUNSIP01"].schema_uid == at.type_uid(cat, "Ion Pump")
    assert objs[f"{tag}-AST-histar-GUNQUA01"].schema_uid == at.type_uid(cat, "Power Supply")
    assert objs[f"{tag}-ELM-GUNQUA01"].schema_uid == at.type_uid(ws, "Quadrupole")


def test_every_key_it_writes_is_declared_by_the_type_it_writes_to(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    undeclared = {}
    for obj in objects(db, ws).values():
        declared = {a["key"] for a in effective_attributes(db, db.get(Schema, obj.schema_uid))}
        missing = set(obj.attributes) - declared
        if missing:
            undeclared.setdefault(obj.type, set()).update(missing)
    assert not undeclared, undeclared


def test_without_the_catalogues_types_it_says_so_and_writes_nothing(db, tag):
    ws = f"inf-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Bare"))
    db.commit()
    with pytest.raises(ValueError, match="Seed the types first"):
        run(db, ws, tag)
    db.rollback()
    assert not db.query(Asset).filter(Asset.workspace_id == ws).count()


# --- a person's word outranks a guess ----------------------------------------------------------------------------

def test_what_somebody_has_since_entered_survives_a_re_read(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    pump = objects(db, ws)[f"{tag}-AST-vac-gunvpc-GUNSIP01"]
    pump.attributes = {**pump.attributes, "serial": "IPC-77", "condition": "Good",
                       "description": "Replaced in 2025 after the arc."}
    db.commit()
    run(db, ws, tag)
    db.expire_all()
    again = objects(db, ws)[f"{tag}-AST-vac-gunvpc-GUNSIP01"].attributes
    assert again["serial"] == "IPC-77" and again["condition"] == "Good"
    assert again["description"] == "Replaced in 2025 after the arc."        # not put back to the inference


def test_running_it_twice_creates_nothing(db, split, tag):
    _, ws = split
    run(db, ws, tag)
    n_objects, n_edges = len(objects(db, ws)), len(edges(db, ws))
    again = run(db, ws, tag)
    assert again.counts["relations"] == 0
    assert (len(objects(db, ws)), len(edges(db, ws))) == (n_objects, n_edges)


def test_turning_it_on_after_an_import_adds_to_it_without_disturbing_it(db, split, tag):
    _, ws = split
    run(db, ws, tag, infer=False)
    before = {k: (a.type, {n: v for n, v in a.attributes.items() if n != "imported_at"})
              for k, a in objects(db, ws).items()}
    run(db, ws, tag, infer=True)
    after = objects(db, ws)
    for key, (kind, attrs) in before.items():
        assert after[key].type == kind, key
        assert {n: v for n, v in after[key].attributes.items() if n != "imported_at"} == attrs, key
    assert of_type(db, ws, "Ion Pump")                                    # and now it has the pumps


# --- ELI: a unit with several channels ---------------------------------------------------------------------------------

UNITS = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    bdelilibera03:
      template: libera-spe
      devgroup: diag
      devtype: bpm
      iocprefix: LEL:DIA:BPM01
      host: bdelilibera03.lnf.infn.it
      zones: [LEL]
      devices: [{name: BPM01}, {name: BPM02}]
    scandicat-mod:
      template: scandinova-scandicat-mod
      devgroup: modulator
      devtype: ppt
      devices: [{name: MOD01}, {name: MOD02}]
"""


def test_a_multi_channel_bpm_unit_is_one_digitizer_and_a_bpm_per_channel(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=UNITS)
    assert of_type(db, ws, "Digitizer") == [f"{tag}-AST-bdelilibera03"]
    assert of_type(db, ws, "Beam Position Monitor") == [f"{tag}-ELM-BPM01", f"{tag}-ELM-BPM02"]
    e = edges(db, ws)
    for bpm in ("BPM01", "BPM02"):
        assert (f"{tag}-ELM-{bpm}", "realized by", f"{tag}-AST-bdelilibera03") in e
        assert (f"{tag}-DEV-bdelilibera03-{bpm}", "acts on", f"{tag}-ELM-{bpm}") in e
    assert objects(db, ws)[f"{tag}-ELM-BPM01"].attributes["zone"] == ["LEL"]


def test_a_modulator_ioc_with_channels_makes_a_modulator_per_channel(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=UNITS)
    assert of_type(db, ws, "Modulator") == [f"{tag}-AST-scandicat-mod-MOD01", f"{tag}-AST-scandicat-mod-MOD02"]
    assert (f"{tag}-DEV-scandicat-mod-MOD01", "acts on", f"{tag}-AST-scandicat-mod-MOD01") in edges(db, ws)


def test_the_unit_types_are_declared_and_the_channels_say_they_are_inferred(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=UNITS)
    for key in (f"{tag}-ELM-BPM01", f"{tag}-AST-bdelilibera03", f"{tag}-AST-scandicat-mod-MOD01"):
        obj = objects(db, ws)[key]
        declared = {a["key"] for a in effective_attributes(db, db.get(Schema, obj.schema_uid))}
        assert set(obj.attributes) <= declared, (key, set(obj.attributes) - declared)
        assert obj.attributes["argus_keywords"] == ["inferred"]



# --- motors: axes, screens and mirrors ---------------------------------------------------------------------

MOTION = """
beamline: BEAMLINE
iocDefaults:
  motor: {devgroup: mot}
  adcamera: {devgroup: cam, devtype: camera}
epicsConfiguration:
  iocs:
    tml-ch1:
      iocprefix: SPARC:MOT:TML
      template: motor
      devtype: technosoft-asyn
      devices:
        - {name: AC1FLG01, axid: 3, poi: [{name: YAG, value: 670000}, {name: calibration, value: 550000}]}
        - {name: GUNFLG01, axid: 10, poi: [{name: YAG, value: 688640}, {name: mirror, value: 1688320}]}
        - {name: GUNSOLH1, axid: 2}
    pollux-enea:
      iocprefix: SPARC:MOT:FEL
      template: motor
      devtype: pollux
      devices: [{name: FELFLG01A, axid: 1}, {name: FELFLG01B, axid: 2}]
    pollux-chain-fi-01:
      iocprefix: EUAPS:FIRCK2:W:CTR
      template: motor
      devtype: pollux
      devices:
        - {name: FI4-HMN-01, axid: 5, zones: [FI, FI4, FI4_main]}
        - {name: FI4-VMN-01, axid: 6, zones: [FI, FI4, FI4_main]}
        - {name: FI4-HMN-02, axid: 7}
        - {name: FI8-SLT-01, axid: 1, poi: [{name: YAG-PICCOLO, value: 123}]}
        - {name: FI8-PRH-01, axid: 5}
        - {name: FI8-PRV-01, axid: 6}
        - {name: FI2-MPB-001, axid: 0}
    accameras:
      iocprefix: SPARC:CAM
      template: adcamera
      devices: [{name: AC101}, {name: FEL01}, {name: UTL01}]
"""


def test_every_axis_of_a_motor_controller_is_a_motor_axis(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=MOTION)
    axes = of_type(db, ws, "Motor Axis")
    assert f"{tag}-AST-tml-ch1-GUNSOLH1" in axes and f"{tag}-AST-pollux-chain-fi-01-FI8-SLT-01" in axes
    obj = objects(db, ws)[f"{tag}-AST-tml-ch1-GUNSOLH1"]
    assert obj.attributes["axis_id"] == "2" and obj.attributes["argus_system"] == "Motion"
    # An axis whose code says nothing gets no element: what it moves is not in the file.
    e = edges(db, ws)
    assert (f"{tag}-DEV-tml-ch1-GUNSOLH1", "acts on", f"{tag}-AST-tml-ch1-GUNSOLH1") in e
    assert not [k for k in e if k[1] == "composed of"
                and (k[2].endswith(":FI8-SLT-01") or k[2].endswith(":FI2-MPB-001"))]
    assert f"{tag}-AST-pollux-chain-fi-01-FI2-MPB-001" in axes


def test_a_flag_is_a_screen_station_composed_of_its_actuator(db, split, tag):
    cat, ws = split
    run(db, ws, tag, text=MOTION)
    objs, e = objects(db, ws), edges(db, ws)
    assert of_type(db, ws, "Screen Station") == [
        f"{tag}-ELM-AC1FLG01", f"{tag}-ELM-FELFLG01A", f"{tag}-ELM-FELFLG01B", f"{tag}-ELM-GUNFLG01"]
    assert f"{tag}-AST-tml-ch1-AC1FLG01" in of_type(db, ws, "Actuator")
    assert (f"{tag}-ELM-AC1FLG01", "composed of", f"{tag}-AST-tml-ch1-AC1FLG01") in e
    station = objs[f"{tag}-ELM-AC1FLG01"].attributes
    assert station["insertion_positions"] == ["YAG", "calibration"] and station["lattice_name"] == "AC1FLG01"
    assert objs[f"{tag}-AST-tml-ch1-AC1FLG01"].attributes["position_labels"] == ["YAG", "calibration"]
    assert objs[f"{tag}-ELM-AC1FLG01"].schema_uid == at.type_uid(ws, "Screen Station")


def test_a_screen_is_composed_of_the_camera_its_name_pairs_it_with(db, split, tag):
    _, ws = split
    importer = run(db, ws, tag, text=MOTION)
    e = edges(db, ws)
    assert (f"{tag}-ELM-AC1FLG01", "composed of", f"{tag}-AST-accameras-AC101") in e
    # two flags of a pair share their camera
    assert (f"{tag}-ELM-FELFLG01A", "composed of", f"{tag}-AST-accameras-FEL01") in e
    assert (f"{tag}-ELM-FELFLG01B", "composed of", f"{tag}-AST-accameras-FEL01") in e
    # no camera by that name, so none is invented; and a camera with no flag is not a screen
    assert not [k for k in e if k[0] == f"{tag}-ELM-GUNFLG01" and k[1] == "composed of"
                and ":AST:accameras:" in k[2]]
    assert not [k for k in e if k[1] == "composed of" and k[2].endswith(":accameras:UTL01")]
    assert importer.counts["screens_paired"] == 3


def test_an_h_v_pair_of_axes_is_one_mirror(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=MOTION)
    objs, e = objects(db, ws), edges(db, ws)
    assert of_type(db, ws, "Mirror") == [
        f"{tag}-ELM-FI4-MMIR-001", f"{tag}-ELM-FI4-MMIR-002", f"{tag}-ELM-FI8-PAR-001"]
    for axis in ("FI4-HMN-01", "FI4-VMN-01"):
        assert (f"{tag}-ELM-FI4-MMIR-001", "composed of", f"{tag}-AST-pollux-chain-fi-01-{axis}") in e
    # the second mirror has one axis so far, and is still its own mirror
    assert (f"{tag}-ELM-FI4-MMIR-002", "composed of", f"{tag}-AST-pollux-chain-fi-01-FI4-HMN-02") in e
    # the parabolic mirror is one mirror with a horizontal and a vertical axis
    for axis in ("FI8-PRH-01", "FI8-PRV-01"):
        assert (f"{tag}-ELM-FI8-PAR-001", "composed of", f"{tag}-AST-pollux-chain-fi-01-{axis}") in e
    assert "horizontal axis of the main-laser mirror FI4-MMIR-001" in \
        objs[f"{tag}-AST-pollux-chain-fi-01-FI4-HMN-01"].attributes["description"]
    main, parabolic = objs[f"{tag}-ELM-FI4-MMIR-001"].attributes, objs[f"{tag}-ELM-FI8-PAR-001"].attributes
    assert main["zone"] == ["FI", "FI4", "FI4_main"] and main["beam"] == "main"
    assert parabolic["mirror_kind"] == "Parabolic" and "beam" not in parabolic


def test_motion_objects_are_declared_and_say_they_are_inferred(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=MOTION)
    undeclared = {}
    for obj in objects(db, ws).values():
        declared = {a["key"] for a in effective_attributes(db, db.get(Schema, obj.schema_uid))}
        missing = set(obj.attributes) - declared
        if missing:
            undeclared.setdefault(obj.type, set()).update(missing)
    assert not undeclared, undeclared
    for obj in objects(db, ws).values():
        if obj.type in ("Motor Axis", "Actuator", "Screen Station", "Mirror"):
            assert obj.attributes["argus_keywords"] == ["inferred"], obj.key


def test_motion_is_not_inferred_unless_asked_for(db, split, tag):
    _, ws = split
    run(db, ws, tag, infer=False, text=MOTION)
    assert not of_type(db, ws, "Motor Axis") and not of_type(db, ws, "Screen Station")


def test_running_the_motion_import_twice_creates_nothing(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=MOTION)
    before = (set(objects(db, ws)), edges(db, ws))
    again = run(db, ws, tag, text=MOTION)
    assert (set(objects(db, ws)), edges(db, ws)) == before
    assert again.counts["relations"] == 0


# --- the plant: cooling, timing and what gates RF --------------------------------------------------------------

PLANT = """
beamline: BEAMLINE
iocDefaults:
  smc: {devgroup: cool, devtype: smc}
  polyscience: {devgroup: cool, devtype: polyscience}
  mrf-pci-230: {devgroup: timing}
  adcamera: {devgroup: cam, devtype: camera}
  libera-llrf: {devgroup: rf, devtype: llrf}
  scandinova-scandicat-mod: {devgroup: modulator, devtype: ppt}
  agilent-vac: {devgroup: vac, devtype: 4uhv, devfunc: ion}
epicsConfiguration:
  iocs:
    chiller-smc:
      iocprefix: LEL:CHL
      template: smc
      devices: [{name: GUN}, {name: ACC01}, {name: BOCX}]
    chiller-poly-roof:
      iocprefix: LEL:CHL
      template: polyscience
      devices: [{name: MOD}]
    scandicat-mod:
      iocprefix: LEL:MOD:SCAT
      template: scandinova-scandicat-mod
      devices: [{name: MOD01}, {name: MOD02}]
    evg:
      iocprefix: LEL:TIM
      template: mrf-pci-230
      devices: [{name: TMG, devtype: evg230}]
    evr-a:
      iocprefix: LEL:TIM
      template: mrf-pci-230
      devices: [{name: EVR-LLRF, devtype: evr230}, {name: EVR-CAM, devtype: evr230}, {name: EVR-LAS, devtype: evr230},
                {name: "DIA:FCT01", devtype: m9210}]
    llrf01: {iocprefix: LEL-RF-LLRF01, template: libera-llrf, host: plelillrfs001.int.eli-np.ro}
    cams:
      iocprefix: LEL
      template: adcamera
      devices: [{name: "SCN01:CAM01"}, {name: "SCN02:CAM01"}]
    vpcon01:
      iocprefix: LEL:VAC
      iocroot: VPCON01
      template: agilent-vac
      devices: [{name: IONP01, channel: 1}, {name: IONP02, channel: 2}]
    rf-conditioning-gun:
      iocprefix: SSRIP:RF:CONDITIONING01
      pump:
        - {name: "VPCON01:IONP01", prefix: "LEL:VAC:", suffix: ":PRES_RB", tsh: 1E-7}
        - {name: "VPCON01:IONP02", prefix: "LEL:VAC:", suffix: ":PRES_RB", tsh: 1E-7}
        - {name: "VPCON09:IONP99", prefix: "LEL:VAC:", suffix: ":PRES_RB", tsh: 1E-7}
"""


def test_a_chiller_cools_the_element_it_names_and_a_hall_chiller_every_modulator(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=PLANT)
    e = edges(db, ws)
    assert (f"{tag}-AST-chiller-smc-GUN", "cools", f"{tag}-ELM-GUN") in e
    assert (f"{tag}-AST-chiller-smc-ACC01", "cools", f"{tag}-ELM-ACC01") in e
    assert of_type(db, ws, "RF Gun") == [f"{tag}-ELM-GUN"]
    for mod in ("MOD01", "MOD02"):
        assert (f"{tag}-AST-chiller-poly-roof-MOD", "cools", f"{tag}-AST-scandicat-mod-{mod}") in e
    # a chiller whose target is not known cools nothing in the graph
    assert not [k for k in e if k[0] == f"{tag}-AST-chiller-smc-BOCX" and k[1] == "cools"]
    assert f"{tag}-AST-chiller-smc-BOCX" in of_type(db, ws, "Chiller")


def test_timing_receivers_are_timed_by_the_generator_and_trigger_what_their_names_say(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=PLANT)
    e = edges(db, ws)
    gen = f"{tag}-AST-evg-TMG"
    for receiver in ("EVR-LLRF", "EVR-CAM", "EVR-LAS"):
        assert (f"{tag}-AST-evr-a-{receiver}", "timed by", gen) in e
    assert (f"{tag}-AST-evr-a-EVR-LLRF", "triggers", f"{tag}-AST-llrf01") in e
    for cam in ("SCN01:CAM01", "SCN02:CAM01"):
        assert (f"{tag}-AST-evr-a-EVR-CAM", "triggers", f"{tag}-AST-cams-{cam.replace(':', '-')}") in e
    assert not [k for k in e if k[0] == f"{tag}-AST-evr-a-EVR-LAS" and k[1] == "triggers"]
    assert not [k for k in objects(db, ws) if "FCT01" in k and ":AST:" in k]


def test_two_generators_leave_the_receivers_untied_because_nothing_says_which(db, split, tag):
    _, ws = split
    text = PLANT.replace("devices: [{name: TMG, devtype: evg230}]",
                         "devices: [{name: TMG, devtype: evg230}, {name: TMG2, devtype: evg230}]")
    run(db, ws, tag, text=text)
    assert not [k for k in edges(db, ws) if k[1] == "timed by"]


def test_the_pumps_an_rf_conditioning_ioc_watches_gate_it(db, split, tag):
    """The file says RF is not raised above a pressure: RF depends on those pumps."""
    _, ws = split
    importer = run(db, ws, tag, text=PLANT)
    e = edges(db, ws)
    ioc = f"{tag}-IOC-rf-conditioning-gun"
    for pump in ("IONP01", "IONP02"):
        assert (ioc, "enabled by", f"{tag}-DEV-vpcon01-{pump}") in e                     # what the file states
        assert (ioc, "enabled by", f"{tag}-AST-vpcon01-{pump}") in e                     # the pump itself
    assert importer.counts["gates"] == 2 and importer.counts["gates_unresolved"] == 1     # VPCON09 is not there
    assert objects(db, ws)[ioc].attributes["permit_conditions"] == [
        "LEL:VAC:VPCON01:IONP01:PRES_RB < 1E-7", "LEL:VAC:VPCON01:IONP02:PRES_RB < 1E-7"]


def test_without_inference_the_gate_reaches_the_device_and_not_an_invented_pump(db, split, tag):
    _, ws = split
    run(db, ws, tag, infer=False, text=PLANT)
    e = edges(db, ws)
    assert (f"{tag}-IOC-rf-conditioning-gun", "enabled by", f"{tag}-DEV-vpcon01-IONP01") in e
    assert not [k for k in e if k[1] == "enabled by" and ":AST:" in k[2]]


def test_every_relation_the_import_writes_has_a_meaning_for_a_failure(db, split, tag):
    from app.services.causal_model import classify
    _, ws = split
    run(db, ws, tag, text=PLANT)
    run(db, ws, f"{tag}X", text=MOTION)
    written = {t for _, t, _ in edges(db, ws)}
    assert written and not [t for t in written if classify(t) is None], written


# --- the real configurations, walked ---------------------------------------------------------------------------

import os

from app.services.causal_model import classify
from app.services.root_cause import impact_of, root_causes

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")


def _real(repo):
    path = os.path.join(_ROOT, repo, "deploy", "values.yaml")
    if not os.path.exists(path):
        pytest.skip(f"{repo} is not next to this repository")
    return open(path).read()


@pytest.mark.parametrize("repo", ["epik8-sparc", "epik8s-btf", "epik8s-euaps", "epik8s-eli"])
def test_every_relation_a_real_configuration_makes_means_something_to_a_failure(db, split, tag, repo):
    _, ws = split
    importer = run(db, ws, tag, text=_real(repo))
    written = {t for _, t, _ in edges(db, ws)}
    assert written and not [t for t in written if classify(t) is None], written
    assert importer.counts["gates_unresolved"] == 0            # every pump a conditioning IOC names is found


def test_a_stopped_serial_converter_in_sparc_blinds_its_pumps_and_stops_the_rf_that_watches_them(db, split, tag):
    _, ws = split
    importer = run(db, ws, tag, text=_real("epik8-sparc"))
    assert importer.counts["gates"] >= 20
    moxa = db.query(Asset).filter(Asset.workspace_id == ws, Asset.key.like("NET-%SCSPARCSIPMXA001")).one()
    result = impact_of(db, ws, moxa.uid)
    assert result["by_loss"].get("control", 0) >= 30 and result["by_loss"].get("permit", 0) >= 1
    assert result["by_type"].get("Ion Pump", 0) >= 10
    # what it must not do: the pumps are readable no more, not stopped, so no element loses function
    assert not [a for a in result["affected"] if "function" in a["losses"]]


def test_two_pump_readouts_lost_behind_different_iocs_point_at_the_converter_they_share(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=_real("epik8-sparc"))
    one, two = "SPARC-DEV-vac-gunvpc-GUNSIP01", "SPARC-DEV-vac-kly02vpc-W2KSIP03"   # the file says `beamline: sparc`
    result = root_causes(db, ws, [one, two], symptom_kind={one: "control", two: "control"})
    assert result["candidates"][0]["key"].endswith("SCSPARCSIPMXA001") and result["candidates"][0]["fit"] == 1.0


def test_the_eli_event_generator_reaches_every_receiver_and_what_they_trigger(db, split, tag):
    _, ws = split
    run(db, ws, tag, text=_real("epik8s-eli"))
    generator = db.query(Asset).filter(Asset.workspace_id == ws, Asset.key.like("%-AST-plelievg001-TMG")).one()
    result = impact_of(db, ws, generator.uid)
    assert result["by_type"].get("Timing Module", 0) >= 7             # every receiver
    assert result["by_type"].get("Camera", 0) >= 6 and result["by_type"].get("Low-Level RF Unit", 0) >= 1
    assert all(a["via_inference"] for a in result["affected"])       # every object here was inferred
