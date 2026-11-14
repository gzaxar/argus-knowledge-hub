"""A rack layout: what is mounted where in a workspace's racks, written as a file and applied through the rack service
(docs/rack-elevation.md, "Updating an imported demo").

A layout names records by the identifiers of the bundle they came from. In a clone where an identifier was taken,
the bundle import renamed it `uuid5(<workspace>, <identifier>)` (app/bundle/core.py); both are tried, so the same
file applies to the demo however it was imported.

    {"racks": [{"rack": "nf-rack-a02", "units": [
        {"asset": "nf-hv-01", "start_u": 20, "height_u": 2},
        {"asset": "nf-rdhx-a05", "kind": "zero_u", "face": "rear"},
        {"shelf": "Spares shelf", "start_u": 20, "height_u": 1},
        {"asset": "nf-ap-spare-01", "on_shelf": "Spares shelf"},
        {"reserve": "Hypervisor host 05", "start_u": 26, "height_u": 2}]}]}

Applying it changes only what differs: a unit already where the layout says is left alone (no new history row),
one elsewhere is moved, shelves and reserved spaces are matched by their label. Nothing is taken out and no record,
relation, ticket, document or attachment is touched. A unit mounted in a rack stops being a point of its own on a
floor plan (`points_to_rack`): it is placed inside its rack, which is the one point the plan shows.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.bundle.core import NAMESPACE
from app.models.asset import Asset
from app.services import indoor, racks


class LayoutError(Exception):
    pass


def resolve(db: Session, workspace_id: str, ref: str) -> Optional[Asset]:
    for uid in (ref, str(uuid.uuid5(NAMESPACE, f"{workspace_id}:{ref}"))):
        a = db.get(Asset, uid)
        if a is not None and a.workspace_id == workspace_id and a.deleted_at is None:
            return a
    return None


def _same(slot: racks.Slot, start, height, face, shelf_uid) -> bool:
    return (slot.start_u == start and slot.height_u == height and slot.face == face
            and (slot.shelf_uid or None) == (shelf_uid or None))


def apply(db: Session, workspace_id: str, layout: dict, *, actor: str, points_to_rack: bool = True,
          dry_run: bool = False) -> dict:
    """Apply the layout rack by rack. The caller commits. Returns what changed, what was already so, and what
    could not be found; a rack whose result would overlap or stick out is refused whole and reported."""
    report = {"changed": [], "unchanged": 0, "missing": [], "refused": [], "points_moved": 0}
    for spec in layout.get("racks", []):
        rack = resolve(db, workspace_id, spec["rack"])
        if rack is None:
            report["missing"].append(spec["rack"])
            continue
        now = racks.current(db, rack.uid)
        by_label = {s.label: s for s in now if s.kind in ("shelf", "reserved") and s.label}
        ops: list[dict] = []
        shelves: dict[str, str] = {}
        units: list[Asset] = []
        for u in spec.get("units", []):
            face = u.get("face", "front")
            if "shelf" in u or "reserve" in u:
                label = u.get("shelf") or u.get("reserve")
                kind = "shelf" if "shelf" in u else "reserved"
                have = by_label.get(label)
                if have is not None and have.kind == kind and _same(have, u.get("start_u"), u.get("height_u", 1), face, None):
                    shelves[label] = have.uid
                    report["unchanged"] += 1
                    continue
                if have is not None:
                    ops.append({"op": "remove", "mounting_uid": have.uid})
                ref = f"new:{label}"
                ops.append({"op": "shelf" if kind == "shelf" else "reserve", "start_u": u.get("start_u"),
                            "height_u": u.get("height_u", 1), "face": face, "label": label, "ref": ref,
                            "source": "layout"})
                shelves[label] = ref
                continue
            unit = resolve(db, workspace_id, u["asset"])
            if unit is None:
                report["missing"].append(u["asset"])
                continue
            units.append(unit)
            kind = u.get("kind", "device")
            shelf = shelves.get(u["on_shelf"]) if u.get("on_shelf") else None
            if u.get("on_shelf") and shelf is None:
                raise LayoutError(f"{u['asset']}: no shelf {u['on_shelf']!r} earlier in rack {spec['rack']}")
            height = 0 if kind == "zero_u" else u.get("height_u") or racks.suggested_height(db, unit) or 1
            start = None if kind == "zero_u" or shelf else u.get("start_u")
            here = racks.mounting_of(db, unit.uid)
            if here is not None and here.rack_uid == rack.uid and here.kind == kind and \
                    _same(racks._slot(here), start, height, face, shelf):
                report["unchanged"] += 1
                continue
            ops.append({"op": "place", "asset_uid": unit.uid, "kind": kind, "start_u": start, "height_u": height or None,
                        "face": face, "shelf_uid": shelf, "source": "layout",
                        **({"note": u["note"]} if u.get("note") else {})})
        if ops:
            result = racks.plan(db, rack, ops) if dry_run else racks.apply(db, rack, ops, actor)
            if not result["ok"]:
                report["refused"].append({"rack": rack.name, "problems": result["problems"]})
                continue
            report["changed"] += [f"{rack.name}: {c['text']}" for c in result["changes"]]
        if points_to_rack and not dry_run:
            for unit in units:
                p = indoor.current(db, unit.uid)
                if p is not None and p.plan_uid and p.place_uid != rack.uid:
                    indoor.place(db, unit, place_uid=rack.uid, actor=actor,
                                 note="in its rack: the rack is its point on the plan")
                    report["points_moved"] += 1
    return report
