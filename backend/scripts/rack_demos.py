"""Puts the demo bundles' units into their racks and cleans their floor plans, through the application, then exports
the bundle again (docs/rack-elevation.md, "The demos").

Run inside the API container with DATABASE_URL pointing at an EMPTY database (it is migrated here):

    PYTHONPATH=/app python scripts/rack_demos.py <bundle dir> <layout.json> <output dir>

1. The bundle is applied as its own workspace (the identifiers stay those of the files).
2. The rack layout is applied (app/services/rack_layout.py): each unit at its units, front or rear; a unit in a rack
   stops being a point of its own on the plan — its rack is.
2b. Before that, each rack gets its power: PDU A and PDU B (0U, rear) fed by two UPS and feeding every unit; on the
   linac the Kubernetes cluster stops being a box in a rack (the Moxa's serial lines are already there, port by port).
   The PDUs are written into the layout file, so an imported demo gets their places too.
3. Each floor plan's drawing keeps only the building: rooms, room numbers, the beam axis, north and the title. The
   unit markers and labels drawn into it before (a rectangle and a label in #1e293b) go: ARGUS draws the records
   over the drawing, by layer (docs/plan-layers.md). The building is then drawn as a room schedule
   (scripts/demo_plan_drawing.py): same geometry, labels that fit their rooms where no point or route covers
   them, column grid, doors, shielding.
3a. The linac's scintillator screens get a point each, just under the screen unit they are part of.
3b. Before that, inside each building a route (a cable, a pipe) runs along the gaps between rooms to the room it
   serves (scripts/demo_routes_inside.py): the part outside is kept.
4. The tour gains the plan by layers, a rack and (for a beam model) the tunnel; the bundle is exported with it.

Records, relations, tickets, documents and attachments are not touched: the export has the same identifiers plus the
rack mountings and the placements moved into racks. Running it again on its own output changes nothing.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC, LAYOUT, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
ACTOR = "ARGUS demo authors"

subprocess.run(["alembic", "upgrade", "head"], check=True, cwd="/app", capture_output=True)

from sqlalchemy import select, text  # noqa: E402

from app.bundle import core  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.asset import Asset  # noqa: E402
from app.models.indoor import FloorPlan  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import plan_layers, rack_layout  # noqa: E402

bundle = core.read(SRC)
WS, NAME = bundle.manifest["workspace"]["id"], bundle.manifest["workspace"]["name"]
db = SessionLocal()
assert db.get(Workspace, WS) is None, "use an empty database"
rep = core.apply(db, bundle, workspace_id=WS, name=NAME, actor=ACTOR, people_access=True, dry_run=False,
                 files_root=Path(f"/tmp/{WS}-files"))
assert rep.view()["ok"], rep.view()
assert not rep.renamed, rep.renamed[:5]
db.commit()
# A new workspace gets the installation's default icons and ticket values; the bundle carries its own.
for table in ("icons", "global_values"):
    keep = [json.loads(x)["uid"] for x in (SRC / "records" / f"{table}.jsonl").read_text().splitlines() if x.strip()]
    db.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w AND NOT (uid = ANY(:keep))"), {"w": WS, "keep": keep})
db.commit()

# ---- what makes the racks tell a story: their power (PDU A and B from two UPS) and, for the linac, a cluster
# that is not a box in a rack. Added once: a second run finds them there.
from app.ledger import engine as ledger_engine  # noqa: E402
from app.models.asset import Relation  # noqa: E402

layout = json.loads(LAYOUT.read_text())
EXTRAS = {
    "it-services-demo": {"prefix": "NF", "feeds": {"a": "nf-ups-01", "b": "nf-ups-02"},
                         "racks": ["nf-rack-a01", "nf-rack-a02", "nf-rack-a03", "nf-rack-a04", "nf-rack-a05",
                                   "nf-rack-a06", "nf-rack-mdf1", "nf-rack-b01"]},
    "valmora-linac-demo": {"prefix": "VL", "feeds": {"a": "vl-ups-srv", "b": "vl-ups-ctl"},
                           "racks": ["vl-rk-s01", "vl-rk-s02", "vl-rk-s03", "vl-rk-ctrl", "vl-rk-a12-3"]},
}


def relate(a: str, verb: str, b: str) -> None:
    if db.scalar(select(Relation.id).where(Relation.from_asset_uid == a, Relation.to_asset_uid == b,
                                           Relation.relation_type == verb)) is None:
        db.add(Relation(workspace_id=WS, from_asset_uid=a, to_asset_uid=b, relation_type=verb))


extra = EXTRAS.get(WS)
if extra:
    pdu_type = ledger_engine.ensure_type(db, WS, "Power Distribution Unit")
    for spec in layout["racks"]:
        if spec["rack"] not in extra["racks"]:
            continue
        rack = db.get(Asset, spec["rack"])
        # What the PDUs feed: the units, not the PDUs themselves (they are in the layout too, after a first run).
        units = [u["asset"] for u in spec["units"] if u.get("asset") and not u["asset"].startswith(f"{spec['rack']}-pdu-")]
        short = rack.name.split(" — ")[0].replace("Rack ", "")
        for side, ups in extra["feeds"].items():
            uid = f"{spec['rack']}-pdu-{side}"
            if db.get(Asset, uid) is None:
                db.add(Asset(uid=uid, workspace_id=WS, schema_uid=pdu_type.uid, type="Power Distribution Unit",
                             key=f"{extra['prefix']}-PDU-{short}-{side.upper()}", name=f"PDU {side.upper()} — {short}",
                             record_status="Active",
                             attributes={"argus_location": spec["rack"], "serial": f"SYN-PDU-{short}-{side.upper()}",
                                         "description": f"Rack PDU, feed {side.upper()} (synthetic)."}))
                db.flush()
            relate(ups, "powers", uid)
            for unit in units:
                relate(uid, "powers", unit)
            if not any(u.get("asset") == uid for u in spec["units"]):
                spec["units"].append({"asset": uid, "kind": "zero_u", "face": "rear",
                                      "note": f"feed {side.upper()} from {db.get(Asset, ups).name}"})
    # A PDU powering itself or its twin (an earlier run of this script made those): taken out.
    db.execute(text("DELETE FROM relations WHERE workspace_id = :w AND relation_type = 'powers' "
                    "AND from_asset_uid LIKE '%-pdu-_' AND to_asset_uid LIKE '%-pdu-_' "
                    "AND split_part(from_asset_uid, '-pdu-', 1) = split_part(to_asset_uid, '-pdu-', 1)"), {"w": WS})
    if WS == "valmora-linac-demo":
        # The Kubernetes cluster is its nodes (`part of` it), not a box in rack S01.
        kc = db.get(Asset, "vl-kc")
        if (kc.attributes or {}).get("argus_location"):
            kc.attributes = {k: v for k, v in kc.attributes.items() if k != "argus_location"}
        db.execute(text("DELETE FROM relations WHERE from_asset_uid = 'vl-kc' AND relation_type = 'located in'"))
    db.commit()
    ledger_engine.derive_located_in(db, [WS])
    db.commit()
    LAYOUT.write_text(json.dumps(layout, indent=1) + "\n")       # the PDUs' places, for imported demos too

report = rack_layout.apply(db, WS, layout, actor=ACTOR)
assert not report["missing"] and not report["refused"], report
db.commit()
print(f"racks: {len(report['changed'])} changes, {report['unchanged']} already so, "
      f"{report['points_moved']} plan points moved into their racks")

# ---- the drawings keep the building only, drawn as a room schedule (scripts/demo_plan_drawing.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_plan_drawing import redraw  # noqa: E402

# ---- inside a building, a cable or pipe runs along the gaps between rooms to the room it serves
# (scripts/demo_routes_inside.py): only the part inside the building is redrawn, the map keeps the rest.
from demo_routes_inside import inside as in_box, reroute  # noqa: E402

from app.models.spatial import SpatialFeature  # noqa: E402
from app.services import indoor, spatial  # noqa: E402

from app.models.indoor import PlaceLevel  # noqa: E402

drawn_plans = []
for plan in db.scalars(select(FloorPlan).where(FloorPlan.workspace_id == WS).order_by(FloorPlan.name)):
    model = indoor._drawing(plan) if plan.transform else None
    if model and model.get("building") and model.get("rooms"):
        level = db.get(PlaceLevel, plan.level_uid) if plan.level_uid else None
        drawn_plans.append((plan, tuple(model["building"]), [tuple(r["box"]) for r in model["rooms"]],
                            abs(level.ordinal) if level else 0))
# A cable comes into a building at the ground floor: of a building's floors, the ground one is tried first.
drawn_plans.sort(key=lambda d: (d[0].place_uid, d[3], d[0].name))


def to_geo(t: dict, x: float, y: float) -> list[float]:
    return [round(t["c"] + t["a"] * x + t["b"] * y, 8), round(t["f"] + t["d"] * x + t["e"] * y, 8)]


rerouted = 0
routes = db.scalars(select(SpatialFeature).where(SpatialFeature.workspace_id == WS, SpatialFeature.role == "route",
                                                 SpatialFeature.state == "confirmed",
                                                 SpatialFeature.valid_until.is_(None)))
for feature in list(routes):
    coords = [list(c[:2]) for c in spatial.geojson(feature.geometry)["coordinates"]]
    before = [list(c) for c in coords]
    for place in dict.fromkeys(d[0].place_uid for d in drawn_plans):
        floors = []
        for plan, building, rooms, _ in (d for d in drawn_plans if d[0].place_uid == place):
            pts = [indoor.to_plan(plan.transform, lon, lat) for lon, lat in coords]
            ends = [q for q in (pts[0], pts[-1]) if in_box(q, building)]
            if len(ends) == 1:
                floors.append((plan, building, rooms, pts, any(in_box(ends[0], r) for r in rooms)))
        if not floors:
            continue
        # The floor whose rooms hold the route's end, the lowest first; else the lowest.
        plan, building, rooms, pts, _ = next((f for f in floors if f[4]), floors[0])
        new = reroute(pts, building, rooms)
        if new:
            coords = [to_geo(plan.transform, x, y) for x, y in new]
    if coords != before:
        asset = db.get(Asset, feature.subject_uid)
        spatial.set_location(db, asset, {"type": "LineString", "coordinates": coords}, actor=ACTOR, role="route",
                             note="inside the buildings, along the gaps between rooms to the room it serves")
        rerouted += 1
db.commit()
print(f"routes: {rerouted} run inside their buildings along the gaps between rooms")

# ---- what a beamline unit holds is shown with it: the linac's scintillator screens, a point each just under the
# screen unit they are part of on the bunker's plan (an asset with no point there is otherwise offered one).
if WS == "valmora-linac-demo":
    for screen_key, unit_key in (("VL-SCN-1", "VL-U-SCR01"), ("VL-SCN-2", "VL-U-SCR02"), ("VL-SCN-3", "VL-U-SCR03")):
        screen = db.scalar(select(Asset).where(Asset.workspace_id == WS, Asset.key == screen_key))
        unit = db.scalar(select(Asset).where(Asset.workspace_id == WS, Asset.key == unit_key))
        where = indoor.current(db, unit.uid) if unit is not None else None
        mine = indoor.current(db, screen.uid) if screen is not None else None
        if screen is None or where is None or not where.plan_uid or (mine is not None and mine.plan_uid):
            continue
        indoor.place(db, screen, place_uid=where.place_uid, level_uid=where.level_uid, plan_uid=where.plan_uid,
                     x=where.plan_x, y=where.plan_y + 7, actor=ACTOR, note=f"with {unit_key}, the unit it is part of")
        print(f"{screen_key}: on the plan with {unit_key}")
    db.commit()

MARK = re.compile(r'<rect [^>]*stroke="#1e293b"[^>]*/>\s*<text [^>]*fill="#1e293b"[^>]*>[^<]*</text>\s*')
plans = list(db.scalars(select(FloorPlan).where(FloorPlan.workspace_id == WS)))
for plan in plans:
    path = Path(plan.storage_path)
    svg = path.read_text()
    clean = MARK.sub("", svg)
    if clean != svg:
        print(f"{plan.name}: {len(MARK.findall(svg))} unit markers taken out of the drawing")
    drawn = redraw(clean, plan_layers.drawn_over(db, plan))       # room labels clear of the points and routes
    if drawn != svg:
        path.write_text(drawn)
        print(f"{plan.name}: redrawn")
db.commit()

# ---- the tour
demo = bundle.manifest["demo"]
steps = demo["steps"]
links = {s["link"] for s in steps}
busiest = max(layout["racks"], key=lambda r: len(r["units"]))["rack"]
main_plan = max(plans, key=lambda p: db.scalar(text("SELECT count(*) FROM indoor_placements WHERE plan_uid = :p "
                                                    "AND state = 'confirmed'"), {"p": p.uid}) or 0)
rack = db.get(Asset, busiest)
new = [
    {"link": f"/plans/{main_plan.uid}", "title": "The plan, layer by layer",
     "text": f"{main_plan.name}: the drawing shows the building; rooms, racks and plant are drawn over it and can be "
             "turned on and off, with open tickets and activities. A rack is one point: click it to open it."},
    {"link": f"/racks/{busiest}", "title": "Inside a rack, unit by unit",
     "text": f"{rack.name}: front and rear, what takes which units, the free space and the space kept for what is "
             "coming. Moving a unit is previewed before it is saved, and the rack keeps its history."},
]
if db.scalar(text("SELECT count(*) FROM assets WHERE workspace_id = :w AND type = 'Beam Path'"), {"w": WS}):
    new.append({"link": "/tunnel", "title": "The tunnel along the beam",
                "text": "The beam model to scale along s, the rooms it crosses, and at each element the hardware "
                        "installed there: its room, its rack, the supply that powers it and that supply's rack."})
at = next((i + 1 for i, s in enumerate(steps) if "rack" in s["title"].lower()), 3)
steps[at:at] = [s for s in new if s["link"] not in links]

if OUT.exists():
    shutil.rmtree(OUT)
core.export(db, WS, OUT, actor=ACTOR, demo=demo)
print("exported:", OUT)
db.close()
