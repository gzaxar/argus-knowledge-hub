"""Governing `Other Equipment` (asset-model-revision §5.5).

* **The vocabulary.** `equipment_class` values are owned by the catalogue.
  Adding one is a catalogue decision. A class that already is a type of its
  own in this catalogue starts out promoted, pointing to that type: it is
  not assignable, so nobody files a PLC as "Other Equipment, class PLC".
* **The report** (monthly, or on demand): Other Equipment per class,
  workspace and source; the share of `Unclassified` among all Equipment,
  with its alert; classes whose objects appear in tickets or in causal
  relations; the "key: value" lines people keep writing into descriptions;
  and the class-specific attributes people asked for.
* **Promotion reviews** open when a class meets any threshold.
* **Promotion** creates a child type of `Asset` carrying the requested
  attributes, retypes the class's objects in place (same uids, a `retyped`
  record event each), and the class is no longer assignable (I-CAT-1).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.equipment_class import EquipmentClass, EquipmentClassRequest, EquipmentClassReview
from app.models.issue import Issue
from app.models.ledger import TicketLink
from app.models.schema import Schema

OTHER = "Other Equipment"
# The starting vocabulary, and the classes the catalogue already has as a type under another name: the
# accelerator package (backend/packages/accelerator/vocabulary.yaml).
def _vocabulary() -> dict:
    from app.packages import defaults
    return defaults.equipment_classes()


SEED = list(_vocabulary().get("classes") or [])
UNCLASSIFIED = str(_vocabulary().get("unclassified") or "Unclassified")
ALREADY_A_TYPE = dict(_vocabulary().get("already_a_type") or {})
THRESHOLDS = {"objects": 25, "workspaces": 2, "requested_attributes": 3}
ALERT_SHARE, ALERT_MIN, ALERT_ABSOLUTE = 0.05, 10, 50
KEY_VALUE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/-]{1,30}?)\s*[:=]\s*\S", re.M)


class ClassError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _type_names(db: Session) -> set[str]:
    return set(db.scalars(select(Schema.name).where(Schema.applies_to == "objects")))


def seed(db: Session, actor: str = "catalogue") -> list[str]:
    """The starting vocabulary; idempotent."""
    types = _type_names(db)
    added = []
    for name in SEED:
        if db.get(EquipmentClass, name) is not None:
            continue
        as_type = ALREADY_A_TYPE.get(name, name)
        promoted = as_type in types and name != UNCLASSIFIED
        db.add(EquipmentClass(name=name, status="promoted" if promoted else "active",
                              promoted_type=as_type if promoted else None, added_by=actor, added_at=now(),
                              note="already a type of its own in the catalogue" if promoted else "seed"))
        added.append(name)
    db.flush()
    return added


def vocabulary(db: Session) -> list[EquipmentClass]:
    seed(db)
    return list(db.scalars(select(EquipmentClass).order_by(EquipmentClass.name)))


def assert_assignable(db: Session, value) -> None:
    """I-CAT-1: only an active class can be given to an object."""
    seed(db)
    c = db.get(EquipmentClass, str(value)) if value else None
    if c is None:
        raise ClassError(f"'{value}' is not an equipment class; the catalogue adds classes")
    if c.status != "active":
        where = f": use the type {c.promoted_type}" if c.promoted_type else ""
        raise ClassError(f"the class '{value}' is {c.status} and can no longer be assigned{where}")


def add_class(db: Session, name: str, actor: str, note: Optional[str] = None) -> EquipmentClass:
    name = name.strip()
    if not name:
        raise ClassError("a class needs a name")
    if db.get(EquipmentClass, name) is not None:
        raise ClassError(f"'{name}' already exists")
    if name in _type_names(db):
        raise ClassError(f"'{name}' is already a type; create the object with that type")
    c = EquipmentClass(name=name, status="active", added_by=actor, added_at=now(), note=note)
    db.add(c)
    db.flush()
    return c


def request_attribute(db: Session, workspace_id: str, actor: str, class_name: str, attribute: str,
                      reason: Optional[str] = None) -> EquipmentClassRequest:
    if db.get(EquipmentClass, class_name) is None:
        raise ClassError(f"unknown class '{class_name}'")
    if not attribute.strip():
        raise ClassError("name the attribute")
    r = EquipmentClassRequest(class_name=class_name, attribute=attribute.strip(), reason=reason,
                              requested_by=actor, workspace_id=workspace_id, created_at=now())
    db.add(r)
    db.flush()
    return r


# --------------------------------------------------------------------------- report

def _descendants(db: Session, names: set[str]) -> set[str]:
    """Schema uids of these types and everything below them."""
    rows = list(db.scalars(select(Schema).where(Schema.applies_to == "objects")))
    children = defaultdict(list)
    for s in rows:
        if s.parent_schema_uid:
            children[s.parent_schema_uid].append(s.uid)
    out, todo = set(), [s.uid for s in rows if s.name in names]
    while todo:
        uid = todo.pop()
        if uid not in out:
            out.add(uid)
            todo += children.get(uid, [])
    return out


def _live():
    return (Asset.deleted_at.is_(None), Asset.merged_into_uid.is_(None), Asset.record_status != "Retired")


def report(db: Session) -> dict:
    from app.services.causal_model import classify
    seed(db)
    others = list(db.scalars(select(Asset).where(Asset.type == OTHER, *_live())))
    per_class: dict[str, dict] = defaultdict(lambda: {"objects": 0, "workspaces": Counter(), "sources": Counter(),
                                                       "in_tickets": 0, "causal": 0, "description_keys": Counter()})
    uids_by_class = defaultdict(list)
    for a in others:
        attrs = a.attributes or {}
        cls = attrs.get("equipment_class") or UNCLASSIFIED
        row = per_class[cls]
        row["objects"] += 1
        row["workspaces"][a.workspace_id] += 1
        row["sources"][attrs.get("argus_source") or "manual"] += 1
        for key in KEY_VALUE.findall(str(attrs.get("description") or "")):
            row["description_keys"][key.strip().lower()] += 1
        uids_by_class[cls].append(a.uid)
    for cls, uids in uids_by_class.items():
        ticketed = set(db.scalars(select(AssetTicket.asset_uid).where(AssetTicket.asset_uid.in_(uids)))) \
            | set(db.scalars(select(Issue.asset_uid).where(Issue.asset_uid.in_(uids), Issue.deleted_at.is_(None)))) \
            | set(db.scalars(select(TicketLink.asset_uid).where(TicketLink.asset_uid.in_(uids))))
        per_class[cls]["in_tickets"] = len(ticketed)
        causal = set()
        for r in db.scalars(select(Relation).where((Relation.from_asset_uid.in_(uids)) | (Relation.to_asset_uid.in_(uids)))):
            if classify(r.relation_type) is not None:
                causal |= {r.from_asset_uid, r.to_asset_uid} & set(uids)
        per_class[cls]["causal"] = len(causal)
    requests = defaultdict(set)
    for r in db.scalars(select(EquipmentClassRequest)):
        requests[r.class_name].add(r.attribute.lower())

    equipment_types = _descendants(db, {"Asset"})
    equipment = db.scalar(select(func.count()).select_from(Asset).where(
        Asset.schema_uid.in_(equipment_types), *_live())) or 0
    unclassified = per_class[UNCLASSIFIED]["objects"] if UNCLASSIFIED in per_class else 0
    share = unclassified / equipment if equipment else 0.0
    alert = alert_for(unclassified, equipment)

    classes = []
    statuses = {c.name: c for c in db.scalars(select(EquipmentClass))}
    for name in sorted(set(per_class) | set(statuses)):
        row = per_class.get(name) or {"objects": 0, "workspaces": Counter(), "sources": Counter(), "in_tickets": 0,
                                      "causal": 0, "description_keys": Counter()}
        c = statuses.get(name)
        classes.append({
            "class": name, "status": c.status if c else "unknown", "promoted_type": c.promoted_type if c else None,
            "objects": row["objects"], "workspaces": dict(row["workspaces"]), "sources": dict(row["sources"]),
            "in_tickets": row["in_tickets"], "causal": row["causal"],
            "requested_attributes": sorted(requests.get(name, set())),
            "description_keys": [{"key": k, "count": n} for k, n in row["description_keys"].most_common(5) if n > 1],
            "triggers": _triggers(name, row, requests.get(name, set())),
        })
    return {"at": now().isoformat(), "equipment": equipment, "other_equipment": len(others),
            "unclassified": {"count": unclassified, "share": round(share, 4), "alert": alert,
                             "rule": f"> {ALERT_SHARE:.0%} of Equipment and at least {ALERT_MIN}, or more than {ALERT_ABSOLUTE}"},
            "classes": classes}


def _triggers(name: str, row: dict, requested: set) -> list[dict]:
    """The thresholds a class meets, each with a stable kind."""
    if name == UNCLASSIFIED:
        return []             # Unclassified raises the alert; it is never promoted itself
    out = []
    if row["objects"] >= THRESHOLDS["objects"]:
        out.append({"kind": "objects", "text": f"{row['objects']} active objects (≥ {THRESHOLDS['objects']})"})
    if len(row["workspaces"]) >= THRESHOLDS["workspaces"]:
        out.append({"kind": "workspaces",
                    "text": f"objects in {len(row['workspaces'])} workspaces (≥ {THRESHOLDS['workspaces']})"})
    if len(requested) >= THRESHOLDS["requested_attributes"]:
        out.append({"kind": "requested_attributes", "text": f"{len(requested)} class-specific attributes requested "
                                                            f"(≥ {THRESHOLDS['requested_attributes']})"})
    if row["causal"]:
        out.append({"kind": "causal", "text": f"{row['causal']} object(s) with a causal role"})
    return out


def alert_for(unclassified: int, equipment: int) -> bool:
    """§5.5: more than 5 % of Equipment and at least 10 records, or more than 50."""
    share = unclassified / equipment if equipment else 0.0
    return (share > ALERT_SHARE and unclassified >= ALERT_MIN) or unclassified > ALERT_ABSOLUTE


def open_reviews(db: Session) -> list[EquipmentClassReview]:
    """Open a promotion review for each active class that meets a threshold
    and has none open. A declined class is reviewed again only when a new
    kind of trigger appears."""
    opened = []
    for c in report(db)["classes"]:
        if c["status"] != "active" or not c["triggers"]:
            continue
        existing = list(db.scalars(select(EquipmentClassReview).where(EquipmentClassReview.class_name == c["class"])))
        if any(r.status == "open" for r in existing):
            continue
        kinds = {t["kind"] for t in c["triggers"]}
        declined = [r for r in existing if r.status == "declined"]
        if declined and kinds <= {t["kind"] for r in declined for t in r.triggers}:
            continue
        r = EquipmentClassReview(class_name=c["class"], triggers=c["triggers"], status="open", opened_at=now())
        db.add(r)
        opened.append(r)
    db.flush()
    return opened


def open_review(db: Session, class_name: str, actor: str, reason: str) -> EquipmentClassReview:
    """A person opens a review: a query or dashboard that filters on the
    class is a threshold ARGUS cannot see for itself."""
    c = db.get(EquipmentClass, class_name)
    if c is None or c.status != "active" or class_name == UNCLASSIFIED:
        raise ClassError(f"'{class_name}' is not an active class")
    if not reason.strip():
        raise ClassError("say which query or dashboard needs the class")
    if db.scalar(select(EquipmentClassReview.id).where(EquipmentClassReview.class_name == class_name,
                                                       EquipmentClassReview.status == "open")):
        raise ClassError(f"a review of '{class_name}' is already open")
    r = EquipmentClassReview(class_name=class_name, status="open", opened_at=now(),
                             triggers=[{"kind": "query", "text": f"requested by {actor}: {reason}"}])
    db.add(r)
    db.flush()
    return r


def decline(db: Session, review_id: int, actor: str, reason: str) -> EquipmentClassReview:
    r = db.get(EquipmentClassReview, review_id)
    if r is None or r.status != "open":
        raise ClassError("no open review with that id")
    if not reason.strip():
        raise ClassError("a declined promotion needs a reason")
    r.status, r.decided_by, r.decided_at, r.reason = "declined", actor, now(), reason
    db.flush()
    return r


def promote(db: Session, catalogue_workspace_id: str, actor: str, class_name: str, type_name: str,
            reason: str) -> dict:
    """The class becomes a child type of `Asset`; its objects are retyped in
    place; the class is no longer assignable."""
    import uuid
    from app.ledger import engine
    c = db.get(EquipmentClass, class_name)
    if c is None or c.status != "active" or class_name == UNCLASSIFIED:
        raise ClassError(f"'{class_name}' cannot be promoted")
    type_name = type_name.strip()
    if not type_name or type_name in _type_names(db):
        raise ClassError(f"'{type_name}' is empty or already a type")
    if not reason.strip():
        raise ClassError("a promotion needs a reason")
    parent = db.scalar(select(Schema).where(Schema.name == "Asset", Schema.workspace_id == catalogue_workspace_id,
                                            Schema.applies_to == "objects"))
    if parent is None:
        raise ClassError("this workspace is not the catalogue (it has no Asset type)")
    requested = sorted({r.attribute for r in db.scalars(select(EquipmentClassRequest)
                                                         .where(EquipmentClassRequest.class_name == class_name))})
    from app.services.asset_types import _attr
    attributes = [_attr(re.sub(r"\W+", "_", a.lower()).strip("_"), a) for a in requested]
    schema = Schema(uid=str(uuid.uuid4()), workspace_id=catalogue_workspace_id, name=type_name,
                    description=f"Promoted from the equipment class '{class_name}': {reason}",
                    parent_schema_uid=parent.uid, attributes=attributes, is_global=True, applies_to="objects",
                    is_concrete=True)
    db.add(schema)
    db.flush()
    objects = [a for a in db.scalars(select(Asset).where(Asset.type == OTHER, *_live()))
               if (a.attributes or {}).get("equipment_class") == class_name]
    decision = engine._record_decision(db, "promote_equipment_class", actor, catalogue_workspace_id,
                                       value={"class": class_name, "type": type_name, "objects": len(objects),
                                              "attributes": requested}, reason=reason)
    # Each object's type becomes a confirmed statement, per workspace: a rebuild
    # keeps it, and withdrawing it puts the object back to Other Equipment.
    from app.ledger import service
    by_workspace: dict[str, list[str]] = {}
    for a in objects:
        by_workspace.setdefault(a.workspace_id, []).append(a.uid)
    for ws, uids in sorted(by_workspace.items()):
        service.retype_many(db, ws, actor, uids, type_name,
                            reason=f"promotion of '{class_name}' ({decision.decision_id}): {reason}",
                            catalogue_decision=True)
    c.status, c.promoted_type = "promoted", type_name
    for r in db.scalars(select(EquipmentClassReview).where(EquipmentClassReview.class_name == class_name,
                                                           EquipmentClassReview.status == "open")):
        r.status, r.decided_by, r.decided_at, r.reason = "promoted", actor, now(), reason
    db.flush()
    return {"class": class_name, "type": type_name, "schema_uid": schema.uid, "retyped": len(objects),
            "attributes": requested, "decision_id": decision.decision_id}


def catalogue_owners() -> list[str]:
    import os
    return [x.strip() for x in os.environ.get("ARGUS_CATALOGUE", "").split(",") if x.strip()]


def monthly(db: Session) -> dict:
    """The monthly run: open the reviews that are due, and tell the catalogue
    owners (ARGUS_CATALOGUE) about them and about the Unclassified alert."""
    from app.models.workflow import Notification
    opened = open_reviews(db)
    rep = report(db)
    home = db.scalar(select(Schema.workspace_id).where(Schema.name == "Asset", Schema.is_global.is_(True)).limit(1))
    messages = [f"Promotion review opened for '{r.class_name}': " + "; ".join(t["text"] for t in r.triggers)
                for r in opened]
    if rep["unclassified"]["alert"]:
        u = rep["unclassified"]
        messages.append(f"Unclassified equipment: {u['count']} objects, {u['share']:.1%} of Equipment ({u['rule']})")
    if home:
        for who in catalogue_owners():
            for m in messages:
                db.add(Notification(workspace_id=home, recipient=who, kind="catalogue", title=m,
                                    detail={"path": "/catalogue/equipment-classes"}, created_at=now()))
    db.flush()
    return {"opened": [r.class_name for r in opened], "alert": rep["unclassified"]["alert"], "notified": messages,
            "report": rep}
