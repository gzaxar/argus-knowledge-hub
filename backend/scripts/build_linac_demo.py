"""Extends the Valmora linac demo bundle through the application itself, then exports it again.

How demo_workspaces/medium-linac was made: scripts/linac_demo_scenarios.py added the three troubleshooting stories to
the files, then this script added the rest of the laboratory. Run it inside the API container, with DATABASE_URL
pointing at an EMPTY database (it is migrated here):

    PYTHONPATH=/app python scripts/build_linac_demo.py <bundle dir> <output dir>

Running it on the current bundle changes nothing but a new beam-model revision; edit it to change the demo.

It applies the bundle as workspace valmora-linac-demo (the identifiers stay those of the files), adds what the
accelerator demo needs, derives the `located in` edges, and exports the workspace as a bundle with the same tour.
Everything is synthetic: the Valmora linac, its people, suppliers and figures are fictional.
"""
import json
import math
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
WS = "valmora-linac-demo"
ACTOR = "ARGUS demo authors"
C = "2026-03-02T09:00:00+00:00"
KW = ["synthetic-demo"]

subprocess.run(["alembic", "upgrade", "head"], check=True, cwd="/app", capture_output=True)

from sqlalchemy import select  # noqa: E402

from app.bundle import core  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.asset import Asset, Relation  # noqa: E402
from app.models.document import Document, DocumentRelation, DocumentRevision  # noqa: E402
from app.models.indoor import FloorPlan  # noqa: E402
from app.models.issue import Issue, IssueComment  # noqa: E402
from app.models.schema import Schema  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import indoor, spatial  # noqa: E402

db = SessionLocal()
assert db.get(Workspace, WS) is None, "use an empty database"
bundle = core.read(SRC)
rep = core.apply(db, bundle, workspace_id=WS, name="Medium Linac Facility (synthetic demo)", actor=ACTOR,
                 people_access=True, dry_run=False, files_root=Path("/tmp/linac-files"))
assert rep.view()["ok"], rep.view()
assert not rep.renamed, rep.renamed[:5]
db.commit()
demo = bundle.manifest["demo"]

# A new workspace gets the installation's default icons and ticket values; the bundle carries its own. Keep the
# bundle's, so the export is the bundle plus what is added here, not twice the defaults.
from sqlalchemy import text  # noqa: E402
for table in ("icons", "global_values"):
    keep = [json.loads(x)["uid"] for x in (SRC / "records" / f"{table}.jsonl").read_text().splitlines() if x.strip()]
    gone = db.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w AND NOT (uid = ANY(:keep))"),
                      {"w": WS, "keep": keep}).rowcount
    print(f"{table}: {gone} defaults removed")
db.commit()

# ------------------------------------------------------------------------------------------------ helpers
schemas = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == WS))}
PLANS = {p.name: p for p in db.scalars(select(FloorPlan).where(FloorPlan.workspace_id == WS))}
ACC = PLANS["Accelerator Building — ground floor"]
ADM0 = PLANS["Administration Building — ground floor"]
ADM1 = PLANS["Administration Building — first floor"]
made = {"assets": 0, "relations": 0, "tickets": 0, "documents": 0}


def asset(uid, key, name, typ, **attrs):
    a = db.get(Asset, uid)
    if a is None:
        a = Asset(uid=uid, workspace_id=WS, schema_uid=schemas[typ], key=key, name=name, type=typ,
                  attributes={"argus_keywords": KW, **attrs})
        db.add(a)
        made["assets"] += 1
    else:
        a.attributes = {**(a.attributes or {}), **attrs}
    db.flush()
    return a


def update(uid, **attrs):
    a = db.get(Asset, uid)
    a.attributes = {**(a.attributes or {}), **attrs}
    db.flush()


def rel(a, verb, b):
    exists = db.scalar(select(Relation).where(Relation.from_asset_uid == a, Relation.to_asset_uid == b,
                                              Relation.relation_type == verb))
    if exists is None:
        assert db.get(Asset, a) and db.get(Asset, b), (a, verb, b)
        db.add(Relation(workspace_id=WS, from_asset_uid=a, to_asset_uid=b, relation_type=verb))
        made["relations"] += 1


def on_plan(uid, plan, place, x, y, note=None):
    indoor.place(db, db.get(Asset, uid), place_uid=place, level_uid=plan.level_uid, plan_uid=plan.uid, x=x, y=y,
                 actor=ACTOR, note=note)


def at(uid, lat, lon, accuracy=3.0):
    spatial.set_location(db, db.get(Asset, uid), spatial.point(lat, lon, accuracy_m=accuracy), actor=ACTOR,
                         source="manual", accuracy_m=accuracy)


def outline(uid, ring):
    geom = spatial.shape(db, {"type": "Polygon", "coordinates": [ring + [ring[0]]]}, "outline")
    spatial.set_location(db, db.get(Asset, uid), geom, actor=ACTOR, source="manual", role="outline")


def route(uid, line):
    geom = spatial.shape(db, {"type": "LineString", "coordinates": line}, "route")
    spatial.set_location(db, db.get(Asset, uid), geom, actor=ACTOR, source="manual", role="route")


def ticket(uid, kind, state, prio, title, desc, asset_uid, created, assignee, by, closed=None, attrs=None,
           comments=()):
    if db.get(Issue, uid):
        return
    db.add(Issue(uid=uid, workspace_id=WS, schema_uid=schemas[kind], title=title, description=desc, state=state,
                 priority=prio, asset_uid=asset_uid, assignee=assignee, created_by=by, labels=KW,
                 attributes=attrs or {}, closed_at=closed))
    db.flush()
    for i, (author, body) in enumerate(comments, start=1):
        db.add(IssueComment(uid=f"{uid}-c{i}", issue_uid=uid, author=author, body=body))
    made["tickets"] += 1


NOTE = "> **Synthetic demo content.** The Valmora linac, its people, suppliers and figures are fictional.\n\n\n"


def document(uid, code, title, typ, body, describes, owner):
    if db.get(Document, uid):
        return
    d = Document(uid=uid, workspace_id=WS, code=code, title=title, document_type_uid=schemas[typ],
                 owner_user_id=owner, confidentiality="interno")
    db.add(d)
    db.flush()
    r = DocumentRevision(uid=uid + "-r1", document_uid=uid, revision_number=1, state="published",
                         body_markdown=NOTE + body, authored_by=owner)
    db.add(r)
    db.flush()
    d.current_revision_uid = r.uid
    for a in describes:
        db.add(DocumentRelation(workspace_id=WS, from_document_uid=uid, to_type="asset", to_uid=a,
                                relation_type="describes"))
    made["documents"] += 1


# ------------------------------------------------------------------------------------------------ organisation
for uid, key, name, role in [
    ("vl-org-td", "VL-ORG-TD", "Technical Division", "electrical, cooling, HVAC, buildings and mechanical services"),
    ("vl-org-rp", "VL-ORG-RP", "Radiation Protection Service", "radiation monitoring, dosimetry, work permits"),
    ("vl-org-adm", "VL-ORG-ADM", "Administration Office", "purchasing, contracts, invoices, inventory"),
    ("vl-org-it", "VL-ORG-IT", "IT and Networks Service", "servers, Kubernetes, networks, telephony, backups"),
    ("vl-org-ctrl", "VL-ORG-CTRL", "Controls Group", "EPICS, EPIK8s, IOCs, control room consoles"),
]:
    asset(uid, key, name, "Organization", internal=True, responsibility=role)

# ------------------------------------------------------------------------------------------------ racks
RACKS = [
    # uid, key, name, room, plan, x, y, units, feed
    ("vl-rk-s01", "VL-RK-S01", "Rack S01 — Kubernetes nodes and storage", "vl-room-server", ADM0, 272, 148, 42, "UPS-SRV A"),
    ("vl-rk-s02", "VL-RK-S02", "Rack S02 — core network and firewall", "vl-room-server", ADM0, 296, 148, 42, "UPS-SRV B"),
    ("vl-rk-s03", "VL-RK-S03", "Rack S03 — IOC host and archiver", "vl-room-server", ADM0, 320, 148, 42, "UPS-SRV A"),
    ("vl-rk-a12-1", "VL-RK-A12-1", "Rack A12-1 — quadrupole supplies Q1–Q3 and serial line", "vl-room-service", ACC, 611, 214, 42, "DP-MAG"),
    ("vl-rk-a12-2", "VL-RK-A12-2", "Rack A12-2 — supplies Q4–Q6, dipole, solenoid, correctors", "vl-room-service", ACC, 611, 160, 42, "DP-MAG"),
    ("vl-rk-a12-3", "VL-RK-A12-3", "Rack A12-3 — vacuum controller, gauge module, vacuum PLC", "vl-room-service", ACC, 645, 186, 42, "UPS-CTL"),
    ("vl-rk-ctrl", "VL-RK-CTRL", "Rack CTRL — controls switch, timing, PSS PLC", "vl-room-control", ACC, 560, 30, 42, "UPS-CTL"),
]
for uid, key, name, room, plan, x, y, units, feed in RACKS:
    asset(uid, key, name, "Rack", argus_location=room, rack_units=units, power_feed=feed, cooling="room air")
    on_plan(uid, plan, room, x, y)

IN_RACK = {
    "vl-rk-a12-1": ["vl-ps-q1", "vl-ps-q2", "vl-ps-q3", "vl-moxa-01"],
    "vl-rk-a12-2": ["vl-ps-q4", "vl-ps-q5", "vl-ps-q6", "vl-ps-dip", "vl-ps-sol", "vl-ps-cor"],
    "vl-rk-a12-3": ["vl-vac-ctl", "vl-vac-ctl-gm", "vl-plc-vac"],
    "vl-rk-ctrl": ["vl-sw-ctl", "vl-plc-pss"],
    "vl-rk-s03": ["vl-srv-ioc", "vl-srv-arch"],
    "vl-rk-s02": ["vl-fw"],
}
for rack, units in IN_RACK.items():
    for i, u in enumerate(units):
        if db.get(Asset, u) is not None:
            update(u, argus_location=rack, rack_position=40 - 3 * i)
            # Placed inside the rack now, at the point on the plan it already had.
            here = indoor.current(db, u)
            if here is not None and here.plan_uid and here.place_uid != rack:
                indoor.place(db, db.get(Asset, u), place_uid=rack, level_uid=here.level_uid, plan_uid=here.plan_uid,
                             x=here.plan_x, y=here.plan_y, actor=ACTOR, note=f"rack unit {40 - 3 * i}")
timing = db.scalar(select(Asset.uid).where(Asset.workspace_id == WS, Asset.type.like("%Timing%")))
if timing:
    update(timing, argus_location="vl-rk-ctrl")

# ------------------------------------------------------------------------------------------------ IT and EPIK8s
asset("vl-sw-core", "VL-SW-CORE", "Core switch SW-CORE", "Switch", argus_location="vl-rk-s02", ip="10.20.0.2",
      n_ports=48, is_managed=True, manufacturer="Synthetica Networks", model="SN-C48X", firmware_version="9.2.1",
      inventory_number="VL-INV-IT-0101")
asset("vl-sw-adm", "VL-SW-ADM", "Access switch SW-ADM (offices, PoE)", "Switch", argus_location="vl-rk-s02",
      ip="10.30.0.3", n_ports=48, supports_poe=True, is_managed=True, inventory_number="VL-INV-IT-0102")
asset("vl-pp-adm", "VL-PP-ADM", "Patch panel PP-ADM (office outlets)", "Patch Panel", argus_location="vl-rk-s02",
      n_ports=48, medium="copper cat6a")
asset("vl-pp-fo", "VL-PP-FO", "Fibre patch panel PP-FO (to the Campus Data Centre)", "Patch Panel",
      argus_location="vl-rk-s02", n_ports=24, medium="single-mode fibre")
asset("vl-kc", "VL-K8S", "Kubernetes cluster vl-k8s (controls)", "Computing Node", argus_location="vl-rk-s01",
      role="Kubernetes cluster: control services and containerised IOCs", os="Kubernetes 1.31")
for i in (1, 2, 3):
    asset(f"vl-kn{i}", f"VL-K8S-N{i}", f"Kubernetes node vl-k8s-n{i}", "Server", argus_location="vl-rk-s01",
          rack_position=40 - 2 * i, cpu="2 × 32 cores", ram_gb=256, os="Rocky Linux 9", ip=f"10.20.1.{10 + i}",
          is_virtual=False, inventory_number=f"VL-INV-IT-02{i:02d}", purchase_order="VL-PO-2026-0501")
    rel(f"vl-kn{i}", "part of", "vl-kc")
    rel(f"vl-kn{i}", "connects to", "vl-sw-core")
asset("vl-nas-01", "VL-NAS-01", "Storage NAS-01 (cluster volumes)", "Storage System", argus_location="vl-rk-s01",
      capacity_tb=96, protocols=["NFS", "S3"], ip="10.20.1.30", inventory_number="VL-INV-IT-0210")
rel("vl-kc", "hosted on", "vl-nas-01")
rel("vl-srv-ioc", "part of", "vl-kc")
update("vl-srv-ioc", role="Kubernetes node for the IOCs (controls network, bare metal)")
asset("vl-epik8s", "VL-EPIK8S", "EPIK8s configuration — Valmora linac", "Control Configuration",
      git_url="https://git.valmora.example/controls/epik8s-valmora-linac", config_path="deploy/values.yaml",
      namespace="valmora-linac", cluster="vl-k8s", argocd_project="valmora-linac",
      epics_address_list="10.20.255.255", git_revision="main", git_commit="4f1c2a9")
rel("vl-epik8s", "deployed on", "vl-kc")
SERVICES = [
    ("vl-svc-arch", "VL-SVC-ARCH", "EPICS Archiver Appliance", "archiver", "https://archiver.valmora.example"),
    ("vl-svc-alarm", "VL-SVC-ALARM", "Phoebus alarm server", "alarm-server", None),
    ("vl-svc-savres", "VL-SVC-SAVRES", "Save-and-restore service", "save-and-restore", "https://saveandrestore.valmora.example"),
    ("vl-svc-olog", "VL-SVC-OLOG", "Olog electronic logbook", "olog", "https://olog.valmora.example"),
    ("vl-svc-cf", "VL-SVC-CF", "ChannelFinder", "channelfinder", "https://cf.valmora.example"),
    ("vl-svc-mcp", "VL-SVC-MCP", "ARGUS beamline MCP server", "argus-mcp", "https://mcp.valmora.example"),
    ("vl-svc-argocd", "VL-SVC-ARGOCD", "Argo CD (EPIK8s deployments)", "argocd", "https://argocd.valmora.example"),
]
for uid, key, name, svc, url in SERVICES:
    asset(uid, key, name, "Control Service", service=svc, url=url, replicas=1,
          chart_url="oci://registry.valmora.example/epik8s/" + svc)
    rel(uid, "hosted on", "vl-kc")
    rel(uid, "deployed by", "vl-epik8s")
rel("vl-svc-arch", "hosted on", "vl-srv-arch")
for ioc in db.scalars(select(Asset.uid).where(Asset.workspace_id == WS, Asset.type == "IOC")):
    rel(ioc, "deployed by", "vl-epik8s")
asset("vl-net-ctrl", "VL-NET-CTRL", "Controls network 10.20.0.0/16", "Control Network", network_name="controls",
      cidr="10.20.0.0/16", vlan=20, address_list="10.20.255.255")
for u in ("vl-sw-core", "vl-sw-ctl", "vl-srv-ioc", "vl-kn1", "vl-kn2", "vl-kn3"):
    rel(u, "on segment", "vl-net-ctrl")
rel("vl-sw-ctl", "connects to", "vl-sw-core")
rel("vl-srv-ioc", "connects to", "vl-sw-core")
rel("vl-srv-arch", "connects to", "vl-sw-core")
rel("vl-fw", "connects to", "vl-sw-core")
rel("vl-sw-adm", "connects to", "vl-sw-core")

# The Campus Data Centre: another building, outside the site, where the backups go.
asset("vl-bld-dc2", "VL-BLD-DC2", "Campus Data Centre (IT, external building)", "Building",
      address="Via del Campus 12, Valmora (fictional)", operated_by="IT and Networks Service")
DC = [[11.95612, 44.62672], [11.95668, 44.62672], [11.95668, 44.62703], [11.95612, 44.62703]]
outline("vl-bld-dc2", DC)
asset("vl-room-dc2", "VL-ROOM-DC2.01", "DC2 machine room", "Room", argus_location="vl-bld-dc2")
asset("vl-rk-dc2", "VL-RK-DC2-07", "Rack DC2-07 — Valmora backups", "Rack", argus_location="vl-room-dc2",
      rack_units=42, power_feed="DC2 UPS A+B")
at("vl-rk-dc2", 44.62688, 11.95640)
asset("vl-rtr-dc2", "VL-RTR-DC2", "Router RTR-DC2 (campus backbone)", "Router", argus_location="vl-rk-dc2",
      ip="10.99.0.1")
asset("vl-bkp-01", "VL-BKP-01", "Backup server BKP-01", "Storage System", argus_location="vl-rk-dc2",
      capacity_tb=240, protocols=["restic", "S3"], ip="10.99.7.10", inventory_number="VL-INV-IT-0301",
      schedule="nightly 02:00; retention 30 days")
asset("vl-tape-01", "VL-TAPE-01", "Tape library TAPE-01 (LTO-9)", "Storage System", argus_location="vl-rk-dc2",
      capacity_tb=900, protocols=["LTO-9"], schedule="weekly full, Sunday 06:00; off-site copy monthly")
for u in ("vl-rtr-dc2", "vl-bkp-01", "vl-tape-01"):
    at(u, 44.62688, 11.95641, 2.0)
asset("vl-fo-dc2", "VL-FO-DC2", "Fibre link Administration Building → Campus Data Centre", "Fibre Cable",
      fibre_mode="single-mode", length_m=420, cable_label="FO-DC2-01", from_asset="vl-pp-fo", to_asset="vl-rtr-dc2")
route("vl-fo-dc2", [[11.95247, 44.62530], [11.95330, 44.62560], [11.95480, 44.62610], [11.95612, 44.62680]])
rel("vl-fo-dc2", "connects to", "vl-pp-fo")
rel("vl-fo-dc2", "connects to", "vl-rtr-dc2")
rel("vl-sw-core", "connects to", "vl-pp-fo")
rel("vl-rtr-dc2", "connects to", "vl-fo-dc2")
rel("vl-bkp-01", "connects to", "vl-rtr-dc2")
for src in ("vl-srv-arch", "vl-kc", "vl-nas-01", "vl-svc-savres", "vl-svc-olog"):
    rel(src, "backed up to", "vl-bkp-01")
rel("vl-bkp-01", "backed up to", "vl-tape-01")

# ------------------------------------------------------------------------------------------------ electrical
asset("vl-ups-srv", "VL-UPS-SRV", "Server room UPS UPS-SRV", "UPS", argus_location="vl-room-server",
      rated_power_kva=40, autonomy_min=25, battery_installed_on="2025-06-10", inventory_number="VL-INV-TD-0410")
on_plan("vl-ups-srv", ADM0, "vl-room-server", 268, 100)
asset("vl-db-adm", "VL-DB-ADM", "Administration building distribution board DB-ADM", "Switchboard",
      argus_location="vl-bld-adm", board_level="building")
on_plan("vl-db-adm", ADM0, "vl-bld-adm", 250, 170)
rel("vl-msb", "powers", "vl-db-adm")
rel("vl-db-adm", "powers", "vl-ups-srv")
for r in ("vl-rk-s01", "vl-rk-s02", "vl-rk-s03"):
    rel("vl-ups-srv", "powers", r)
for r in ("vl-rk-a12-1", "vl-rk-a12-2"):
    rel("vl-dp-mag", "powers", r)
for r in ("vl-rk-a12-3", "vl-rk-ctrl"):
    rel("vl-ups-ctl", "powers", r)
for u in ("vl-kn1", "vl-kn2", "vl-kn3", "vl-nas-01"):
    rel("vl-rk-s01", "powers", u)
for u in ("vl-sw-core", "vl-sw-adm", "vl-fw"):
    rel("vl-rk-s02", "powers", u)
for u in ("vl-srv-ioc", "vl-srv-arch"):
    rel("vl-rk-s03", "powers", u)
asset("vl-cb-mcw", "VL-CB-MCW", "Breaker CB-MCW (magnet cooling pumps)", "Circuit Breaker",
      argus_location="vl-room-cooling", breaker_kind="MCCB", trip_curve="D")

# ------------------------------------------------------------------------------------------------ magnet cooling water
asset("vl-mcw-loop", "VL-MCW-LOOP", "Magnet and power supply cooling water (demineralised, 25 °C)", "Plant System",
      design_flow_m3h=18, supply_temp_c=25, conductivity_max_us_cm=0.5)
asset("vl-ch-mcw", "VL-CH-MCW", "Chiller CH-MCW (magnet water)", "Chiller", argus_location="vl-room-cooling",
      capacity_kw=120, refrigerant="R-1234ze", inventory_number="VL-INV-TD-0520")
asset("vl-hx-mcw", "VL-HX-MCW", "Heat exchanger HX-MCW", "Heat Exchanger", argus_location="vl-room-cooling",
      duty_kw=110)
asset("vl-p-mcw1", "VL-P-MCW1", "Magnet water pump P-MCW1 (duty)", "Water Pump", argus_location="vl-room-cooling",
      flow_m3h=18, head_m=32, motor_power_kw=5.5)
asset("vl-p-mcw2", "VL-P-MCW2", "Magnet water pump P-MCW2 (standby)", "Water Pump", argus_location="vl-room-cooling",
      flow_m3h=18, head_m=32, motor_power_kw=5.5)
UTL = PLANS["Utilities Building"]
for uid, x, y in (("vl-ch-mcw", 230, 95), ("vl-hx-mcw", 235, 155), ("vl-p-mcw1", 195, 155), ("vl-p-mcw2", 195, 125),
                  ("vl-cb-mcw", 268, 85)):
    on_plan(uid, UTL, "vl-room-cooling", x, y)
rel("vl-mcw-loop", "delivered by", "vl-hx-mcw")
rel("vl-hx-mcw", "cools", "vl-mcw-loop")
rel("vl-ch-mcw", "cools", "vl-hx-mcw")
rel("vl-mcw-loop", "redundantly delivered by", "vl-p-mcw1")
rel("vl-mcw-loop", "redundantly delivered by", "vl-p-mcw2")
rel("vl-dp-utl", "powers", "vl-cb-mcw")
for u in ("vl-p-mcw1", "vl-p-mcw2", "vl-ch-mcw"):
    rel("vl-cb-mcw", "powers", u)
cooled = ["vl-ps-q1", "vl-ps-q2", "vl-ps-q3", "vl-ps-q4", "vl-ps-q5", "vl-ps-q6", "vl-ps-dip", "vl-ps-sol"]
cooled += [u for u in db.scalars(select(Asset.uid).where(Asset.workspace_id == WS, Asset.uid.in_(
    [f"vl-unit-qua0{i}" for i in range(1, 7)] + ["vl-unit-dip01", "vl-unit-sol01"])))]
for u in cooled:
    rel("vl-mcw-loop", "cools", u)

# ------------------------------------------------------------------------------------------------ civil HVAC and user rooms
asset("vl-ahu-adm", "VL-AHU-ADM", "Administration building air handling unit AHU-ADM", "Air Handling Unit",
      argus_location="vl-bld-adm", airflow_m3h=6000)
asset("vl-crac-srv", "VL-CRAC-SRV", "Server room in-row cooler CRAC-SRV", "HVAC Equipment",
      argus_location="vl-room-server", capacity_kw=25)
on_plan("vl-crac-srv", ADM0, "vl-room-server", 320, 100)
for r in ("vl-rk-s01", "vl-rk-s02", "vl-rk-s03"):
    rel("vl-crac-srv", "cools", r)
rel("vl-ups-srv", "powers", "vl-crac-srv")
asset("vl-ac-ctrl", "VL-AC-CTRL", "Control room split air conditioner AC-CTRL", "HVAC Equipment",
      argus_location="vl-room-control", capacity_kw=7)
on_plan("vl-ac-ctrl", ACC, "vl-room-control", 650, 60)
rel("vl-ac-ctrl", "air-conditions", "vl-room-control")
ROOMS = [  # room, plan, label, desks [(x, y)], ext base
    ("vl-room-offices0", ADM0, "D0.01", [(60, 60), (120, 60), (60, 120), (180, 120)], 2100),
    ("vl-room-offices1", ADM1, "D1.01", [(60, 60), (120, 60), (180, 60), (60, 120), (120, 120)], 2200),
    ("vl-room-meeting", ADM1, "D1.02", [(285, 90)], 2290),
]
for room, plan, label, desks, ext in ROOMS:
    fcu = f"vl-fcu-{label.lower().replace('.', '')}"
    asset(fcu, f"VL-FCU-{label}", f"Fan coil unit FCU-{label}", "Fan Coil Unit", argus_location=room, capacity_kw=3.5)
    on_plan(fcu, plan, room, desks[0][0] + 20, desks[0][1] - 30)
    rel(fcu, "air-conditions", room)
    rel("vl-ahu-adm", "air-conditions", room)
    for i, (x, y) in enumerate(desks, start=1):
        out = f"vl-out-{label.lower().replace('.', '')}-{i}"
        asset(out, f"VL-OUT-{label}-{i}", f"Network outlet {label}-{i}", "Equipment Port", argus_location=room,
              port_label=f"{label}-{i}", port_kind="rj45", link_speed="1G", port_role="office outlet (PoE)")
        on_plan(out, plan, room, x, y + 12)
        rel(out, "connects to", "vl-pp-adm")
        phone = f"vl-tel-{label.lower().replace('.', '')}-{i}"
        asset(phone, f"VL-TEL-{ext + i}", f"IP phone ext. {ext + i} ({label})", "IT Peripheral",
              argus_location=room, peripheral_kind="IP phone", extension=str(ext + i), attached_to=out,
              model="Synthetica VP-30")
        on_plan(phone, plan, room, x, y)
        rel(phone, "connects to", out)
rel("vl-pp-adm", "connects to", "vl-sw-adm")
update("vl-room-offices0", occupants="Administration Office and Radiation Protection Service",
       services="IP telephony, fan coils, PoE network outlets")
update("vl-room-offices1", occupants="Technical Division and IT and Networks Service",
       services="IP telephony, fan coils, PoE network outlets")

# ------------------------------------------------------------------------------------------------ control room consoles
for i, (x, y) in ((3, (555, 95)), (4, (615, 95))):
    asset(f"vl-ws-op{i}", f"VL-OPI-{i}", f"Operator console OPI-{i}", "Workstation", argus_location="vl-room-control",
          workstation_role="operator console (Phoebus)", console_group="operations", os="Rocky Linux 9",
          inventory_number=f"VL-INV-CTRL-00{i}")
    on_plan(f"vl-ws-op{i}", ACC, "vl-room-control", x, y)
    rel(f"vl-ws-op{i}", "connects to", "vl-sw-ctl")
asset("vl-videowall", "VL-VIDEOWALL", "Control room video wall (4 × 55\")", "IT Peripheral",
      argus_location="vl-room-control", peripheral_kind="display wall")
on_plan("vl-videowall", ACC, "vl-room-control", 580, 24)

# ------------------------------------------------------------------------------------------------ radiation protection
asset("vl-rm-3", "VL-RM-3", "Neutron monitor RM-3 (bunker door)", "Radiation Monitor", argus_location="vl-room-corridor",
      detector_kind="neutron (rem counter)", alarm_threshold="10 µSv/h", calibration_due="2026-11-20")
on_plan("vl-rm-3", ACC, "vl-room-corridor", 470, 40)
for u in ("vl-rm-1", "vl-rm-2", "vl-rm-3"):
    rel(u, "maintained by", "vl-org-rp")
rel("vl-rm-3", "protects", "vl-room-corridor")

# ------------------------------------------------------------------------------------------------ who maintains what
for u in ("vl-tr-1", "vl-msb", "vl-db-acc", "vl-db-adm", "vl-ups-ctl", "vl-ups-srv", "vl-chiller", "vl-ch-mcw",
          "vl-p-mcw1", "vl-p-mcw2", "vl-hx-mcw", "vl-ahu-adm", "vl-ahu-bunker", "vl-ahu-gallery", "vl-ac-ctrl",
          "vl-crac-srv", "vl-mcw-loop", "vl-cw-loop"):
    if db.get(Asset, u):
        rel(u, "maintained by", "vl-org-td")
for u in ("vl-kc", "vl-nas-01", "vl-sw-core", "vl-sw-adm", "vl-fw", "vl-bkp-01", "vl-tape-01", "vl-rtr-dc2",
          "vl-fo-dc2", "vl-pp-adm"):
    rel(u, "maintained by", "vl-org-it")
for u in ("vl-epik8s", "vl-srv-ioc", "vl-srv-arch", "vl-moxa-01", "vl-sw-ctl", "vl-ws-op1", "vl-ws-op2",
          "vl-ws-op3", "vl-ws-op4"):
    if db.get(Asset, u):
        rel(u, "maintained by", "vl-org-ctrl")

# ------------------------------------------------------------------------------------------------ purchasing
POS = [
    ("vl-po-0412", "VL-PO-2026-0412", "Purchase order: Moxa NPort 5650-8 (two, one as spare)", 2980.0, "vl-org-it",
     "vl-budget-maint", "2026-02-10", "delivered", ["vl-moxa-01", "vl-moxa-spare"]),
    ("vl-po-0455", "VL-PO-2026-0455", "Purchase order: spare thyratron (Synthetica RF)", 18400.0, "vl-org-srf",
     "vl-budget-rf", "2026-09-02", "delivered", ["vl-sp-thy-01"]),
    ("vl-po-0501", "VL-PO-2026-0501", "Purchase order: three Kubernetes nodes and NAS", 61250.0, "vl-org-it",
     "vl-budget-maint", "2026-04-15", "delivered", ["vl-kn1", "vl-kn2", "vl-kn3", "vl-nas-01"]),
    ("vl-po-0520", "VL-PO-2026-0520", "Purchase order: magnet water chiller CH-MCW", 74800.0, "vl-org-cool",
     "vl-budget-maint", "2026-05-06", "delivered", ["vl-ch-mcw"]),
]
for uid, key, name, amount, vendor, budget, on, status, items in POS:
    asset(uid, key, name, "Purchase Order", po_number=key.replace("VL-", ""), ordered_from=vendor,
          budget_line=budget, ordered_on=on, amount_eur=amount, order_status=status)
    rel(uid, "with", vendor)
    for n, item in enumerate(items, start=1):
        if db.get(Asset, item):
            rel(item, "purchased with", uid)
            inv = (db.get(Asset, item).attributes or {}).get("inventory_number")
            update(item, purchase_order=key, inventory_number=inv or f"VL-INV-{key[-4:]}-{n:02d}")
asset("vl-inv-0455", "VL-INV-2026-0455", "Invoice for PO-2026-0455 (spare thyratron)", "Invoice",
      invoice_number="SRF-26-1187", issued_by="vl-org-srf", bills_order="vl-po-0455", issued_on="2026-10-01",
      due_on="2026-10-31", amount_eur=18400.0, payment_status="paid")
rel("vl-inv-0455", "for", "vl-po-0455")
asset("vl-inv-0501", "VL-INV-2026-0501", "Invoice for PO-2026-0501 (Kubernetes nodes)", "Invoice",
      invoice_number="SN-2026-0731", issued_by="vl-org-it", bills_order="vl-po-0501", issued_on="2026-06-20",
      due_on="2026-07-20", amount_eur=61250.0, payment_status="paid")
rel("vl-inv-0501", "for", "vl-po-0501")

# ------------------------------------------------------------------------------------------------ the MAD-X model and the test beam
from app.models.beam_model import BeamModelDocument, BeamModelValue  # noqa: E402
from app.services import beam_model_v2 as v2  # noqa: E402

row = db.scalar(select(BeamModelDocument).where(BeamModelDocument.workspace_id == WS,
                                                BeamModelDocument.model_id == "valmora-linac",
                                                BeamModelDocument.current.is_(True)))
doc = json.loads(json.dumps(row.document))
design = next(d for d in doc["datasets"] if d["id"] == "design-2026")
comps = {c["id"]: c for c in doc["components"]}
order = sorted(design["values"], key=lambda k: design["values"][k]["s"])
sys.path.insert(0, str(Path(__file__).resolve().parent))
from linac_demo_optics import match, twiss as _twiss  # noqa: E402
ELS = [(el, design["values"][el]["s"], (design["values"][el].get("physics") or {}).get("length", 0.0))
       for el in order if el in design["values"]]
QUADS = [q for q in order if comps.get(q, {}).get("type") == "quadrupole"]
TARGET, BETA_T = "SCR02", 2.4


def twiss(k):
    return _twiss(ELS, k)[0]


def c_design(k):
    o, worst = _twiss(ELS, k)
    return worst + 0.2 * abs(o[TARGET]["betx"] - o[TARGET]["bety"])


def c_tb(k):
    o, worst = _twiss(ELS, k)
    t = o[TARGET]
    return 10 * ((t["betx"] - BETA_T) ** 2 + (t["bety"] - BETA_T) ** 2) + 4 * (t["alfx"] ** 2 + t["alfy"] ** 2) + \
        (0 if worst < 40 else (worst - 40) ** 2)


k_design = {q: round(v, 3) for q, v in match(ELS, QUADS, c_design)[0].items()}
k_tb = {q: round(v, 3) for q, v in match(ELS, QUADS, c_tb, seed=11)[0].items()}
for q in QUADS:
    design["values"][q].setdefault("physics", {})["k1"] = k_design[q]
opt_design, opt_tb = twiss(k_design), twiss(k_tb)
E_DESIGN, E_TB = 0.125, 0.100                                   # GeV
BRHO_TB = E_TB / 0.299792458
GRAD_PER_A = 1.0                                                # T/m per A, the quadrupoles' excitation (synthetic)
supplies = {q: f"PS-Q{q[-1]}" for q in QUADS}
current = {q: round(abs(k_tb[q]) * BRHO_TB / GRAD_PER_A, 2) for q in QUADS}

design.update(simulator="MAD-X", simulator_version="5.09.03", source="valmora-linac.madx", git_commit="8e21d4b")
for el, o in opt_design.items():
    design["values"][el].setdefault("optics", {}).update(o)
tb_values = {}
for el in order:
    v = design["values"].get(el)
    if not v:
        continue
    phys = dict(v.get("physics") or {})
    if el in k_tb:
        phys["k1"] = k_tb[el]
    tb_values[el] = {"s": v["s"], "physics": phys, "optics": opt_tb[el]}
TB = {"id": "test-beam-2026-11", "name": "Test beam TB-2026-11 — 100 MeV, waist at SCR02 (MAD-X)",
      "kind": "commissioning", "category": "optics", "path": "linac-line",
      "source": "valmora-linac.madx (MATCH TB-2026-11)", "version": "2026.11", "git_commit": "c37a0f2",
      "simulator": "MAD-X", "simulator_version": "5.09.03", "generated_at": "2026-11-10T16:20:00+00:00",
      "valid_from": "2026-11-24", "valid_until": "2026-11-26",
      "configuration": {"energy_mev": 100, "bunch_charge_pc": 5, "target": TARGET, "beta_target_m": BETA_T,
                        "rf_off": ["ACC04"], "user_group": "DetLab (fictional)"},
      "values": tb_values}
doc["datasets"] = [d for d in doc["datasets"] if d["id"] != TB["id"]] + [TB]

# The records: the test beam dataset beside the design one, and every element's values in both.
key = lambda ident: f"{WS}:valmora-linac/{ident}"  # noqa: E731
subject = {el: db.scalar(select(Asset.uid).where(Asset.key == key(el))) for el in order}
design_uid = db.scalar(select(Asset.uid).where(Asset.key == key("dataset/design-2026")))
path_uid = db.scalar(select(Asset.uid).where(Asset.key == key("path/linac-line")))
update(design_uid, simulator="MAD-X", simulator_version="5.09.03", source="valmora-linac.madx", git_commit="8e21d4b")
tb_uid = str(uuid.uuid5(uuid.NAMESPACE_URL, key("dataset/test-beam-2026-11")))
asset(tb_uid, key("dataset/test-beam-2026-11"), TB["name"], "Model Dataset", dataset_kind="commissioning",
      model_id="valmora-linac", version=TB["version"], source=TB["source"], git_commit=TB["git_commit"],
      simulator="MAD-X", simulator_version="5.09.03", generated_at=TB["generated_at"], valid_from=TB["valid_from"],
      valid_until=TB["valid_until"])
rel(tb_uid, "models", path_uid)
for v in db.scalars(select(BeamModelValue).where(BeamModelValue.dataset_uid == design_uid)):
    el = next((e for e, u in subject.items() if u == v.subject_uid), None)
    if el is None:
        continue
    phys = dict(v.physics or {})
    if el in k_design:
        phys["k1"] = k_design[el]
    v.physics, v.optics = phys, {**(v.optics or {}), **opt_design.get(el, {})}
    if db.scalar(select(BeamModelValue).where(BeamModelValue.dataset_uid == tb_uid,
                                              BeamModelValue.subject_uid == v.subject_uid)) is None:
        db.add(BeamModelValue(workspace_id=WS, dataset_uid=tb_uid, subject_uid=v.subject_uid, path_uid=v.path_uid,
                              s=v.s, x=v.x, y=v.y, z=v.z, yaw=v.yaw, pitch=v.pitch, roll=v.roll,
                              physics=tb_values[el]["physics"], optics=tb_values[el]["optics"]))
row.current = False
db.flush()
db.add(BeamModelDocument(workspace_id=WS, model_id="valmora-linac", revision=v2.revision(doc), current=True,
                         document=doc, report={**(row.report or {}),
                                               "summary": {**(row.report or {}).get("summary", {}), "datasets": 3}},
                         imported_by="elena.varga@valmora-linac.example"))
db.flush()
print("beam model: test beam dataset", tb_uid, "values", len(tb_values))

MADX_TYPES = {"rf_gun": "RFCAVITY", "accelerating_structure": "RFCAVITY", "solenoid": "SOLENOID",
              "corrector": "KICKER", "bpm": "MONITOR", "screen": "INSTRUMENT", "faraday_cup": "INSTRUMENT",
              "current_transformer": "INSTRUMENT", "quadrupole": "QUADRUPOLE", "dipole": "SBEND", "beam_dump": "MARKER",
              "valve": "MARKER", "marker": "MARKER"}
lines = ["! Valmora linac (synthetic) — MAD-X model, revision 2026.1 (git 8e21d4b)",
         "! Element names are the ARGUS component ids; positions are the entry of each element.", "",
         "BEAM, PARTICLE=ELECTRON, ENERGY=0.125;", ""]
for el in order:
    c = comps.get(el)
    if not c:
        continue
    v = design["values"][el]
    L = (v.get("physics") or {}).get("length", 0.0)
    kind = MADX_TYPES.get(c["type"], "MARKER")
    extra = ""
    if kind == "QUADRUPOLE":
        extra = f", K1={k_design[el]:.4f}"
    elif kind == "RFCAVITY":
        extra = ", VOLT=0, FREQ=2998"
    elif kind == "SBEND":
        extra = f", ANGLE={(v.get('physics') or {}).get('angle', 0.0):.4f}"
    lines.append(f"{el}: {kind}{', L=' + format(L, 'g') if L and kind != 'MARKER' else ''}{extra};")
last = order[-1]
total = design["values"][last]["s"] + (design["values"][last].get("physics") or {}).get("length", 0.0)
lines += ["", f"LINAC: SEQUENCE, L={total:g}, REFER=ENTRY;"]
for el in order:
    if el in comps:
        lines.append(f"  {el}, AT={design['values'][el]['s']:g};")
lines += ["ENDSEQUENCE;", "", "USE, SEQUENCE=LINAC;",
          "TWISS, BETX=5.0, ALFX=0, BETY=5.0, ALFY=0, FILE=\"design.tfs\";", "",
          f"! Test beam TB-2026-11: 100 MeV, ACC04 off, a round parallel beam at SCR02 (beta {BETA_T} m)",
          "BEAM, PARTICLE=ELECTRON, ENERGY=0.100;",
          "MATCH, SEQUENCE=LINAC, BETX=5.0, ALFX=0, BETY=5.0, ALFY=0;"]
lines += [f"  VARY, NAME={q}->K1, STEP=1.0E-4;" for q in QUADS]
lines += [f"  CONSTRAINT, RANGE={TARGET}, BETX={BETA_T}, BETY={BETA_T}, ALFX=0, ALFY=0;",
          "  CONSTRAINT, SEQUENCE=LINAC, RANGE=#S/#E, BETX<40, BETY<40;", "  LMDIF, CALLS=2000, TOLERANCE=1.0E-8;",
          "ENDMATCH;", "TWISS, FILE=\"tb-2026-11.tfs\";"]
MADX = "\n".join(lines) + "\n"

rows = "\n".join(f"| {q} | {supplies[q]} | {k_design[q]:.3f} | {k_tb[q]:.3f} | {current[q]:.2f} |" for q in QUADS)
t = opt_tb[TARGET]
document("vl-doc-madx", "VL-MD-001", "MAD-X model of the Valmora linac", "Specification", f"""# MAD-X model of the Valmora linac

The beam model in ARGUS (*Beam model → Valmora Linac*) is this MAD-X lattice, imported with **+ New → Beam model**:
the element names are the ARGUS component ids, so each element is one record linked to its installed unit, its
power supply and its control channels. The design optics (dataset *Design layout 2026*) and the test beam optics
(dataset *Test beam TB-2026-11*) are datasets of the same model, each with its simulator, source file and git commit.

Repository: `git.valmora.example/beam-physics/valmora-linac-optics` (fictional), file `valmora-linac.madx`.

```
{MADX}```

## Using it with ARGUS

- **Upload a new revision** (the `.madx`, or the `.tfs` written by `TWISS`): ARGUS updates the same records and keeps
  the previous revision; a new dataset sits beside the design one.
- **From element to hardware**: QUA01 → its installed unit → `powers` ← PS-Q1 → IOC magnets-ps → the PVs.
- **Optimisation is done by the codes, not by ARGUS**: MAD-X `MATCH` (or Xsuite) runs where the physicists run it,
  reading the model and the current settings through the beamline MCP server; the result comes back as a dataset
  and as a proposed magnet set, which an operator confirms.
""", ["vl-unit-qua01", "vl-unit-qua02", "vl-unit-qua03", "vl-unit-qua04", "vl-unit-qua05", "vl-unit-qua06"]
         if db.get(Asset, "vl-unit-qua01") else [], "vl-u-elena")
document("vl-doc-tb", "VL-TB-001", "Test beam TB-2026-11: optics and magnet settings", "Test Report",
         f"""# Test beam TB-2026-11: optics and magnet settings

For the DetLab group (fictional): **100 MeV electrons, 1–5 pC, a round, parallel beam at screen SCR02** (24–26
November 2026): equal beta in both planes and no divergence there (a waist), for their detector's acceptance scan.
ACC04 is off; the quadrupoles are re-matched with MAD-X `MATCH` (model `VL-MD-001`, dataset *Test beam TB-2026-11*).

Result at {TARGET}: β<sub>x</sub> = {t['betx']:.2f} m, β<sub>y</sub> = {t['bety']:.2f} m, α<sub>x</sub> = {t['alfx']:.2f},
α<sub>y</sub> = {t['alfy']:.2f}; largest β along the line below 40 m.

| Quadrupole | Supply | k1 design (m⁻²) | k1 test beam (m⁻²) | Current (A) |
|---|---|---:|---:|---:|
{rows}

Currents from |k1| × Bρ (0.334 T·m at 100 MeV) ÷ 1.0 T/m per A (synthetic excitation); the sign of k1 is the
supply's polarity. With a normalised emittance of 1 µm the beam at SCR02 is about 0.1 mm (rms).

## How the settings reach the machine

1. The matched dataset is imported into ARGUS beside the design one.
2. Through the beamline MCP server, `apply_magnet_set` prepares the six currents as a **preview with a one-time
   code**; the shift leader confirms it within 10 minutes, PV by PV. A save-and-restore snapshot of the machine is
   taken first, so the design settings come back with one restore.
3. The run is logged in Olog with the dataset id and the snapshot.

Conditions: radiation work permit (ticket), RM-3 calibrated, beam dump DMP01 interlocked, spot measured on SCR02.
""", ["vl-ps-q1", "vl-ps-q2", "vl-ps-q3", "vl-ps-q4", "vl-ps-q5", "vl-ps-q6"], "vl-u-elena")
document("vl-doc-rp-tb", "VL-RP-001", "Radiation protection plan — test beam TB-2026-11", "Safety Document",
         """# Radiation protection plan — test beam TB-2026-11

- Beam power below 1 W at 100 MeV, 5 pC, 10 Hz; bunker closed and searched; PSS interlock on the bunker door.
- Monitors: RM-1 (gallery, γ), RM-2 (control room), **RM-3 (neutron, bunker door: calibration expired on 20 November —
  it must be renewed before the run)**. Alarm thresholds as in their records.
- DetLab users: electronic dosimeters, escorted access in the gallery only; no access to the bunker with beam on.
- Work under the radiation work permit; the Radiation Protection Service signs it off.
""", ["vl-rm-1", "vl-rm-2", "vl-rm-3", "vl-ra-bunker"], "vl-u-amira")
document("vl-doc-it", "VL-DR-003", "Controls computing: EPIK8s cluster, network and backups", "Design Report",
         """# Controls computing: EPIK8s cluster, network and backups

- **Cluster `vl-k8s`**: three nodes (`VL-K8S-N1..N3`, rack S01) and the IOC node `SRV-IOC` (rack S03), volumes on
  NAS-01. Everything is deployed by **EPIK8s** from `git.valmora.example/controls/epik8s-valmora-linac` through
  Argo CD (project `valmora-linac`): the seven IOCs, the Archiver Appliance, the Phoebus alarm server,
  save-and-restore, Olog, ChannelFinder and the ARGUS beamline MCP server.
- **Network**: controls 10.20.0.0/16 (VLAN 20) through SW-CORE (rack S02) and SW-CTL (control room); offices on SW-ADM
  with PoE for the IP phones; FW-1 to the campus.
- **Backups**: every night at 02:00 the archiver, the cluster (etcd and volumes), save-and-restore and Olog go to
  **BKP-01 in the Campus Data Centre**, over the fibre link FO-DC2-01 (420 m); BKP-01 writes a full copy to the LTO-9
  tape library every Sunday, and a tape leaves the building every month.
- **Restoring**: cluster and services are rebuilt from git by Argo CD; data from BKP-01. A lost fibre link stops
  the backups, not the machine.
""", ["vl-kc", "vl-epik8s", "vl-bkp-01", "vl-fo-dc2", "vl-sw-core"], "vl-u-noor")
document("vl-doc-purch", "VL-PR-003", "Purchasing: from request to inventory number", "Procedure",
         """# Purchasing: from request to inventory number

1. A **procurement request** ticket says what, why, for which budget line, and the quote.
2. The Administration Office issues the **purchase order** (record type Purchase Order: number, supplier, budget
   line, amount).
3. On delivery, a **goods receipt** ticket; the receiver checks the item against the order.
4. The item gets its **inventory number** (`VL-INV-…`) and label, and its record links the order (`purchased with`).
5. The **invoice** is recorded against the order and paid by the Administration Office.
""", [], "vl-u-amira")
ticket("vl-t-019", "Goods Receipt", "closed", "low", "Goods receipt: two Moxa NPort 5650-8 (PO-2026-0412)",
       "Two Moxa NPort 5650-8 delivered; one installed as VL-MOXA-01, one kept as spare VL-MOXA-SPARE (synthetic).",
       "vl-moxa-spare", "2026-02-24T10:00:00+00:00", "vl-u-noor", "vl-u-amira", "2026-02-24T15:00:00+00:00",
       comments=[("vl-u-amira", "Checked against PO-2026-0412; inventory numbers VL-INV-0412-01 and -02 assigned.")])
ticket("vl-t-020", "Procurement Request", "submitted", "medium", "Second spare thyratron for the modulators",
       "After the August trips and the 2026 run plan, a second spare thyratron is requested (budget line RF; quote "
       "SRF-Q-26-0921, EUR 18,900) (synthetic).", "vl-sp-thy-01", "2026-11-05T09:30:00+00:00", "vl-u-amira",
       "vl-u-jonas")
ticket("vl-t-021", "Safety Inspection", "new", "high", "RM-3 neutron monitor: calibration due before the test beam",
       "The calibration of RM-3 expires on 20 November; the test beam of 24 November needs it renewed first (synthetic).",
       "vl-rm-3", "2026-11-06T08:00:00+00:00", "vl-u-amira", "vl-u-amira")
ticket("vl-t-022", "Service Request", "in_progress", "high", "Test beam TB-2026-11 for DetLab: 100 MeV, round parallel beam at SCR02",
       "DetLab asks for 100 MeV electrons, 1–5 pC, a round parallel beam at SCR02, 24–26 November (synthetic).",
       "vl-unit-scr02" if db.get(Asset, "vl-unit-scr02") else None, "2026-10-28T11:00:00+00:00", "vl-u-elena",
       "vl-u-elena", comments=[("vl-u-elena", "Optics matched with MAD-X (VL-TB-001); magnet set ready as a "
                                              "proposal through the beamline MCP server.")])
ticket("vl-t-023", "Radiation Work Permit", "under_review", "high", "Radiation work permit: test beam TB-2026-11",
       "Work under beam for TB-2026-11; conditions in VL-RP-001 (synthetic).", "vl-ra-bunker",
       "2026-11-07T09:00:00+00:00", "vl-u-amira", "vl-u-elena")
ticket("vl-t-024", "Incident", "closed", "medium", "Archiver nightly backup to the Campus Data Centre failed",
       "The 02:00 backup of the archiver did not complete (synthetic).", "vl-srv-arch", "2026-10-15T07:30:00+00:00",
       "vl-u-noor", "vl-u-noor", "2026-10-15T12:00:00+00:00",
       attrs={"argus_root_cause": "Fibre link FO-DC2-01 down during the campus fibre maintenance (announced).",
              "argus_corrective_action": "Backup re-run at 11:00 after the link came back; maintenance windows now "
                                         "move the backup schedule."})
ticket("vl-t-025", "Service Request", "new", "low", "Fan coil FCU-D1.01 noisy, little cooling",
       "In the engineering offices the fan coil rattles and the room stays warm in the afternoon (synthetic).",
       "vl-fcu-d101", "2026-11-11T14:20:00+00:00", None, "vl-u-luca")
ticket("vl-t-026", "Service Request", "closed", "low", "New IP phone and two outlets for the radiation protection desk",
       "Desk moved in D0.01 (synthetic).", "vl-out-d001-4", "2026-09-01T09:00:00+00:00", "vl-u-noor", "vl-u-amira",
       "2026-09-03T16:00:00+00:00", comments=[("vl-u-noor", "Outlets D0.01-3/4 patched to SW-ADM ports 23–24; "
                                                            "phone ext. 2104 on the PoE VLAN.")])

db.commit()
from app.ledger.engine import derive_all  # noqa: E402
print("derived:", derive_all(db, [WS]))
db.commit()

# ------------------------------------------------------------------------------------------------ the floor plans show the racks
def draw(plan, items):
    path = Path(plan.storage_path)
    svg = path.read_text()
    add = "".join(f'<rect x="{x - 6}" y="{y - 6}" width="12" height="12" fill="#c7d2fe" stroke="#1e293b" stroke-width="1.5"/>'
                  f'<text x="{x}" y="{y + 17}" font-family="Helvetica, Arial, sans-serif" font-size="7" '
                  f'text-anchor="middle" fill="#1e293b">{label}</text>\n' for label, x, y in items if label not in svg)
    path.write_text(svg.replace("</svg>", add + "</svg>"))


draw(ADM0, [("RK-S01", 272, 148), ("RK-S02", 296, 148), ("RK-S03", 320, 148)])
draw(ACC, [("RK-A12-1", 611, 214), ("RK-A12-2", 611, 160), ("RK-A12-3", 645, 186), ("RK-CTRL", 560, 30)])

# ------------------------------------------------------------------------------------------------ the tour
steps = demo["steps"]
NEW = [
    {"link": "/assets/vl-room-service", "title": "Racks in the service area",
     "text": "Three racks hold the magnet supplies, the Moxa, the vacuum controller and its gauge module; each unit "
             "has its rack and position, and the plan shows where."},
    {"link": "/assets/vl-kc", "title": "Controls computing on EPIK8s",
     "text": "The Kubernetes cluster, its nodes, the services EPIK8s deploys from git, and the nightly backups to the "
             "Campus Data Centre over the fibre link."},
    {"link": "/assets/vl-mcw-loop", "title": "Magnet cooling water",
     "text": "The circuit that cools the magnets and their supplies: chiller, heat exchanger, two pumps in duty and "
             "standby — and what stops if it does."},
    {"link": "/documents/vl-doc-tb", "title": "A test beam from the MAD-X model",
     "text": "The MAD-X model is the beam model in ARGUS; the test beam's matched optics is a dataset of it, and the "
             "magnet settings go to the machine as a proposal an operator confirms."},
    {"link": "/assets/vl-po-0501", "title": "From purchase order to inventory number",
     "text": "Orders, invoices and goods receipts linked to the items they bought, with inventory numbers."},
]
links = {s["link"] for s in steps}
steps[len(steps) - 2:len(steps) - 2] = [s for s in NEW if s["link"] not in links]
demo["description"] = ("A medium-sized electron linac (fictional Valmora): buildings, floor plans and racks, the beam "
                       "model from MAD-X with design and test beam optics, RF, vacuum, magnets and their supplies, "
                       "magnet cooling water, electrical distribution, civil HVAC and offices with phones and network "
                       "outlets, controls on EPIK8s with backups to an external data centre, radiation protection, "
                       "purchasing with inventory numbers, tickets, runbooks and contracts.")

uids = {u for u in db.scalars(select(Asset.uid).where(Asset.workspace_id == WS)) if len(u) >= 6}
clash = []
for a in db.scalars(select(Asset).where(Asset.workspace_id == WS)):
    texts = [a.name] + [v for v in (a.attributes or {}).values() if isinstance(v, str)]
    for t in texts:
        for u in uids:
            if u != a.uid and u in t and not t == u:
                clash.append((a.uid, u, t[:60]))
assert not clash, clash[:10]

if OUT.exists():
    shutil.rmtree(OUT)
core.export(db, WS, OUT, actor=ACTOR, demo=demo)
print("made:", made, "| export:", OUT)
print(json.dumps({q: {"k1_design": k_design[q], "k1_tb": round(k_tb[q], 3), "I_A": current[q]} for q in QUADS}))
print("SCR02 design", opt_design[TARGET], "test beam", opt_tb[TARGET])
db.close()
