"""Which templates there are for a workspace and a person, which one applies, and their versions.

Choosing the template, in this order (`resolve`):

1. the one the person picks explicitly;
2. their own personal copy for that document type, if they set one as theirs (active);
3. the workspace's active variant for that type;
4. the official template ARGUS ships.

Only published versions are used to make documents. Workspace variants are made and published by those who
may approve documents in the workspace; a personal copy by anyone who may create documents, and only they see
it. Official templates cannot be changed: a variant starts as a copy of one and keeps where it came from.
"""
from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_template import DocumentTemplate, DocumentTemplateVersion
from app.services import doc_templates as dt


class StoreError(Exception):
    def __init__(self, message: str, status: int = 409, problems: Optional[list] = None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


@dataclass
class Chosen:
    template: dt.Template
    scope: str                       # official | workspace | personal
    ref: str                         # official:<id> | <uid>
    version_uid: Optional[str]       # the version row (None for an official one until it is first used)
    reason: str
    row: Optional[DocumentTemplate] = None

    def view(self) -> dict:
        return {"ref": self.ref, "scope": self.scope, "id": self.template.id, "version": self.template.version,
                "name": self.row.name if self.row else self.template.title,
                "document_type": self.template.document_type, "reason": self.reason}


def official_ref(t: dt.Template) -> str:
    return f"official:{t.id}"


def _visible(q, workspace_id: str, user_id: Optional[str]):
    from sqlalchemy import or_
    return q.where(DocumentTemplate.workspace_id == workspace_id, DocumentTemplate.archived.is_(False),
                   or_(DocumentTemplate.scope == "workspace",
                       (DocumentTemplate.scope == "personal") & (DocumentTemplate.owner_user_id == user_id)))


def variant(db: Session, workspace_id: str, user_id: Optional[str], uid: str) -> DocumentTemplate:
    row = db.scalar(_visible(select(DocumentTemplate), workspace_id, user_id).where(DocumentTemplate.uid == uid))
    if row is None:
        raise StoreError("No such template here", 404)
    return row


def version_row(db: Session, row: DocumentTemplate, version: Optional[int] = None) -> DocumentTemplateVersion:
    v = version or row.latest_version
    out = db.scalar(select(DocumentTemplateVersion).where(DocumentTemplateVersion.template_uid == row.uid,
                                                          DocumentTemplateVersion.version == v))
    if out is None:
        raise StoreError(f"{row.name} has no published version {v}" if v else
                         f"{row.name} has not been published yet", 409)
    return out


def snapshot_official(db: Session, t: dt.Template, actor: Optional[str] = None) -> DocumentTemplateVersion:
    """The official template's text at its version, kept (once) so it survives a newer one shipping."""
    row = db.scalar(select(DocumentTemplateVersion).where(
        DocumentTemplateVersion.official_id == t.id, DocumentTemplateVersion.version == t.version,
        DocumentTemplateVersion.sha256 == t.sha256))
    if row is None:
        row = DocumentTemplateVersion(uid=str(uuid.uuid4()), official_id=t.id, version=t.version, source=t.source,
                                      sha256=t.sha256, created_by=actor or "argus", note="shipped with ARGUS")
        db.add(row)
        db.flush()
    return row


def listing(db: Session, workspace_id: str, user_id: Optional[str], document_type: Optional[str] = None) -> list[dict]:
    """The official templates and this workspace's variants and the person's copies, newest official versions
    and whether a variant's base has a newer official version."""
    officials = dt.official_templates()
    out = []
    for t in officials.values():
        if document_type and t.document_type != document_type:
            continue
        out.append({"ref": official_ref(t), "scope": "official", "id": t.id, "name": t.title,
                    "document_type": t.document_type, "version": t.version, "published": True, "active": False,
                    "editable": False})
    q = _visible(select(DocumentTemplate), workspace_id, user_id).order_by(DocumentTemplate.document_type,
                                                                           DocumentTemplate.created_at)
    if document_type:
        q = q.where(DocumentTemplate.document_type == document_type)
    for r in db.scalars(q):
        base = dt.official_by_id(r.base_template_id)
        out.append({"ref": r.uid, "scope": r.scope, "id": _id_of(r), "name": r.name, "document_type": r.document_type,
                    "version": r.latest_version, "published": r.latest_version > 0, "active": r.active,
                    "base": {"id": r.base_template_id, "version": r.base_version},
                    "official_update": base.version if base and base.version > r.base_version else None,
                    "editable": True})
    return out


def _id_of(row: DocumentTemplate) -> str:
    m = re.search(r"(?m)^id:\s*([a-z0-9-]+)\s*$", row.draft_source or "")
    return m.group(1) if m else row.uid


def get(db: Session, workspace_id: str, user_id: Optional[str], ref: str) -> Chosen:
    """A template by its reference: official:<id>, a variant's uid (its latest published version) or uid@n."""
    if ref.startswith("official:"):
        t = dt.official_by_id(ref.split(":", 1)[1])
        if t is None:
            raise StoreError("No such official template", 404)
        return Chosen(t, "official", ref, None, "chosen")
    uid, _, n = ref.partition("@")
    row = variant(db, workspace_id, user_id, uid)
    v = version_row(db, row, int(n) if n.isdigit() else None)
    return Chosen(dt.load(v.source), row.scope, row.uid, v.uid, "chosen", row)


def resolve(db: Session, workspace_id: str, user_id: Optional[str], document_type: str,
            explicit: Optional[str] = None) -> Chosen:
    """The template that applies, and why (the order is in this module's description)."""
    if explicit:
        chosen = get(db, workspace_id, user_id, explicit)
        if chosen.template.document_type != document_type:
            raise StoreError(f"{chosen.view()['name']} is for {chosen.template.document_type}, not {document_type}",
                             422)
        chosen.reason = "chosen by you"
        return chosen
    base = select(DocumentTemplate).where(DocumentTemplate.workspace_id == workspace_id,
                                          DocumentTemplate.document_type == document_type,
                                          DocumentTemplate.active.is_(True), DocumentTemplate.archived.is_(False),
                                          DocumentTemplate.latest_version > 0)
    if user_id:
        mine = db.scalar(base.where(DocumentTemplate.scope == "personal", DocumentTemplate.owner_user_id == user_id))
        if mine is not None:
            v = version_row(db, mine)
            return Chosen(dt.load(v.source), "personal", mine.uid, v.uid, "your personal copy, set as yours", mine)
    ws = db.scalar(base.where(DocumentTemplate.scope == "workspace"))
    if ws is not None:
        v = version_row(db, ws)
        return Chosen(dt.load(v.source), "workspace", ws.uid, v.uid, "the workspace's active variant", ws)
    t = dt.official_templates().get(document_type)
    if t is None:
        raise StoreError(f"There is no template for {document_type!r}: make one from the official template of a "
                         "similar type", 404)
    return Chosen(t, "official", official_ref(t), None, "the official template")


# --------------------------------------------------------------------------- making and changing variants

def _set_front(source: str, key: str, value) -> str:
    pattern = re.compile(rf"(?m)^{key}:.*$")
    line = f"{key}: {value}"
    if pattern.search(source.split("\n---", 1)[0] if source.startswith("---") else ""):
        head, sep, rest = source.partition("\n---")
        return pattern.sub(line, head, count=1) + sep + rest
    return source.replace("---\n", f"---\n{line}\n", 1)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:20] or "x"


def create(db: Session, workspace_id: str, user_id: Optional[str], *, base_ref: str, scope: str,
           name: Optional[str] = None) -> DocumentTemplate:
    """A workspace variant or a personal copy, starting from an official template or from a variant here."""
    if scope not in ("workspace", "personal"):
        raise StoreError("scope is workspace or personal", 422)
    source_of = get(db, workspace_id, user_id, base_ref)
    if source_of.scope == "official":
        official, official_version = source_of.template.id, source_of.template.version
        snapshot_official(db, source_of.template, user_id)
    else:
        official, official_version = source_of.row.base_template_id, source_of.row.base_version
    uid = str(uuid.uuid4())
    suffix = _slug(workspace_id) + ("-" + uid[:6] if scope == "personal" else "")
    source = _set_front(source_of.template.source, "id", f"{official}--{suffix}"[:60].rstrip("-"))
    source = _set_front(source, "version", 1)
    row = DocumentTemplate(uid=uid, workspace_id=workspace_id, scope=scope,
                           owner_user_id=user_id, document_type=source_of.template.document_type,
                           name=(name or "").strip()[:120] or f"{source_of.template.title} ({'workspace' if scope == 'workspace' else 'mine'})",
                           base_template_id=official, base_version=official_version, draft_source=source,
                           latest_version=0, active=False, created_by=user_id)
    db.add(row)
    db.flush()
    return row


def save_draft(row: DocumentTemplate, source: str) -> list[dict]:
    """Keep the edited text (even with problems, so work is not lost) and say what is wrong with it. The id and
    the document type are the variant's own and cannot be changed by editing."""
    if len(source.encode()) > dt.MAX_SOURCE:
        raise StoreError(f"The template is larger than {dt.MAX_SOURCE // 1024} KB", 413)
    t, problems = dt.parse(source)
    if t is not None and t.document_type != row.document_type:
        problems.append(dt.Problem(f"document_type must stay {row.document_type!r}: make a variant of the other "
                                   "type's template instead"))
    row.draft_source = source
    return [p.view() for p in problems]


def publish(db: Session, row: DocumentTemplate, actor: Optional[str], note: Optional[str] = None) -> DocumentTemplateVersion:
    """The draft as the next immutable version."""
    source = _set_front(row.draft_source, "version", row.latest_version + 1)
    t, problems = dt.parse(source)
    errors = [p for p in problems if p.severity == "error"]
    if t is not None and t.document_type != row.document_type:
        errors.append(dt.Problem(f"document_type must stay {row.document_type!r}"))
    if errors:
        raise StoreError("The template has errors: fix them before publishing", 422, [p.view() for p in errors])
    if row.latest_version:
        previous = version_row(db, row)
        if previous.sha256 == t.sha256:
            raise StoreError("Nothing changed since the last published version", 409)
    v = DocumentTemplateVersion(uid=str(uuid.uuid4()), template_uid=row.uid, version=row.latest_version + 1,
                                source=source, sha256=t.sha256, note=(note or "").strip()[:2000] or None,
                                created_by=actor)
    db.add(v)
    row.latest_version += 1
    row.draft_source = source
    db.flush()
    return v


def activate(db: Session, row: DocumentTemplate, on: bool) -> None:
    """Make it the default for its type (in the workspace, or for its owner), or stop."""
    if on and row.latest_version == 0:
        raise StoreError("Publish it before making it the default", 409)
    if on:
        q = select(DocumentTemplate).where(DocumentTemplate.workspace_id == row.workspace_id,
                                           DocumentTemplate.document_type == row.document_type,
                                           DocumentTemplate.scope == row.scope, DocumentTemplate.active.is_(True),
                                           DocumentTemplate.uid != row.uid)
        if row.scope == "personal":
            q = q.where(DocumentTemplate.owner_user_id == row.owner_user_id)
        for other in db.scalars(q):
            other.active = False
    row.active = on
    db.flush()


def _diff(a: str, b: str, a_name: str, b_name: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True), a_name, b_name))


def compare(db: Session, row: DocumentTemplate) -> dict:
    """The variant against the official text it came from, and what ARGUS changed in its official template
    since then (never applied to the variant by itself)."""
    base = db.scalar(select(DocumentTemplateVersion).where(DocumentTemplateVersion.official_id == row.base_template_id,
                                                           DocumentTemplateVersion.version == row.base_version)
                     .order_by(DocumentTemplateVersion.created_at))
    current = dt.official_by_id(row.base_template_id)
    base_source = base.source if base else (current.source if current and current.version == row.base_version else "")
    out = {"base": {"id": row.base_template_id, "version": row.base_version},
           "against_base": _diff(base_source, row.draft_source, f"official {row.base_template_id} v{row.base_version}",
                                 f"{row.name} (draft)"),
           "official_update": None}
    if current and current.version > row.base_version:
        out["official_update"] = {"version": current.version,
                                  "changes": _diff(base_source, current.source,
                                                   f"official v{row.base_version}", f"official v{current.version}")}
    return out


def rebase(db: Session, row: DocumentTemplate) -> None:
    """Record that the variant has been brought up to the newest official version (after the person merged what
    they wanted into the draft); the variant's text is never replaced."""
    current = dt.official_by_id(row.base_template_id)
    if current is None or current.version <= row.base_version:
        raise StoreError("There is no newer official version", 409)
    snapshot_official(db, current)
    row.base_version = current.version
