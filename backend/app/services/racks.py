"""A rack's elevation: what is mounted where, checked, previewed and changed (docs/rack-elevation.md).

Every change is a list of operations. `plan` works them out on a copy and says what would change and what is
wrong; `apply` does the same and, when nothing is wrong, writes: the old row is closed, a new one opened, so a
unit's moves stay readable. A photograph read on the phone ends here too, as the same operations with their
evidence.
"""
import uuid
from dataclasses import dataclass, field, replace
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.mixins import utcnow
from app.models.rack import FACES, KINDS, RackMounting

DEFAULT_UNITS = 42
RACK_TYPES = {"Rack"}
# What is never bolted into a rack: places, ports and cables (they belong to a unit), and records that are not
# hardware. A type a workspace adds is offered: the person mounting it knows.
NOT_MOUNTED = RACK_TYPES | {
    "Location", "Room", "Building", "Area", "Storage", "Storage Location", "Equipment Port", "Cable Run",
    "Ethernet Cable", "Fibre Cable", "Fibre Link", "Software Product", "Software License", "Network Segment", "IT Service", "Product Model", "Vendor", "Organization",
    "Contract", "Purchase Order", "Invoice", "Budget Line", "Software Version", "Software Licence", "Installation",
    "Equipment Position", "Work Package", "Virtual Machine",
}


class RackError(ValueError):
    pass


@dataclass
class Slot:
    """One mounting as the checks see it: a row of the table, or one an operation would make."""
    uid: str
    asset_uid: Optional[str]
    kind: str
    start_u: Optional[int]
    height_u: int
    face: str
    shelf_uid: Optional[str] = None
    label: Optional[str] = None
    note: Optional[str] = None
    source: str = "manual"
    evidence: Optional[dict] = None
    row: Optional[RackMounting] = field(default=None, compare=False)   # the stored row, when it is one

    @property
    def top_u(self) -> Optional[int]:
        return None if self.start_u is None else self.start_u + max(self.height_u, 1) - 1

    def takes_units(self) -> bool:
        """A 0U device and a unit standing on a shelf take no unit of their own."""
        return self.kind != "zero_u" and self.shelf_uid is None and self.start_u is not None


def rack_of(db: Session, uid: str) -> Asset:
    rack = db.get(Asset, uid)
    if rack is None or rack.deleted_at is not None:
        raise RackError("no such rack")
    if rack.type not in RACK_TYPES:
        raise RackError(f"{rack.name} is a {rack.type}, not a rack")
    return rack


def units_of(rack: Asset) -> int:
    try:
        n = int((rack.attributes or {}).get("rack_units") or DEFAULT_UNITS)
    except (TypeError, ValueError):
        n = DEFAULT_UNITS
    return n if 1 <= n <= 100 else DEFAULT_UNITS


def _slot(row: RackMounting) -> Slot:
    return Slot(uid=row.uid, asset_uid=row.asset_uid, kind=row.kind, start_u=row.start_u, height_u=row.height_u,
                face=row.face, shelf_uid=row.shelf_uid, label=row.label, note=row.note, source=row.source,
                evidence=row.evidence, row=row)


def current(db: Session, rack_uid: str) -> list[Slot]:
    rows = db.scalars(select(RackMounting).where(RackMounting.rack_uid == rack_uid, RackMounting.state == "confirmed")
                      .order_by(RackMounting.start_u.desc().nullslast(), RackMounting.uid))
    return [_slot(r) for r in rows]


def mounting_of(db: Session, asset_uid: str) -> Optional[RackMounting]:
    """Where a unit is mounted now, in whichever rack."""
    return db.scalar(select(RackMounting).where(RackMounting.asset_uid == asset_uid,
                                                RackMounting.state == "confirmed"))


def suggested_height(db: Session, asset: Asset) -> Optional[int]:
    """How many units a unit probably takes: what it says itself, else what its product model says. A suggestion:
    the person mounting it has the last word."""
    for source in (asset, _model_of(db, asset)):
        value = (source.attributes or {}).get("rack_units") if source is not None else None
        try:
            if value not in (None, ""):
                return max(1, int(round(float(value))))
        except (TypeError, ValueError):
            continue
    return None


def _model_of(db: Session, asset: Asset) -> Optional[Asset]:
    ref = (asset.attributes or {}).get("product_model")
    if not isinstance(ref, str) or not ref:
        return None
    return db.get(Asset, ref) or db.scalar(select(Asset).where(or_(Asset.key == ref, Asset.name == ref)).limit(1))


# --- the checks --------------------------------------------------------------------------------------------------

def _faces(slot: Slot) -> set[str]:
    return {"front", "rear"} if slot.face == "both" else {slot.face}


def problems(slots: list[Slot], units: int, names: dict[str, str]) -> list[dict]:
    """What is wrong with a set of mountings: outside the rack, two things in one unit, a unit twice, a shelf
    that is not there."""
    out: list[dict] = []
    name = lambda s: names.get(s.asset_uid or "", s.label or s.kind)  # noqa: E731
    by_uid = {s.uid: s for s in slots}
    seen: dict[str, Slot] = {}
    for s in slots:
        if s.kind not in KINDS:
            out.append({"code": "kind", "mounting": s.uid, "message": f"{s.kind} is not a kind of mounting"})
        if s.face not in FACES:
            out.append({"code": "face", "mounting": s.uid, "message": f"{s.face} is not front, rear or both"})
        if s.asset_uid:
            if s.asset_uid in seen:
                out.append({"code": "twice", "mounting": s.uid, "asset_uid": s.asset_uid,
                            "message": f"{name(s)} is mounted twice"})
            seen[s.asset_uid] = s
        elif s.kind in ("device", "zero_u"):
            out.append({"code": "nothing", "mounting": s.uid, "message": "a device mounting names its unit"})
        if s.shelf_uid:
            shelf = by_uid.get(s.shelf_uid)
            if shelf is None or shelf.kind != "shelf":
                out.append({"code": "shelf", "mounting": s.uid, "message": f"{name(s)} stands on a shelf that is not in this rack"})
            continue
        if s.kind == "zero_u":
            continue
        if s.start_u is None or s.height_u < 1:
            out.append({"code": "unit", "mounting": s.uid, "message": f"{name(s)} needs a first unit and a height"})
            continue
        if s.start_u < 1 or s.top_u > units:
            out.append({"code": "capacity", "mounting": s.uid, "asset_uid": s.asset_uid,
                        "message": f"{name(s)} would take U{s.start_u}–U{s.top_u}: the rack has U1–U{units}"})
    taking = [s for s in slots if s.takes_units() and s.height_u >= 1]
    for i, a in enumerate(taking):
        for b in taking[i + 1:]:
            if a.start_u <= b.top_u and b.start_u <= a.top_u and _faces(a) & _faces(b):
                lo, hi = max(a.start_u, b.start_u), min(a.top_u, b.top_u)
                where = f"U{lo}" if lo == hi else f"U{lo}–U{hi}"
                side = ", ".join(sorted(_faces(a) & _faces(b)))
                out.append({"code": "overlap", "mounting": b.uid, "with": a.uid, "asset_uid": b.asset_uid,
                            "message": f"{name(b)} and {name(a)} both take {where} ({side})"})
    return out


def free_ranges(slots: list[Slot], units: int, face: str) -> list[dict]:
    """The runs of empty units on one face, lowest first."""
    taken = set()
    for s in slots:
        if s.takes_units() and face in _faces(s):
            taken.update(range(s.start_u, s.top_u + 1))
    out, start = [], None
    for u in range(1, units + 2):
        if u <= units and u not in taken:
            start = u if start is None else start
        elif start is not None:
            out.append({"from_u": start, "to_u": u - 1, "units": u - start})
            start = None
    return out


# --- reading -----------------------------------------------------------------------------------------------------

def _names(db: Session, slots: list[Slot]) -> dict[str, Asset]:
    uids = [s.asset_uid for s in slots if s.asset_uid]
    return {a.uid: a for a in db.scalars(select(Asset).where(Asset.uid.in_(uids)))} if uids else {}


def _view(slot: Slot, assets: dict[str, Asset]) -> dict:
    a = assets.get(slot.asset_uid or "")
    return {"uid": slot.uid, "kind": slot.kind, "start_u": slot.start_u, "height_u": slot.height_u,
            "top_u": slot.top_u if slot.takes_units() else None, "face": slot.face, "shelf_uid": slot.shelf_uid,
            "label": slot.label, "note": slot.note, "source": slot.source, "evidence": slot.evidence,
            "asset": {"uid": a.uid, "key": a.key, "name": a.name, "type": a.type} if a is not None else None,
            "since": slot.row.valid_from.isoformat() if slot.row is not None and slot.row.valid_from else None}


def elevation(db: Session, rack: Asset, slots: Optional[list[Slot]] = None) -> dict:
    slots = current(db, rack.uid) if slots is None else slots
    assets = _names(db, slots)
    units = units_of(rack)
    names = {uid: a.name for uid, a in assets.items()}
    used = {f: units - sum(r["units"] for r in free_ranges(slots, units, f)) for f in ("front", "rear")}
    return {"rack": {"uid": rack.uid, "key": rack.key, "name": rack.name, "units": units,
                     "workspace_id": rack.workspace_id},
            "mountings": [_view(s, assets) for s in slots],
            "free": {f: free_ranges(slots, units, f) for f in ("front", "rear")},
            "used_units": used,
            "problems": problems(slots, units, names),
            "plan": _plan_of(db, rack),
            "unplaced": unplaced(db, rack, slots)}


def unplaced(db: Session, rack: Asset, slots: list[Slot]) -> list[dict]:
    """Units said to be in the rack (`located in` it, or placed inside it) that have no position in it yet: to be
    mounted, with the height their model suggests. Ports, cables and the like are not units."""
    from app.models.asset import Relation
    from app.models.indoor import IndoorPlacement
    here = {s.asset_uid for s in slots if s.asset_uid}
    uids = set(db.scalars(select(Relation.from_asset_uid).where(Relation.to_asset_uid == rack.uid,
                                                                Relation.relation_type == "located in")))
    uids |= set(db.scalars(select(IndoorPlacement.asset_uid).where(IndoorPlacement.place_uid == rack.uid,
                                                                   IndoorPlacement.state == "confirmed")))
    out = []
    for uid in sorted(uids - here):
        a = db.get(Asset, uid)
        if a is None or a.deleted_at is not None or a.type in NOT_MOUNTED or mounting_of(db, uid) is not None:
            continue
        out.append({"uid": a.uid, "key": a.key, "name": a.name, "type": a.type,
                    "serial": (a.attributes or {}).get("serial"), "suggested_height_u": suggested_height(db, a),
                    "mounted": None})
    return sorted(out, key=lambda c: c["name"])


def _plan_of(db: Session, rack: Asset) -> Optional[dict]:
    """The floor plan the rack is a point on, to go back to it with its layers."""
    from app.models.indoor import FloorPlan
    from app.services import indoor
    p = indoor.current(db, rack.uid)
    plan = db.get(FloorPlan, p.plan_uid) if p is not None and p.plan_uid else None
    return {"uid": plan.uid, "name": plan.name} if plan is not None else None


def history(db: Session, rack_uid: str, limit: int = 200) -> list[dict]:
    rows = list(db.scalars(select(RackMounting).where(RackMounting.rack_uid == rack_uid)
                           .order_by(RackMounting.created_at.desc(), RackMounting.uid).limit(limit)))
    assets = _names(db, [_slot(r) for r in rows])
    return [{**_view(_slot(r), assets), "state": r.state, "by": r.confirmed_by,
             "from": r.valid_from.isoformat() if r.valid_from else None,
             "until": r.valid_until.isoformat() if r.valid_until else None} for r in rows]


# --- changing ----------------------------------------------------------------------------------------------------

def _int(value, what: str, least: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise RackError(f"{what} is a whole number")
    if n < least:
        raise RackError(f"{what} is at least {least}")
    return n


def _work_out(db: Session, rack: Asset, ops: list[dict]) -> tuple[list[Slot], list[Slot], list[dict]]:
    """The mountings after the operations, the stored ones they close, and what changes, in words."""
    slots = current(db, rack.uid)
    closed: list[Slot] = []
    changes: list[dict] = []
    assets: dict[str, Asset] = {}
    refs: dict[str, str] = {}

    def asset(uid: str) -> Asset:
        if uid not in assets:
            a = db.get(Asset, uid)
            if a is None or a.deleted_at is not None:
                raise RackError(f"no record {uid}")
            if a.type in RACK_TYPES:
                raise RackError(f"{a.name} is a rack: a rack is not mounted in a rack")
            assets[uid] = a
        return assets[uid]

    def where(s: Slot) -> str:
        if s.shelf_uid:
            return "on a shelf"
        if s.kind == "zero_u" or s.start_u is None:
            return "0U"
        span = f"U{s.start_u}" if s.height_u <= 1 else f"U{s.start_u}–U{s.top_u}"
        return f"{span} {s.face}"

    def drop(s: Slot) -> None:
        slots.remove(s)
        if s.row is not None:
            closed.append(s)

    for i, op in enumerate(ops):
        what = str(op.get("op") or "")
        if what in ("place", "shelf", "reserve"):
            kind = {"place": str(op.get("kind") or "device"), "shelf": "shelf", "reserve": "reserved"}[what]
            if what == "place" and kind not in ("device", "zero_u"):
                raise RackError("place puts a device or a 0U device: use shelf or reserve for the others")
            unit = asset(str(op["asset_uid"])) if op.get("asset_uid") else None
            if what == "place" and unit is None:
                raise RackError("place names the unit (asset_uid)")
            # A shelf made earlier in the same change is named by the `ref` it was given there.
            shelf_uid = refs.get(str(op.get("shelf_uid")), op.get("shelf_uid")) or None
            zero = kind == "zero_u"
            height = 0 if zero else _int(op.get("height_u") or (suggested_height(db, unit) if unit else None) or 1,
                                         "the height in units")
            start = None if zero or shelf_uid else _int(op.get("start_u"), "the first unit")
            new = Slot(uid=str(uuid.uuid4()), asset_uid=unit.uid if unit else None, kind=kind,
                       start_u=start, height_u=height, face=str(op.get("face") or "front"), shelf_uid=shelf_uid,
                       label=(str(op["label"]).strip() or None) if op.get("label") else None,
                       note=(str(op["note"]).strip() or None) if op.get("note") else None,
                       source=str(op.get("source") or "manual"), evidence=op.get("evidence") or None)
            before = None
            if unit is not None:
                here = next((s for s in slots if s.asset_uid == unit.uid), None)
                elsewhere = None if here else mounting_of(db, unit.uid)
                if here is not None:
                    before = f"{where(here)}"
                    drop(here)
                elif elsewhere is not None:
                    other = db.get(Asset, elsewhere.rack_uid)
                    before = f"{other.name if other else 'another rack'}, {where(_slot(elsewhere))}"
                    closed.append(_slot(elsewhere))
            slots.append(new)
            if op.get("ref"):
                refs[str(op["ref"])] = new.uid
            name = unit.name if unit else (new.label or kind)
            changes.append({"op": what, "mounting": new.uid, "asset_uid": new.asset_uid, "name": name,
                            "before": before, "after": where(new),
                            "text": f"{name}: {before + ' → ' if before else ''}{where(new)}"})
        elif what == "update":
            s = next((x for x in slots if x.uid == op.get("mounting_uid")), None)
            if s is None:
                raise RackError("no such mounting in this rack")
            new = replace(s, uid=str(uuid.uuid4()), row=None,
                          start_u=_int(op["start_u"], "the first unit") if "start_u" in op and op["start_u"] is not None else s.start_u,
                          height_u=_int(op["height_u"], "the height in units") if op.get("height_u") is not None else s.height_u,
                          face=str(op.get("face") or s.face),
                          label=op["label"] if "label" in op else s.label,
                          note=op["note"] if "note" in op else s.note)
            before = where(s)
            drop(s)
            # What stood on a shelf follows it.
            for child in [x for x in slots if x.shelf_uid == s.uid]:
                slots[slots.index(child)] = replace(child, shelf_uid=new.uid) if child.row is None else child
                if child.row is not None:
                    drop(child)
                    slots.append(replace(child, uid=str(uuid.uuid4()), row=None, shelf_uid=new.uid))
            slots.append(new)
            unit = db.get(Asset, new.asset_uid) if new.asset_uid else None
            name = unit.name if unit else (new.label or new.kind)
            changes.append({"op": "update", "mounting": new.uid, "asset_uid": new.asset_uid, "name": name,
                            "before": before, "after": where(new), "text": f"{name}: {before} → {where(new)}"})
        elif what == "remove":
            s = next((x for x in slots if x.uid == op.get("mounting_uid")
                      or (op.get("asset_uid") and x.asset_uid == op.get("asset_uid"))), None)
            if s is None:
                raise RackError("no such mounting in this rack")
            if any(x.shelf_uid == s.uid for x in slots):
                raise RackError("the shelf still carries something: move or remove that first")
            unit = db.get(Asset, s.asset_uid) if s.asset_uid else None
            name = unit.name if unit else (s.label or s.kind)
            drop(s)
            changes.append({"op": "remove", "mounting": s.uid, "asset_uid": s.asset_uid, "name": name,
                            "before": where(s), "after": None, "text": f"{name}: taken out of {where(s)}"})
        else:
            raise RackError(f"operation {i + 1}: {what or 'nothing'} is not place, shelf, reserve, update or remove")
    return slots, closed, changes


def plan(db: Session, rack: Asset, ops: list[dict]) -> dict:
    """What the operations would do, written nowhere."""
    try:
        slots, _closed, changes = _work_out(db, rack, ops)
    except RackError as exc:
        return {"ok": False, "changes": [], "problems": [{"code": "operation", "message": str(exc)}],
                "elevation": elevation(db, rack)}
    view = elevation(db, rack, slots)
    return {"ok": not view["problems"], "changes": changes, "problems": view["problems"], "elevation": view}


def apply(db: Session, rack: Asset, ops: list[dict], actor: str) -> dict:
    """The operations, written when nothing is wrong with the result. The caller commits."""
    slots, closed, changes = _work_out(db, rack, ops)
    view = elevation(db, rack, slots)
    if view["problems"]:
        return {"ok": False, "changes": changes, "problems": view["problems"], "elevation": view}
    now = utcnow()
    for s in closed:
        s.row.state = "superseded" if any(x.asset_uid and x.asset_uid == s.asset_uid for x in slots) \
            or any(x.kind == s.kind and x.label == s.label and not x.asset_uid and not s.asset_uid for x in slots) \
            else "removed"
        s.row.valid_until = now
    for s in slots:
        if s.row is None:
            db.add(RackMounting(uid=s.uid, workspace_id=rack.workspace_id, rack_uid=rack.uid, asset_uid=s.asset_uid,
                                kind=s.kind, start_u=s.start_u, height_u=s.height_u, face=s.face,
                                shelf_uid=s.shelf_uid, label=s.label, note=s.note, source=s.source,
                                evidence=s.evidence, state="confirmed", valid_from=now, confirmed_by=actor))
    db.flush()
    return {"ok": True, "changes": changes, "problems": [], "elevation": elevation(db, rack)}


def follow_location(db: Session, rack: Asset, changes: list[dict], actor: str) -> list[str]:
    """A unit put in a rack is located in it: its `Located in` says so, as a person's statement in the ledger, and
    the `located in` edge follows. What cannot be written is reported, not hidden: the mounting stands either way."""
    from app.ledger import engine, service
    notes: list[str] = []
    target = rack.key or rack.name
    for c in changes:
        if c["op"] not in ("place", "shelf") or not c.get("asset_uid"):
            continue
        unit = db.get(Asset, c["asset_uid"])
        if unit is None or (unit.attributes or {}).get("argus_location") in (rack.key, rack.name, rack.uid):
            continue
        try:
            with db.begin_nested():
                service.edit_values(db, unit.workspace_id, actor, unit.uid, {"argus_location": target},
                                    reason=f"mounted in {rack.name}")
        except Exception as exc:  # noqa: BLE001 — a frozen workspace, a source that owns the field
            notes.append(f"{unit.name}: its location was not changed ({exc})")
    try:
        engine.derive_located_in(db, [rack.workspace_id])
    except Exception:  # noqa: BLE001
        pass
    return notes


def candidates(db: Session, workspace_id: str, q: str, limit: int = 20) -> list[dict]:
    """Records that could be mounted, by name, key or serial, each with where it is mounted now and the height
    its model suggests."""
    text = f"%{q.strip()}%"
    rows = db.scalars(select(Asset).where(
        Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None), Asset.record_status != "Retired",
        Asset.type.notin_(NOT_MOUNTED),
        or_(Asset.name.ilike(text), Asset.key.ilike(text), Asset.attributes["serial"].astext.ilike(text)))
        .order_by(Asset.name).limit(limit))
    out = []
    for a in rows:
        m = mounting_of(db, a.uid)
        rack = db.get(Asset, m.rack_uid) if m is not None else None
        out.append({"uid": a.uid, "key": a.key, "name": a.name, "type": a.type,
                    "serial": (a.attributes or {}).get("serial"), "suggested_height_u": suggested_height(db, a),
                    "mounted": {"rack_uid": m.rack_uid, "rack": rack.name if rack else None, "start_u": m.start_u,
                                "height_u": m.height_u, "face": m.face} if m is not None else None})
    return out
