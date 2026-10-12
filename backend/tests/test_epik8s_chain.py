"""The whole chain an EPIK8s configuration implies, as import options: the controllers between lines and
what they run, the converters' ports in the IT workspace, the inventory linked instead of duplicated, and
the AI's proposals for the channels no rule recognises."""
import json
import secrets
import uuid

import pytest

from app.db import SessionLocal
from app.ledger import control_binding
from app.ledger import service
from app.models.asset import Asset, Relation
from app.models.import_job import ImportJob
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import asset_types as at
from app.services import epik8s_import

CONFIG = """
beamline: BEAMLINE
iocDefaults:
  agilent-vac: {devgroup: vac, devtype: ipcmini, devfunc: ion}
  tpg: {devgroup: vac, devtype: tpg366}
  odd: {devgroup: xyz, template: odd}
epicsConfiguration:
  iocs:
    vac-ipc:
      iocprefix: EUAPS:VAC
      template: agilent-vac
      iocparam: [{name: server, value: scflameprmxavac002.lnf.infn.it}, {name: port, value: 4003}]
      devices: [{name: GUNSIP01, channel: 1}, {name: GUNSIP02, channel: 2}]
    vgc-tpg366-fi-01:
      iocprefix: EUAPS:VAC
      template: tpg
      iocparam: [{name: server, value: scflameprmxavac002.lnf.infn.it}, {name: port, value: 4004}]
      devices: [{name: FI31VUG01, channel: 1}, {name: FI32VUG01, channel: 2}]
    odd-ioc:
      iocprefix: EUAPS:ODD
      template: odd
      devices: [{name: ZZZ01}]
"""


@pytest.fixture()
def world(monkeypatch):
    t = secrets.token_hex(3)
    tag, ws, it = f"T{t}".upper(), f"chain-{t}", f"chain-it-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=w, name=w) for w in (ws, it)])
    db.flush()
    at.ensure_asset_types(db, ws)
    gauge_type = db.query(Schema).filter(Schema.workspace_id == ws, Schema.name == "Vacuum Gauge").one()
    # The inventory already holds one of the gauges, under its tag.
    inv = str(uuid.uuid4())
    service.create_record(db, ws, "test", uid=inv, schema_uid=gauge_type.uid, key=f"INV-{t}", name="FI31-V-VUG-FR-001",
                          type_name="Vacuum Gauge", attributes={})
    db.add(LLMConfig(workspace_id=ws, base_url="https://gateway.example/v1", model="m-1", enabled=True,
                     last_check_ok=True))
    db.commit()
    db.close()
    monkeypatch.setattr(epik8s_import, "_fetch", lambda *a, **k: CONFIG.replace("BEAMLINE", tag))
    monkeypatch.setattr(epik8s_import, "_resolve_commit", lambda *a, **k: "abc123")
    yield {"tag": tag, "ws": ws, "it": it, "inv": inv}
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    for w in (ws, it):
        allow_purge(db)
        db.delete(db.get(Workspace, w))
        db.commit()
    db.query(LLMConfig).filter(LLMConfig.workspace_id == ws).delete()
    db.commit()
    db.close()


def run(w, **options):
    db = SessionLocal()
    uid = str(uuid.uuid4())
    db.add(ImportJob(uid=uid, workspace_id=w["ws"], source="epik8s"))
    db.commit()
    db.close()
    epik8s_import.run_epik8s_import(uid, w["ws"], "github", "https://git.example/x", None, **options)
    db = SessionLocal()
    job = db.get(ImportJob, uid)
    assert job.status == "completed", job.error
    counts = dict(job.counts)
    db.close()
    return counts


def names_and_edges(ws_ids):
    db = SessionLocal()
    names = {a.uid: a.name for a in db.query(Asset)}
    edges = {(names.get(r.from_asset_uid), r.relation_type, names.get(r.to_asset_uid))
             for r in db.query(Relation).filter(Relation.workspace_id.in_(ws_ids))}
    db.close()
    return edges


def test_controllers_ports_and_the_inventory_first(world):
    w = world
    counts = run(w, infer_elements=True, infer_controllers=True, link_inventory=True, it_workspace=w["it"])
    assert counts["inferred_controllers"] == 2 and counts["linked_to_inventory"] == 1
    assert counts["ports"] == 2 and counts["inventory_link_proposals"] == 1
    e = names_and_edges([w["ws"], w["it"]])
    # The IPCMini powers the two ion pumps and is reached through the Moxa's Access Point.
    assert ("vac-ipc controller", "powers", "GUNSIP01 Ion Pump") in e
    assert ("vac-ipc controller", "reached through", "scflameprmxavac002") in e
    # The TPG 366 powers the gauge it got inferred; the other one is the inventory's, linked by proposal.
    assert ("vgc-tpg366-fi-01 controller", "powers", "FI32VUG01 Vacuum Gauge") in e
    assert not any(n == "FI31VUG01 Vacuum Gauge" for _, _, n in e)                     # no inferred twin
    pending = SessionLocal()
    proposals = control_binding.proposals(pending, w["ws"])
    pending.close()
    assert {(p["subject"]["name"], p["target"]["name"]) for p in proposals} == {("FI31VUG01", "FI31-V-VUG-FR-001")}
    # The Moxa's ports, in the IT workspace: 4003 is P3, 4004 is P4.
    assert ("scflameprmxavac002 P3", "port of", "scflameprmxavac002") in e
    assert ("scflameprmxavac002 P4", "port of", "scflameprmxavac002") in e
    db = SessionLocal()
    ctl = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.name == "vgc-tpg366-fi-01 controller").one()
    assert ctl.type == "Vacuum Controller" and ctl.attributes["model"] == "TPG 366" and ctl.attributes["n_channels"] == 2
    db.close()
    # A second read changes nothing.
    again = run(w, infer_elements=True, infer_controllers=True, link_inventory=True, it_workspace=w["it"])
    assert again["ports"] == 2
    assert names_and_edges([w["ws"], w["it"]]) == e


def test_the_ai_proposes_what_unrecognised_channels_drive_and_nothing_is_confirmed(world, monkeypatch):
    w = world
    seen = []

    def complete(endpoint, system, user, max_tokens=512, extra=None):
        seen.append(user)
        return json.dumps({"channels": [{"id": 1, "type": "Chiller", "confidence": 0.7, "reason": "odd cooling unit"}]})

    monkeypatch.setattr("app.services.llm.complete", complete)
    counts = run(w, infer_elements=True, ai_unrecognised=True)
    assert counts["ai_asked"] == 1 and counts["ai_proposed"] == 1
    assert "ZZZ01" in seen[0] and "GUNSIP01" not in seen[0]                         # only what no rule knew
    db = SessionLocal()
    unit = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.name == "ZZZ01 Chiller").one()
    assert unit.type == "Chiller" and unit.record_status == "Provisional"            # a proposal, not a record
    device = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.name == "ZZZ01").one()
    assert db.query(Relation).filter(Relation.from_asset_uid == device.uid,
                                     Relation.relation_type == "acts on").count() == 0
    db.close()


# --- a workspace nobody seeded (bugs/importing-epik8s.txt) ---------------------------------------------

@pytest.fixture()
def unseeded(monkeypatch):
    """A beamline workspace with no object types, next to a catalogue holding the shared (global) set: what
    a workspace created in the web app looks like before anyone runs the seeder."""
    t = secrets.token_hex(3)
    tag, ws, cat = f"T{t}".upper(), f"bare-{t}", f"cat-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=w, name=w) for w in (ws, cat)])
    db.flush()
    at.ensure_asset_types(db, cat, scope=at.SCOPE_GLOBAL)
    db.commit()
    db.close()
    monkeypatch.setattr(epik8s_import, "_fetch", lambda *a, **k: CONFIG.replace("BEAMLINE", tag))
    monkeypatch.setattr(epik8s_import, "_resolve_commit", lambda *a, **k: "abc123")
    yield {"tag": tag, "ws": ws, "cat": cat}
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    for w in (ws, cat):
        allow_purge(db)
        db.delete(db.get(Workspace, w))
        db.commit()
    db.close()


def _fails(w, **options) -> str:
    db = SessionLocal()
    uid = str(uuid.uuid4())
    db.add(ImportJob(uid=uid, workspace_id=w["ws"], source="epik8s"))
    db.commit()
    db.close()
    epik8s_import.run_epik8s_import(uid, w["ws"], "github", "https://git.example/x", None, **options)
    db = SessionLocal()
    job = db.get(ImportJob, uid)
    db.close()
    assert job.status == "failed"
    return job.error or ""


def _install(w, catalogue=None):
    from app.packages.install import install
    db = SessionLocal()
    install(db, w["ws"], ["accelerator"], catalogue_workspace_id=catalogue)
    db.commit()
    db.close()


def test_an_import_into_a_workspace_without_the_catalogue_imports_nothing_and_says_what_to_install(unseeded):
    """Imports no longer install the catalogue behind the workspace's back (the old fallback adopted the only
    catalogue there was, or put the whole of it in the workspace): the workspace is told to install it."""
    error = _fails(unseeded, infer_elements=True)
    assert "accelerator catalogue" in error and "Install accelerator first" in error
    db = SessionLocal()
    assert db.query(Schema).filter(Schema.workspace_id == unseeded["ws"]).count() == 0
    assert db.query(Asset).filter(Asset.workspace_id == unseeded["ws"]).count() == 0
    db.close()


def test_once_installed_against_its_catalogue_the_import_uses_the_shared_types_where_they_are(unseeded):
    _install(unseeded, catalogue=unseeded["cat"])
    run(unseeded, infer_elements=True)
    db = SessionLocal()
    # Its own beamline types hang from the catalogue; the shared ones are used where they are.
    assert at.catalogue_of(db, unseeded["ws"]) == unseeded["cat"]
    usable = at.resolve_type_uids(db, unseeded["ws"])
    assert {"Quadrupole", "Dipole", "Beam Position Monitor", "IOC", "Power Supply"} <= set(usable)
    # a shared type (Power Supply) is used from the catalogue, not copied into the beamline
    assert db.query(Schema).filter(Schema.workspace_id == unseeded["ws"], Schema.name == "Power Supply").count() == 0
    assert db.query(Schema).filter(Schema.workspace_id == unseeded["ws"], Schema.name == "Quadrupole").count() == 1
    db.close()


def test_installing_against_a_catalogue_that_lacks_a_shared_type_says_which_and_applies_nothing(unseeded):
    """bugs/importing-epik8s.txt, second report: a catalogue lacking Observable. The fallback quietly added it
    to the catalogue workspace; now the catalogue is brought up to date by its own administrators."""
    from app.packages.install import PackageProblem, install
    db = SessionLocal()
    try:
        obs = db.query(Schema).filter(Schema.workspace_id == unseeded["cat"], Schema.name == "Observable").one()
        db.delete(obs)
        db.flush()
        with pytest.raises(PackageProblem, match="Observable"):
            install(db, unseeded["ws"], ["accelerator"], catalogue_workspace_id=unseeded["cat"])
    finally:
        db.rollback()
        db.close()


def test_a_workspace_seeded_before_the_record_began_imports_as_before(world):
    """The world fixture puts the catalogue in directly (as workspaces made before packages had it): the
    import records it as detected and goes ahead."""
    run(world, infer_elements=True)
    from app.packages.install import history
    db = SessionLocal()
    assert {(h.package_id, h.action) for h in history(db, world["ws"])} >= {("accelerator", "detected")}
    db.close()


# --- an overlay file (values-linac.yaml) -------------------------------------------------------------

BASE = """
beamline: BEAMLINE
namespace: ns-BEAMLINE
iocDefaults:
  caenels: {charturl: "https://github.com/infn-epics/ioc-chart.git", devgroup: mag}
epicsConfiguration:
  iocs:
    main-only: {template: caenels, devtype: fastps, iocprefix: MAIN:MAG, devices: [{name: PS, ip: 10.0.0.1}]}
"""

OVERLAY = """
epicsConfiguration:
  iocs:
    easy-linac-1:
      template: caenels
      devtype: easydriver
      iocprefix: LINAC:MAG:EASY
      devices:
        - {name: CHHLL023, ip: 192.168.190.190, port: 10001, zones: LINAC}
        - {name: CVVLL023, ip: 192.168.190.191, port: 10001, zones: LINAC}
"""


def test_an_overlay_takes_its_beamline_and_template_defaults_from_values_yaml(unseeded, monkeypatch):
    """bugs: values-linac.yaml has no `beamline` nor `iocDefaults`; imported alone it made a facility called
    "unknown" and inferred nothing, since its magnet supplies' devgroup is in values.yaml."""
    fetched = []

    def fetch(provider, repo, pat, branch, path):
        fetched.append(path)
        return {"deploy/values.yaml": BASE, "deploy/values-linac.yaml": OVERLAY}[path].replace(
            "BEAMLINE", unseeded["tag"].lower())
    monkeypatch.setattr(epik8s_import, "_fetch", fetch)
    _install(unseeded, catalogue=unseeded["cat"])
    run(unseeded, path="deploy/values-linac.yaml", infer_elements=True)
    assert fetched == ["deploy/values-linac.yaml", "deploy/values.yaml"]
    db = SessionLocal()
    job = db.query(ImportJob).filter(ImportJob.workspace_id == unseeded["ws"]).one()
    assert job.status == "completed", job.error
    tag = unseeded["tag"]
    keys = {a.key: a for a in db.query(Asset).filter(Asset.workspace_id == unseeded["ws"])}
    assert not any(k.startswith("UNKNOWN:") for k in keys)
    assert f"{tag}:IOC:easy-linac-1" in keys
    assert f"{tag}:IOC:main-only" not in keys                 # the base's own IOCs are its own import's
    # its own configuration record, beside (not over) the beamline's
    assert f"{tag}:CFG:values-linac" in keys and f"{tag}:CFG" not in keys
    assert job.counts["inferred_elements"] > 0                # caenels' devgroup came from values.yaml
    db.close()


def test_with_base_keeps_the_overlay_and_merges_template_defaults():
    base = {"beamline": "btf", "namespace": "n", "iocDefaults": {"ocem": {"devgroup": "mag", "devtype": "E642"},
                                                                  "motor": {"devgroup": "mot"}},
            "epicsConfiguration": {"iocs": {"a": {}}}, "nfsMounts": [{"name": "data"}]}
    overlay = {"iocDefaults": {"ocem": {"devtype": "E643"}}, "epicsConfiguration": {"iocs": {"b": {}}}}
    out = epik8s_import.with_base(overlay, base)
    assert out["beamline"] == "btf" and out["epicsConfiguration"] == {"iocs": {"b": {}}}
    assert out["iocDefaults"] == {"ocem": {"devgroup": "mag", "devtype": "E643"}}
    assert "nfsMounts" not in out
    assert epik8s_import.base_values_path("deploy/values.yaml", {}) is None
    assert epik8s_import.base_values_path("deploy/values-linac.yaml", {"beamline": "x"}) is None
    assert epik8s_import.base_values_path("deploy/values-linac.yaml", {}) == "deploy/values.yaml"


def test_two_files_ai_proposals_do_not_withdraw_each_other(world, monkeypatch):
    """values.yaml and values-linac.yaml shared one `ai-channels:` stream: each run's revision replaced the
    other file's proposals (or was held for retracting them all)."""
    w = world
    other = CONFIG.replace("odd-ioc", "odd-ioc2").replace("ZZZ01", "YYY01").replace("EUAPS:ODD", "EUAPS:ODD2")
    files = {"deploy/values.yaml": CONFIG, "deploy/values-linac.yaml": other}
    monkeypatch.setattr(epik8s_import, "_fetch",
                        lambda provider, repo, pat, branch, path: files[path].replace("BEAMLINE", w["tag"]))

    def complete(endpoint, system, user, max_tokens=512, extra=None):
        return json.dumps({"channels": [{"id": 1, "type": "Chiller", "confidence": 0.7, "reason": "cooling"}]})
    monkeypatch.setattr("app.services.llm.complete", complete)
    run(w, path="deploy/values.yaml", infer_elements=True, ai_unrecognised=True)
    run(w, path="deploy/values-linac.yaml", infer_elements=True, ai_unrecognised=True)
    db = SessionLocal()
    names = {a.name for a in db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.type == "Chiller",
                                                     Asset.record_status == "Provisional")}
    assert {"ZZZ01 Chiller", "YYY01 Chiller"} <= names
    db.close()


ELI_SCREENS = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    cam01: {template: adcamera, devgroup: cam, devtype: camera, iocprefix: LEL, devices: [{name: "SCN01:CAM01", id: 10.16.4.21}]}
    cam02: {template: adcamera, devgroup: cam, devtype: camera, iocprefix: LEL, devices: [{name: "SCN02:CAM01", id: 10.16.4.22}]}
    diag-tml:
      template: motor
      devgroup: mot
      devtype: technosoft-asyn
      iocprefix: LEL
      devices: [{axid: 1, name: "SCN01:MOT01"}, {axid: 2, name: "SCN02:MOT01"}]
"""


def test_eli_screen_stations_are_composed_of_their_camera_and_motor(world, monkeypatch):
    w = world
    monkeypatch.setattr(epik8s_import, "_fetch", lambda *a, **k: ELI_SCREENS.replace("BEAMLINE", w["tag"]))
    counts = run(w, infer_elements=True)
    db = SessionLocal()
    for n in ("01", "02"):
        station = db.query(Asset).filter(Asset.workspace_id == w["ws"], Asset.key == f"{w['tag']}:ELM:SCN{n}").one()
        assert station.type == "Screen Station"
        parts = {db.get(Asset, r.to_asset_uid).type for r in db.query(Relation).filter(
            Relation.from_asset_uid == station.uid, Relation.relation_type == "composed of")}
        assert parts == {"Camera", "Motor Axis"}
    assert counts["inferred Screen Station"] == 2
    db.close()
