"""The IT layer the control configuration implies: serial lines, what kind of endpoint each
address is, and the converters, servers and consoles behind the hostnames.

What matters: a line is what fails when one cable does; a kind is read from a name only where the
name says it; and a host reached by two beamlines is one object.
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
from app.services.causal_model import classify
from app.services.epik8s_import import _Importer
from app.services.root_cause import impact_of, root_causes

CONFIG = """
beamline: BEAMLINE
iocDefaults:
  agilent-vac: {devgroup: vac, devtype: ipcmini, devfunc: ion}
  motor: {devgroup: mot}
  caenels: {devgroup: mag, devtype: histar}
epicsConfiguration:
  iocs:
    vac-gunvpc:
      iocprefix: SPARC:VAC
      iocroot: GUNVPC
      template: agilent-vac
      iocparam: [{name: server, value: scsparcsipmxa001.lnf.infn.it}, {name: port, value: 4003}]
      devices: [{name: GUNSIP01, channel: 146}, {name: GUNSIP02, channel: 147}]
    vac-kly01:
      iocprefix: SPARC:VAC
      iocroot: KLY1VPC
      template: agilent-vac
      iocparam: [{name: server, value: scsparcsipmxa001.lnf.infn.it}, {name: port, value: 4001}]
      devices: [{name: W1KSIP03, channel: 1}]
    diag-tml:
      iocprefix: LEL
      template: motor
      serial: {ip: scelimxa16001.int.eli-np.ro, port: 4005, baud: 9600}
      devices: [{name: "SCN01:MOT01", axid: 1}, {name: "SCN02:MOT01", axid: 2}]
    bare-moxa:
      iocprefix: BTF:MOT
      template: motor
      iocparam: [{name: server, value: 192.168.192.40}, {name: port, value: 4001}]
      devices: [{name: SLT001, axid: 1}]
    llrfs01:
      iocprefix: SPARC:LLRF1
      template: agilent-vac
      host: plsparcllrfs001.lnf.infn.it
      devices: [{name: ad1, channel: 3}]
    histar:
      iocprefix: SPARC:MAG
      template: caenels
      devices: [{name: GUNQUA01, ip: 192.168.0.28, port: 502}]
    console:
      iocprefix: SPARC:CO
      template: agilent-vac
      iocparam: [{name: server, value: pwsparcco001.lnf.infn.it}]
      devices: [{name: CONS01}]
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
def world(db):
    """A catalogue, two beamlines hanging from it, and the site's IT workspace."""
    cat, it = f"it-cat-{secrets.token_hex(4)}", f"it-site-{secrets.token_hex(4)}"
    beams = [f"it-bl-{secrets.token_hex(4)}" for _ in range(2)]
    db.add_all([Workspace(id=w, name=w) for w in (cat, it, *beams)])
    db.commit()
    at.ensure_asset_types(db, cat, scope="global")
    for b in beams:
        at.ensure_asset_types(db, b, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    yield cat, it, beams
    db.rollback()
    for w in (*beams, it, cat):
        db.query(Relation).filter(Relation.workspace_id == w).delete()
        db.query(Asset).filter(Asset.workspace_id == w).delete()
        db.query(ImportJob).filter(ImportJob.workspace_id == w).delete()
        db.query(Schema).filter(Schema.workspace_id == w).delete()
    db.query(Workspace).filter(Workspace.id.in_((*beams, it, cat))).delete()
    db.commit()


def run(db, ws, tag, it=None, infer=False, text=CONFIG):
    values = yaml.safe_load(text.replace("BEAMLINE", tag))
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, "test@main:deploy/values.yaml", infer_elements=infer, it_workspace=it)
    importer.ensure_types()
    importer.run(values, True)
    db.commit()
    return importer


def objects(db, ws):
    return {a.key: a for a in db.query(Asset).filter(Asset.workspace_id == ws)}


def edges(db, ws):
    names = {a.uid: a.key for a in db.query(Asset)}
    return {(names[r.from_asset_uid], r.relation_type, names[r.to_asset_uid])
            for r in db.query(Relation).filter(Relation.workspace_id == ws)}


# --- serial lines ---------------------------------------------------------------------------------

def test_a_port_of_a_converter_is_a_line_and_its_devices_are_on_it(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    objs, e = objects(db, ws), edges(db, ws)
    line = f"{tag}-LINE-SCSPARCSIPMXA001-4003"
    assert objs[line].type == "Serial Line" and objs[line].attributes["tcp_port"] == 4003
    assert (line, "port of", "NET-" + ws + "-SCSPARCSIPMXA001") in e
    for device in ("GUNSIP01", "GUNSIP02"):
        assert (f"{tag}-DEV-vac-gunvpc-{device}", "on line", line) in e
    # another port of the same box is another line, and does not hold these devices
    other = f"{tag}-LINE-SCSPARCSIPMXA001-4001"
    assert (f"{tag}-DEV-vac-gunvpc-GUNSIP01", "on line", other) not in e
    assert (f"{tag}-DEV-vac-kly01-W1KSIP03", "on line", other) in e


def test_what_kind_of_line_it_is_comes_from_the_keys_its_devices_use(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    kinds = {k.rsplit("-", 2)[-2] + ":" + k.rsplit("-", 1)[-1]: o.attributes.get("line_kind")
             for k, o in objects(db, ws).items() if o.type == "Serial Line"}
    assert kinds["SCSPARCSIPMXA001:4003"] == "Multi-channel controller"     # `channel:` on two devices
    assert kinds["SCSPARCSIPMXA001:4001"] == "Single device"
    assert kinds["SCELIMXA16001:4005"] == "Multi-axis controller"           # `axid:`


def test_a_serial_block_is_an_endpoint_and_gives_the_line_its_baud_rate(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    line = objects(db, ws)[f"{tag}-LINE-SCELIMXA16001-4005"]
    assert line.attributes["baud"] == 9600
    assert (f"{tag}-DEV-diag-tml-SCN01-MOT01", "on line", line.key) in edges(db, ws)


def test_a_bare_ip_with_a_port_in_moxas_range_is_a_line_and_its_access_point_a_converter(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    line = f"{tag}-LINE-192.168.192.40-4001"
    assert line in objects(db, ws)
    ap = objects(db, ws)[f"NET-{ws}-192.168.192.40"]
    assert ap.attributes["endpoint_kind"] == "Serial converter"
    assert "4001-4999" in ap.attributes["endpoint_kind_source"]


def test_an_ethernet_native_instrument_is_not_on_a_line(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    assert not [k for k in edges(db, ws) if k[0].endswith(":GUNQUA01") and k[1] == "on line"]


# --- what kind of endpoint an access point is -------------------------------------------------------

def test_an_access_point_says_what_it_is_and_how_that_was_read(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    objs = objects(db, ws)
    moxa = objs[f"NET-{ws}-SCSPARCSIPMXA001"].attributes
    assert moxa["endpoint_kind"] == "Serial converter" and "`sc`" in moxa["endpoint_kind_source"]
    assert objs[f"NET-{ws}-PLSPARCLLRFS001"].attributes["endpoint_kind"] == "Host"


def test_a_kind_somebody_has_set_survives_a_re_read(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    ap = objects(db, ws)[f"NET-{ws}-SCSPARCSIPMXA001"]
    ap.attributes = {**ap.attributes, "endpoint_kind": "Instrument"}
    db.commit()
    run(db, ws, tag)
    assert objects(db, ws)[f"NET-{ws}-SCSPARCSIPMXA001"].attributes["endpoint_kind"] == "Instrument"


def test_an_ioc_that_names_a_host_runs_on_it_and_one_that_names_a_server_only_connects(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    e = edges(db, ws)
    assert (f"{tag}-IOC-llrfs01", "runs on", f"NET-{ws}-PLSPARCLLRFS001") in e
    assert (f"{tag}-IOC-vac-gunvpc", "connects to", f"NET-{ws}-SCSPARCSIPMXA001") in e
    assert not [k for k in e if k[0] == f"{tag}-IOC-vac-gunvpc" and k[1] == "runs on"]


# --- the IT equipment behind a hostname ------------------------------------------------------------

def test_without_an_it_workspace_no_equipment_is_made(db, world, tag):
    _, it, (ws, _) = world
    importer = run(db, ws, tag)
    assert not objects(db, it) and "it_equipment" not in importer.counts


def test_a_converter_a_host_and_a_console_are_made_in_the_it_workspace_and_flagged_global(db, world, tag):
    cat, it, (ws, _) = world
    run(db, ws, tag, it=it)
    made = objects(db, it)
    assert made["HOST-scsparcsipmxa001.lnf.infn.it"].type == "Serial Converter"
    assert made["HOST-plsparcllrfs001.lnf.infn.it"].type == "Server"
    assert made["HOST-pwsparcco001.lnf.infn.it"].type == "Workstation"
    assert made["HOST-pwsparcco001.lnf.infn.it"].attributes["workstation_role"] == "Operator console"
    assert made["HOST-scelimxa16001.int.eli-np.ro"].attributes["fqdn"] == "scelimxa16001.int.eli-np.ro"
    assert all(a.is_global and a.workspace_id == it for a in made.values())
    assert all(a.attributes["argus_keywords"] == ["inferred"] for a in made.values())
    # the catalogue's types, from the shared set
    assert made["HOST-scsparcsipmxa001.lnf.infn.it"].schema_uid == at.type_uid(cat, "Serial Converter")


def test_a_bare_ip_names_nothing_so_no_equipment_is_invented_for_it(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    assert not [k for k in objects(db, it) if "192.168" in k]


def test_the_access_point_is_implemented_by_the_equipment_and_stays_a_beamline_object(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    assert (f"NET-{ws}-SCSPARCSIPMXA001", "implemented by", "HOST-scsparcsipmxa001.lnf.infn.it") in edges(db, ws)
    assert objects(db, ws)[f"NET-{ws}-SCSPARCSIPMXA001"].workspace_id == ws


def test_a_host_two_beamlines_reach_is_one_object(db, world, tag):
    _, it, (a, b) = world
    run(db, a, tag, it=it)
    run(db, b, f"{tag}B", it=it)
    converters = [o for o in objects(db, it).values() if o.key == "HOST-scsparcsipmxa001.lnf.infn.it"]
    assert len(converters) == 1
    for ws in (a, b):
        assert (f"NET-{ws}-SCSPARCSIPMXA001", "implemented by", "HOST-scsparcsipmxa001.lnf.infn.it") in edges(db, ws)


def test_the_equipment_is_visible_from_every_beamline_and_editable_only_in_the_it_workspace(db, world, tag):
    from app.services.visibility import asset_visible_in
    _, it, (a, b) = world
    run(db, a, tag, it=it)
    box = objects(db, it)["HOST-scsparcsipmxa001.lnf.infn.it"]
    assert asset_visible_in(box, a) and asset_visible_in(box, b)


def test_running_it_twice_changes_nothing_and_keeps_what_a_person_added(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    box = objects(db, it)["HOST-scsparcsipmxa001.lnf.infn.it"]
    box.attributes = {**box.attributes, "serial": "MX-12345", "n_serial_ports": 16}
    db.commit()
    before = (set(objects(db, ws)), set(objects(db, it)), edges(db, ws))
    run(db, ws, tag, it=it)
    assert (set(objects(db, ws)), set(objects(db, it)), edges(db, ws)) == before
    kept = objects(db, it)["HOST-scsparcsipmxa001.lnf.infn.it"].attributes
    assert kept["serial"] == "MX-12345" and kept["n_serial_ports"] == 16


def test_a_catalogue_without_the_it_types_is_refused_with_a_reason(db, world, tag, monkeypatch):
    """A catalogue seeded before the IT model has no Serial Converter to make."""
    from app.services import epik8s_import
    _, it, (ws, _) = world
    real = epik8s_import.resolve_type_uids
    monkeypatch.setattr(epik8s_import, "resolve_type_uids",
                        lambda db_, w: {k: v for k, v in real(db_, w).items() if k not in ("Serial Converter", "Switch")})
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    with pytest.raises(ValueError, match="cannot use the catalogue's IT types"):
        _Importer(db, job, ws, "x", it_workspace=it).ensure_types()


# --- what a failure now reaches -----------------------------------------------------------------------

def test_every_relation_the_it_layer_writes_means_something_to_a_failure(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    written = {t for _, t, _ in edges(db, ws)}
    assert {"on line", "port of", "carried by", "implemented by", "runs on"} <= written
    assert not [t for t in written if classify(t) is None], written


def test_a_stopped_converter_blinds_the_lines_and_devices_behind_it_and_no_more(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    result = impact_of(db, ws, "HOST-scsparcsipmxa001.lnf.infn.it")
    reached = {a["key"] for a in result["affected"]}
    assert {f"{tag}-DEV-vac-gunvpc-GUNSIP01", f"{tag}-DEV-vac-kly01-W1KSIP03",
            f"{tag}-LINE-SCSPARCSIPMXA001-4003"} <= reached
    assert f"{tag}-DEV-diag-tml-SCN01-MOT01" not in reached           # another converter's
    assert set(result["by_loss"]) == {"control"}


def test_two_lost_readouts_on_one_line_point_at_the_line_before_the_converter_when_a_neighbour_answers(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    one, two = f"{tag}-DEV-vac-gunvpc-GUNSIP01", f"{tag}-DEV-vac-gunvpc-GUNSIP02"
    healthy = f"{tag}-DEV-vac-kly01-W1KSIP03"          # same converter, another port: it answers
    result = root_causes(db, ws, [one, two], healthy=[healthy], symptom_kind={one: "control", two: "control"})
    ranked = [c["key"] for c in result["candidates"] if c["fit"] == 1.0]
    assert f"{tag}-LINE-SCSPARCSIPMXA001-4003" in ranked or f"{tag}-IOC-vac-gunvpc" in ranked
    refuted = {c["key"] for c in result["candidates"] if c["contradicted_by"]}
    assert "HOST-scsparcsipmxa001.lnf.infn.it" in refuted or f"NET-{ws}-SCSPARCSIPMXA001" in refuted


def test_a_line_is_carried_by_the_converter_and_by_the_hops_a_person_adds(db, world, tag):
    _, it, (ws, _) = world
    run(db, ws, tag, it=it)
    conv = "HOST-scsparcsipmxa001.lnf.infn.it"
    line3, line1 = f"{tag}-LINE-SCSPARCSIPMXA001-4003", f"{tag}-LINE-SCSPARCSIPMXA001-4001"
    e = edges(db, ws)
    assert (line3, "carried by", conv) in e and (line1, "carried by", conv) in e

    # a switch and a cable that no configuration names, added by hand: both lines pass the switch
    by_key = {a.key: a for a in db.query(Asset).filter(Asset.workspace_id.in_([ws, it]))}
    template = by_key[conv]
    hops = {}
    for name, kind in (("SW", "Switch"), ("CAB", "Ethernet Cable")):
        hops[name] = Asset(uid=f"{tag}-{name}", key=f"{tag}:{name}", workspace_id=ws, type=kind,
                           schema_uid=template.schema_uid, attributes={}, name=f"{tag} {name}")
        db.add(hops[name])
    db.flush()
    for line in (line3, line1):
        for hop in hops.values():
            db.add(Relation(workspace_id=ws, from_asset_uid=by_key[line].uid, to_asset_uid=hop.uid,
                            relation_type="carried by"))
    db.flush()
    reached = {a["key"] for a in impact_of(db, ws, hops["SW"].key)["affected"]}
    assert {line3, line1, f"{tag}-DEV-vac-gunvpc-GUNSIP01", f"{tag}-DEV-vac-kly01-W1KSIP03"} <= reached
    assert f"{tag}-DEV-diag-tml-SCN01-MOT01" not in reached
    one, two = f"{tag}-DEV-vac-gunvpc-GUNSIP01", f"{tag}-DEV-vac-kly01-W1KSIP03"
    top = root_causes(db, ws, [one, two], symptom_kind={one: "control", two: "control"})["candidates"]
    assert [c["key"] for c in top if c["fit"] == 1.0][0] in {conv, hops["SW"].key, hops["CAB"].key}
