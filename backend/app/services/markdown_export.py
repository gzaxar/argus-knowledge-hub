"""One document, asset or ticket as a Markdown file.

The same text is the download ("Export ▸ Markdown") and what the web's print
view renders, so a printout, a PDF saved from it and the .md file say the same
thing. It shows what the reader may see and nothing else: restricted fields are
dropped by `redacted_attributes`, neighbours the reader cannot see are left out
(I-ACL-1), and sections the reader may not read (tickets, documents) are omitted.

Links to attachments stay `/v1/attachments/<uid>`: the print view fetches them
with the reader's token, and a client saving the file makes them absolute
against the API it talks to.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.global_value import GlobalValue
from app.models.issue import Issue, IssueComment
from app.models.schema import Schema
from app.models.user import User
from app.services import knowledge_hub as hub
from app.services import workflows
from app.services.attribute_validation import effective_attributes
from app.services.visibility import asset_visible_in, redacted_attributes

# --------------------------------------------------------------------- formatting

def _cell(value: object) -> str:
    """A value fit for a table cell: one line, pipes escaped."""
    return str(value).replace("\r", "").replace("\n", "<br>").replace("|", "\\|")


def _when(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _table(rows: Iterable[tuple[str, object]]) -> list[str]:
    rows = [(k, v) for k, v in rows if v not in (None, "", [], {})]
    if not rows:
        return []
    return ["| | |", "|---|---|", *(f"| **{_cell(k)}** | {_cell(v)} |" for k, v in rows), ""]


def _size(n: Optional[int]) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class _Names:
    """Turns stored ids (users, assets, enumeration options) into the words a
    reader knows, looking each one up once."""

    def __init__(self, db: Session, workspace_id: str):
        self.db, self.workspace_id = db, workspace_id
        self._users: dict[str, str] = {}
        self._workflows: dict[tuple, dict] = {}

    def state(self, issue: Issue) -> str:
        """The workflow's name for a ticket's state ("In progress", not "in_progress")."""
        key = (issue.workspace_id, issue.schema_uid)
        if key not in self._workflows:
            self._workflows[key] = workflows.workflow_for(self.db, issue.workspace_id, issue.schema_uid)
        state = workflows.state_of(self._workflows[key], issue.state)
        return state["name"] if state else issue.state

    def user(self, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        if user_id not in self._users:
            u = self.db.get(User, user_id)
            self._users[user_id] = (u.name or u.email) if u is not None else user_id
        return self._users[user_id]

    def asset(self, ref: object) -> Optional[str]:
        a = self.db.get(Asset, str(ref)) or self.db.scalar(select(Asset).where(Asset.key == str(ref)))
        if a is None or a.deleted_at is not None or not asset_visible_in(a, self.workspace_id):
            return None
        return f"{a.key} — {a.name}"

    def value(self, attr: dict, value: object) -> str:
        kind = attr.get("type")
        if isinstance(value, list):
            return ", ".join(self.value(attr, v) for v in value)
        if kind == "reference":
            return self.asset(value) or "(not visible)"
        if kind in ("user", "current_user"):
            return self.user(str(value)) or str(value)
        if kind == "enumeration":
            option = next((o for o in attr.get("options") or [] if o.get("id") == value), None)
            return str(option.get("value")) if option else str(value)
        if kind == "boolean":
            return "yes" if value else "no"
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def attributes(self, schema: Optional[Schema], values: dict) -> list[tuple[str, object]]:
        """Each field the type defines, labelled and in the type's order, then
        anything stored that the type no longer names. Internal argus_* keys
        are bookkeeping, not content."""
        defs = effective_attributes(self.db, schema) if schema is not None else []
        rows, seen = [], set()
        for attr in defs:
            key = attr.get("key") or attr.get("name")
            seen.add(key)
            if key in values and values[key] not in (None, "", []):
                rows.append((attr.get("name") or key, self.value(attr, values[key])))
        for key, value in values.items():
            if key not in seen and not key.startswith("argus_") and value not in (None, "", []):
                rows.append((key, self.value({}, value)))
        return rows


def _attachments(rows: Iterable[Attachment]) -> list[str]:
    rows = list(rows)
    if not rows:
        return []
    out = ["## Attachments", ""]
    for a in rows:
        size = _size(a.file_size)
        out.append(f"- [{a.filename}](/v1/attachments/{a.uid})" + (f" ({size})" if size else ""))
    return out + [""]


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------- documents

def document(db: Session, workspace_id: str, doc: Document, revision: Optional[DocumentRevision],
             access: hub.Access) -> str:
    names = _Names(db, workspace_id)
    doc_type = db.get(Schema, doc.document_type_uid) if doc.document_type_uid else None
    lines = [f"# {doc.code} — {doc.title}", ""]
    rev_label = None
    if revision is not None:
        rev_label = f"{revision.revision_number} · {revision.state}"
        if revision.uid == doc.current_revision_uid:
            rev_label += " · current"
    lines += _table([
        ("Type", doc_type.name if doc_type else None),
        ("Revision", rev_label),
        ("Authority", doc.authority_level),
        ("Confidentiality", doc.confidentiality),
        ("Owner", names.user(doc.owner_user_id)),
        ("Author", names.user(revision.authored_by) if revision else None),
        ("Approved by", names.user(revision.approved_by) if revision else None),
        ("Published", _when(revision.published_at) if revision and revision.published_at else None),
        ("Valid from", _when(revision.valid_from) if revision and revision.valid_from else None),
        ("Valid until", _when(revision.valid_until) if revision and revision.valid_until else None),
        ("Next review", _when(revision.next_review_due) if revision and revision.next_review_due else None),
        ("Workspace", doc.workspace_id),
        ("Exported", _when(datetime.now(timezone.utc))),
    ])
    if revision is None:
        lines += ["_This document has no revision yet._", ""]
        return _finish(lines)

    fields = names.attributes(doc_type, revision.attributes or {})
    if fields:
        lines += ["## Fields", "", *_table(fields)]
    if (revision.body_markdown or "").strip():
        lines += ["---", "", revision.body_markdown.strip(), ""]
    steps = sorted(revision.steps or [], key=lambda s: s.get("ordine") or 0)
    if steps:
        lines += ["## Steps", ""]
        for n, s in enumerate(steps, 1):
            mark = "[ ] " if s.get("checklist") else ""
            text = (s.get("testo") or "").strip().replace("\n", "\n   ")
            lines.append(f"{n}. {mark}{'**' + text + '**' if s.get('voce_critica') else text}")
        lines.append("")

    if access.assets:
        applies = []
        for rel in db.scalars(select(DocumentRelation).where(DocumentRelation.from_document_uid == doc.uid)):
            if rel.to_type == "asset":
                label = names.asset(rel.to_uid)
                if label:
                    applies.append(f"- {label} ({rel.relation_type})")
            elif rel.to_type == "schema":
                schema = db.get(Schema, rel.to_uid)
                if schema is not None:
                    applies.append(f"- every {schema.name} ({rel.relation_type})")
        if applies:
            lines += ["## Applies to", "", *applies, ""]
    lines += _attachments(db.scalars(select(Attachment).where(Attachment.document_revision_uid == revision.uid)
                                     .order_by(Attachment.filename)))
    return _finish(lines)


# --------------------------------------------------------------------- assets

def asset(db: Session, workspace_id: str, a: Asset, access: hub.Access) -> str:
    names = _Names(db, workspace_id)
    schema = db.get(Schema, a.schema_uid) if a.schema_uid else None
    lineage = hub.schema_lineage(db, a.schema_uid)
    attrs = redacted_attributes(db, a)
    lines = [f"# {a.key} — {a.name}", ""]
    lines += _table([
        ("Type", " › ".join(s.name for s in reversed(lineage)) or a.type),
        ("Status", a.record_status),
        ("Lifecycle", attrs.get("argus_lifecycle")),
        ("System", attrs.get("argus_system")),
        ("Workspace", a.workspace_id),
        ("Updated", _when(a.updated_at)),
        ("Exported", _when(datetime.now(timezone.utc))),
    ])
    fields = names.attributes(schema, attrs)
    if fields:
        lines += ["## Fields", "", *_table(fields)]

    related = []
    for rel in db.scalars(select(Relation).where(
            or_(Relation.from_asset_uid == a.uid, Relation.to_asset_uid == a.uid)).order_by(Relation.relation_type)):
        outgoing = rel.from_asset_uid == a.uid
        label = names.asset(rel.to_asset_uid if outgoing else rel.from_asset_uid)
        if label:
            related.append(f"- {rel.relation_type} {'→' if outgoing else '←'} {label}")
    if related:
        lines += ["## Relations", "", *related, ""]

    if access.tickets:
        tickets = hub.tickets_for_assets(db, workspace_id, [a.uid])
        if tickets:
            lines += ["## Tickets", "", "| Ticket | State | Priority | Updated |", "|---|---|---|---|"]
            for t in tickets[:100]:
                key = (t.attributes or {}).get("argus_source_key")
                title = f"{key} {t.title}" if key else t.title
                lines.append(f"| {_cell(title)} | {_cell(names.state(t))} | {_cell(t.priority or '')} | {_when(t.updated_at)} |")
            lines.append("")
    if access.documents:
        docs = hub.documents_for_asset(db, workspace_id, a)
        if docs:
            lines += ["## Documents", ""]
            lines += [f"- {d['code']} — {d['title']}" + (f" ({d['state']})" if d.get("state") else "") for d in docs]
            lines.append("")
    lines += _attachments(db.scalars(select(Attachment).where(Attachment.asset_uid == a.uid)
                                     .order_by(Attachment.filename)))
    return _finish(lines)


# --------------------------------------------------------------------- tickets

def ticket(db: Session, workspace_id: str, issue: Issue, access: hub.Access) -> str:
    names = _Names(db, workspace_id)
    schema = db.get(Schema, issue.schema_uid) if issue.schema_uid else None
    attrs = redacted_attributes(db, issue)
    priority = issue.priority
    if priority:
        gv = db.scalar(select(GlobalValue).where(GlobalValue.key == "priority",
                                                 GlobalValue.workspace_id == issue.workspace_id))
        option = next((o for o in (gv.options or []) if o.get("id") == priority), None) if gv else None
        priority = option.get("value") if option else priority
    key = attrs.get("argus_source_key")
    lines = [f"# {key + ' — ' if key else ''}{issue.title}", ""]
    lines += _table([
        ("Type", schema.name if schema else None),
        ("State", names.state(issue)),
        ("Priority", priority),
        ("Assignee", names.user(issue.assignee)),
        ("Reported by", names.user(issue.created_by)),
        ("Created", _when(issue.created_at)),
        ("Due", _when(issue.due_date) if issue.due_date else None),
        ("Closed", _when(issue.closed_at) if issue.closed_at else None),
        ("Labels", ", ".join(issue.labels or [])),
        ("Original", attrs.get("argus_source_url")),
        ("Workspace", issue.workspace_id),
        ("Exported", _when(datetime.now(timezone.utc))),
    ])
    if (issue.description or "").strip():
        lines += ["## Description", "", issue.description.strip(), ""]
    fields = names.attributes(schema, attrs)
    if fields:
        lines += ["## Fields", "", *_table(fields)]
    if access.assets:
        equipment = [f"- {a.key} — {a.name}" for a in hub.linked_assets_of_ticket(db, workspace_id, issue)]
        if equipment:
            lines += ["## Equipment", "", *equipment, ""]
    comments = list(db.scalars(select(IssueComment).where(IssueComment.issue_uid == issue.uid)
                               .order_by(IssueComment.created_at)))
    if comments:
        lines += ["## Comments", ""]
        for c in comments:
            lines += [f"**{names.user(c.author) or c.author}** · {_when(c.created_at)}", "", c.body.strip(), "", "---", ""]
        lines.pop(-2)
    lines += _attachments(db.scalars(select(Attachment).where(Attachment.issue_uid == issue.uid)
                                     .order_by(Attachment.filename)))
    return _finish(lines)


def access_for(db: Session, identity, workspace_id: str) -> hub.Access:
    """Which sections the caller may read, as the hub's context endpoints decide it."""
    from app.auth import PatIdentity
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        return hub.Access(identity.may("read", "objects"), identity.may("read", "tickets"),
                          identity.may("read", "documents"))

    def can(resource: str) -> bool:
        return resolve_permission(db, identity.user, workspace_id, "read", resource)
    return hub.Access(assets=can("objects"), tickets=can("tickets"), documents=can("documents"))


# What the three /markdown endpoints declare, so the contract says text, not JSON.
OPENAPI = {"response_class": PlainTextResponse,
           "responses": {200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}}}


def response(text: str, stem: str) -> PlainTextResponse:
    """The Markdown as a download named after the record."""
    name = (re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "export")[:120] + ".md"
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
