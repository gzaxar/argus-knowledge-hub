"""Electronic logbook entries from a facility's Olog, kept as Logbook Entry documents.

Each facility runs the Phoebus Olog service (EPIK8s, phoebus-services-chart). A daily job there
(`tools/olog-to-argus`) reads the entries written since its last run and sends them here with the
facility's robot token: one document per entry, published, because an entry is already in use where
it was written. An entry edited in Olog arrives again with a later modify time and becomes a new
revision; one already here unchanged is left alone. Sending the same batch twice changes nothing.

The text of an entry is matched against the inventory (`text_links`): equipment named in it is related
to the entry, so a magnet's page lists what the logbook says about it.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.services.document_types import ensure_document_kinds, type_uid

KIND = "Logbook Entry"
ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")
MAX_ATTACHMENT_BYTES = int(os.environ.get("ARGUS_OLOG_MAX_ATTACHMENT_MB", "50")) * 1024 * 1024


# How Olog's editor puts a file in the text: ![caption](attachment/<file id>){width=… height=…}
OLOG_FILE_LINK = re.compile(r"\]\(attachment/([^)\s]+)\)(\{[^}]*\})?")


def link_files(db: Session, revision: DocumentRevision) -> bool:
    """Point the entry's references to its files at the copies kept here, so its images show where the author
    put them. A reference to a file not received yet is left as it is, and resolved when the file arrives.
    Only the links change, never the words: the revision stays what Olog says."""
    body = revision.body_markdown or ""
    if "](attachment/" not in body:
        return False
    files = {a.backend_id.rsplit(":", 1)[-1]: a.uid for a in db.scalars(select(Attachment).where(
        Attachment.document_revision_uid == revision.uid, Attachment.backend_id.like("olog:%")))}

    def to_copy(m: re.Match) -> str:
        uid = files.get(m.group(1))
        return f"](/v1/attachments/{uid})" if uid else m.group(0)
    linked = OLOG_FILE_LINK.sub(to_copy, body)
    if linked == body:
        return False
    revision.body_markdown = linked
    return True


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "olog"


def entry_uid(workspace_id: str, facility: str, entry_id: Any) -> str:
    return f"olog-{_slug(workspace_id)}-{_slug(facility)}-{_slug(str(entry_id))}"


def _when(value: Any) -> Optional[datetime]:
    """Olog's times: epoch milliseconds (Olog-es) or ISO text (older Olog and some clients)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return _when(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _names(items: Any) -> list[str]:
    return [str(i.get("name")) for i in (items or []) if isinstance(i, dict) and i.get("name")]


def _properties(items: Any) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for p in items or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        attrs = {str(a.get("name")): str(a.get("value") or "") for a in (p.get("attributes") or [])
                 if isinstance(a, dict) and a.get("name")}
        out[str(p["name"])] = attrs
    return out


def _body(entry: dict, created: Optional[datetime], url: Optional[str]) -> str:
    """The entry as a reader sees it in Olog: who, when, where it was logged, then the text."""
    text = (entry.get("source") or entry.get("description") or "").strip()
    head = []
    if created:
        head.append(f"**Logged:** {created.strftime('%Y-%m-%d %H:%M UTC')}")
    if entry.get("owner"):
        head.append(f"**By:** {entry['owner']}")
    if entry.get("level"):
        head.append(f"**Level:** {entry['level']}")
    if _names(entry.get("logbooks")):
        head.append(f"**Logbooks:** {', '.join(_names(entry.get('logbooks')))}")
    if _names(entry.get("tags")):
        head.append(f"**Tags:** {', '.join(_names(entry.get('tags')))}")
    parts = [" · ".join(head)] if head else []
    if text:
        parts.append(text)
    props = _properties(entry.get("properties"))
    if props:
        rows = ["| Property | Attribute | Value |", "|---|---|---|"]
        for name, attrs in props.items():
            for k, v in (attrs or {"": ""}).items():
                rows.append(f"| {name} | {k} | {v.replace('|', '/')} |")
        parts.append("\n".join(rows))
    if url:
        parts.append(f"[Open in Olog]({url})")
    return "\n\n".join(parts)


def _title(entry: dict) -> str:
    title = (entry.get("title") or "").strip()
    if title:
        return title[:300]
    first = (entry.get("description") or entry.get("source") or "").strip().splitlines()
    return (first[0][:120] if first else "") or f"Logbook entry {entry.get('id')}"


def upsert_entries(db: Session, workspace_id: str, facility: str, entries: list[dict],
                   entry_url: Optional[str] = None, link_equipment: bool = True) -> dict:
    """Store a batch of Olog entries. Returns, per entry, what happened and which of its files are still
    needed (the sender uploads only those)."""
    types = ensure_document_kinds(db, workspace_id)
    doc_type = types.get(KIND) or type_uid(workspace_id, KIND)
    facility = (facility or "olog").strip()
    results, counts = [], {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id in (None, ""):
            counts["rejected"] += 1
            results.append({"id": None, "status": "rejected", "error": "an entry without an id"})
            continue
        uid = entry_uid(workspace_id, facility, entry_id)
        created = _when(entry.get("createdDate"))
        modified = _when(entry.get("modifyDate")) or created
        version = (modified or created).isoformat() if (modified or created) else str(entry_id)
        url = entry_url.replace("{id}", str(entry_id)) if entry_url else None
        doc = db.get(Document, uid)
        if doc is not None and doc.workspace_id != workspace_id:
            counts["rejected"] += 1
            results.append({"id": entry_id, "status": "rejected", "error": "the entry belongs to another workspace"})
            continue
        current = db.get(DocumentRevision, doc.current_revision_uid) if doc and doc.current_revision_uid else None
        if current is not None and (current.attributes or {}).get("argus_source_version") == version:
            status = "unchanged"
        else:
            if doc is None:
                code = f"OLOG-{_slug(facility).upper()}-{entry_id}"
                if db.scalar(select(Document.uid).where(Document.code == code)) is not None:
                    code = f"{code}-{_slug(workspace_id).upper()}"
                doc = Document(uid=uid, workspace_id=workspace_id, code=code, title=_title(entry),
                               document_type_uid=doc_type, source="olog", authority_level="informativo",
                               retention_class="permanent")
                db.add(doc)
                db.flush()
                status = "created"
            else:
                status = "updated"
            doc.title = _title(entry)
            doc.document_type_uid = doc.document_type_uid or doc_type
            attributes = {
                "argus_source": "olog", "argus_source_id": str(entry_id), "argus_source_url": url,
                "argus_source_facility": facility, "argus_source_version": version,
                "argus_source_author": entry.get("owner"),
                "argus_source_created": created.isoformat() if created else None,
                "olog_level": entry.get("level"), "olog_logbooks": _names(entry.get("logbooks")),
                "olog_tags": _names(entry.get("tags")), "olog_properties": _properties(entry.get("properties")),
                "argus_keywords": _names(entry.get("logbooks")) + _names(entry.get("tags")),
            }
            revision = DocumentRevision(
                uid=f"{uid}-r{(current.revision_number + 1) if current else 1}",
                document_uid=doc.uid, revision_number=(current.revision_number + 1) if current else 1,
                state="published", body_markdown=_body(entry, created, url), attributes=attributes,
                published_at=modified or created or datetime.now(timezone.utc),
                valid_from=created.date() if created else None,
            )
            db.add(revision)
            db.flush()
            if current is not None:
                # The files stay where they are and follow the entry: they were attached to the entry,
                # not to one wording of it.
                for a in db.scalars(select(Attachment).where(Attachment.document_revision_uid == current.uid)):
                    a.document_revision_uid = revision.uid
                current.state = "superseded"
                current.superseded_by_uid = revision.uid
            doc.current_revision_uid = revision.uid
            db.flush()
            link_files(db, revision)            # the files it already had, now on this revision
            if link_equipment:
                _link_equipment(db, workspace_id, doc, f"{doc.title}\n{revision.body_markdown}")
        counts[status] += 1
        db.flush()                       # the session does not autoflush: the files moved above must be seen
        have = {a.backend_id for a in db.scalars(select(Attachment).where(
            Attachment.document_revision_uid == doc.current_revision_uid))}
        needed = [{"id": str(a.get("id") or a.get("filename")), "filename": a.get("filename") or str(a.get("id")),
                   "file_type": a.get("fileMetadataDescription") or a.get("fileType")}
                  for a in (entry.get("attachments") or []) if isinstance(a, dict)
                  and (a.get("id") or a.get("filename"))
                  and _attachment_key(facility, entry_id, a.get("id") or a.get("filename")) not in have]
        results.append({"id": entry_id, "uid": doc.uid, "code": doc.code, "status": status,
                        "attachments_needed": needed})
    db.commit()
    return {"counts": counts, "entries": results}


def _attachment_key(facility: str, entry_id: Any, attachment_id: Any) -> str:
    return f"olog:{_slug(facility)}:{entry_id}:{attachment_id}"


def _link_equipment(db: Session, workspace_id: str, doc: Document, text: str) -> None:
    from app.services.text_links import objects_mentioned
    already = set(db.scalars(select(DocumentRelation.to_uid).where(
        DocumentRelation.from_document_uid == doc.uid, DocumentRelation.to_type == "asset")))
    for found in objects_mentioned(db, workspace_id, text):
        if found["uid"] not in already:
            db.add(DocumentRelation(workspace_id=workspace_id, from_document_uid=doc.uid, to_type="asset",
                                    to_uid=found["uid"], relation_type="mentions"))


def add_attachment(db: Session, workspace_id: str, facility: str, entry_id: str, attachment_id: str,
                   filename: str, content: bytes, mime_type: Optional[str], source_url: Optional[str] = None) -> dict:
    """One of an entry's files, kept once whatever how often it is sent."""
    doc = db.get(Document, entry_uid(workspace_id, facility, entry_id))
    if doc is None or doc.workspace_id != workspace_id or not doc.current_revision_uid:
        raise LookupError("Send the entry before its files")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{filename} is over the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit")
    key = _attachment_key(facility, entry_id, attachment_id)
    existing = db.scalar(select(Attachment).join(DocumentRevision, DocumentRevision.uid == Attachment.document_revision_uid)
                         .where(DocumentRevision.document_uid == doc.uid, Attachment.backend_id == key))
    if existing is not None:
        return {"uid": existing.uid, "status": "unchanged"}
    import hashlib
    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    path = os.path.join(ATTACHMENTS_DIR, uid)
    with open(path, "wb") as f:
        f.write(content)
    db.add(Attachment(uid=uid, workspace_id=workspace_id, document_revision_uid=doc.current_revision_uid,
                      filename=filename, mime_type=mime_type, file_size=len(content),
                      sha256=hashlib.sha256(content).hexdigest(), storage_path=path, backend_id=key,
                      backend_url=source_url))
    db.flush()
    link_files(db, db.get(DocumentRevision, doc.current_revision_uid))
    db.commit()
    return {"uid": uid, "status": "created"}
