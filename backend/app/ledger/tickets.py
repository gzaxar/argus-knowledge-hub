"""Ticket attribution (asset-model-revision §8.6).

A ticket has exactly one **subject**: the record it is about (`Issue.asset_uid`).
What else it touches is derived, never typed in:

* `involved_equipment` — for a subject position (or a Control Device, through
  the positions it acts on), the units whose Confirmed Installation there
  overlaps the incident time. One unit that definitely covers the whole
  incident is `definite`; otherwise every overlapping unit is `possible`.
* `involved_position` — for a subject unit, where it was installed.
* `migration-split` — a legacy ticket nothing covers is linked, `possible`,
  to the equipment its legacy object became (§12.4). Never counted.

Counting (I-TKT-2) is over distinct tickets, from subject links and definite
derived links only; a group is never the sum of its members.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ledger import engine, temporal
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.issue import Issue
from app.models.ledger import MigrationMap, TicketLink
from app.services.visibility import can_see, restriction_clause

LEGACY_WINDOW = timedelta(days=7)
DERIVATION = "attribution/1"


def ticket_key(issue: Issue) -> str:
    return (issue.attributes or {}).get("argus_source_key") or issue.uid


def _instant(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return temporal.parse_instant(value)
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None


def _endpoint(value, role: str) -> Optional[temporal.Bounds]:
    if not value:
        return None
    if isinstance(value, dict):
        return temporal.bounds(value, role)
    t = _instant(value)
    return temporal.Bounds(t, t) if t else None


def incident_range(issue: Issue) -> tuple[datetime, datetime, str]:
    """(earliest, latest, source) of the time the ticket is about (§8.6)."""
    a = issue.attributes or {}
    start = _endpoint(a.get("occurred_from"), "from")
    if start is not None and start.placed:
        end = _endpoint(a.get("occurred_until"), "until")
        latest = end.latest if end is not None and end.latest != temporal.POS_INF else start.latest
        return start.earliest, latest, "occurrence"
    if a.get("argus_source"):
        created = _instant(a.get("argus_source_created")) or issue.created_at
        return created - LEGACY_WINDOW, created, "legacy_created_fallback"
    reported = _instant(a.get("reported_at")) or issue.created_at
    return reported, reported, "reported_at"


def _classify(views: list[dict], earliest: datetime, latest: datetime, key: str) -> list[tuple[str, str]]:
    """[(uid, certainty)] of the units (or positions) involved."""
    covering, overlapping = [], []
    for v in views:
        iv = v["interval"]
        if not iv.placed:
            continue
        if iv.start.latest <= earliest and latest < iv.end.earliest:
            covering.append(v[key])
        if iv.start.earliest <= latest and earliest < iv.end.latest:
            overlapping.append(v[key])
    if len(set(covering)) == 1:
        return [(covering[0], "definite")]
    return [(uid, "possible") for uid in sorted(set(overlapping))]


def _positions_of(db: Session, subject: Asset) -> list[str]:
    if subject.type in engine.INSTALLABLE:
        return [subject.uid]
    if subject.type == "Control Device":
        return list(db.scalars(select(Relation.to_asset_uid).where(
            Relation.from_asset_uid == subject.uid, Relation.relation_type == "acts on",
            Relation.derivation == "ledger")))
    return []


def derive_for_ticket(db: Session, issue: Issue) -> list[TicketLink]:
    db.execute(delete(TicketLink).where(TicketLink.ticket_uid == issue.uid))
    links, source = plan_links(db, issue)
    attrs = dict(issue.attributes or {})
    if source == "legacy_created_fallback":
        if attrs.get("occurrence_source") != source:
            attrs["occurrence_source"] = source
            issue.attributes = attrs
    elif attrs.pop("occurrence_source", None) is not None:
        issue.attributes = attrs
    db.add_all(links)
    db.flush()
    return links


def plan_links(db: Session, issue: Issue) -> tuple[list[TicketLink], str]:
    """The links a ticket should have, and where its incident range came from — read only: nothing is added to
    the session or changed, so the invariant report (I-TKT-3) can compare them inside the export's read-only
    snapshot."""
    subject = db.get(Asset, issue.asset_uid) if issue.asset_uid else None
    links: list[TicketLink] = []

    def add(uid: str, role: str, certainty: str, origin: str, detail: Optional[dict] = None):
        links.append(TicketLink(workspace_id=issue.workspace_id, ticket_uid=issue.uid, asset_uid=uid, role=role,
                                certainty=certainty, origin=origin,
                                derivation=DERIVATION if origin != "ticket" else None, detail=detail))

    if subject is not None:
        add(subject.uid, "subject", "definite", "ticket")
    for uid in db.scalars(select(AssetTicket.asset_uid).where(AssetTicket.ticket_key == ticket_key(issue))):
        if subject is None or uid != subject.uid:
            add(uid, "related", "definite", "ticket")
    earliest, latest, source = incident_range(issue)
    detail = {"incident": [earliest.isoformat(), latest.isoformat()], "source": source}
    if subject is not None:
        positions = _positions_of(db, subject)
        involved = []
        for p in positions:
            involved += _classify(engine.installations(db, position_uid=p, status="Confirmed"),
                                  earliest, latest, "asset_uid")
        # A unit that is definitely involved through one position and possibly
        # through another is reported once, with its strongest certainty.
        best: dict[str, str] = {}
        for uid, c in involved:
            best[uid] = "definite" if "definite" in (c, best.get(uid)) else "possible"
        for uid, c in sorted(best.items()):
            add(uid, "involved_equipment", c, "derived", detail)
        if not best and positions and source == "legacy_created_fallback":
            for p in positions:
                # A rolled-back migration leaves its map rows; their records are retired.
                for m in db.scalars(select(MigrationMap).join(Asset, Asset.uid == MigrationMap.new_uid).where(
                        MigrationMap.legacy_uid == p, MigrationMap.role == "equipment",
                        Asset.record_status != "Retired")):
                    add(m.new_uid, "involved_equipment", "possible", "migration-split", detail)
        if not positions and db.scalar(select(func.count()).select_from(Relation).where(
                Relation.relation_type == "installation of", Relation.to_asset_uid == subject.uid)):
            for uid, c in _classify(engine.installations(db, asset_uid=subject.uid, status="Confirmed"),
                                    earliest, latest, "position_uid"):
                if uid:
                    add(uid, "involved_position", c, "derived", detail)
    return links, source


def derive_ticket_links(db: Session, *, workspace_ids: Optional[Iterable[str]] = None,
                        ticket_uids: Optional[Iterable[str]] = None) -> dict:
    """Recompute the links of the tickets whose subject lives in these
    workspaces, or is a unit installed in them (I-TKT-3)."""
    q = select(Issue).where(Issue.deleted_at.is_(None), Issue.asset_uid.isnot(None))
    if ticket_uids is not None:
        q = q.where(Issue.uid.in_(list(ticket_uids)))
    elif workspace_ids is not None:
        ids = list(workspace_ids)
        # Only a ticket on a position, a control device or an installed unit
        # has links the ledger can move; the others keep the subject and
        # related links written with the ticket, unless it has none yet.
        records = select(Asset.uid).where(Asset.workspace_id.in_(ids),
                                          Asset.type.in_([*engine.INSTALLABLE, "Control Device"]))
        units = select(Relation.to_asset_uid).where(Relation.relation_type == "installation of",
                                                   Relation.workspace_id.in_(ids))
        linked = select(TicketLink.ticket_uid).where(TicketLink.workspace_id.in_(ids))
        unlinked = select(Issue.uid).where(Issue.workspace_id.in_(ids), Issue.uid.not_in(linked))
        q = q.where(Issue.asset_uid.in_(records) | Issue.asset_uid.in_(units) | Issue.uid.in_(unlinked))
    n = 0
    for issue in db.scalars(q):
        derive_for_ticket(db, issue)
        n += 1
    return {"tickets_attributed": n}


def _visible_tickets():
    return TicketLink.ticket_uid.in_(select(Issue.uid).where(restriction_clause(Issue)))


def _counted():
    """I-TKT-2: subject links and definite derived links; never related,
    possible or migration-split links. Restricted tickets the viewer may not
    see are not counted either (I-ACL-1)."""
    return _visible_tickets() & (TicketLink.role == "subject") | _visible_tickets() & (
        TicketLink.role.in_(("involved_equipment", "involved_position"))
        & (TicketLink.certainty == "definite") & (TicketLink.origin == "derived"))


def record_counts(db: Session, uid: str) -> dict:
    subject = db.scalar(select(func.count(func.distinct(TicketLink.ticket_uid))).where(
        TicketLink.asset_uid == uid, TicketLink.role == "subject", _visible_tickets()))
    involved = db.scalar(select(func.count(func.distinct(TicketLink.ticket_uid))).where(
        TicketLink.asset_uid == uid, TicketLink.role.in_(("involved_equipment", "involved_position")),
        _visible_tickets(),
        TicketLink.certainty == "definite", TicketLink.origin == "derived"))
    return {"subject": subject or 0, "involved": involved or 0}


def group_count(db: Session, uids: Iterable[str]) -> int:
    """Distinct tickets over a group's members — never a sum (§8.6)."""
    return db.scalar(select(func.count(func.distinct(TicketLink.ticket_uid))).where(
        TicketLink.asset_uid.in_(list(uids)), _counted())) or 0


def links_of_ticket(db: Session, ticket_uid: str) -> list[dict]:
    out = []
    for link in db.scalars(select(TicketLink).where(TicketLink.ticket_uid == ticket_uid).order_by(TicketLink.id)):
        a = db.get(Asset, link.asset_uid)
        if a is not None and not can_see(a):
            continue
        out.append({"asset_uid": link.asset_uid, "name": a.name if a else None, "key": a.key if a else None,
                    "type": a.type if a else None, "role": link.role, "certainty": link.certainty,
                    "origin": link.origin, "detail": link.detail})
    return out


def tickets_involving(db: Session, asset_uid: str) -> list[dict]:
    out = []
    for link in db.scalars(select(TicketLink).where(TicketLink.asset_uid == asset_uid,
                                                    TicketLink.role != "subject")):
        issue = db.get(Issue, link.ticket_uid)
        if issue is None or not can_see(issue):
            continue
        out.append({"ticket_uid": issue.uid, "key": ticket_key(issue), "title": issue.title, "state": issue.state,
                    "role": link.role, "certainty": link.certainty, "origin": link.origin})
    return out


# --------------------------------------------------------------------------- I-TKT-4

INCIDENT_TYPES = {"operational incident", "operational-incident"}


class OccurrenceRequired(ValueError):
    code = "I-TKT-4"


def is_incident_type(db: Session, schema_uid: Optional[str]) -> bool:
    from app.models.schema import Schema
    schema = db.get(Schema, schema_uid) if schema_uid else None
    return schema is not None and schema.name.strip().lower() in INCIDENT_TYPES


def validate_occurrence(db: Session, schema_uid: Optional[str], attributes: dict) -> None:
    """An operational incident created in ARGUS says when it happened, with
    the precision known (I-TKT-4). Only a ticket migrated from Jira may lack
    it; it then gets the creation-date fallback."""
    attributes = attributes or {}
    if not is_incident_type(db, schema_uid) or attributes.get("argus_source") == "jira":
        return
    value = attributes.get("occurred_from")
    if not value:
        raise OccurrenceRequired("an operational incident needs occurred_from: when it happened, "
                                 "with the precision known (a day, a month)")
    try:
        start = _endpoint(value, "from")
    except (temporal.TemporalError, KeyError, ValueError) as exc:
        raise OccurrenceRequired(f"occurred_from is not a valid time: {exc}")
    if start is None or not start.placed:
        raise OccurrenceRequired("occurred_from must name a time")
