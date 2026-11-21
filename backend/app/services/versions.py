"""Record versions and preconditions (flutter-app-design §3.3, §5.4; revision §24.3 item 3).

The version of each kind of record:
- **Asset, Position, Installation:** the highest ledger status-event sequence number that touched
  the record. Each event names its predicate, so the server can tell which fields changed since a
  version.
- **Ticket:** its `version`. Each change bumps it, and `field_versions` keeps, per field, the
  version that last changed that field.
- **Document:** its current revision and that revision's state.

A command carries the version the person saw, as `If-Match`. When the record has moved on since
then:
- if nothing the command changes has changed, the command is applied;
- if a field it changes has changed, the answer is 409 `stale`, with the current values;
- if that field is protected (§5.4), the command becomes a review item with what the person
  submitted. It is never applied over the change.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# §5.4: fields whose conflicting change is never applied, only reviewed. The active ledger policy's
# protected predicates are added to these.
PROTECTED = {"attr:serial", "attr:inventory_number", "attr:ip", "attr:mac", "attr:fqdn", "attr:safety_class",
             "rel:acts on"}
REVIEW_TYPE = "stale_command"


def parse_if_match(value: Optional[str]) -> Optional[str]:
    """`"12"`, `W/"12"` or `12` → `12`; None when the header is absent or `*`."""
    if value is None:
        return None
    v = value.strip()
    if v.startswith("W/"):
        v = v[2:]
    v = v.strip('"')
    return None if v in ("", "*") else v


def etag(version) -> str:
    return f'"{version}"'


# --------------------------------------------------------------------------- ledger records

def asset_version(db: Session, uid: str) -> int:
    from app.models.ledger import StatusEvent
    return int(db.scalar(select(func.max(StatusEvent.seq)).where(StatusEvent.subject_uid == uid)) or 0)


def changed_since(db: Session, uid: str, seen: int) -> set[str]:
    from app.models.ledger import StatusEvent
    return set(db.scalars(select(StatusEvent.predicate).where(StatusEvent.subject_uid == uid,
                                                              StatusEvent.seq > seen)))


def protected_predicates(db: Session) -> set[str]:
    out = set(PROTECTED)
    try:
        from app.ledger import engine
        policy, _row = engine.active_policy(db)
        for p in policy.protected:
            preds = p.get("predicate")
            out.update(preds if isinstance(preds, list) else [preds] if preds else [])
    except Exception:
        pass
    return out


def _int(seen: str, what: str) -> int:
    try:
        return int(seen)
    except ValueError:
        raise HTTPException(status_code=412, detail={
            "error": f"If-Match must be the {what} version this client read.", "code": "invalid",
            "field": "If-Match"})


def check_asset(db: Session, record, seen_header: Optional[str], changes: dict, command: dict,
                actor: str) -> None:
    """Refuse, or turn into a review item, an edit made against an older version."""
    seen_raw = parse_if_match(seen_header)
    if seen_raw is None:
        return
    seen = _int(seen_raw, "record")
    current = asset_version(db, record.uid)
    if seen >= current:
        return
    touched = set(changes) & changed_since(db, record.uid, seen)
    if not touched:
        return                                  # the record moved on elsewhere: apply
    values = {p: _current_value(record, p) for p in sorted(touched)}
    protected = touched & protected_predicates(db)
    if protected:
        cid = open_review(db, record, command, actor, seen, current, values)
        raise HTTPException(status_code=409, detail={
            "error": "This record changed since you read it, in a field that needs review. "
                     "Your change was not applied; it is waiting in the review queue.",
            "code": "stale", "review_item": cid, "field": sorted(protected)[0],
            "current": {"version": current, "values": values}})
    raise HTTPException(status_code=409, detail={
        "error": "Someone changed this since you read it. Compare the current values and try again.",
        "code": "stale", "field": sorted(touched)[0], "current": {"version": current, "values": values}})


def _current_value(record, predicate: str):
    if predicate == "name":
        return record.name
    if predicate.startswith("attr:"):
        return (record.attributes or {}).get(predicate[5:])
    return None


def open_review(db: Session, record, command: dict, actor: str, seen, current, values: dict,
                evidence: Optional[dict] = None) -> str:
    """A command that may not be applied over a change becomes a review item (§5.4). It is committed
    at once: the caller then refuses the command, and the refusal must not roll it back."""
    from app.models.ledger import Conflict, ConflictEvent
    detail = {"command": command, "submitted_by": actor, "seen_version": seen, "current_version": current,
              "current": values, "evidence": evidence or {}, "at": datetime.now(timezone.utc).isoformat()}
    cid = hashlib.sha256(json.dumps([REVIEW_TYPE, record.uid, command, seen], sort_keys=True, default=str)
                         .encode()).hexdigest()[:24]
    if db.get(Conflict, cid) is None:
        ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type=REVIEW_TYPE, subject_uid=record.uid,
                           detail=detail, cause=f"stale command by {actor}", at=datetime.now(timezone.utc))
        db.add(ev)
        db.flush()
        db.add(Conflict(conflict_id=cid, conflict_type=REVIEW_TYPE, severity="non-blocking",
                        workspace_id=record.workspace_id, subject_uid=record.uid, detail=detail,
                        opened_seq=ev.seq))
    db.commit()
    return cid


def close_review(db: Session, cid: str, actor: str, outcome: str) -> None:
    from app.models.ledger import Conflict, ConflictEvent
    c = db.get(Conflict, cid)
    if c is None or c.conflict_type != REVIEW_TYPE:
        raise HTTPException(status_code=404, detail={"error": "No such review item.", "code": "not_found"})
    db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type=REVIEW_TYPE, subject_uid=c.subject_uid,
                         detail={**(c.detail or {}), "outcome": outcome}, cause=f"{outcome} by {actor}",
                         at=datetime.now(timezone.utc)))
    db.delete(c)


# --------------------------------------------------------------------------- tickets

TICKET_FIELDS = ("title", "description", "state", "priority", "assignee", "asset_uid", "schema_uid", "due_date",
                 "service_uid", "assigned_group_uid")


def ticket_snapshot(issue) -> dict:
    out = {f: getattr(issue, f, None) for f in TICKET_FIELDS}
    for k, v in (issue.attributes or {}).items():
        out[f"attributes.{k}"] = v
    return out


def ticket_fields_in(patch: dict, issue) -> set[str]:
    """The fields an update would change."""
    out = {f for f in TICKET_FIELDS if f in patch and patch[f] != getattr(issue, f, None)}
    if patch.get("attributes") is not None:
        old, new = issue.attributes or {}, patch["attributes"]
        out |= {f"attributes.{k}" for k in set(old) | set(new) if old.get(k) != new.get(k)}
    return out


def check_ticket(issue, seen_header: Optional[str], fields: Iterable[str]) -> None:
    seen_raw = parse_if_match(seen_header)
    if seen_raw is None:
        return
    seen = _int(seen_raw, "ticket")
    if seen >= (issue.version or 1):
        return
    fv = issue.field_versions or {}
    stale = sorted(f for f in fields if int(fv.get(f, 0)) > seen)
    if stale:
        snap = ticket_snapshot(issue)
        raise HTTPException(status_code=409, detail={
            "error": "Someone changed this ticket since you read it. Compare the current values and try again.",
            "code": "stale", "field": stale[0],
            "current": {"version": issue.version, "values": {f: _jsonable(snap.get(f)) for f in stale}}})


def bump_ticket(issue, fields: Iterable[str]) -> None:
    fields = set(fields)
    if not fields:
        return
    issue.version = (issue.version or 1) + 1
    fv = dict(issue.field_versions or {})
    for f in fields:
        fv[f] = issue.version
    issue.field_versions = fv


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


# --------------------------------------------------------------------------- documents

def document_version(doc, revision) -> str:
    return f"{revision.uid}:{revision.state}" if revision is not None else "none"
