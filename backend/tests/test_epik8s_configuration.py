"""Reading a control configuration as objects of the catalogue's types.

What is worth testing is what could quietly go wrong: two networks that share a
name read as one, a mount named by a service and by the top level made twice, a
template only some IOCs refer to left out of the graph, and a key written that
no type declares.
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

RICH = """
beamline: BEAMLINE
namespace: sparc
epik8namespace: k8sda.lnf.infn.it
giturl: https://baltig.infn.it/lnf-da-control/epik8-sparc.git
gitrev: main
argocdProject: sparc
ingressClassName: nginx
baseIp: 10.43.240.0/22
iocDefaults:
  agilent-vac:
    devgroup: vac
    devtype: ipcmini
    devfunc: ion
    charturl: https://github.com/infn-epics/ioc-chart.git
    autosync: true
    asset: https://servicedesk.infn.it/secure/ObjectSchema.jspa?id=44&typeId=2505&objectId=129491
nfsMounts:
  - {name: data, server: 192.168.197.157, path: /data/sparc, mountPath: /nfs/data}
nfsBackups:
  - {name: backups, server: 192.168.197.157, path: /data/backups, mountPath: /nfs/backups}
epicsConfiguration:
  address_list: "10.0.0.1 10.0.0.2"
  max_array_bytes: "10000000"
  services:
    docs:
      desc: Documentation
      image: nginx
      replicaCount: 2
      targetRevision: v1.2
      nfsMounts:
        - {name: httpsrv-nfs, server: 192.168.197.157, path: /data/sparc, mountPath: /usr/share/nginx/html}
        - {name: private, server: 192.168.197.157, path: /data/docs-only, mountPath: /x}
  iocs:
    vac-gunvpc:
      iocprefix: SPARC:VAC
      iocroot: GUNVPC
      template: agilent-vac
      autosync: false
      networks:
        - {name: control, annotation: sparc-magnets}
      iocinit:
        - {name: PixelFormat, value: Mono16}
      iocparam:
        - {name: server, value: scsparcsipmxa001.lnf.infn.it}
        - {name: port, value: 4003}
      devices:
        - {name: GUNSIP01, channel: 146}
    histar:
      iocprefix: SPARC:MAG:HISTAR
      template: caenels
      networks:
        - {name: control, annotation: sparc-magnets}
        - {name: vlan-197, annotation: sparc-net}
      devices:
        - {name: GUNQUA01, ip: 192.168.0.28}
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
def workspace(db):
    ws = f"cfg-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Beamline"))
    db.commit()
    at.ensure_asset_types(db, ws)
    db.commit()
    return ws


@pytest.fixture()
def tag():
    return f"T{secrets.token_hex(3)}".upper()      # keys are unique across the installation


def run(db, ws, tag, text=RICH):
    values = yaml.safe_load(text.replace("BEAMLINE", tag))
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, "test@main:deploy/values.yaml")
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


# --- the configuration itself ---------------------------------------------------------

def test_the_file_is_an_object_that_says_which_revision_it_was(db, workspace, tag):
    run(db, workspace, tag)
    cfg = objects(db, workspace)[f"{tag}-CFG"]
    assert cfg.type == "Control Configuration"
    assert cfg.attributes["git_revision"] == "main"
    assert cfg.attributes["config_path"] == "deploy/values.yaml"
    assert cfg.attributes["argocd_project"] == "sparc" and cfg.attributes["base_ip"] == "10.43.240.0/22"
    assert cfg.attributes["max_array_bytes"] == 10000000                # a number, not "10000000"
    assert cfg.attributes["epics_address_list"] == "10.0.0.1 10.0.0.2"
    assert (f"{tag}-CFG", "configures", tag) in edges(db, workspace)


def test_everything_the_file_declares_says_so(db, workspace, tag):
    run(db, workspace, tag)
    e = edges(db, workspace)
    for key in (f"{tag}-IOC-vac-gunvpc", f"{tag}-IOC-histar", f"{tag}-SVC-docs",
                f"{tag}-DEV-vac-gunvpc-GUNSIP01", f"{tag}-DEV-histar-GUNQUA01",
                f"{tag}-TPL-agilent-vac", f"{tag}-NET-sparc-magnets", f"{tag}-MNT-data"):
        assert (key, "declared in", f"{tag}-CFG") in e, key


def test_every_object_says_which_facility_it_belongs_to(db, workspace, tag):
    run(db, workspace, tag)
    for obj in objects(db, workspace).values():
        assert obj.attributes["argus_facility"] == tag, obj.key


# --- templates -----------------------------------------------------------------------------

def test_a_template_is_one_object_that_its_iocs_share(db, workspace, tag):
    run(db, workspace, tag)
    objs, e = objects(db, workspace), edges(db, workspace)
    defined = objs[f"{tag}-TPL-agilent-vac"]
    assert defined.type == "IOC Template"
    assert defined.attributes["devfunc"] == "ion" and defined.attributes["autosync"] is True
    assert "servicedesk.infn.it" in defined.attributes["inventory_url"]
    assert (f"{tag}-IOC-vac-gunvpc", "templated from", f"{tag}-TPL-agilent-vac") in e


def test_a_template_only_the_iocs_name_is_still_in_the_graph(db, workspace, tag):
    """`caenels` is in no iocDefaults; the recipe lives in the chart repository. The
    IOCs that use it still share its fate, and that has to be a walkable edge."""
    run(db, workspace, tag)
    objs = objects(db, workspace)
    named = objs[f"{tag}-TPL-caenels"]
    assert named.attributes["template_name"] == "caenels" and "chart_url" not in named.attributes
    assert (f"{tag}-IOC-histar", "templated from", f"{tag}-TPL-caenels") in edges(db, workspace)


# --- networks -------------------------------------------------------------------------------------

def test_two_networks_with_one_name_are_told_apart_by_their_annotation(db, workspace, tag):
    run(db, workspace, tag)
    objs = objects(db, workspace)
    nets = {k for k, o in objs.items() if o.type == "Control Network"}
    assert nets == {f"{tag}-NET-sparc-magnets", f"{tag}-NET-sparc-net"}
    assert objs[f"{tag}-NET-sparc-magnets"].attributes["network_name"] == "control"
    assert objs[f"{tag}-NET-sparc-net"].attributes["vlan"] == 197
    e = edges(db, workspace)
    # one network, two IOCs on it
    assert (f"{tag}-IOC-vac-gunvpc", "on network", f"{tag}-NET-sparc-magnets") in e
    assert (f"{tag}-IOC-histar", "on network", f"{tag}-NET-sparc-magnets") in e


# --- storage --------------------------------------------------------------------------------------

def test_the_same_server_and_path_is_one_mount_however_many_things_name_it(db, workspace, tag):
    run(db, workspace, tag)
    objs, e = objects(db, workspace), edges(db, workspace)
    mounts = {k for k, o in objs.items() if o.type == "Storage Mount"}
    # `data` at the top level and the docs service's `httpsrv-nfs` are one place
    assert mounts == {f"{tag}-MNT-data", f"{tag}-MNT-backups", f"{tag}-MNT-docs-private"}
    assert (f"{tag}-SVC-docs", "mounts", f"{tag}-MNT-data") in e
    assert (f"{tag}-SVC-docs", "mounts", f"{tag}-MNT-docs-private") in e
    assert objs[f"{tag}-MNT-backups"].attributes["is_backup"] is True
    assert objs[f"{tag}-MNT-data"].attributes["is_backup"] is False
    assert objs[f"{tag}-MNT-data"].attributes["export_path"] == "/data/sparc"
    assert (f"{tag}-MNT-data", "part of", tag) in e


# --- what an IOC and a service now carry --------------------------------------------------------------

def test_an_ioc_and_a_service_carry_what_the_file_says_about_them(db, workspace, tag):
    run(db, workspace, tag)
    objs = objects(db, workspace)
    ioc = objs[f"{tag}-IOC-vac-gunvpc"].attributes
    assert ioc["autosync"] is False                       # an explicit false is a value, not an absence
    assert ioc["networks"] == ["sparc-magnets"]
    assert "PixelFormat" in ioc["ioc_init"]
    svc = objs[f"{tag}-SVC-docs"].attributes
    assert svc["image"] == "nginx" and svc["replicas"] == 2 and svc["chart_revision"] == "v1.2"
    assert objs[f"{tag}-DEV-vac-gunvpc-GUNSIP01"].attributes["pv"] == f"SPARC:VAC:GUNVPC:GUNSIP01"


# --- the catalogue has to describe what is written ---------------------------------------------------

def test_every_key_written_is_declared_by_the_type_it_is_written_to(db, workspace, tag):
    run(db, workspace, tag)
    undeclared = {}
    for obj in objects(db, workspace).values():
        schema = db.get(Schema, obj.schema_uid)
        declared = {a["key"] for a in effective_attributes(db, schema)}
        missing = set(obj.attributes) - declared
        if missing:
            undeclared.setdefault(obj.type, set()).update(missing)
    assert not undeclared, undeclared


def test_the_objects_are_of_the_catalogues_types(db, workspace, tag):
    run(db, workspace, tag)
    for obj in objects(db, workspace).values():
        assert obj.schema_uid == at.type_uid(workspace, obj.type), obj.key


def test_running_it_twice_creates_nothing(db, workspace, tag):
    run(db, workspace, tag)
    n_objects, n_edges = len(objects(db, workspace)), len(edges(db, workspace))
    again = run(db, workspace, tag)
    assert again.counts["relations"] == 0
    assert (len(objects(db, workspace)), len(edges(db, workspace))) == (n_objects, n_edges)


def test_with_no_catalogue_at_all_it_still_makes_its_own_types(db, tag):
    ws = f"cfg-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Bare"))
    db.commit()
    run(db, ws, tag)
    made = {s.name for s in db.query(Schema).filter(Schema.workspace_id == ws)}
    assert {"Facility", "IOC", "Control Device", "Control Configuration", "IOC Template",
            "Control Network", "Storage Mount", "Access Point", "Control Service"} <= made


def test_it_uses_the_types_of_a_split_catalogue_where_they_are(db, tag):
    cat, ws = f"cfg-cat-{secrets.token_hex(4)}", f"cfg-{secrets.token_hex(4)}"
    db.add_all([Workspace(id=cat, name="Catalogue"), Workspace(id=ws, name="Beamline")])
    db.commit()
    at.ensure_asset_types(db, cat, scope="global")
    at.ensure_asset_types(db, ws, scope="beamline", catalogue_workspace_id=cat)
    db.commit()
    run(db, ws, tag)
    for obj in objects(db, ws).values():
        assert obj.schema_uid == at.type_uid(ws, obj.type), obj.key       # the machine's own types
    assert db.query(Schema).filter(Schema.workspace_id == ws).count() == len(at.BEAMLINE_TYPES)   # none made up


def test_one_pv_on_two_iocs_is_recorded_twice_and_reported(db, workspace, tag):
    """SPARC's file does this. The hub records what the file says, and says it is odd."""
    text = RICH.replace("""    histar:""", """    second:
      iocprefix: SPARC:VAC
      iocroot: GUNVPC
      devices:
        - {name: GUNSIP01, channel: 1}
    histar:""")
    importer = run(db, workspace, tag, text)
    objs = objects(db, workspace)
    assert f"{tag}-DEV-vac-gunvpc-GUNSIP01" in objs and f"{tag}-DEV-second-GUNSIP01" in objs
    assert any("SPARC:VAC:GUNVPC:GUNSIP01 is configured on two IOCs" in w
               for w in importer.job.warnings)
