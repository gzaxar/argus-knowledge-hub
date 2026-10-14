"""Identity reconciliation (asset-model-revision §10, D4).

* **Automatic binding on immutable identifiers.** An Insight object is bound
  by its objectId; when Insight re-keys it, the ARGUS record takes the new
  key and the old one becomes a `former_key` alias. No candidate is raised.
* **No automatic merging.** Different source objects sharing a strong
  identifier (serial per manufacturer, inventory number, MAC) become an
  `identity_candidate` review item. The steward merges, rejects the
  candidate, or confirms both as distinct.
* **Uniqueness at creation, after cutover.** Once ARGUS is the system of
  record for a scope, creating a record with a strong identifier an active
  record already holds is refused, pointing to that record (I-ID-1).
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Iterable, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.ledger import engine
from app.ledger.engine import InvariantError, LedgerError, canonical, now
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetComment, AssetLabel, AssetTicket
from app.models.attachment import Attachment
from app.models.document import DocumentRelation
from app.models.issue import Issue
from app.models.ledger import (Conflict, ConflictEvent, Decision, IdentityBinding, LedgerStream, RecordEvent,
                               TicketLink)
from app.ledger.writer import ledger_writer

IMMUTABLE_ID_KINDS = {"insight", "jira", "glpi"}
INACTIVE = ("Merged", "Retired")
CANDIDATE = "identity_candidate"


# A MAC identifies hardware: the network interface it is burned into (an Equipment Port, or an IT box's own
# primary interface). A registration that names it (an Address Record, a DHCP lease) points at that hardware
# and is not a second holder of it, so two such records are not duplicates.
MAC_NAMES_HARDWARE_NOT = {"Address Record"}


def strong_identifiers(attributes: dict, type_name: Optional[str] = None) -> list[tuple[str, str]]:
    """(name, normalized value) of a record's strong identifiers (§10)."""
    a = attributes or {}
    out = []
    # A serial is unique only per manufacturer; without one it is not strong.
    if a.get("serial") and a.get("manufacturer"):
        out.append(("serial", f"{str(a.get('manufacturer') or '').strip().lower()}|{str(a['serial']).strip()}"))
    if a.get("inventory_number"):
        out.append(("inventory_number", str(a["inventory_number"]).strip()))
    if a.get("mac") and type_name not in MAC_NAMES_HARDWARE_NOT:
        out.append(("mac", str(a["mac"]).strip().lower().replace("-", ":")))
    return out


def _holders(db: Session, name: str, value: str, exclude: Optional[str] = None) -> list[Asset]:
    col = Asset.attributes
    if name == "serial":
        manufacturer, serial = value.split("|", 1)
        q = select(Asset).where(col["serial"].astext == serial)
        rows = [a for a in db.scalars(q)
                if str((a.attributes or {}).get("manufacturer") or "").strip().lower() == manufacturer]
    else:
        rows = list(db.scalars(select(Asset).where(col[name].astext.isnot(None))))
        rows = [a for a in rows if dict(strong_identifiers(a.attributes, a.type)).get(name) == value]
    return [a for a in rows if a.uid != exclude and a.record_status not in INACTIVE]


# --------------------------------------------------------------------------- re-keying (A34)

def maybe_rekey(db: Session, stream: LedgerStream, uid: str, exists_value, cause: str) -> None:
    """The source re-keyed an object it identifies immutably: follow it, and
    keep the old key as an alias so every old reference still resolves."""
    if stream.kind not in IMMUTABLE_ID_KINDS or not isinstance(exists_value, dict):
        return
    new_key = exists_value.get("key")
    record = db.get(Asset, uid)
    if record is None or not new_key or record.key == new_key:
        return
    clash = db.scalar(select(Asset).where(Asset.key == new_key, Asset.uid != uid).limit(1))
    if clash is not None:
        raise LedgerError(f"the source re-keyed {record.key} to {new_key}, which {clash.uid} already holds")
    add_label(db, uid, "former_key", record.key, stream.kind)
    db.add(RecordEvent(uid=uid, kind="rekeyed", before={"key": record.key}, after={"key": new_key}, cause=cause,
                       at=now()))
    record.key = new_key
    db.flush()


def add_label(db: Session, uid: str, label_type: str, value: str, namespace: str) -> Optional[str]:
    """Add an alias label unless it exists; returns the new label's uid."""
    exists = db.scalar(select(AssetLabel).where(AssetLabel.asset_uid == uid, AssetLabel.type == label_type,
                                                AssetLabel.value == value).limit(1))
    if exists is not None:
        return None
    label_uid = str(uuid.uuid4())
    db.add(AssetLabel(uid=label_uid, asset_uid=uid, type=label_type, value=value, namespace=namespace,
                      issuer="ledger", verified=True, created_at=now(), updated_at=now()))
    return label_uid


# --------------------------------------------------------------------------- candidates (A35)

def _pair_id(pair: tuple, identifier: tuple) -> str:
    return hashlib.sha256(canonical([CANDIDATE, sorted(pair), list(identifier)]).encode()).hexdigest()[:24]


def _dismissed(db: Session, workspace_ids: Iterable[str]) -> set[frozenset]:
    out = set()
    for d in db.scalars(select(Decision).where(Decision.kind.in_(("reject_candidate", "confirm_new")),
                                               Decision.workspace_id.in_(list(workspace_ids)))):
        out.add(frozenset((d.target or {}).get("records") or []))
    return out


def detect_candidates(db: Session, uids: Iterable[str], cause: str) -> None:
    """Open (or close) identity candidates for these records. Never merges."""
    uids = [u for u in set(uids) if u]
    for uid in uids:
        record = db.get(Asset, uid)
        if record is None:
            continue
        wanted: dict[str, tuple] = {}
        if record.record_status not in INACTIVE:
            for ident in strong_identifiers(record.attributes, record.type):
                for other in _holders(db, *ident, exclude=uid):
                    pair = tuple(sorted((uid, other.uid)))
                    if frozenset(pair) in _dismissed(db, {record.workspace_id, other.workspace_id}):
                        continue
                    wanted[_pair_id(pair, ident)] = (pair, ident)
        existing = {c.conflict_id: c for c in db.scalars(select(Conflict).where(
            Conflict.conflict_type == CANDIDATE, Conflict.detail["records"].contains([uid])))}
        for cid, (pair, (name, value)) in wanted.items():
            if cid in existing or db.get(Conflict, cid) is not None:
                continue
            owner = db.get(Asset, pair[0])
            detail = {"records": list(pair), "identifier": name, "value": value.split("|")[-1],
                      "score": 0.9 if name != "mac" else 0.95,
                      "evidence": f"both records hold {name} {value.split('|')[-1]}"}
            ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type=CANDIDATE, subject_uid=owner.uid,
                               predicate=f"attr:{name}", detail=detail, cause=cause, at=now())
            db.add(ev)
            db.flush()
            db.add(Conflict(conflict_id=cid, conflict_type=CANDIDATE, severity="non-blocking",
                            workspace_id=owner.workspace_id, subject_uid=owner.uid, predicate=f"attr:{name}",
                            detail=detail, opened_seq=ev.seq))
            db.flush()
        for cid, row in existing.items():
            if cid not in wanted:
                others = [u for u in row.detail["records"] if u != uid]
                still = others and all((db.get(Asset, u) is not None
                                        and db.get(Asset, u).record_status not in INACTIVE) for u in others) \
                    and record.record_status not in INACTIVE \
                    and frozenset(row.detail["records"]) not in _dismissed(db, {record.workspace_id}) \
                    and any(i[0] == row.detail["identifier"] for i in strong_identifiers(record.attributes, record.type))
                if not still:
                    db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type=CANDIDATE,
                                         subject_uid=row.subject_uid, detail=row.detail, cause=cause, at=now()))
                    db.delete(row)
    db.flush()


def dismiss_candidate(db: Session, workspace_id: str, actor: str, records: list[str], kind: str,
                      reason: Optional[str] = None) -> Decision:
    """`reject_candidate` (not the same thing) or `confirm_new` (both are real)."""
    if kind not in ("reject_candidate", "confirm_new") or len(set(records)) != 2:
        raise LedgerError("name the two records of the candidate")
    d = engine._record_decision(db, kind, actor, workspace_id, target={"records": sorted(records)}, reason=reason)
    detect_candidates(db, records, f"decision:{d.decision_id}")
    return d


MOVABLE = ((Issue, "asset_uid", "uid"), (AssetTicket, "asset_uid", "uid"), (AssetLabel, "asset_uid", "uid"),
           (AssetComment, "asset_uid", "uid"), (Attachment, "asset_uid", "uid"))
OVERLAP = "merge_installation_overlap"


@ledger_writer
def merge(db: Session, workspace_id: str, actor: str, survivor_uid: str, loser_uid: str,
          reason: Optional[str] = None) -> Decision:
    """A steward's merge (§10): the survivor keeps its uid; everything that
    pointed at the loser points at the survivor; the loser's source refs are
    rebound, so its claims now compete on the survivor under the policy; the
    loser stays as a `Merged` tombstone. What moved is kept on the decision,
    so `unmerge` can put it back."""
    survivor, loser = db.get(Asset, survivor_uid), db.get(Asset, loser_uid)
    if survivor is None or loser is None or survivor_uid == loser_uid:
        raise LedgerError("name two different records")
    if workspace_id not in (survivor.workspace_id, loser.workspace_id):
        raise LedgerError("a merge is decided in the workspace of one of its records")
    if loser.record_status == "Merged" or survivor.record_status == "Merged":
        raise LedgerError("a merged record cannot be merged again")
    moved: dict = {"relations_from": [], "relations_to": [], "document_relations": [], "bindings": [],
                   "labels_added": [], "loser_status": loser.record_status}
    decision = engine._record_decision(db, "merge", actor, workspace_id, subject_uid=survivor_uid,
                                       target={"survivor": survivor_uid, "loser": loser_uid}, reason=reason)
    cause = f"merge:{decision.decision_id}"
    # Derived and ledger edges are recomputed; asserted ones move.
    db.execute(delete(Relation).where(Relation.from_asset_uid == loser_uid, Relation.derivation.isnot(None)))
    db.execute(delete(Relation).where(Relation.to_asset_uid == loser_uid, Relation.derivation == "derived"))
    for r in db.scalars(select(Relation).where(or_(Relation.from_asset_uid == loser_uid,
                                                   Relation.to_asset_uid == loser_uid))):
        if r.from_asset_uid == loser_uid:
            r.from_asset_uid = survivor_uid
            moved["relations_from"].append(r.id)
        if r.to_asset_uid == loser_uid:
            r.to_asset_uid = survivor_uid
            moved["relations_to"].append(r.id)
    for model, col, pk in MOVABLE:
        ids = []
        for row in db.scalars(select(model).where(getattr(model, col) == loser_uid)):
            setattr(row, col, survivor_uid)
            ids.append(getattr(row, pk))
        moved[model.__tablename__] = ids
    for rel in db.scalars(select(DocumentRelation).where(DocumentRelation.to_type == "asset",
                                                         DocumentRelation.to_uid == loser_uid)):
        rel.to_uid = survivor_uid
        moved["document_relations"].append(rel.id)
    db.execute(delete(TicketLink).where(TicketLink.asset_uid == loser_uid))
    for b in list(db.scalars(select(IdentityBinding).where(IdentityBinding.uid == loser_uid))):
        if not b.source_ref.startswith("uid:"):
            engine.bind(db, b.source_ref, survivor_uid, f"rebound: {cause}")
            moved["bindings"].append(b.source_ref)
    for label_type, value in (("former_key", loser.key), ("former_uid", loser.uid)):
        uid = add_label(db, survivor_uid, label_type, value, "merge")
        if uid:
            moved["labels_added"].append(uid)
    # The pre-image `unmerge` needs, as an audit event of its own.
    db.add(RecordEvent(uid=loser_uid, kind="merge_moved", after=moved, cause=cause, at=now()))
    db.add(RecordEvent(uid=loser_uid, kind="status", before=loser.record_status, after="Merged", cause=cause,
                       at=now()))
    loser.record_status, loser.merged_into_uid = "Merged", survivor_uid
    db.flush()
    engine.project_subject(db, survivor_uid, cause)
    try:
        engine.validate_installations(db, [survivor_uid], strict=True)
    except InvariantError as exc:
        # Both units were installed somewhere at overlapping times: the merge
        # stands, and the overlap is a blocking item for review (§10).
        _open(db, OVERLAP, survivor, "blocking", {"merge": decision.decision_id, "error": str(exc)}, cause)
    detect_candidates(db, [survivor_uid, loser_uid], cause)
    engine.derive_all(db, {survivor.workspace_id, loser.workspace_id})
    _rederive_tickets(db, [survivor_uid, loser_uid])
    return decision


@ledger_writer
def unmerge(db: Session, workspace_id: str, actor: str, merge_decision_id: str,
            reason: Optional[str] = None) -> Decision:
    """Reverse a merge from what it recorded: every row it moved goes back to
    the loser (unless it has moved on since), the source refs are rebound,
    the labels it added are removed, and the loser is restored."""
    m = db.scalar(select(Decision).where(Decision.decision_id == merge_decision_id, Decision.kind == "merge"))
    if m is None or m.workspace_id != workspace_id:
        raise LedgerError("no such merge in this workspace")
    if db.scalar(select(Decision).where(Decision.kind == "unmerge",
                                        Decision.target["merge"].astext == merge_decision_id).limit(1)):
        raise LedgerError("this merge has already been undone")
    survivor_uid, loser_uid = m.target["survivor"], m.target["loser"]
    pre = db.scalar(select(RecordEvent).where(RecordEvent.uid == loser_uid, RecordEvent.kind == "merge_moved",
                                              RecordEvent.cause == f"merge:{merge_decision_id}"))
    moved = (pre.after if pre else None) or {}
    loser = db.get(Asset, loser_uid)
    if loser is None or loser.merged_into_uid != survivor_uid:
        raise LedgerError("the merged record is no longer a tombstone of this merge")
    decision = engine._record_decision(db, "unmerge", actor, workspace_id, subject_uid=loser_uid,
                                       target={"merge": merge_decision_id, "survivor": survivor_uid,
                                               "loser": loser_uid}, supersedes=[merge_decision_id], reason=reason)
    cause = f"unmerge:{decision.decision_id}"
    for rid in moved.get("relations_from", []):
        r = db.get(Relation, rid)
        if r is not None and r.from_asset_uid == survivor_uid:
            r.from_asset_uid = loser_uid
    for rid in moved.get("relations_to", []):
        r = db.get(Relation, rid)
        if r is not None and r.to_asset_uid == survivor_uid:
            r.to_asset_uid = loser_uid
    for model, col, _pk in MOVABLE:
        for pk in moved.get(model.__tablename__, []):
            row = db.get(model, pk)
            if row is not None and getattr(row, col) == survivor_uid:
                setattr(row, col, loser_uid)
    for rid in moved.get("document_relations", []):
        rel = db.get(DocumentRelation, rid)
        if rel is not None and rel.to_uid == survivor_uid:
            rel.to_uid = loser_uid
    for ref in moved.get("bindings", []):
        if engine.resolve_ref(db, ref) == survivor_uid:
            engine.bind(db, ref, loser_uid, f"rebound: {cause}")
    for label_uid in moved.get("labels_added", []):
        label = db.get(AssetLabel, label_uid)
        if label is not None:
            db.delete(label)
    before = loser.record_status
    loser.record_status, loser.merged_into_uid = moved.get("loser_status") or "Active", None
    db.add(RecordEvent(uid=loser_uid, kind="status", before=before, after=loser.record_status, cause=cause,
                       at=now()))
    for c in db.scalars(select(Conflict).where(Conflict.conflict_type == OVERLAP,
                                               Conflict.subject_uid == survivor_uid)):
        if (c.detail or {}).get("merge") == merge_decision_id:
            _close(db, c, cause)
    db.flush()
    for uid in (survivor_uid, loser_uid):
        engine.project_subject(db, uid, cause)
    detect_candidates(db, [survivor_uid, loser_uid], cause)
    survivor = db.get(Asset, survivor_uid)
    engine.derive_all(db, {survivor.workspace_id, loser.workspace_id})
    _rederive_tickets(db, [survivor_uid, loser_uid])
    return decision


def clear_merge_overlaps(db: Session, uids: Iterable[str], cause: str) -> None:
    """A batch that passed validation has resolved any overlap left by a merge
    of these units (called after validate_installations succeeds)."""
    units = set()
    for uid in uids:
        rec = db.get(Asset, uid)
        if rec is None:
            continue
        if rec.type == engine.INSTALLATION:
            v = engine.installation_view(db, rec)
            units |= {v["asset_uid"], v["position_uid"]}
        units.add(uid)
    for c in db.scalars(select(Conflict).where(Conflict.conflict_type == OVERLAP,
                                               Conflict.subject_uid.in_([u for u in units if u]))):
        _close(db, c, cause)


def _open(db: Session, ctype: str, record: Asset, severity: str, detail: dict, cause: str) -> None:
    cid = hashlib.sha256(canonical([ctype, record.uid, detail.get("merge")]).encode()).hexdigest()[:24]
    if db.get(Conflict, cid) is not None:
        return
    ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type=ctype, subject_uid=record.uid, detail=detail,
                       cause=cause, at=now())
    db.add(ev)
    db.flush()
    db.add(Conflict(conflict_id=cid, conflict_type=ctype, severity=severity, workspace_id=record.workspace_id,
                    subject_uid=record.uid, detail=detail, opened_seq=ev.seq))
    db.flush()


def _close(db: Session, c: Conflict, cause: str) -> None:
    db.add(ConflictEvent(conflict_id=c.conflict_id, kind="resolved", conflict_type=c.conflict_type,
                         subject_uid=c.subject_uid, detail=c.detail, cause=cause, at=now()))
    db.delete(c)


def _rederive_tickets(db: Session, uids: list[str]) -> None:
    from app.ledger.tickets import derive_ticket_links
    derive_ticket_links(db, ticket_uids=[i.uid for i in db.scalars(select(Issue).where(Issue.asset_uid.in_(uids)))])


# --------------------------------------------------------------------------- creation (I-ID-1)

def assert_unique_at_creation(db: Session, workspace_id: str, attributes: dict, exclude: Optional[str] = None,
                              type_name: Optional[str] = None) -> None:
    """After cutover, a new record may not take a strong identifier an active
    record holds. The error names the existing record."""
    from app.ledger.cutover import authoritative
    if not authoritative(db, workspace_id, "objects"):
        return
    for name, value in strong_identifiers(attributes, type_name):
        holders = _holders(db, name, value, exclude=exclude)
        if holders:
            h = holders[0]
            raise DuplicateIdentifier(name, value.split("|")[-1], h)


class DuplicateIdentifier(InvariantError):
    def __init__(self, name: str, value: str, existing: Asset):
        super().__init__("I-ID-1", f"{name} {value} is already held by {existing.key} ({existing.name})")
        self.existing = {"uid": existing.uid, "key": existing.key, "name": existing.name,
                         "workspace_id": existing.workspace_id, "path": f"/assets/{existing.uid}"}
