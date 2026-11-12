"""The unified knowledge layer: one object's whole context in one call.

An asset, the tickets raised about it and the documents that explain it live in
three tables with three kinds of link between them (the ticket's subject and
`asset_tickets`, `document_relations` to an asset, to its type or to its product
model). Every screen that wants "everything about this pump" used to stitch
them together in the browser, from lists of the whole workspace. This module
does it once, on the server, respecting each section's read permission.

Nothing here writes. Every function takes the workspace the caller acts in and
an `Access` saying which sections the caller may read; a section the caller may
not read comes back empty and flagged, never partially.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import and_, func, or_, select, String, cast
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.issue import Issue
from app.models.schema import Schema
from app.services.visibility import (asset_visible_in, can_see, live_assets_clause, redacted_attributes,
                                     restricted_class, visible_assets_clause, visible_issues_clause)

CLOSED_STATES = frozenset({"closed", "done", "resolved", "cancelled", "canceled", "rejected"})


@dataclass(frozen=True)
class Access:
    assets: bool
    tickets: bool
    documents: bool


def is_open(issue: Issue) -> bool:
    return issue.closed_at is None and (issue.state or "").lower() not in CLOSED_STATES


def readable_documents_clause(workspace_id: str):
    """The same rule as the document list: this workspace's own documents, and
    other workspaces' global ones unless they are confidential."""
    return or_(
        Document.workspace_id == workspace_id,
        and_(Document.is_global.is_(True), Document.confidentiality != "riservato"),
    )


# --------------------------------------------------------------------- summaries

def asset_summary(a: Asset) -> dict:
    return {
        "uid": a.uid, "key": a.key, "name": a.name, "type": a.type,
        "schema_uid": a.schema_uid, "workspace_id": a.workspace_id,
        "lifecycle": (a.attributes or {}).get("argus_lifecycle"),
        "system": (a.attributes or {}).get("argus_system"),
        "updated_at": a.updated_at,
    }


def ticket_summary(i: Issue) -> dict:
    return {
        "uid": i.uid, "title": i.title, "state": i.state, "priority": i.priority,
        "assignee": i.assignee, "asset_uid": i.asset_uid, "open": is_open(i), "key": i.key,
        "source_key": (i.attributes or {}).get("argus_source_key"),
        "created_at": i.created_at, "updated_at": i.updated_at, "due_date": i.due_date,
    }


def document_summary(db: Session, d: Document, via: Optional[str] = None,
                     via_label: Optional[str] = None) -> dict:
    current = db.get(DocumentRevision, d.current_revision_uid) if d.current_revision_uid else None
    return {
        "uid": d.uid, "code": d.code, "title": d.title, "authority_level": d.authority_level,
        "workspace_id": d.workspace_id, "is_global": d.is_global,
        "state": current.state if current else None,
        "next_review_due": current.next_review_due if current else None,
        "review_overdue": bool(current and current.next_review_due
                               and current.next_review_due < date.today()),
        "updated_at": d.updated_at, "via": via, "via_label": via_label,
    }


# --------------------------------------------------------------------- building blocks

def schema_lineage(db: Session, schema_uid: Optional[str]) -> list[Schema]:
    """The type and its ancestors, nearest first. A procedure written for
    "Vacuum Pump" applies to every ion pump."""
    out: list[Schema] = []
    seen: set[str] = set()
    uid = schema_uid
    while uid and uid not in seen:
        seen.add(uid)
        schema = db.get(Schema, uid)
        if schema is None:
            break
        out.append(schema)
        uid = schema.parent_schema_uid
    return out


def tickets_for_assets(db: Session, workspace_id: str, asset_uids: Iterable[str]) -> list[Issue]:
    """Native tickets about these assets: those whose subject they are, and
    those linked to them through `asset_tickets` (keyed by the ticket's uid or,
    for imported ones, its source key)."""
    uids = list(set(asset_uids))
    if not uids:
        return []
    found: dict[str, Issue] = {}
    for issue in db.scalars(select(Issue).where(
            Issue.workspace_id == workspace_id, Issue.asset_uid.in_(uids),
            Issue.deleted_at.is_(None), visible_issues_clause())):
        found[issue.uid] = issue
    keys = {t.ticket_key for t in db.scalars(select(AssetTicket).where(AssetTicket.asset_uid.in_(uids)))}
    keys -= set(found)
    if keys:
        source_key = Issue.attributes["argus_source_key"].astext
        for issue in db.scalars(select(Issue).where(
                Issue.workspace_id == workspace_id, Issue.deleted_at.is_(None), visible_issues_clause(),
                or_(Issue.uid.in_(keys), source_key.in_(keys)))):
            found[issue.uid] = issue
    return sorted(found.values(), key=lambda i: (not is_open(i), -(i.updated_at.timestamp() if i.updated_at else 0)))


def external_tickets_for_asset(db: Session, workspace_id: str, asset: Asset, native: list[Issue]) -> list[dict]:
    """Tickets recorded on the asset that have no native ticket here: the
    Jira archive's, until those projects are migrated."""
    native_keys = {i.uid for i in native} | {
        (i.attributes or {}).get("argus_source_key") for i in native}
    out = []
    for t in db.scalars(select(AssetTicket).where(AssetTicket.asset_uid == asset.uid)):
        if t.ticket_key in native_keys:
            continue
        out.append({"key": t.ticket_key, "summary": t.summary, "status": t.status,
                    "type": t.type, "url": t.backend_url, "updated": t.updated})
    return out


def documents_for_asset(db: Session, workspace_id: str, asset: Asset) -> list[dict]:
    """The knowledge that applies to this asset, and why:

    * `asset`   — written about this very object;
    * `type`    — about its type or an ancestor type;
    * `product` — about the product model it is an instance of;
    * `service` — documents naming it as their responsible service.
    """
    lineage = schema_lineage(db, asset.schema_uid)
    type_names = {s.uid: s.name for s in lineage}
    product_uid = (asset.attributes or {}).get("product_model")
    targets = [and_(DocumentRelation.to_type == "asset", DocumentRelation.to_uid == asset.uid)]
    if type_names:
        targets.append(and_(DocumentRelation.to_type == "schema",
                            DocumentRelation.to_uid.in_(list(type_names))))
    if isinstance(product_uid, str) and product_uid:
        targets.append(and_(DocumentRelation.to_type == "asset", DocumentRelation.to_uid == product_uid))

    rows = db.execute(
        select(DocumentRelation, Document)
        .join(Document, Document.uid == DocumentRelation.from_document_uid)
        .where(or_(*targets), readable_documents_clause(workspace_id))
    ).all()
    product = db.get(Asset, product_uid) if isinstance(product_uid, str) and product_uid else None
    if product is not None and not can_see(product):
        product = None
    rank = {"asset": 0, "product": 1, "type": 2, "service": 3}
    best: dict[str, dict] = {}
    for rel, doc in rows:
        if rel.to_type == "schema":
            via, label = "type", type_names.get(rel.to_uid)
        elif rel.to_uid == asset.uid:
            via, label = "asset", rel.relation_type
        else:
            via, label = "product", product.name if product else None
        current = best.get(doc.uid)
        if current is None or rank[via] < rank[current["via"]]:
            best[doc.uid] = document_summary(db, doc, via, label)
    for doc in db.scalars(select(Document).where(
            Document.responsible_service_asset_uid == asset.uid,
            readable_documents_clause(workspace_id))):
        best.setdefault(doc.uid, document_summary(db, doc, "service", None))
    return sorted(best.values(), key=lambda d: (rank[d["via"]], d["code"] or ""))


def neighbours(db: Session, workspace_id: str, asset: Asset, limit: int = 60) -> dict:
    out_rows = db.execute(
        select(Relation, Asset).join(Asset, Asset.uid == Relation.to_asset_uid)
        .where(Relation.from_asset_uid == asset.uid, visible_assets_clause(workspace_id))
    ).all()
    in_rows = db.execute(
        select(Relation, Asset).join(Asset, Asset.uid == Relation.from_asset_uid)
        .where(Relation.to_asset_uid == asset.uid, visible_assets_clause(workspace_id))
    ).all()
    items = [
        {"relation": r.relation_type, "direction": "out", **asset_summary(a)} for r, a in out_rows
    ] + [
        {"relation": r.relation_type, "direction": "in", **asset_summary(a)} for r, a in in_rows
    ]
    by_relation = Counter(f"{i['direction']}:{i['relation']}" for i in items)
    return {"total": len(items), "by_relation": dict(by_relation), "items": items[:limit]}


# --------------------------------------------------------------------- contexts

def asset_context(db: Session, workspace_id: str, asset: Asset, access: Access) -> dict:
    lineage = schema_lineage(db, asset.schema_uid)
    tickets = tickets_for_assets(db, workspace_id, [asset.uid]) if access.tickets else []
    external = external_tickets_for_asset(db, workspace_id, asset, tickets) if access.tickets else []
    docs = documents_for_asset(db, workspace_id, asset) if access.documents else []
    graph = neighbours(db, workspace_id, asset)
    open_tickets = [t for t in tickets if is_open(t)]
    from app.intake.guide import nature
    from app.ledger.engine import pending_derive
    schema = db.get(Schema, asset.schema_uid) if asset.schema_uid else None
    return {
        "asset": asset_summary(asset),
        # equipment | position | control | other, so a client need not interpret the type tree.
        "nature": nature(db, schema) if schema is not None else "other",
        # Derived edges and counts not yet updated after an edit (I-UX-1).
        "processing": pending_derive(db, asset.workspace_id),
        "restricted": restricted_class(asset),
        "merged": _merge_of(db, asset),
        "type_path": [s.name for s in reversed(lineage)],
        "access": {"tickets": access.tickets, "documents": access.documents},
        "stats": {
            "open_tickets": len(open_tickets),
            "tickets": len(tickets),
            "external_tickets": len(external),
            "documents": len(docs),
            "documents_overdue": sum(1 for d in docs if d["review_overdue"]),
            "relations": graph["total"],
        },
        "tickets": [ticket_summary(t) for t in tickets[:50]],
        "external_tickets": external[:50],
        "documents": docs,
        "relations": graph,
    }


def _merge_of(db: Session, asset: Asset) -> Optional[dict]:
    """For a merge tombstone: its survivor and the merge decision to undo."""
    if asset.record_status != "Merged" or not asset.merged_into_uid:
        return None
    from app.models.ledger import RecordEvent
    ev = db.scalar(select(RecordEvent).where(RecordEvent.uid == asset.uid, RecordEvent.kind == "status",
                                             RecordEvent.cause.like("merge:%")).order_by(RecordEvent.seq.desc()).limit(1))
    survivor = db.get(Asset, asset.merged_into_uid)
    return {"into": asset_summary(survivor) if survivor is not None else None,
            "decision_id": ev.cause.split(":", 1)[1] if ev else None}


def linked_assets_of_ticket(db: Session, workspace_id: str, issue: Issue) -> list[Asset]:
    source_key = (issue.attributes or {}).get("argus_source_key") or issue.uid
    keys = {issue.uid, source_key}
    assets: dict[str, Asset] = {}
    if issue.asset_uid:
        subject = db.get(Asset, issue.asset_uid)
        if subject is not None and asset_visible_in(subject, workspace_id):
            assets[subject.uid] = subject
    for _t, a in db.execute(
            select(AssetTicket, Asset).join(Asset, Asset.uid == AssetTicket.asset_uid)
            .where(AssetTicket.ticket_key.in_(keys), visible_assets_clause(workspace_id))).all():
        assets.setdefault(a.uid, a)
    return list(assets.values())


def ticket_context(db: Session, workspace_id: str, issue: Issue, access: Access) -> dict:
    """What a technician working this ticket needs next to it: the equipment
    it is about, the procedures and manuals for that equipment, and what else
    is currently open on the same equipment."""
    assets = linked_assets_of_ticket(db, workspace_id, issue) if access.assets else []
    linked_doc_uids = {
        r.from_document_uid for r in db.scalars(select(DocumentRelation).where(
            DocumentRelation.to_type == "issue", DocumentRelation.to_uid == issue.uid))
    }
    knowledge: dict[str, dict] = {}
    if access.documents:
        for asset in assets:
            for doc in documents_for_asset(db, workspace_id, asset):
                if doc["uid"] in linked_doc_uids:
                    continue
                entry = knowledge.setdefault(doc["uid"], {**doc, "for_assets": []})
                entry["for_assets"].append({"uid": asset.uid, "name": asset.name})
    concurrent = []
    if access.tickets and assets:
        concurrent = [ticket_summary(t) for t in tickets_for_assets(db, workspace_id, [a.uid for a in assets])
                      if t.uid != issue.uid and is_open(t)][:20]
    return {
        "ticket": ticket_summary(issue),
        "access": {"assets": access.assets, "documents": access.documents},
        "assets": [asset_summary(a) for a in assets],
        "suggested_documents": list(knowledge.values())[:30],
        "concurrent_tickets": concurrent,
    }


def document_context(db: Session, workspace_id: str, doc: Document, access: Access) -> dict:
    """Where a document applies: the assets it covers directly, the types it
    covers (with how many assets of them there are), and what is open on
    those assets right now."""
    direct: list[Asset] = []
    types: list[dict] = []
    for rel in db.scalars(select(DocumentRelation).where(DocumentRelation.from_document_uid == doc.uid)):
        if rel.to_type == "asset":
            a = db.get(Asset, rel.to_uid)
            if a is not None and asset_visible_in(a, workspace_id):
                direct.append(a)
        elif rel.to_type == "schema":
            schema = db.get(Schema, rel.to_uid)
            if schema is None:
                continue
            subtree = _schema_subtree(db, schema.uid)
            count = db.scalar(select(func.count()).select_from(Asset).where(
                Asset.schema_uid.in_(subtree), visible_assets_clause(workspace_id), Asset.deleted_at.is_(None),
                live_assets_clause())) or 0
            types.append({"uid": schema.uid, "name": schema.name, "assets": count})
    if doc.responsible_service_asset_uid:
        a = db.get(Asset, doc.responsible_service_asset_uid)
        if a is not None and asset_visible_in(a, workspace_id) and a not in direct:
            direct.append(a)
    # Instances of a product model the document is about inherit it too.
    instances: list[Asset] = []
    if direct:
        product_uids = [a.uid for a in direct]
        instances = list(db.scalars(select(Asset).where(
            visible_assets_clause(workspace_id),
            Asset.attributes["product_model"].astext.in_(product_uids)).limit(200)))
    covered = {a.uid: a for a in direct + instances}
    open_tickets = []
    if access.tickets and covered:
        open_tickets = [ticket_summary(t) for t in tickets_for_assets(db, workspace_id, covered)
                        if is_open(t)][:30]
    return {
        "document": document_summary(db, doc),
        "access": {"assets": access.assets, "tickets": access.tickets},
        "assets": [asset_summary(a) for a in direct] if access.assets else [],
        "instances": [asset_summary(a) for a in instances[:50]] if access.assets else [],
        "types": types,
        "open_tickets": open_tickets,
    }


def _schema_subtree(db: Session, root_uid: str) -> list[str]:
    out, frontier = [root_uid], [root_uid]
    while frontier:
        children = list(db.scalars(select(Schema.uid).where(Schema.parent_schema_uid.in_(frontier))))
        children = [c for c in children if c not in out]
        out.extend(children)
        frontier = children
    return out


# --------------------------------------------------------------------- search

def _score(q: str, *fields: Optional[str]) -> int:
    ql = q.lower()
    best = 0
    for f in fields:
        if not f:
            continue
        fl = f.lower()
        if fl == ql:
            best = max(best, 100)
        elif fl.startswith(ql):
            best = max(best, 60)
        elif ql in fl:
            best = max(best, 30)
    return best


def unified_search(db: Session, workspace_id: str, access: Access, q: str, limit: int = 8) -> dict:
    """One query across the three sections, ranked within each: exact match,
    then prefix, then substring; attribute values are searched for assets, so
    a serial number or an IP finds its equipment."""
    q = q.strip()
    empty = {"query": q, "assets": [], "tickets": [], "documents": []}
    if len(q) < 2:
        return empty
    like = f"%{q}%"
    fetch = limit * 4
    result = dict(empty)
    if access.assets:
        from app.models.asset_subresources import AssetLabel
        from app.services.identifiers import label_match
        rows = db.scalars(select(Asset).where(
            visible_assets_clause(workspace_id), Asset.deleted_at.is_(None), live_assets_clause(),
            or_(Asset.key.ilike(like), Asset.name.ilike(like), Asset.type.ilike(like),
                label_match(lambda c: c.ilike(like)),
                cast(Asset.attributes, String).ilike(like))).limit(fetch)).all()
        # Its labels: a QR code, a barcode, a former key, an alias.
        labels: dict[str, list[str]] = {}
        for uid, value in db.execute(select(AssetLabel.asset_uid, AssetLabel.value)
                                     .where(AssetLabel.asset_uid.in_([a.uid for a in rows]))):
            labels.setdefault(uid, []).append(value or "")
        # A match only inside a field the viewer may not see is no match (I-ACL-1).
        ql = q.lower()
        rows = [a for a in rows if ql in f"{a.key} {a.name} {a.type}".lower()
                or any(ql in v.lower() for v in labels.get(a.uid, []))
                or ql in json.dumps(redacted_attributes(db, a), default=str).lower()]
        ranked = sorted(rows, key=lambda a: -max(_score(q, a.key, a.name, *labels.get(a.uid, [])),
                                                 10 if q.lower() in (a.type or "").lower() else 1))
        result["assets"] = [asset_summary(a) for a in ranked[:limit]]
    if access.tickets:
        source_key = Issue.attributes["argus_source_key"].astext
        rows = db.scalars(select(Issue).where(
            Issue.workspace_id == workspace_id, Issue.deleted_at.is_(None), visible_issues_clause(),
            or_(Issue.title.ilike(like), Issue.uid.ilike(like), source_key.ilike(like),
                Issue.description.ilike(like))).limit(fetch)).all()
        ranked = sorted(rows, key=lambda i: (-_score(q, i.title, i.uid, (i.attributes or {}).get("argus_source_key")),
                                             not is_open(i)))
        result["tickets"] = [ticket_summary(i) for i in ranked[:limit]]
    if access.documents:
        rows = db.scalars(select(Document).where(
            readable_documents_clause(workspace_id),
            or_(Document.code.ilike(like), Document.title.ilike(like))).limit(fetch)).all()
        ranked = sorted(rows, key=lambda d: -_score(q, d.code, d.title))
        result["documents"] = [document_summary(db, d) for d in ranked[:limit]]
    return result


# --------------------------------------------------------------------- overview

def overview(db: Session, workspace_id: str, access: Access, user_id: Optional[str]) -> dict:
    """The operations cockpit: what needs attention, across the three sections."""
    out: dict = {"access": {"assets": access.assets, "tickets": access.tickets,
                            "documents": access.documents}}
    if access.assets:
        out["assets"] = {
            "own": db.scalar(select(func.count()).select_from(Asset).where(
                Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None), live_assets_clause(),
                visible_assets_clause(workspace_id))) or 0,
            "recent": [asset_summary(a) for a in db.scalars(
                select(Asset).where(Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None),
                                    live_assets_clause(), visible_assets_clause(workspace_id))
                .order_by(Asset.updated_at.desc()).limit(8))],
        }
    if access.tickets:
        issues = list(db.scalars(select(Issue).where(
            Issue.workspace_id == workspace_id, Issue.deleted_at.is_(None), visible_issues_clause())))
        open_issues = [i for i in issues if is_open(i)]
        by_state = Counter((i.state or "new") for i in open_issues)
        by_priority = Counter((i.priority or "none") for i in open_issues)
        mine = [i for i in open_issues if user_id and i.assignee == user_id]
        unassigned = [i for i in open_issues if not i.assignee]
        per_asset = Counter(i.asset_uid for i in open_issues if i.asset_uid)
        hotspots = []
        for asset_uid, count in per_asset.most_common(8):
            asset = db.get(Asset, asset_uid)
            if asset is not None and asset_visible_in(asset, workspace_id):
                hotspots.append({**asset_summary(asset), "open_tickets": count})
        recent = sorted(issues, key=lambda i: i.updated_at or i.created_at, reverse=True)[:8]
        out["tickets"] = {
            "open": len(open_issues), "total": len(issues),
            "by_state": dict(by_state), "by_priority": dict(by_priority),
            "mine": [ticket_summary(i) for i in mine[:10]],
            "unassigned": len(unassigned),
            "without_asset": sum(1 for i in open_issues if not i.asset_uid),
            "hotspots": hotspots,
            "recent": [ticket_summary(i) for i in recent],
        }
    if access.documents:
        docs = list(db.scalars(select(Document).where(Document.workspace_id == workspace_id)))
        in_review, overdue = [], []
        for d in docs:
            summary = document_summary(db, d)
            if summary["state"] == "in_review":
                in_review.append(summary)
            if summary["review_overdue"]:
                overdue.append(summary)
        pending_revisions = db.scalar(select(func.count()).select_from(DocumentRevision).join(
            Document, Document.uid == DocumentRevision.document_uid).where(
            Document.workspace_id == workspace_id, DocumentRevision.state == "in_review")) or 0
        unlinked = 0
        linked = {r for r in db.scalars(select(DocumentRelation.from_document_uid).where(
            DocumentRelation.workspace_id == workspace_id,
            DocumentRelation.to_type.in_(("asset", "schema"))))}
        unlinked = sum(1 for d in docs if d.uid not in linked and not d.responsible_service_asset_uid)
        recent = sorted(docs, key=lambda d: d.updated_at or d.created_at, reverse=True)[:8]
        out["documents"] = {
            "total": len(docs),
            "in_review": pending_revisions,
            "awaiting_review": in_review[:10],
            "review_overdue": overdue[:10],
            "not_linked_to_assets": unlinked,
            "recent": [document_summary(db, d) for d in recent],
        }
    return out
