"""A rack surveyed from a phone (docs/rack-census.md).

1. The rack is photographed, front and, if useful, rear. An existing rack is recognised (by the key or name read on
   it, or chosen); otherwise a new one is proposed. Its identifier, height in units, room and point on the floor plan
   are confirmed by the person — the indoor position is never taken from a guess.
2. Each unit is photographed, and its label or nameplate separately when needed. What is read — type, manufacturer,
   model, serial number of that very unit, height and units — comes back as **proposals with their evidence and
   confidence**, never as values: the person takes, corrects or types each one. A value that could not be read stays
   empty and is asked for. The product model catalogue suggests a height, and says so.
3. A unit is linked to an existing record, or a new one is proposed; possible duplicates (the same serial, the same
   name, a unit of the same model already in this rack) are shown before anything is made.
4. The whole rack is reviewed: what is missing, what overlaps, what may be a duplicate. Applying makes the rack and
   the records, mounts every unit through the rack service (its checks and its history), and keeps the photos on the
   records they show, with where each value came from.

Nothing changes in the inventory until it is applied. A survey can be left at any step and resumed, on any device.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.asset import Asset
from app.models.attachment import Attachment
from app.models.rack import RackCensus
from app.models.schema import Schema
from app.services import racks

FIELDS = ("type", "name", "manufacturer", "model", "serial", "height_u", "start_u", "face")
REQUIRED_NEW = ("type", "name")
ROLES = ("rack_front", "rack_rear", "device", "label")
DEFAULT_UNITS = 42


class CensusError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _data(c: RackCensus) -> dict:
    d = dict(c.data or {})
    d.setdefault("rack", {"photos": [], "proposals": {}, "values": {}, "candidates": []})
    d.setdefault("items", [])
    return d


def _save(c: RackCensus, d: dict) -> None:
    c.data = d
    c.updated_at = now()
    flag_modified(c, "data")


def get(db: Session, workspace_id: str, uid: str) -> RackCensus:
    c = db.get(RackCensus, uid)
    if c is None or c.workspace_id != workspace_id:
        raise CensusError("no such survey here")
    return c


def _open(db: Session, workspace_id: str, uid: str) -> RackCensus:
    c = get(db, workspace_id, uid)
    if c.state != "open":
        raise CensusError(f"this survey is {c.state}: start a new one")
    return c


# --------------------------------------------------------------------------- starting, resuming

def start(db: Session, workspace_id: str, actor: str, *, rack_uid: Optional[str] = None,
          place_uid: Optional[str] = None) -> RackCensus:
    """A survey of a rack that exists, or of one still to be identified (in a place, when the person says where)."""
    d = {"rack": {"photos": [], "proposals": {}, "values": {}, "candidates": []}, "items": []}
    if rack_uid:
        rack = racks.rack_of(db, rack_uid)
        if rack.workspace_id != workspace_id:
            raise CensusError("that rack belongs to another workspace")
        d["rack"]["existing"] = rack.uid
    if place_uid:
        d["rack"]["values"]["place_uid"] = place_uid
    c = RackCensus(uid=str(uuid.uuid4()), workspace_id=workspace_id, rack_uid=rack_uid, state="open",
                   created_by=actor, data=d)
    db.add(c)
    db.flush()
    return c


def open_surveys(db: Session, workspace_id: str, limit: int = 50) -> list[RackCensus]:
    return list(db.scalars(select(RackCensus).where(RackCensus.workspace_id == workspace_id,
                                                    RackCensus.state == "open")
                           .order_by(RackCensus.updated_at.desc()).limit(limit)))


def abandon(db: Session, workspace_id: str, uid: str) -> RackCensus:
    c = _open(db, workspace_id, uid)
    c.state = "abandoned"
    c.updated_at = now()
    return c


# --------------------------------------------------------------------------- photos and what is read on them

def _store(db: Session, workspace_id: str, actor: str, content: bytes, filename: str, mime: str) -> str:
    from app.routers.attachments import ATTACHMENTS_DIR
    import hashlib
    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    path = os.path.join(ATTACHMENTS_DIR, uid)
    with open(path, "wb") as f:
        f.write(content)
    db.add(Attachment(uid=uid, workspace_id=workspace_id, asset_uid=None, filename=filename or f"{uid}.jpg",
                      mime_type=mime, file_size=len(content), storage_path=path,
                      sha256=hashlib.sha256(content).hexdigest(), author=actor))
    db.flush()
    return uid


def _proposal(field: dict, source: str) -> dict:
    return {"value": field.get("value"), "label": field.get("label"), "confidence": field.get("confidence"),
            "evidence": field.get("evidence"), "grounded": bool(field.get("grounded")), "source": source}


def read_photo(db: Session, workspace_id: str, actor: str, image: bytes, mime: str, *, rack: bool = False) -> dict:
    """What the configured vision model reads on a photo, as proposals by field; {} with a note when there is no
    vision model (then everything is typed) or the reading fails. Never a value that was not read."""
    from fastapi import HTTPException

    from app.intake import assist
    from app.routers.intake import _endpoint
    from app.services.llm import LLMError
    try:
        config, ep, profile_id = _endpoint(db, workspace_id, "asset")
    except HTTPException as e:
        return {"proposals": {}, "note": f"Nothing was read: {e.detail}. Fill in what you see."}
    if not config.vision_model:
        return {"proposals": {}, "note": "No vision model is configured: fill in what you see."}
    draft = {}
    if rack:
        t = db.scalar(select(Schema).where(Schema.workspace_id == workspace_id, Schema.applies_to == "objects",
                                           Schema.name.in_(racks.RACK_TYPES)).limit(1))
        if t is not None:
            draft["schema_uid"] = t.uid
    try:
        out = assist.assist_asset(db, workspace_id, actor, ep, image=image, mime_type=mime or "image/jpeg",
                                  draft=draft, profile_id=profile_id)
    except LLMError as e:
        return {"proposals": {}, "note": f"The photo could not be read ({e}). Fill in what you see."}
    fields = out.get("fields") or {}
    p: dict = {}
    source = "rack photo" if rack else "photo"
    if "schema_uid" in fields:
        f = fields["schema_uid"]
        p["type"] = {**_proposal(f, source), "value": f["value"], "label": f.get("label")}
    for target, names in (("name", ("name",)), ("key", ("key",)),
                          ("serial", ("attributes.serial", "attributes.serial_number")),
                          ("manufacturer", ("attributes.manufacturer", "attributes.vendor")),
                          ("model", ("attributes.model", "attributes.model_code")),
                          ("height_u", ("attributes.rack_units",)),
                          ("start_u", ("attributes.rack_position", "attributes.rack_unit"))):
        for n in names:
            if n in fields:
                p[target] = _proposal(fields[n], source)
                break
    for k in ("height_u", "start_u"):
        if k in p:
            try:
                p[k]["value"] = int(round(float(p[k]["value"])))
            except (TypeError, ValueError):
                p.pop(k)
    return {"proposals": p, "run_id": out.get("run_id"),
            "note": None if p else "Nothing could be read on this photo: fill in what you see."}


UNITS_SYSTEM = (
    "You look at a photograph of a rack of a laboratory or technical facility, taken from its front or its rear.\n"
    "List every unit mounted in it that you can see, from the top down: a server, a switch, a patch panel, an "
    "instrument chassis, a power unit, a shelf with a device on it. A blank panel or an empty space is not a unit.\n"
    "Answer with one JSON object only, no prose and no code fence:\n"
    '{"rack": {"label": "the rack\'s own name or number, as written on it", "total_units": 42, "evidence": "..."},\n'
    ' "units": [{"kind": "one of the types given, or what it is", "manufacturer": "...", "model": "...",\n'
    '            "label": "the name written on its own label", "height_u": 1, "gap_above_u": 0, "start_u": null,\n'
    '            "confidence": 0.8, "evidence": "what you see that says it"}]}\n'
    "height_u is how many rack units it takes (1 U = 44.45 mm); gap_above_u how many empty units there are between "
    "it and the unit above (0 for the first one, unless the top of the rack shows). Racks are often not full: measure "
    "each gap against the height of a 1 U front panel and the holes of the rails (three holes a unit); a shelf, a "
    "bracket or cables lying in the space are not units. start_u is its lowest unit only "
    "when the unit numbers are printed on the rails and you can read them; otherwise null. total_units only when "
    "it is written or the numbers on the rails show it. Leave out a manufacturer, a model or a label you cannot read: "
    "never guess a name, a serial number or a number. Units that look the same are listed one by one.\n"
)
MAX_SEEN = 60


def _int(v, lo: int, hi: int) -> Optional[int]:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _text(v) -> Optional[str]:
    if v is None:
        return None
    t = str(v).strip()
    return t[:120] if t and t.lower() not in ("null", "none", "unknown", "n/a", "-", "?") else None


UNITS_SIDE = 3072
UNITS_TIMEOUT = 300


def _smaller(image: bytes, mime: str) -> tuple[bytes, str]:
    """A phone's photo of a whole rack, at most UNITS_SIDE pixels a side: enough to tell the units apart, and a vision
    model reads it in a fraction of the time (a 12-megapixel photo can outlast the gateway's wait)."""
    import io
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(image)) as im:
            if max(im.size) <= UNITS_SIDE:
                return image, mime
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((UNITS_SIDE, UNITS_SIDE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
            return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 — not a picture PIL reads: sent as it is
        return image, mime


def start_units_reading(db: Session, workspace_id: str, image: bytes, mime: str) -> Optional[dict]:
    """Ask the vision model for the units on a photo of the whole rack, in the background (it can take a minute or
    two, as long as the photo's own reading, which goes on meanwhile); None when there is no vision model."""
    import hashlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException

    from app.intake import assist
    from app.routers.intake import _endpoint
    from app.services import llm
    try:
        config, ep, profile_id = _endpoint(db, workspace_id, "asset")
    except HTTPException:
        return None
    if not config.vision_model:
        return None
    types = [s.name for s in assist._visible_types(db, workspace_id, "objects")
             if s.name not in racks.RACK_TYPES and s.name not in racks.NOT_MOUNTED][:400]
    user = "Types: " + ", ".join(types) + "\n\nList the units in this rack, from the top down."
    picture, kind = _smaller(image, mime or "image/jpeg")
    pool = ThreadPoolExecutor(max_workers=1)
    # A whole rack is a long answer: it may take longer than the usual wait (the ingress waits up to ten minutes).
    future = pool.submit(lambda: llm.look(ep, picture, kind, UNITS_SYSTEM, user, timeout=UNITS_TIMEOUT))
    pool.shutdown(wait=False)
    return {"future": future, "ep": ep, "profile_id": profile_id, "types": types, "started": time.monotonic(),
            "refs": [{"kind": "image", "bytes": len(image), "mime_type": mime}],
            "hashes": [hashlib.sha256(image).hexdigest()]}


def read_units(db: Session, workspace_id: str, actor: str, image: bytes, mime: str,
               job: Optional[dict] = None) -> dict:
    """The units the vision model sees in a photo of the whole rack, top down — each with what it is, its height and
    the gap above it, and its maker, model and label when they can be read — and what is written on the rack itself.
    Nothing when there is no vision model or the reading fails; then the units are photographed one by one. `job`:
    the reading started before (start_units_reading), to wait for."""
    from app.intake import assist
    from app.services.llm import LLMError
    job = job if job is not None else start_units_reading(db, workspace_id, image, mime)
    if job is None:
        return {"units": [], "rack": {}, "note": None}
    ep, profile_id, types, started = job["ep"], job["profile_id"], job["types"], job["started"]
    refs, hashes = job["refs"], job["hashes"]
    try:
        reply = job["future"].result()
    except LLMError as e:
        assist._record(db, workspace_id, actor, "asset", ep, input_refs=refs, hashes=hashes, redactions={}, output=None,
                       validations=[], outcome="failed", error=str(e), started=started, model=ep.vision_model,
                       profile_id=profile_id, operation="rack.units", rule_id="ai.rack.units/1")
        return {"units": [], "rack": {}, "note": f"The units could not be read on the photo ({e})."}
    data = assist._payload(reply) or {}
    by_name = {t.lower(): t for t in types}
    by_name.update({t.lower() + "es" if t.lower().endswith(("s", "x", "ch", "sh")) else t.lower() + "s": t
                    for t in types})           # "switches" is a Switch
    units = []
    for u in (data.get("units") if isinstance(data.get("units"), list) else [])[:MAX_SEEN]:
        if not isinstance(u, dict):
            continue
        kind = _text(u.get("kind"))
        conf = u.get("confidence")
        units.append({
            "kind": kind, "type": by_name.get((kind or "").lower()),
            "manufacturer": _text(u.get("manufacturer")), "model": _text(u.get("model")), "label": _text(u.get("label")),
            "height_u": _int(u.get("height_u"), 1, 20), "gap_above_u": _int(u.get("gap_above_u"), 0, 59) or 0,
            "start_u": _int(u.get("start_u"), 1, 60),
            "confidence": max(0.0, min(1.0, float(conf))) if isinstance(conf, (int, float)) else None,
            "evidence": _text(u.get("evidence"))})
    r = data.get("rack") if isinstance(data.get("rack"), dict) else {}
    rack = {"label": _text(r.get("label")), "total_units": _int(r.get("total_units"), 1, 60),
            "evidence": _text(r.get("evidence"))}
    run = assist._record(db, workspace_id, actor, "asset", ep, input_refs=refs, hashes=hashes, redactions={},
                         output={"units": units, "rack": rack}, validations=[], outcome="proposed" if units else "draft_only",
                         error=None, started=started, model=ep.vision_model, profile_id=profile_id,
                         operation="rack.units", rule_id="ai.rack.units/1")
    return {"units": units, "rack": rack, "run_id": run.id,
            "note": None if units else "No unit could be told apart on this photo: photograph them one by one."}


def positions(units: list[dict], top_u: Optional[int]) -> list[Optional[int]]:
    """Each seen unit's lowest unit: read on the rails, or counted down from the top unit the person says, with the
    heights and gaps seen. None where neither is known, or where the count runs out of the rack."""
    out: list[Optional[int]] = []
    top = top_u
    for u in units:
        h = u.get("height_u") or 1
        if u.get("start_u"):
            start = u["start_u"]
        elif top is not None:
            start = top - (u.get("gap_above_u") or 0) - h + 1
        else:
            start = None
        out.append(start if start and start >= 1 else None)
        top = start - 1 if start else None
    return out


def take_seen(db: Session, workspace_id: str, uid: str, *, units: Optional[list[int]] = None,
              top_u: Optional[int] = None, use: bool = False, rack: bool = False) -> RackCensus:
    """The units seen on the photo of the whole rack become units of the survey (those chosen, or all): each with what
    was read as proposals — or, when the person says so (`use`), as its values, still to be checked in the review. A
    name not written on the unit is made from what it is and its place from the top, and says so. `rack`: the rack
    itself is a new record, named and sized from what was read on it where the person has not said."""
    c = _open(db, workspace_id, uid)
    d = _data(c)
    seen = d["rack"].get("seen")
    if not seen or not seen.get("units"):
        raise CensusError("no units were seen on a photo of the whole rack: photograph its front first")
    if top_u is not None and not 1 <= top_u <= 60:
        raise CensusError("the top unit is between 1 and 60")
    all_units = seen["units"]
    chosen = sorted(set(units)) if units else list(range(len(all_units)))
    if any(i < 0 or i >= len(all_units) for i in chosen):
        raise CensusError("no such unit on the photo")
    already = set(seen.get("taken") or [])
    chosen = [i for i in chosen if i not in already]
    if not chosen:
        raise CensusError("those units are already in the survey")
    starts = positions(all_units, top_u)
    for i in chosen:
        u = all_units[i]
        n = i + 1
        conf = u.get("confidence") or 0.6
        ev = u.get("evidence") or "seen on the photo of the rack"
        prop = lambda v, **k: {"value": v, "confidence": conf, "evidence": ev, "grounded": True,  # noqa: E731
                               "source": "rack photo", **k}
        p: dict = {}
        if u.get("type"):
            schema = db.scalar(select(Schema).where(Schema.name == u["type"], Schema.applies_to == "objects",
                                                    or_(Schema.workspace_id == workspace_id, Schema.is_global.is_(True)))
                               .order_by(Schema.is_global))
            if schema is not None:
                p["type"] = prop(schema.uid, label=schema.name)
        for f in ("manufacturer", "model"):
            if u.get(f):
                p[f] = prop(u[f])
        if u.get("label"):
            p["name"] = prop(u["label"], evidence=f"written on it: {u['label']}")
        else:
            what = " ".join(x for x in (u.get("manufacturer"), u.get("model")) if x) or u.get("kind") or "Unit"
            p["name"] = {"value": f"{what} {n}", "confidence": 0.3, "grounded": False, "source": "rack photo",
                         "evidence": f"no name is written on it: made from what it is and its place ({n}) from the top"}
        if u.get("height_u"):
            p["height_u"] = prop(u["height_u"])
        if starts[i]:
            read = bool(u.get("start_u"))
            p["start_u"] = prop(starts[i], confidence=conf if read else min(conf, 0.7), evidence=(
                "read on the rails" if read else f"counted down from U{top_u}: heights and gaps seen on the photo"))
        item = {"id": str(uuid.uuid4())[:8], "photos": [], "proposals": p, "values": {}, "decision": None,
                "asset_uid": None, "created_at": now().isoformat(), "seen_in": {"photo": seen["photo"], "index": i}}
        face = {"value": seen.get("face") or "front", "source": "rack photo"}
        item["values"]["face"] = face
        if use:
            for k, v in p.items():
                item["values"][k] = {"value": v["value"], "source": v["source"],
                                     **({"confidence": v["confidence"]} if v.get("confidence") else {})}
        _suggest(db, workspace_id, item)
        item["duplicates"] = duplicates(db, workspace_id, item, _rack_uid(d))
        if use and not any(x["strength"] in ("strong", "medium") for x in item["duplicates"]):
            item["decision"] = "create"
        d["items"].append(item)
    seen["taken"] = sorted(already | set(chosen))
    if rack and not _rack_uid(d):
        rv, rp = d["rack"]["values"], d["rack"].get("proposals") or {}
        for f in ("name", "units"):
            if not rv.get(f) and (rp.get(f) or {}).get("value"):
                rv[f] = rp[f]["value"]
        if not rv.get("units") and top_u:
            rv["units"] = top_u
        d["rack"]["candidates"] = _rack_candidates(db, workspace_id, d)
    _save(c, d)
    return c


def _catalogue(db: Session, workspace_id: str, manufacturer: Optional[str], model: Optional[str]) -> Optional[Asset]:
    """The product model a manufacturer and model name designate, if the catalogue has exactly one."""
    if not model:
        return None
    text = f"%{model.strip()}%"
    rows = list(db.scalars(select(Asset).where(
        Asset.workspace_id == workspace_id, Asset.type == "Product Model", Asset.deleted_at.is_(None),
        or_(Asset.attributes["model_code"].astext.ilike(model.strip()), Asset.name.ilike(text))).limit(5)))
    if manufacturer and len(rows) > 1:
        rows = [r for r in rows if manufacturer.lower() in f"{r.name} {(r.attributes or {}).get('vendor', '')}".lower()]
    return rows[0] if len(rows) == 1 else None


def _value(item: dict, field: str):
    v = (item.get("values") or {}).get(field)
    return v["value"] if isinstance(v, dict) else v


def _suggest(db: Session, workspace_id: str, item: dict) -> None:
    """Proposals from the catalogue: its product model, and the height it gives — said to come from there."""
    props = item.setdefault("proposals", {})
    maker = _value(item, "manufacturer") or (props.get("manufacturer") or {}).get("value")
    model = _value(item, "model") or (props.get("model") or {}).get("value")
    pm = _catalogue(db, workspace_id, maker, model)
    if pm is None:
        props.pop("product_model", None)
        return
    props["product_model"] = {"value": pm.uid, "label": pm.name, "confidence": 0.9, "grounded": True,
                              "evidence": f"catalogue: {pm.name}", "source": "catalogue"}
    units = (pm.attributes or {}).get("rack_units")
    if units and "height_u" not in props:
        try:
            props["height_u"] = {"value": max(1, int(round(float(units)))), "confidence": 0.9, "grounded": True,
                                 "evidence": f"catalogue: {pm.name} is {units} U", "source": "catalogue"}
        except (TypeError, ValueError):
            pass


def duplicates(db: Session, workspace_id: str, item: dict, rack_uid: Optional[str]) -> list[dict]:
    """Records this unit may already be: the same serial, the same key or name, or a unit of the same model already in
    this rack. Strongest first."""
    out: dict[str, dict] = {}

    def add(a: Asset, why: str, strength: str):
        if a.uid not in out and a.deleted_at is None:
            out[a.uid] = {"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "why": why, "strength": strength,
                          "mounted": _where(db, a.uid)}
    serial = _value(item, "serial") or ((item.get("proposals") or {}).get("serial") or {}).get("value")
    if serial:
        for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                                Asset.attributes["serial"].astext == str(serial)).limit(5)):
            add(a, f"the same serial number {serial}", "strong")
    key = ((item.get("proposals") or {}).get("key") or {}).get("value")
    if key:
        a = db.scalar(select(Asset).where(Asset.key == str(key), Asset.workspace_id == workspace_id))
        if a is not None:
            add(a, f"the key {key} read on it", "strong")
    name = _value(item, "name")
    if name:
        for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.name.ilike(str(name)))
                            .limit(5)):
            add(a, "the same name", "medium")
    model = _value(item, "model")
    if rack_uid and model:
        for s in racks.current(db, rack_uid):
            a = db.get(Asset, s.asset_uid) if s.asset_uid else None
            if a is not None and str(model).lower() in f"{a.name} {(a.attributes or {}).get('model', '')}".lower():
                add(a, f"a {model} already in this rack", "weak")
    order = {"strong": 0, "medium": 1, "weak": 2}
    return sorted(out.values(), key=lambda x: order[x["strength"]])


def _where(db: Session, uid: str) -> Optional[dict]:
    m = racks.mounting_of(db, uid)
    if m is None:
        return None
    rack = db.get(Asset, m.rack_uid)
    return {"rack_uid": m.rack_uid, "rack": rack.name if rack else None, "start_u": m.start_u, "height_u": m.height_u,
            "face": m.face}


def _rack_candidates(db: Session, workspace_id: str, d: dict) -> list[dict]:
    """Racks this one may be: the key or name read on it, or the racks of the place said."""
    props, values = d["rack"].get("proposals") or {}, d["rack"].get("values") or {}
    found: dict[str, dict] = {}
    for f in ("key", "name"):
        v = (props.get(f) or {}).get("value")
        if v:
            for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.type.in_(racks.RACK_TYPES),
                                                    Asset.deleted_at.is_(None),
                                                    or_(Asset.key == str(v), Asset.name.ilike(f"%{v}%"))).limit(5)):
                found.setdefault(a.uid, {"uid": a.uid, "key": a.key, "name": a.name, "why": f"the {f} read on it"})
    place = values.get("place_uid")
    if place:
        from app.services import indoor
        for a, _p in indoor.placed_in(db, place):
            if a.type in racks.RACK_TYPES:
                found.setdefault(a.uid, {"uid": a.uid, "key": a.key, "name": a.name, "why": "in the room said"})
    return list(found.values())[:10]


def add_photo(db: Session, workspace_id: str, actor: str, uid: str, role: str, content: bytes, filename: str,
              mime: str, item_id: Optional[str] = None) -> dict:
    """A photo of the rack (front, rear), of a unit (a new item, or another view of one) or of its label."""
    if role not in ROLES:
        raise CensusError(f"a photo is one of: {', '.join(ROLES)}")
    c = _open(db, workspace_id, uid)
    d = _data(c)
    photo = _store(db, workspace_id, actor, content, filename, mime)
    if role.startswith("rack_"):
        job = start_units_reading(db, workspace_id, content, mime)      # both readings at once
        reading = read_photo(db, workspace_id, actor, content, mime, rack=True)
        d["rack"]["photos"].append({"uid": photo, "role": role})
        for k, v in reading["proposals"].items():
            d["rack"]["proposals"].setdefault(k, v)
        d["rack"]["note"] = reading.get("note")
        seen = read_units(db, workspace_id, actor, content, mime, job=job)
        if seen["units"] or not (d["rack"].get("seen") or {}).get("units"):
            d["rack"]["seen"] = {"photo": photo, "face": "rear" if role == "rack_rear" else "front",
                                 "units": seen["units"], "note": seen.get("note"), "taken": [],
                                 "run_id": seen.get("run_id")}
        r = seen.get("rack") or {}
        if r.get("label"):
            d["rack"]["proposals"].setdefault("name", {"value": r["label"], "confidence": 0.8, "grounded": True,
                                                       "evidence": r.get("evidence") or f"written on it: {r['label']}",
                                                       "source": "rack photo"})
        if r.get("total_units"):
            d["rack"]["proposals"]["units"] = {"value": r["total_units"], "confidence": 0.7, "grounded": True,
                                               "evidence": r.get("evidence") or "the numbers on the rails",
                                               "source": "rack photo"}
        d["rack"]["candidates"] = _rack_candidates(db, workspace_id, d)
        _save(c, d)
        return {"photo": photo, "reading": reading, "survey": view(db, c)}
    item = next((i for i in d["items"] if i["id"] == item_id), None) if item_id else None
    if item is None:
        if role == "label" and item_id:
            raise CensusError("no such unit in this survey")
        item = {"id": str(uuid.uuid4())[:8], "photos": [], "proposals": {}, "values": {}, "decision": None,
                "asset_uid": None, "created_at": now().isoformat()}
        d["items"].append(item)
    reading = read_photo(db, workspace_id, actor, content, mime)
    item["photos"].append({"uid": photo, "role": role})
    for k, v in reading["proposals"].items():
        old = item["proposals"].get(k)
        # A label is read for the identity of the unit: its serial wins over the one guessed from the front.
        if old is None or (role == "label" and k in ("serial", "model", "manufacturer")) or \
                (v.get("confidence") or 0) > (old.get("confidence") or 0):
            item["proposals"][k] = {**v, "source": "label" if role == "label" else v["source"]}
    item["note"] = reading.get("note")
    _suggest(db, workspace_id, item)
    item["duplicates"] = duplicates(db, workspace_id, item, _rack_uid(d))
    _save(c, d)
    return {"photo": photo, "item": item["id"], "reading": reading, "survey": view(db, c)}


def _rack_uid(d: dict) -> Optional[str]:
    return d["rack"].get("existing")


# --------------------------------------------------------------------------- what the person says

def set_rack(db: Session, workspace_id: str, uid: str, *, existing: Optional[str] = None,
             values: Optional[dict] = None) -> RackCensus:
    """The rack is that existing one; or a new one with these values (name, key, units, place_uid, level_uid,
    plan_uid, x, y, position_confirmed)."""
    c = _open(db, workspace_id, uid)
    d = _data(c)
    if existing:
        rack = racks.rack_of(db, existing)
        if rack.workspace_id != workspace_id:
            raise CensusError("that rack belongs to another workspace")
        d["rack"]["existing"] = rack.uid
        c.rack_uid = rack.uid
    elif existing == "":
        d["rack"].pop("existing", None)
        c.rack_uid = None
    if values:
        allowed = {"name", "key", "units", "place_uid", "level_uid", "plan_uid", "x", "y", "position_confirmed"}
        bad = set(values) - allowed
        if bad:
            raise CensusError(f"not a value of the rack: {', '.join(sorted(bad))}")
        if "units" in values and values["units"] is not None and not (1 <= int(values["units"]) <= 60):
            raise CensusError("a rack has between 1 and 60 units")
        d["rack"]["values"].update(values)
        d["rack"]["candidates"] = _rack_candidates(db, workspace_id, d)
    _save(c, d)
    return c


def set_item(db: Session, workspace_id: str, uid: str, item_id: str, *, values: Optional[dict] = None,
             decision: Optional[str] = None, asset_uid: Optional[str] = None, duplicate_checked: Optional[bool] = None
             ) -> RackCensus:
    """The person's values for a unit (each one taken from a proposal or typed: `{"serial": {"value": "X",
    "source": "label"}}` or just the value, typed), and whether it is an existing record, a new one, or left out."""
    c = _open(db, workspace_id, uid)
    d = _data(c)
    item = next((i for i in d["items"] if i["id"] == item_id), None)
    if item is None:
        raise CensusError("no such unit in this survey")
    for k, v in (values or {}).items():
        if k not in FIELDS and k != "product_model":
            raise CensusError(f"{k} is not a value of a unit; they are {', '.join(FIELDS)}")
        if v is None or v == "":
            item["values"].pop(k, None)
            continue
        entry = v if isinstance(v, dict) and "value" in v else {"value": v, "source": "person"}
        if k in ("height_u", "start_u"):
            try:
                entry["value"] = int(entry["value"])
            except (TypeError, ValueError):
                raise CensusError(f"{k} is a whole number of units")
        if k == "face" and entry["value"] not in ("front", "rear", "both"):
            raise CensusError("face is front, rear or both")
        item["values"][k] = entry
    if decision is not None:
        if decision not in ("link", "create", "skip"):
            raise CensusError("decision is link, create or skip")
        item["decision"] = decision
    if asset_uid is not None:
        if asset_uid:
            a = db.get(Asset, asset_uid)
            if a is None or a.workspace_id != workspace_id or a.deleted_at is not None:
                raise CensusError("no such record here")
            if a.type in racks.NOT_MOUNTED:
                raise CensusError(f"{a.name} is a {a.type}: it is not mounted in a rack")
        item["asset_uid"] = asset_uid or None
        if asset_uid:
            item["decision"] = "link"
    if duplicate_checked is not None:
        item["duplicate_checked"] = bool(duplicate_checked)
    _suggest(db, workspace_id, item)
    item["duplicates"] = duplicates(db, workspace_id, item, _rack_uid(d))
    _save(c, d)
    return c


def remove_item(db: Session, workspace_id: str, uid: str, item_id: str) -> RackCensus:
    c = _open(db, workspace_id, uid)
    d = _data(c)
    d["items"] = [i for i in d["items"] if i["id"] != item_id]
    _save(c, d)
    return c


# --------------------------------------------------------------------------- the review

def _units(db: Session, d: dict) -> Optional[int]:
    if _rack_uid(d):
        return racks.units_of(db.get(Asset, _rack_uid(d)))
    v = (d["rack"].get("values") or {}).get("units")
    return int(v) if v else None


def review(db: Session, workspace_id: str, uid: str) -> dict:
    """Everything that stands between the survey and the inventory: what is missing, what overlaps, what may be a
    duplicate — and, when nothing does, what applying will do."""
    c = get(db, workspace_id, uid)
    d = _data(c)
    missing: list[dict] = []
    rack_uid = _rack_uid(d)
    rv = d["rack"].get("values") or {}
    if not rack_uid:
        for f, what in (("name", "the rack's name"), ("units", "how many units the rack has"),
                        ("place_uid", "the room it is in")):
            if not rv.get(f):
                missing.append({"item": None, "field": f, "message": f"Say {what}."})
        if rv.get("plan_uid") and not rv.get("position_confirmed"):
            missing.append({"item": None, "field": "position_confirmed",
                            "message": "Confirm the rack's point on the floor plan."})
    units = _units(db, d) or DEFAULT_UNITS
    slots = [s for s in (racks.current(db, rack_uid) if rack_uid else [])]
    names: dict[str, str] = {}
    changes: list[str] = []
    to_create = 0
    for i, item in enumerate(d["items"], start=1):
        label = _value(item, "name") or (item.get("proposals", {}).get("name") or {}).get("value") or f"unit {i}"
        decision = item.get("decision")
        if decision == "skip":
            continue
        if decision not in ("link", "create"):
            missing.append({"item": item["id"], "field": "decision",
                            "message": f"{label}: link it to a record, make a new one, or leave it out."})
            continue
        if decision == "link" and not item.get("asset_uid"):
            missing.append({"item": item["id"], "field": "asset_uid", "message": f"{label}: choose the record."})
            continue
        if decision == "create":
            to_create += 1
            for f in REQUIRED_NEW:
                if not _value(item, f):
                    missing.append({"item": item["id"], "field": f, "message": f"{label}: say its {f}."})
            strong = [x for x in item.get("duplicates") or [] if x["strength"] in ("strong", "medium")]
            if strong and not item.get("duplicate_checked"):
                missing.append({"item": item["id"], "field": "duplicate",
                                "message": f"{label} may already be {strong[0]['key'] or strong[0]['name']} "
                                           f"({strong[0]['why']}): link it, or say it is another one."})
        start, height = _value(item, "start_u"), _value(item, "height_u")
        if start is None:
            missing.append({"item": item["id"], "field": "start_u",
                            "message": f"{label}: its lowest unit was not read — type it."})
            continue
        if height is None:
            missing.append({"item": item["id"], "field": "height_u",
                            "message": f"{label}: how many units it takes was not read — type it."})
            continue
        key = item.get("asset_uid") or f"new:{item['id']}"
        names[key] = label
        slots = [s for s in slots if s.asset_uid != key]
        slots.append(racks.Slot(uid=f"census:{item['id']}", asset_uid=key, kind="device", start_u=int(start),
                                height_u=int(height), face=_value(item, "face") or "front"))
        changes.append(f"{label}: U{start}" + (f"–U{int(start) + int(height) - 1}" if int(height) > 1 else "")
                       + f" {_value(item, 'face') or 'front'}")
    for s in slots:
        if s.asset_uid and s.asset_uid not in names:
            a = db.get(Asset, s.asset_uid)
            names[s.asset_uid] = a.name if a else s.asset_uid
    problems = racks.problems(slots, units, names)
    return {"ok": not missing and not problems, "missing": missing, "problems": problems, "changes": changes,
            "new_records": to_create, "new_rack": not rack_uid, "units": units,
            "free": {f: racks.free_ranges(slots, units, f) for f in ("front", "rear")}}


# --------------------------------------------------------------------------- applying

def _takes_product_model(db: Session, schema: Schema, pm_uid: str) -> bool:
    """Whether the catalogue entry fits the type's product model field. One the field cannot hold (it points at another
    kind of record) is left out rather than refusing the unit; a type without the field keeps it as written."""
    from app.services.attribute_validation import _descendant_schema_uids, effective_attributes
    attr = next((a for a in effective_attributes(db, schema) if isinstance(a, dict) and a.get("key") == "product_model"), None)
    target = db.get(Asset, pm_uid)
    if target is None:
        return False
    if attr is None:
        return True
    ref = attr.get("referenceSchemaUid")
    if attr.get("type") != "reference" or not ref:
        return True
    allowed = {ref} | (_descendant_schema_uids(db, ref) if attr.get("includeChildren") else set())
    return target.schema_uid in allowed


def apply(db: Session, workspace_id: str, uid: str, identity, actor: str) -> dict:
    """Make it so — or, if the review still finds something, nothing at all."""
    from app.auth import get_current_user_id
    from app.routers import assets as forms
    from app.schemas.asset import AssetCreate
    from app.services import indoor
    c = _open(db, workspace_id, uid)
    checked = review(db, workspace_id, uid)
    if not checked["ok"]:
        return {"ok": False, **checked}
    d = _data(c)
    user_id = get_current_user_id(identity)
    rv = d["rack"].get("values") or {}
    rack_uid = _rack_uid(d)
    if not rack_uid:
        rack_type = db.scalar(select(Schema).where(
            or_(Schema.workspace_id == workspace_id, Schema.is_global.is_(True)), Schema.applies_to == "objects",
            Schema.name.in_(racks.RACK_TYPES)).limit(1))
        if rack_type is None:
            raise CensusError("this workspace has no Rack type")
        rack = forms.create_asset(AssetCreate(uid=str(uuid.uuid4()), schema_uid=rack_type.uid, key=rv.get("key") or None,
                                              name=rv["name"], attributes={"rack_units": int(rv["units"])}),
                                  identity=identity, workspace_id=workspace_id, current_user_id=user_id, db=db)
        rack_uid = rack.uid
        confirmed = bool(rv.get("position_confirmed"))
        indoor.place(db, db.get(Asset, rack_uid), place_uid=rv.get("place_uid"), level_uid=rv.get("level_uid"),
                     plan_uid=rv.get("plan_uid") if confirmed else None, x=rv.get("x") if confirmed else None,
                     y=rv.get("y") if confirmed else None, actor=actor, note="rack survey: position confirmed on site")
        d["rack"]["existing"] = rack_uid
        c.rack_uid = rack_uid
    rack = racks.rack_of(db, rack_uid)
    made: list[dict] = []
    ops: list[dict] = []
    photos: dict[str, list[str]] = {rack_uid: [p["uid"] for p in d["rack"]["photos"]]}
    for item in d["items"]:
        if item.get("decision") == "skip":
            continue
        if item["decision"] == "create":
            attrs = {k: _value(item, k) for k in ("serial", "manufacturer", "model") if _value(item, k)}
            schema = db.get(Schema, _value(item, "type"))
            if schema is None:
                schema = db.scalar(select(Schema).where(Schema.name == _value(item, "type"),
                                                        or_(Schema.workspace_id == workspace_id, Schema.is_global.is_(True)))
                                   .order_by(Schema.is_global))      # the workspace's own type before a global one
            if schema is None:
                raise CensusError(f"{_value(item, 'name')}: there is no type {_value(item, 'type')!r} here")
            pm = _value(item, "product_model")              # taken from the catalogue's proposal, or chosen
            if pm and _takes_product_model(db, schema, pm):
                attrs["product_model"] = pm
            asset = forms.create_asset(AssetCreate(uid=str(uuid.uuid4()), schema_uid=schema.uid, name=_value(item, "name"),
                                                   attributes=attrs),
                                       identity=identity, workspace_id=workspace_id, current_user_id=user_id, db=db)
            item["asset_uid"] = asset.uid
            made.append({"uid": asset.uid, "key": asset.key, "name": asset.name})
        sources = {k: {"source": v.get("source"), **({"confidence": v.get("confidence")} if v.get("confidence") else {})}
                   for k, v in (item.get("values") or {}).items() if isinstance(v, dict)}
        ops.append({"op": "place", "asset_uid": item["asset_uid"], "kind": "device",
                    "start_u": int(_value(item, "start_u")), "height_u": int(_value(item, "height_u")),
                    "face": _value(item, "face") or "front", "source": "census",
                    "evidence": {"census": c.uid, "values": sources,
                                 "photos": [p["uid"] for p in item["photos"]]
                                 + ([item["seen_in"]["photo"]] if item.get("seen_in") else [])}})
        photos.setdefault(item["asset_uid"], []).extend(p["uid"] for p in item["photos"])
    result = racks.apply(db, rack, ops, actor) if ops else {"ok": True, "changes": [], "problems": []}
    if not result["ok"]:
        db.rollback()
        return {"ok": False, "missing": [], "problems": result["problems"], "changes": []}
    for asset_uid, uids in photos.items():
        for p in uids:
            att = db.get(Attachment, p)
            if att is not None and att.asset_uid is None:
                att.asset_uid = asset_uid
    c.state, c.applied_at = "applied", now()
    _save(c, d)
    db.commit()
    return {"ok": True, "rack": {"uid": rack.uid, "key": rack.key, "name": rack.name}, "created": made,
            "changes": [x["text"] for x in result["changes"]]}


# --------------------------------------------------------------------------- what a client reads

def view(db: Session, c: RackCensus) -> dict:
    d = _data(c)
    rack = db.get(Asset, _rack_uid(d)) if _rack_uid(d) else None
    return {"uid": c.uid, "state": c.state, "created_by": c.created_by, "created_at": c.created_at,
            "updated_at": c.updated_at,
            "rack": {**d["rack"], "record": {"uid": rack.uid, "key": rack.key, "name": rack.name,
                                             "units": racks.units_of(rack)} if rack else None},
            "items": d["items"]}
