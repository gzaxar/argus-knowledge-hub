"""What a floor plan shows, layer by layer, drawn by ARGUS over the plan's own drawing (docs/plan-layers.md).

The uploaded drawing is the **base**: walls, rooms, doors, what the architect drew. ARGUS never writes on it.
Everything that comes from the records is drawn over it, in layers a person turns on and off:

- **places** — rooms and technical rooms (their outlines, where a plan is placed on the map) and accesses (doors,
  gates): on by default;
- **beamline** — the beamline components placed on the plan: on;
- **racks** — one point per rack, whatever it holds; opening it shows its elevation: on;
- **fixed** — the main fixed plant: klystrons, modulators, chillers, switchboards, UPS, air handling units…: on;
- **devices** — every other record placed on the plan: off;
- **paths** — routes crossing the plan (cables, pipes, fibres): off;
- **zones** — radiation, fire and access zones: off;
- **tickets** — open tickets on what is shown (a rack counts those of what it holds): off;
- **activities** — activities planned or under way, from yesterday to the next 30 days: off.

A unit mounted in a rack, or `located in` one, is not a point of its own: it is in its rack, which says how many
units it holds. Routes and outlines are shown only on a plan placed on the map (their coordinates are turned into
the plan's pixels); outlines that cover the whole plan (its building, the site) are left out.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.indoor import FloorPlan, IndoorPlacement
from app.models.issue import Issue
from app.models.rack import RackMounting
from app.services import indoor, spatial
from app.services.racks import RACK_TYPES
from app.services.visibility import reachable_in

LAYERS = [
    ("places", "Rooms and accesses", True),
    ("beamline", "Beamline", True),
    ("racks", "Racks", True),
    ("fixed", "Main fixed plant", True),
    ("devices", "Other devices", False),
    ("paths", "Cables and pipes", False),
    ("zones", "Zones", False),
    ("tickets", "Open tickets", False),
    ("activities", "Activities", False),
]

ACCESS_TYPES = {"Door", "Gate", "Hatch", "Emergency Exit", "Access Door", "Shielding Door"}
BEAMLINE_TYPES = {"Beamline Component", "Waveguide Section", "Shielding Element", "Survey Reference Point",
                  "Beam Dump", "Undulator", "Collimator"}
FIXED_TYPES = {
    "Klystron", "Modulator", "RF Station", "Chiller", "Heat Exchanger", "Water Pump", "Tank", "Air Handling Unit",
    "HVAC Equipment", "Switchboard", "Distribution Panel", "Transformer", "UPS", "Generator", "Air Compressor",
    "Laser System", "Cooling Tower", "Electronics Crate", "Power Distribution Unit", "Fan Coil Unit",
}
CLOSED_TICKETS = {"resolved", "closed"}


def layer_of(asset: Asset) -> str:
    t = asset.type or ""
    if t in RACK_TYPES:
        return "racks"
    if t in ACCESS_TYPES:
        return "places"
    if t in BEAMLINE_TYPES:
        return "beamline"
    if t in FIXED_TYPES:
        return "fixed"
    return "devices"


def outline_layer(asset: Asset) -> str:
    t = (asset.type or "").lower()
    return "zones" if "zone" in t or t.endswith(" area") and t != "area" else "places"


def _inside(pt: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            hit = not hit
    return hit


def _rack_holdings(db: Session, rack_uids: set[str]) -> dict[str, set[str]]:
    """Per rack, the units it holds: mounted in it, or `located in` it, or placed inside it."""
    held: dict[str, set[str]] = {r: set() for r in rack_uids}
    if not rack_uids:
        return held
    for rack, unit in db.execute(select(RackMounting.rack_uid, RackMounting.asset_uid).where(
            RackMounting.rack_uid.in_(rack_uids), RackMounting.state == "confirmed",
            RackMounting.asset_uid.is_not(None))):
        held[rack].add(unit)
    for unit, rack in db.execute(select(Relation.from_asset_uid, Relation.to_asset_uid).where(
            Relation.to_asset_uid.in_(rack_uids), Relation.relation_type == "located in")):
        held[rack].add(unit)
    for unit, rack in db.execute(select(IndoorPlacement.asset_uid, IndoorPlacement.place_uid).where(
            IndoorPlacement.place_uid.in_(rack_uids), IndoorPlacement.state == "confirmed")):
        held[rack].add(unit)
    return held


def _in_some_rack(db: Session, uids: set[str]) -> set[str]:
    """Which of these records are in a rack, by whichever way it was said."""
    if not uids:
        return set()
    out = set(db.scalars(select(RackMounting.asset_uid).where(RackMounting.asset_uid.in_(uids),
                                                              RackMounting.state == "confirmed")))
    out |= set(db.scalars(select(Relation.from_asset_uid).join(Asset, Asset.uid == Relation.to_asset_uid).where(
        Relation.from_asset_uid.in_(uids), Relation.relation_type == "located in", Asset.type.in_(RACK_TYPES))))
    out |= set(db.scalars(select(IndoorPlacement.asset_uid).join(Asset, Asset.uid == IndoorPlacement.place_uid).where(
        IndoorPlacement.asset_uid.in_(uids), IndoorPlacement.state == "confirmed", Asset.type.in_(RACK_TYPES))))
    return out


def _shapes(db: Session, plan: FloorPlan, may: Callable[[Asset], bool]) -> tuple[list[dict], list[dict]]:
    """(outlines, routes) crossing a plan placed on the map, in the plan's pixels."""
    if not plan.transform:
        return [], []
    w, h, t = plan.width_px, plan.height_px, plan.transform
    corners = indoor.corners(plan) or []
    lons, lats = [c[0] for c in corners], [c[1] for c in corners]
    bbox = (min(lons), min(lats), max(lons), max(lats))
    own = {plan.place_uid} | {c.uid for c in indoor.containers(db, plan.place_uid)}
    box = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    outlines, routes = [], []
    for asset, f in spatial.within(db, Asset.deleted_at.is_(None), bbox, limit=500):
        if f.role not in ("outline", "route") or asset.uid in own or not may(asset):
            continue
        if not reachable_in(asset, plan.workspace_id):
            continue                         # another workspace's record at the same spot (a copy, a neighbour)
        if plan.level_uid and f.role == "outline":
            # A room of another floor of the same building lies over this plan on the map, not on this floor.
            where = indoor.current(db, asset.uid)
            if where is not None and where.level_uid and where.level_uid != plan.level_uid:
                continue
        g = spatial.geojson(f.geometry)
        if f.role == "outline" and g.get("type") == "Polygon":
            ring = [indoor.to_plan(t, lon, lat) for lon, lat, *_ in g["coordinates"][0]]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) < 3 or all(_inside(c, ring) for c in box):
                continue
            outlines.append({"uid": asset.uid, "key": asset.key, "name": asset.name, "type": asset.type,
                             "layer": outline_layer(asset), "points": [[round(x, 1), round(y, 1)] for x, y in ring]})
        elif f.role == "route" and g.get("type") == "LineString":
            line = [indoor.to_plan(t, lon, lat) for lon, lat, *_ in g["coordinates"]]
            routes.append({"uid": asset.uid, "key": asset.key, "name": asset.name, "type": asset.type,
                           "layer": "paths", "points": [[round(x, 1), round(y, 1)] for x, y in line]})
    return outlines, routes


def layers(db: Session, plan: FloorPlan, may: Callable[[Asset], bool], *, may_read_tickets: Callable[[str], bool],
           activities_of: Optional[Callable[[], list]] = None) -> dict:
    """The plan and what it shows, layer by layer (the module's description)."""
    placed = [(a, p) for a, p in indoor.on_plan(db, plan.uid) if may(a)]
    uids = {a.uid for a, _ in placed}
    in_rack = _in_some_rack(db, uids)
    racks = {a.uid for a, _ in placed if a.type in RACK_TYPES}
    held = _rack_holdings(db, racks)
    visible_held = {r: {u for u in units if (x := db.get(Asset, u)) is not None and x.deleted_at is None and may(x)}
                    for r, units in held.items()}
    owner = {u: r for r, units in visible_held.items() for u in units}

    items = []
    for a, p in placed:
        if a.uid in in_rack and a.type not in RACK_TYPES:
            continue
        item = {"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "x": p.plan_x, "y": p.plan_y,
                "layer": layer_of(a), "tickets": 0, "activities": 0}
        if a.uid in racks:
            item["rack"] = {"holds": len(visible_held.get(a.uid, ())),
                            "mounted": db.scalar(select(RackMounting.uid).where(
                                RackMounting.rack_uid == a.uid, RackMounting.state == "confirmed").limit(1)) is not None}
        items.append(item)
    by_uid = {i["uid"]: i for i in items}

    def shown_as(asset_uid: Optional[str]) -> Optional[dict]:
        if not asset_uid:
            return None
        return by_uid.get(asset_uid) or by_uid.get(owner.get(asset_uid, ""))

    counted = set(by_uid) | set(owner)
    tickets = []
    if counted:
        for t in db.scalars(select(Issue).where(Issue.asset_uid.in_(counted), Issue.deleted_at.is_(None),
                                                Issue.state.notin_(CLOSED_TICKETS))):
            target = shown_as(t.asset_uid)
            if target is None or not may_read_tickets(t.workspace_id):
                continue
            target["tickets"] += 1
            tickets.append({"uid": t.uid, "key": t.key, "title": t.title, "state": t.state, "priority": t.priority,
                            "asset_uid": t.asset_uid, "shown_at": target["uid"]})

    activities = []
    for item in (activities_of() if activities_of else []):
        target = shown_as(getattr(item, "asset_uid", None))
        if target is None:
            continue
        target["activities"] += 1
        activities.append({"id": item.id, "title": item.title, "status": item.status,
                           "planned_start": item.planned_start, "asset_uid": item.asset_uid,
                           "shown_at": target["uid"]})

    outlines, routes = _shapes(db, plan, may)
    count = {k: 0 for k, _, _ in LAYERS}
    for i in items:
        count[i["layer"]] += 1
    for s in outlines + routes:
        count[s["layer"]] += 1
    count["tickets"], count["activities"] = len(tickets), len(activities)
    model = indoor._drawing(plan)
    return {**indoor.plan_out(db, plan),
            # A drawing ARGUS made knows its building's walls: routes are drawn inside them, not over the title.
            "building": model["building"] if model else None,
            "layers": [{"id": k, "label": label, "on": on, "count": count[k]} for k, label, on in LAYERS],
            "items": items, "outlines": outlines, "routes": routes, "tickets": tickets, "activities": activities,
            "in_racks": len(owner), "held": owner}


def drawn_over(db: Session, plan: FloorPlan) -> dict:
    """What ARGUS draws over the plan, in its pixels — every point (a rack for what it holds) and every route —
    for a drawing to keep its room labels clear of it (services/plan_drawing.py)."""
    view = layers(db, plan, lambda a: True, may_read_tickets=lambda w: True)
    return {"points": [(i["x"], i["y"]) for i in view["items"] if i["x"] is not None and i["y"] is not None],
            "lines": [r["points"] for r in view["routes"]]}


ACTIVITY_WINDOW = (timedelta(days=-1), timedelta(days=30))


# --------------------------------------------------------------------------- the 3D scene

# Relations that say where or what a record is, not how it works with others: the scene shows those by placing.
NOT_DRAWN = {"located in", "installation of", "installed at", "placed on", "in work package", "supplied by",
             "covered by", "with", "port of", "on segment", "realized by", "instance of", "part of"}
DEFAULT_MPP = 0.1


def metres_per_px(plan: FloorPlan) -> tuple[float, bool]:
    """The plan's scale, from its placement on the map; a tenth of a metre a pixel when it is not placed."""
    import math
    if not plan.transform:
        return DEFAULT_MPP, False
    t = plan.transform
    lon0, lat0 = indoor.to_lonlat(t, 0, 0)
    lon1, lat1 = indoor.to_lonlat(t, 1, 0)
    dx = (lon1 - lon0) * 111_320 * math.cos(math.radians(lat0))
    dy = (lat1 - lat0) * 110_540
    return round(math.hypot(dx, dy), 5) or DEFAULT_MPP, True


def scene(db: Session, plan: FloorPlan, may: Callable[[Asset], bool], *, may_read_tickets: Callable[[str], bool],
          activities_of: Optional[Callable[[], list]] = None) -> dict:
    """The plan's layers, and for a 3D view: its scale, the units in its racks at their units and face, and the
    relations between everything the plan shows (where things are is shown by placing them, not as lines)."""
    view = layers(db, plan, may, may_read_tickets=may_read_tickets, activities_of=activities_of)
    mpp, known = metres_per_px(plan)
    units = []
    for unit_uid, rack_uid in view["held"].items():
        a = db.get(Asset, unit_uid)
        m = db.scalar(select(RackMounting).where(RackMounting.asset_uid == unit_uid, RackMounting.state == "confirmed",
                                                 RackMounting.rack_uid == rack_uid))
        units.append({"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "rack_uid": rack_uid,
                      "start_u": m.start_u if m else None, "height_u": m.height_u if m else None,
                      "face": m.face if m else None, "kind": m.kind if m else None})
    shown = {i["uid"] for i in view["items"]} | {u["uid"] for u in units} | \
        {s["uid"] for s in view["outlines"] + view["routes"]}
    edges = []
    if shown:
        for r in db.scalars(select(Relation).where(Relation.from_asset_uid.in_(shown), Relation.to_asset_uid.in_(shown),
                                                   Relation.relation_type.notin_(NOT_DRAWN))):
            edges.append({"from": r.from_asset_uid, "to": r.to_asset_uid, "type": r.relation_type})
    return {**view, "metres_per_px": mpp, "scale_known": known, "units": units, "relations": edges}
