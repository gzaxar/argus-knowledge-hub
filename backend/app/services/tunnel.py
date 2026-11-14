"""The tunnel along a beam path (docs/plan-layers.md): the model's elements in order of `s`, and for each the hardware
installed there now, where that hardware is (its room, its point on a floor plan, the rack it is in), what powers it
and where that is, and its open tickets. Rooms the path crosses become bands along `s`, from the elements whose
hardware is in them — the model says where along the beam, the inventory says where in the building.

Nothing is made up: an element with no hardware installed shows as a position only; hardware with no room or plan
point says so.
"""
from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.beam_model import BeamAssetBinding
from app.models.issue import Issue
from app.services import beam_model as bm
from app.services import indoor, racks
from app.services.plan_layers import CLOSED_TICKETS

ROOMLESS = racks.RACK_TYPES


def _rack_of(db: Session, uid: str) -> Optional[Asset]:
    m = racks.mounting_of(db, uid)
    if m is not None:
        return db.get(Asset, m.rack_uid)
    r = db.scalar(select(Asset).join(Relation, Relation.to_asset_uid == Asset.uid).where(
        Relation.from_asset_uid == uid, Relation.relation_type == "located in", Asset.type.in_(racks.RACK_TYPES),
        Asset.deleted_at.is_(None)).limit(1))
    return r


def _room_of(db: Session, uid: str, may) -> Optional[Asset]:
    """The nearest place a record is in that is not a rack: through its rack if it is in one."""
    node = uid
    for _ in range(3):
        for c in indoor.containers(db, node):
            if c.type not in ROOMLESS:
                return c if may(c) else None
        rack = _rack_of(db, node)
        if rack is None or rack.uid == node:
            break
        node = rack.uid
    return None


def _brief(a: Optional[Asset]) -> Optional[dict]:
    return None if a is None else {"uid": a.uid, "key": a.key, "name": a.name, "type": a.type}


def tunnel(db: Session, workspace_id: str, path_uid: str, may: Callable[[Asset], bool], *,
           may_read_tickets: Callable[[str], bool], dataset_uid: Optional[str] = None) -> dict:
    from app.ledger.engine import installations_at, now
    g = bm.path_graph(db, workspace_id, path_uid, dataset_uid)
    at = now()
    rows = []
    for n in g["nodes"]:
        units: list[Asset] = []
        for v in installations_at(db, at, position_uid=n["uid"]):
            a = db.get(Asset, v["asset_uid"]) if v.get("asset_uid") else None
            if a is not None and a.deleted_at is None and a not in units:
                units.append(a)
        for b in db.scalars(select(BeamAssetBinding).where(BeamAssetBinding.component_uid == n["uid"],
                                                           BeamAssetBinding.status == "confirmed")):
            a = db.get(Asset, b.asset_uid)
            if a is not None and a.deleted_at is None and a not in units:
                units.append(a)
        hardware = []
        for a in units:
            if not may(a):
                continue
            supplies = []
            for s in bm._sources(db, "powers", [a.uid, n["uid"]]):
                if s.deleted_at is None and may(s) and s.uid not in {x["uid"] for x in supplies}:
                    supplies.append({**_brief(s), "rack": _brief(_rack_of(db, s.uid)),
                                     "room": _brief(_room_of(db, s.uid, may))})
            open_tickets = [t for t in db.scalars(select(Issue).where(
                Issue.asset_uid == a.uid, Issue.deleted_at.is_(None), Issue.state.notin_(CLOSED_TICKETS)))
                if may_read_tickets(t.workspace_id)]
            hardware.append({**_brief(a), "serial": (a.attributes or {}).get("serial"),
                             "room": _brief(_room_of(db, a.uid, may)), "rack": _brief(_rack_of(db, a.uid)),
                             "spot": indoor.spot(db, a.uid, may), "supplies": supplies,
                             "tickets": [{"uid": t.uid, "key": t.key, "title": t.title, "state": t.state}
                                         for t in open_tickets]})
        rows.append({"uid": n["uid"], "name": n["name"], "key": n.get("key"), "element_kind": n.get("element_kind"),
                     "s": n.get("s"), "length": n.get("length"), "index": n["index"], "hardware": hardware})

    with_s = [r for r in rows if r["s"] is not None]
    with_s.sort(key=lambda r: r["s"])
    bands: list[dict] = []
    for r in with_s:
        room = next((h["room"] for h in r["hardware"] if h["room"]), None)
        if room is None:
            continue
        end = r["s"] + (r["length"] or 0)
        if bands and bands[-1]["uid"] == room["uid"]:
            bands[-1]["to_s"] = max(bands[-1]["to_s"], end)
        else:
            bands.append({**room, "from_s": r["s"], "to_s": end})
    length = g.get("length") or max((r["s"] + (r["length"] or 0) for r in with_s), default=None)
    return {"path": g["path"], "topology": g.get("topology"), "length": length, "dataset_uid": g.get("dataset_uid"),
            "elements": rows if not with_s else with_s + [r for r in rows if r["s"] is None],
            "rooms": bands, "with_s": len(with_s) == len(rows) and bool(rows)}
