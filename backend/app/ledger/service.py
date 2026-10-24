"""What people do, expressed as claims and decisions (§3.2: a UI edit is a
claim from the person's stream plus a confirm decision by the same person)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.ledger import engine, temporal
from app.ledger.engine import INSTALLATION, InvariantError, LedgerError, ParsedClaim
from app.models.asset import Asset


def _active(db: Session, uid: str, predicate: str, member: Optional[str] = None) -> list[str]:
    return [d.decision_id for d in engine._active_decisions(db, uid, predicate, member)]


def _multi_attr_batch(db: Session, uid: str, key: str, value, old) -> tuple[list[ParsedClaim], list[dict]]:
    """Claims and confirm-value decisions for one multi-value "set" attribute (engine.MULTI_ATTRS): one
    present/absent statement per member, encoded exactly as set_member's single-member edit does
    (member=json.dumps(item), the claim's value the item itself) — the shape project_subject's
    reassembly expects, and the one this batches for several members changing in the same edit instead
    of set_member's one call per member (which would split them across separate ledger revisions). A
    caller that instead passed the whole list as a single claim's value (every caller here, until this
    fix) made a claim whose auto-derived member was the whole list's own hash, so reassembly read it
    back as a list containing that one whole list, not its items."""
    import json
    predicate = f"attr:{key}"

    def items(v):
        return [] if v is None else (v if isinstance(v, list) else [v])

    new_members = {json.dumps(item): item for item in items(value)}
    old_members = {json.dumps(item): item for item in items(old)}
    wanted = {m: (True, new_members[m]) for m in new_members}
    wanted |= {m: (False, old_members[m]) for m in old_members if m not in new_members}
    claims, batch = [], []
    for member, (present, item) in wanted.items():
        state = "present" if present else "absent"
        claims.append(ParsedClaim(f"uid:{uid}", predicate, item, method="manual", polarity=state, member=member))
        batch.append(confirm_value(uid, predicate, state, member=member, replaces=_active(db, uid, predicate, member)))
    return claims, batch


def confirm_value(uid: str, predicate: str, value, *, member: Optional[str] = None,
                  replaces: Optional[list[str]] = None, reason: Optional[str] = None) -> dict:
    """One decision: supersede what is confirmed now, or confirm afresh."""
    if replaces:
        return {"kind": "supersede", "subject_uid": uid, "predicate": predicate, "member": member,
                "value": value, "supersedes": replaces, "reason": reason}
    return {"kind": "confirm", "subject_uid": uid, "predicate": predicate, "member": member, "value": value,
            "reason": reason}


def edit_value(db: Session, workspace_id: str, actor: str, uid: str, predicate: str, value,
               reason: Optional[str] = None, defer_derive: bool = False) -> list:
    """A person setting a field: their statement, confirmed, replacing any
    confirmation they could see (an edit form shows the current value)."""
    from app.ledger.cutover import assert_writable
    assert_writable(db, workspace_id, "objects")
    stream = engine.person_stream(db, workspace_id, actor)
    if predicate.startswith("attr:") and engine.is_multi(predicate):
        record = db.get(Asset, uid)
        old = (record.attributes or {}).get(predicate[5:]) if record else None
        claims, batch = _multi_attr_batch(db, uid, predicate[5:], value, old)
    else:
        claims = [ParsedClaim(f"uid:{uid}", predicate, value, method="manual")]
        batch = [confirm_value(uid, predicate, value, replaces=_active(db, uid, predicate), reason=reason)]
    engine.add_manual_claims(db, stream, claims, cause=f"edit by {actor}")
    return engine.apply_decisions(db, workspace_id, actor, batch, defer_derive=defer_derive)


def set_member(db: Session, workspace_id: str, actor: str, uid: str, predicate: str, member_value,
               present: bool, reason: Optional[str] = None, defer_derive: bool = False) -> list:
    """Add or remove one member of a set as a confirmed positive or negative
    fact (§7.8.1). Removing is never a `reject`."""
    import json
    from app.ledger.cutover import assert_writable
    assert_writable(db, workspace_id, "objects")
    member = json.dumps(member_value)
    stream = engine.person_stream(db, workspace_id, actor)
    engine.add_manual_claims(db, stream, [ParsedClaim(f"uid:{uid}", predicate, member_value, method="manual",
                                                      member=member,
                                                      polarity="present" if present else "absent")],
                             cause=f"edit by {actor}")
    return engine.apply_decisions(db, workspace_id, actor, [
        confirm_value(uid, predicate, "present" if present else "absent", member=member,
                      replaces=_active(db, uid, predicate, member), reason=reason)], defer_derive=defer_derive)


def confirm_installation(db: Session, workspace_id: str, actor: str, installation_uid: str, *,
                         valid_from: Optional[dict] = None) -> list:
    inst = db.get(Asset, installation_uid)
    if inst is None or inst.type != INSTALLATION:
        raise LedgerError("not an Installation")
    batch = [confirm_value(installation_uid, "exists", "present", replaces=_active(db, installation_uid, "exists"))]
    if valid_from is not None:
        batch.append(confirm_value(installation_uid, "attr:valid_from", valid_from,
                                   replaces=_active(db, installation_uid, "attr:valid_from")))
    return engine.apply_decisions(db, workspace_id, actor, batch)


def reject_installation(db: Session, workspace_id: str, actor: str, installation_uid: str,
                        reason: Optional[str] = None) -> list:
    batch = [confirm_value(installation_uid, "exists", "absent", replaces=_active(db, installation_uid, "exists"),
                           reason=reason)]
    return engine.apply_decisions(db, workspace_id, actor, batch)


def new_installation_claims(db: Session, workspace_id: str, actor: str, position_uid: str, asset_uid: str,
                            valid_from: dict, valid_until: Optional[dict] = None) -> str:
    """A person records a unit at a position; returns the new record's uid."""
    position, unit = db.get(Asset, position_uid), db.get(Asset, asset_uid)
    if position is None or unit is None:
        raise LedgerError("unknown position or asset")
    if position.type not in engine.INSTALLABLE:
        raise InvariantError("I-INS-4", f"{position.type} is not an installable position")
    temporal.bounds(valid_from, "from")
    ref = f"person:inst:{engine.ulid()}"
    claims = [
        ParsedClaim(ref, "exists", {"type": INSTALLATION}, method="manual"),
        ParsedClaim(ref, "rel:installed at", {"ref": f"uid:{position_uid}"}, method="manual"),
        ParsedClaim(ref, "rel:installation of", {"ref": f"uid:{asset_uid}"}, method="manual"),
        ParsedClaim(ref, "attr:valid_from", valid_from, method="manual"),
    ]
    if valid_until is not None:
        claims.append(ParsedClaim(ref, "attr:valid_until", valid_until, method="manual"))
    stream = engine.person_stream(db, workspace_id, actor)
    # The record lives in the position's workspace (I-INS-5).
    if position.workspace_id != workspace_id:
        raise InvariantError("I-INS-5", "an Installation belongs to its position's workspace")
    engine.add_manual_claims(db, stream, claims, cause=f"installation by {actor}")
    uid = engine.resolve_ref(db, ref)
    engine.project_subject(db, uid, f"installation by {actor}")
    return uid


def swap(db: Session, workspace_id: str, actor: str, position_uid: str, new_asset_uid: str, at: dict,
         reason: str = "Unknown") -> dict:
    """End the current installation at a position and start a new one at the
    same instant, as one atomic batch (§8.4). Validation runs once, at the end."""
    current = [v for v in engine.installations(db, position_uid=position_uid, status="Confirmed")
               if v["valid_until"] in (None, {"kind": "open"}) or (v["valid_until"] or {}).get("kind") == "open"]
    batch = []
    for v in current:
        batch.append(confirm_value(v["uid"], "attr:valid_until", at,
                                   replaces=_active(db, v["uid"], "attr:valid_until")))
        batch.append(confirm_value(v["uid"], "attr:removal_reason", reason,
                                   replaces=_active(db, v["uid"], "attr:removal_reason")))
    new_uid = new_installation_claims(db, workspace_id, actor, position_uid, new_asset_uid, at)
    batch.append(confirm_value(new_uid, "exists", "present"))
    engine.apply_decisions(db, workspace_id, actor, batch)
    return {"ended": [v["uid"] for v in current], "installation_uid": new_uid}


def reassign_access_point(db: Session, workspace_id: str, actor: str, ap_uid: str, position_uid: str,
                          at: dict) -> str:
    """A person moves an address to another position (§9.2): the Access Point
    retires with a successor, which serves the new position from `at`."""
    from app.ledger import connectivity
    ap = db.get(Asset, ap_uid)
    if ap is None or ap.type != engine.ACCESS_POINT or ap.workspace_id != workspace_id:
        raise LedgerError("not an Access Point of this workspace")
    if db.get(Asset, position_uid) is None:
        raise LedgerError("unknown position")
    temporal.bounds(at, "from")
    touched = connectivity.reassign(db, ap, position_uid, handover=at, actor=actor, cause=f"reassigned by {actor}")
    for uid in sorted(touched):
        engine.project_subject(db, uid, f"reassigned by {actor}")
    connectivity.validate_access_points(db, touched)
    engine.derive_all(db, [workspace_id])
    return next(v["uid"] for v in connectivity.access_points(db, workspace_id, (ap.attributes or {}).get("address"))
                if v["record_status"] == "Active")


# --------------------------------------------------------------------------- records through the ledger (§13 S5)

def create_record(db: Session, workspace_id: str, actor: str, *, uid: str, schema_uid: str, key: str, name: str,
                  type_name: str, attributes: dict, is_global: bool = False,
                  avatar_icon_uid: Optional[str] = None) -> Asset:
    """A person creating a record: the row, then their statements of its
    existence, name and attributes, confirmed by them, and the projection."""
    from app.ledger.cutover import assert_writable
    from app.ledger.writer import writing
    from app.models.ledger import RecordEvent
    assert_writable(db, workspace_id, "objects")
    with writing(db):
        record = Asset(uid=uid, workspace_id=workspace_id, schema_uid=schema_uid, key=key, name=name, type=type_name,
                       attributes={}, is_global=is_global, avatar_icon_uid=avatar_icon_uid, record_status="Active")
        db.add(record)
        db.flush()
        db.add(RecordEvent(uid=uid, kind="created", after={"key": key, "type": type_name}, cause=f"created by {actor}",
                           at=engine.now()))
        ref = f"uid:{uid}"
        claims = [ParsedClaim(ref, "exists", {"type": type_name, "key": key, "name": name}, method="manual"),
                  ParsedClaim(ref, "name", name, method="manual")]
        batch = [confirm_value(uid, "exists", "present"), confirm_value(uid, "name", name)]
        for k, v in attributes.items():
            if v is None:
                continue
            if engine.is_multi(f"attr:{k}"):
                c, b = _multi_attr_batch(db, uid, k, v, None)
                claims += c
                batch += b
            else:
                claims.append(ParsedClaim(ref, f"attr:{k}", v, method="manual"))
                batch.append(confirm_value(uid, f"attr:{k}", v))
        engine.add_manual_claims(db, engine.person_stream(db, workspace_id, actor), claims,
                                 cause=f"created by {actor}")
        engine.apply_decisions(db, workspace_id, actor, batch)
    return record


def edit_values(db: Session, workspace_id: str, actor: str, uid: str, changes: dict,
                reason: Optional[str] = None) -> list:
    """Several fields at once, as one batch: each a person's statement,
    confirmed, replacing what was confirmed before. A value of None removes
    the field."""
    from app.ledger.cutover import assert_writable
    assert_writable(db, workspace_id, "objects")
    if not changes:
        return []
    stream = engine.person_stream(db, workspace_id, actor)
    current = (db.get(Asset, uid).attributes or {}) if any(engine.is_multi(p) for p in changes) else {}
    claims: list[ParsedClaim] = []
    batch: list[dict] = []
    for p, v in changes.items():
        if p.startswith("attr:") and engine.is_multi(p):
            c, b = _multi_attr_batch(db, uid, p[5:], v, current.get(p[5:]))
            claims += c
            batch += b
        else:
            claims.append(ParsedClaim(f"uid:{uid}", p, v, method="manual"))
            batch.append(confirm_value(uid, p, v, replaces=_active(db, uid, p), reason=reason))
    engine.add_manual_claims(db, stream, claims, cause=f"edit by {actor}")
    return engine.apply_decisions(db, workspace_id, actor, batch)


def retype(db: Session, workspace_id: str, actor: str, uid: str, type_name: str,
           reason: Optional[str] = None) -> list:
    """Change what a record is, in place: a person's statement of its type,
    confirmed, so the change has an author and a reason, a rebuild keeps it
    and withdrawing the statement undoes it."""
    return retype_many(db, workspace_id, actor, [uid], type_name, reason)


def retype_many(db: Session, workspace_id: str, actor: str, uids: list, type_name: str,
                reason: Optional[str] = None, *, catalogue_decision: bool = False) -> list:
    """Several records of one workspace, as one batch. A catalogue decision
    (a class promotion) retypes even where the scope is a read-only mirror:
    what a type is called is the catalogue's, not the mirrored source's."""
    from sqlalchemy import select
    from app.ledger.cutover import assert_writable
    from app.models.schema import Schema
    if not uids:
        return []
    if not catalogue_decision:
        assert_writable(db, workspace_id, "objects")
    known = db.scalar(select(Schema.uid).where(
        Schema.name == type_name, Schema.applies_to == "objects",
        (Schema.workspace_id == workspace_id) | Schema.is_global.is_(True)).limit(1))
    if known is None:
        raise engine.LedgerError(f"there is no type '{type_name}' here")
    engine.add_manual_claims(db, engine.person_stream(db, workspace_id, actor),
                             [ParsedClaim(f"uid:{u}", "type", type_name, method="manual") for u in uids],
                             cause=f"retype by {actor}")
    return engine.apply_decisions(db, workspace_id, actor, [
        confirm_value(u, "type", type_name, replaces=_active(db, u, "type"), reason=reason) for u in uids])


def retype_to(db: Session, workspace_id: str, actor: str, uids: list, schema, reason: Optional[str] = None,
              changes: Optional[dict] = None) -> list:
    """Records of one workspace moved to a type given by its identity (a type migration): the statement names
    the type's uid, so the projection — and any rebuild — puts them on exactly that type, never on another
    of the same name. `changes` are field statements made in the same batch (attr:key → value, None removes)."""
    from app.ledger.cutover import assert_writable
    if not uids:
        return []
    assert_writable(db, workspace_id, "objects")
    value = {"name": schema.name, "schema_uid": schema.uid}
    stream = engine.person_stream(db, workspace_id, actor)
    claims = [ParsedClaim(f"uid:{u}", "type", value, method="manual") for u in uids]
    batch = [confirm_value(u, "type", value, replaces=_active(db, u, "type"), reason=reason) for u in uids]
    for u in uids:
        current = db.get(Asset, u).attributes or {}
        for p, v in ((changes or {}).get(u) or {}).items():
            if p.startswith("attr:") and engine.is_multi(p):
                c, b = _multi_attr_batch(db, u, p[5:], v, current.get(p[5:]))
                claims += c
                batch += b
            else:
                claims.append(ParsedClaim(f"uid:{u}", p, v, method="manual"))
                batch.append(confirm_value(u, p, v, replaces=_active(db, u, p), reason=reason))
    engine.add_manual_claims(db, stream, claims, cause=f"type migration by {actor}")
    return engine.apply_decisions(db, workspace_id, actor, batch)


def relate(db: Session, workspace_id: str, actor: str, from_uid: str, relation_type: str, to_uid: str,
           present: bool = True, reason: Optional[str] = None) -> list:
    """Add or remove an asserted relation. A single-valued one is set or
    cleared; a many-valued one gains or loses a member (§7.8.1)."""
    from app.ledger.cutover import assert_writable
    assert_writable(db, workspace_id, "objects")
    predicate = f"rel:{relation_type}"
    ref = f"uid:{to_uid}"
    stream = engine.person_stream(db, workspace_id, actor)
    if predicate in engine.SINGLE_RELATIONS:
        value = {"ref": ref} if present else None
        engine.add_manual_claims(db, stream, [ParsedClaim(f"uid:{from_uid}", predicate, value, method="manual")],
                                 cause=f"edit by {actor}")
        batch = [confirm_value(from_uid, predicate, value, replaces=_active(db, from_uid, predicate), reason=reason)]
    else:
        engine.add_manual_claims(db, stream, [ParsedClaim(f"uid:{from_uid}", predicate, {"ref": ref}, method="manual",
                                                          polarity="present" if present else "absent")],
                                 cause=f"edit by {actor}")
        state = "present" if present else "absent"
        batch = [confirm_value(from_uid, predicate, state, member=ref, replaces=_active(db, from_uid, predicate, ref),
                               reason=reason)]
    return engine.apply_decisions(db, workspace_id, actor, batch)


def retire_record(db: Session, workspace_id: str, actor: str, uid: str, reason: Optional[str] = None) -> list:
    """Retire, never erase: the record stays, with its history (I-SOR)."""
    from app.ledger.cutover import assert_writable
    assert_writable(db, workspace_id, "objects")
    return engine.apply_decisions(db, workspace_id, actor, [
        confirm_value(uid, "exists", "absent", replaces=_active(db, uid, "exists"), reason=reason)])


def remove_legacy_edge(db: Session, workspace_id: str, actor: str, relation, reason: Optional[str] = None) -> None:
    """An edge from before the ledger has no claim to withdraw: its removal is
    recorded as a decision, with the edge as it was, then made."""
    from app.ledger.writer import writing
    with writing(db):
        engine._record_decision(db, "remove_legacy_edge", actor, workspace_id, subject_uid=relation.from_asset_uid,
                                predicate=f"rel:{relation.relation_type}", reason=reason,
                                target={"to": relation.to_asset_uid, "relation_id": relation.id})
        db.delete(relation)
        db.flush()
