"""What a transfer does indoors, and the reconciliation report before it (docs/sites.md, rule 5).

* **Floors and plans go with their place.** A move gives them the target workspace (their files stay where they
  are); a copy makes new ones for the copied place, with copies of the picture and of the source file, and the
  same control points, fit and residual — the copied plan is where the original was on the map.
* **Placements.** A record transferred takes its current placement. A move keeps it when its place, floor and
  plan are still reachable from the record's workspace afterwards (the same workspace, a global place, or one the
  site shares with it); a copy gives the copied record a placement on the copies of what was copied with it, or
  on the original when the target reaches it. A placement that is not **eligible** is not carried: on a move it
  ends as `withdrawn`, with a line in the record's history; on a copy the copy is simply not placed.
* **Records placed in a moving place** (other workspaces' equipment on its plans) keep their placement when the
  place is still reachable from their workspace after the move, and end as `withdrawn` otherwise.
* **The report** (`preview`) says all of it before anything changes, and every reference to the records that
  would move — relations, reference attributes, placements of other records in them, labels — with whether it
  still resolves afterwards from the referencing record's workspace.
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import Optional

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
from app.services import indoor, sites


# --------------------------------------------------------------------------- after the move, who reaches what

def _would_share(db: Session, asset: Asset, target: str) -> bool:
    """Whether the record would be site-shared once in `target` (a place, in a site, not withheld)."""
    return sites.is_site(db, target) and asset.schema_uid in sites.place_types(db) and not asset.site_withheld


def reaches_after(db: Session, record: Asset, record_ws_after: str, from_ws: str, shared_after: bool) -> bool:
    """Whether `from_ws` reaches `record` once it is in `record_ws_after`."""
    if from_ws == record_ws_after or record.is_global:
        return True
    return shared_after and sites.site_of(db, from_ws) == record_ws_after


def _files_present(plan: FloorPlan) -> bool:
    return bool(plan.storage_path and os.path.exists(plan.storage_path)) and \
        (plan.source_path is None or os.path.exists(plan.source_path))


# --------------------------------------------------------------------------- the report

def preview(db: Session, source: str, target: str, mode: str, asset_uids: set[str]) -> dict:
    """The reconciliation report of a transfer: nothing is changed."""
    db.flush()
    moving = [a for a in (db.get(Asset, u) for u in sorted(asset_uids)) if a is not None and a.workspace_id == source]
    ids = {a.uid for a in moving}
    shared_after = {a.uid: _would_share(db, a, target) for a in moving}
    after_ws = target if mode == "move" else None          # a copy leaves the originals where they are

    records = [{"uid": a.uid, "key": a.key, "name": a.name, "type": a.type, "is_global": a.is_global,
                "site_shared_after": shared_after[a.uid] if mode == "move" else False} for a in moving]

    levels = list(db.scalars(select(PlaceLevel).where(PlaceLevel.place_uid.in_(ids)))) if ids else []
    plans = list(db.scalars(select(FloorPlan).where(FloorPlan.place_uid.in_(ids)))) if ids else []
    indoors = {
        "levels": [{"uid": lv.uid, "place_uid": lv.place_uid, "name": lv.name} for lv in levels],
        "plans": [{"uid": p.uid, "place_uid": p.place_uid, "name": p.name, "files_present": _files_present(p),
                   "placed_on_map": p.transform is not None, "residual_m": p.residual_m} for p in plans],
    }

    def eligible(p: IndoorPlacement, record_ws: str) -> tuple[bool, Optional[str]]:
        for uid in (p.place_uid, _place_of_level(db, p.level_uid), _place_of_plan(db, p.plan_uid)):
            if not uid:
                continue
            place = db.get(Asset, uid)
            if place is None:
                return False, "its place no longer exists"
            moved = place.uid in ids and mode == "move"
            place_ws = target if moved else place.workspace_id
            if mode == "copy" and place.uid in ids:
                continue                                   # the copy is placed on the copy
            ok = reaches_after(db, place, place_ws, record_ws, shared_after.get(place.uid, place.site_shared)
                               if moved else place.site_shared or place.is_global)
            if not ok:
                return False, f"{place.name} would not be reachable from {record_ws}"
        return True, None

    carried = []
    for a in moving:
        p = indoor.current(db, a.uid)
        if p is None:
            continue
        ok, why = eligible(p, target)
        carried.append({"record": a.uid, "name": a.name, "place_uid": p.place_uid, "plan_uid": p.plan_uid,
                        "eligible": ok, "why": why})

    placed_inside = []
    if ids:
        cond = IndoorPlacement.place_uid.in_(ids)
        if levels:
            cond = cond | IndoorPlacement.level_uid.in_([lv.uid for lv in levels])
        if plans:
            cond = cond | IndoorPlacement.plan_uid.in_([p.uid for p in plans])
        for p, a in db.execute(select(IndoorPlacement, Asset).join(Asset, Asset.uid == IndoorPlacement.asset_uid)
                               .where(cond, IndoorPlacement.state == "confirmed", Asset.uid.notin_(ids))):
            ok, why = eligible(p, a.workspace_id) if mode == "move" else (True, None)
            placed_inside.append({"record": {"uid": a.uid, "key": a.key, "name": a.name, "workspace_id": a.workspace_id},
                                  "keeps_placement": ok, "why": why})

    references = []
    if ids:
        for rel in db.scalars(select(Relation).where(or_(Relation.from_asset_uid.in_(ids), Relation.to_asset_uid.in_(ids)))):
            other = rel.to_asset_uid if rel.from_asset_uid in ids else rel.from_asset_uid
            if other in ids:
                continue
            o = db.get(Asset, other)
            references.append({"kind": "relation", "relation_type": rel.relation_type,
                               "from": {"uid": o.uid, "key": o.key, "name": o.name, "workspace_id": o.workspace_id} if o else None,
                               "resolves_after": mode == "copy",
                               "why": None if mode == "copy" else "a move drops a relation crossing the workspace boundary"})
        for a in moving:
            for o in db.scalars(select(Asset).where(cast(Asset.attributes, String).contains(a.uid), Asset.uid.notin_(ids),
                                                    Asset.deleted_at.is_(None))):
                keys = [k for k, v in (o.attributes or {}).items() if v == a.uid or (isinstance(v, list) and a.uid in v)]
                if not keys:
                    continue
                ws_after = after_ws or a.workspace_id
                ok = reaches_after(db, a, ws_after, o.workspace_id, shared_after[a.uid] if mode == "move" else a.site_shared)
                without_global = (o.workspace_id == ws_after or
                                  ((shared_after[a.uid] if mode == "move" else a.site_shared)
                                   and sites.site_of(db, o.workspace_id) == ws_after))
                references.append({"kind": "attribute", "attributes": keys, "to": a.uid,
                                   "from": {"uid": o.uid, "key": o.key, "name": o.name, "workspace_id": o.workspace_id},
                                   "resolves_after": ok, "resolves_if_not_global": without_global,
                                   "why": None if ok else f"{o.workspace_id} would not reach {a.name}"})

    from app.models.asset_subresources import AssetLabel
    labels = db.scalar(select(func.count()).select_from(AssetLabel).where(
        AssetLabel.asset_uid.in_(ids))) if ids else 0

    problems = ([f"{c['name']}: its placement would end ({c['why']})" for c in carried if not c["eligible"]] +
                [f"{x['record']['name']} ({x['record']['workspace_id']}) would lose its placement: {x['why']}"
                 for x in placed_inside if not x["keeps_placement"]] +
                [f"{r['from']['name'] if r['from'] else '?'} ({r['from']['workspace_id'] if r['from'] else '?'}): "
                 f"{r['why']}" for r in references if not r["resolves_after"]] +
                [f"plan {p['name']}: its file is missing" for p in indoors["plans"] if not p["files_present"]])
    return {"source": source, "target": target, "mode": mode, "records": records, "indoors": indoors,
            "placements": carried, "placed_inside": placed_inside, "references": references,
            "labels_carried": labels, "problems": problems, "clean": not problems}


def _place_of_level(db: Session, uid: Optional[str]) -> Optional[str]:
    lv = db.get(PlaceLevel, uid) if uid else None
    return lv.place_uid if lv else None


def _place_of_plan(db: Session, uid: Optional[str]) -> Optional[str]:
    p = db.get(FloorPlan, uid) if uid else None
    return p.place_uid if p else None


# --------------------------------------------------------------------------- carrying

def _end(db: Session, p: IndoorPlacement, reason: str, actor: Optional[str]) -> None:
    at = indoor.now()
    p.state, p.valid_until = "withdrawn", at
    record = db.get(Asset, p.asset_uid)
    if record is not None:
        indoor._history(db, record, f"No longer placed indoors: {reason}", actor, at)


def carry_move(db: Session, source: str, target: str, asset_uids: set[str], actor: Optional[str] = None) -> dict:
    """After the records moved (their workspace_id is the target's): their places' floors and plans, their own
    placements, and the placements of other records in them."""
    counts = {"levels": 0, "plans": 0, "placements": 0, "placements_ended": 0}
    ids = set(asset_uids)
    if not ids:
        return counts
    for lv in db.scalars(select(PlaceLevel).where(PlaceLevel.place_uid.in_(ids))):
        lv.workspace_id = target
        counts["levels"] += 1
    for plan in db.scalars(select(FloorPlan).where(FloorPlan.place_uid.in_(ids))):
        plan.workspace_id = target
        counts["plans"] += 1
    db.flush()
    sites.refresh(db, source, actor=actor)
    sites.refresh(db, target, actor=actor)
    levels = set(db.scalars(select(PlaceLevel.uid).where(PlaceLevel.place_uid.in_(ids))))
    plans = set(db.scalars(select(FloorPlan.uid).where(FloorPlan.place_uid.in_(ids))))
    cond = IndoorPlacement.asset_uid.in_(ids) | IndoorPlacement.place_uid.in_(ids)
    if levels:
        cond = cond | IndoorPlacement.level_uid.in_(levels)
    if plans:
        cond = cond | IndoorPlacement.plan_uid.in_(plans)
    for p in db.scalars(select(IndoorPlacement).where(cond, IndoorPlacement.state == "confirmed")):
        record = db.get(Asset, p.asset_uid)
        if record is None:
            continue
        if p.asset_uid in ids:
            p.workspace_id = target
        reach = [indoor._reachable_place(db, u, record.workspace_id)
                 for u in (p.place_uid, _place_of_level(db, p.level_uid), _place_of_plan(db, p.plan_uid)) if u]
        if all(reach):
            counts["placements"] += p.asset_uid in ids
            continue
        _end(db, p, f"its place is no longer reachable from {record.workspace_id} after a transfer", actor)
        counts["placements_ended"] += 1
    db.flush()
    return counts


def _copy_file(path: Optional[str], new_name: str) -> Optional[str]:
    if not path:
        return None
    new_path = os.path.join(indoor.PLANS_DIR, new_name + os.path.splitext(path)[1])
    os.makedirs(indoor.PLANS_DIR, exist_ok=True)
    try:
        shutil.copyfile(path, new_path)
    except OSError:
        return None
    return new_path


def carry_copy(db: Session, target: str, asset_map: dict[str, str], actor: Optional[str] = None) -> dict:
    """After the records were copied: copies of their places' floors and plans (files, control points, fit), and
    a placement for each copied record that was placed — on the copies, or on the original where the target
    reaches it."""
    counts = {"levels": 0, "plans": 0, "plan_files_missing": 0, "placements": 0, "placements_not_carried": 0}
    if not asset_map:
        return counts
    level_map: dict[str, str] = {}
    plan_map: dict[str, str] = {}
    for lv in list(db.scalars(select(PlaceLevel).where(PlaceLevel.place_uid.in_(asset_map)))):
        new = PlaceLevel(uid=str(uuid.uuid4()), workspace_id=target, place_uid=asset_map[lv.place_uid], name=lv.name,
                         ordinal=lv.ordinal, elevation_m=lv.elevation_m, height_m=lv.height_m, created_by=actor,
                         created_at=indoor.now())
        db.add(new)
        level_map[lv.uid] = new.uid
        counts["levels"] += 1
    db.flush()                                     # the floors first: the plans point at them
    for plan in list(db.scalars(select(FloorPlan).where(FloorPlan.place_uid.in_(asset_map)))):
        uid = str(uuid.uuid4())
        picture = _copy_file(plan.storage_path, uid)
        if picture is None:
            counts["plan_files_missing"] += 1
            continue
        db.add(FloorPlan(uid=uid, workspace_id=target, place_uid=asset_map[plan.place_uid],
                         level_uid=level_map.get(plan.level_uid) if plan.level_uid else None, name=plan.name,
                         storage_path=picture, mime_type=plan.mime_type, width_px=plan.width_px,
                         height_px=plan.height_px, source_filename=plan.source_filename, source_kind=plan.source_kind,
                         source_path=_copy_file(plan.source_path, uid + "-source"),
                         control_points=list(plan.control_points) if plan.control_points else None,
                         transform=dict(plan.transform) if plan.transform else None, residual_m=plan.residual_m,
                         created_by=actor, created_at=indoor.now(), updated_at=indoor.now()))
        plan_map[plan.uid] = uid
        counts["plans"] += 1
    db.flush()
    for old_uid, new_uid in asset_map.items():
        p = indoor.current(db, old_uid)
        if p is None:
            continue
        place_uid = asset_map.get(p.place_uid, p.place_uid) if p.place_uid else None
        level_uid = level_map.get(p.level_uid, p.level_uid) if p.level_uid else None
        plan_uid = plan_map.get(p.plan_uid, p.plan_uid) if p.plan_uid else None
        reach = [indoor._reachable_place(db, u, target)
                 for u in (place_uid, _place_of_level(db, level_uid), _place_of_plan(db, plan_uid)) if u]
        if not all(reach):
            counts["placements_not_carried"] += 1
            continue
        db.add(IndoorPlacement(uid=str(uuid.uuid4()), workspace_id=target, asset_uid=new_uid, place_uid=place_uid,
                               level_uid=level_uid, plan_uid=plan_uid, plan_x=p.plan_x, plan_y=p.plan_y,
                               source=p.source, note=p.note, state="confirmed", valid_from=indoor.now(),
                               confirmed_by=actor, created_at=indoor.now()))
        counts["placements"] += 1
    db.flush()
    sites.refresh(db, target, actor=actor)
    return counts
