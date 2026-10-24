"""Import DokuWiki pages as documents — a source like Confluence (services/confluence_import.py).

A page's link, and with `include_children` every page under it (its namespace and those below). Each wiki page
is one document, found again on the next run by its page id: a page whose content has not changed is skipped; one
that has gets a new revision (the one before is superseded), its pictures with it. Imported pages arrive
published, as they are already in use at the source.

The pages are read as anyone allowed to read the wiki reads them (services/wiki_import.py: only the wikis
allowed, over https), turned into Markdown with their pictures shown in place (services/web_import.py), and:
links between pages imported become links between their documents; a page under another (calorimeter:bgo under
calorimeter) is that document's child; an asset key named in a page links the document to the asset.

DokuWiki publishes no version number for a page's content, so what is compared is a fingerprint of it.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.import_job import ImportJob
from app.services import web_import as wi
from app.services import wiki_import as wk
from app.services.document_types import ensure_document_kinds, type_uid

MAX_PAGES = 500
ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _progress(db: Session, job: ImportJob, message: str, **counts) -> None:
    job.progress = message
    if counts:
        merged = dict(job.counts or {})
        merged.update(counts)
        job.counts = merged
    db.commit()


def fingerprint(body: str) -> str:
    """The page's content, without what the wiki varies from one view to the next (section-edit markers)."""
    stable = re.sub(r"<!--\s*EDIT\{.*?\}\s*-->", "", body, flags=re.S)
    stable = re.sub(r"[?&]tok=[0-9a-f]+", "", stable)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def document_code(host: str, page_id: str, workspace_id: str, db: Session) -> tuple[Optional[Document], str]:
    """The document a wiki page maps to in this workspace (if imported before), and its code."""
    tail = re.sub(r"[^A-Za-z0-9]+", "-", page_id.rsplit(":", 1)[-1]).strip("-").upper()[:24] or "PAGE"
    digest = hashlib.sha1(f"{host}|{page_id}".encode()).hexdigest()[:6].upper()
    preferred = f"WIKI-{tail}-{digest}"
    existing = db.scalar(select(Document).where(Document.workspace_id == workspace_id,
                                                Document.code.in_([preferred, f"{preferred}-{workspace_id}"])))
    if existing is not None:
        return existing, existing.code
    taken = db.scalar(select(Document).where(Document.code == preferred))
    return None, preferred if taken is None else f"{preferred}-{workspace_id}"


def _attach(db: Session, workspace_id: str, revision_uid: str, path: str, content: bytes) -> str:
    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage = os.path.join(ATTACHMENTS_DIR, uid)
    with open(storage, "wb") as f:
        f.write(content)
    db.add(Attachment(uid=uid, workspace_id=workspace_id, document_revision_uid=revision_uid,
                      filename=path.rsplit("/", 1)[-1][-255:], mime_type=wi.mime_of(path), file_size=len(content),
                      storage_path=storage))
    return uid


def _relate(db: Session, workspace_id: str, from_uid: str, to_type: str, to_uid: str, relation: str) -> bool:
    exists = db.scalar(select(DocumentRelation).where(
        DocumentRelation.from_document_uid == from_uid, DocumentRelation.to_type == to_type,
        DocumentRelation.to_uid == to_uid, DocumentRelation.relation_type == relation))
    if exists is not None:
        return False
    db.add(DocumentRelation(workspace_id=workspace_id, from_document_uid=from_uid, to_type=to_type, to_uid=to_uid,
                            relation_type=relation))
    return True


def run_dokuwiki_import(job_uid: str, workspace_id: str, page_url: str, include_children: bool = True,
                        merge_strategy: str = "override", link_assets: bool = True) -> None:
    from app.services.confluence_import import choose_document_type
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    try:
        wiki = wk.open_wiki(page_url)
        host = wiki.origin.split("://", 1)[-1]
        if include_children:
            listed, truncated = wk.namespace_pages(wiki, wiki.page_id, limit=MAX_PAGES)
            if not any(p == wiki.page_id for p, _ in listed):
                listed.insert(0, (wiki.page_id, wiki.page_id.rsplit(":", 1)[-1]))
        else:
            listed, truncated = [(wiki.page_id, wiki.page_id.rsplit(":", 1)[-1])], False
        ids = [p for p, _ in listed]
        names = dict(listed)
        _progress(db, job, f"{len(ids)} page(s) on {host}" + (f" (only the first {MAX_PAGES})" if truncated else ""))
        bodies = wk.fetch_bodies(wiki, ids)
        type_uids = ensure_document_kinds(db, workspace_id)
        db.commit()

        # Every page's document first, so links between them can point at documents made in this run too.
        documents: dict[str, Document] = {}
        changed: list[str] = []
        for page_id in ids:
            doc, code = document_code(host, page_id, workspace_id, db)
            current = db.get(DocumentRevision, doc.current_revision_uid) if doc and doc.current_revision_uid else None
            if current is not None and (current.attributes or {}).get("argus_source_version") == \
                    fingerprint(bodies[page_id]):
                documents[page_id] = doc
                continue
            if doc is None:
                doc = Document(uid=str(uuid.uuid4()), workspace_id=workspace_id, code=code,
                               title=names.get(page_id) or page_id, source="dokuwiki")
                db.add(doc)
                db.flush()
            documents[page_id] = doc
            changed.append(page_id)
        db.commit()

        folder, sources = wk.build_folder(wiki, changed, bodies=bodies, linkable=set(ids), max_pages=MAX_PAGES)
        by_path = {wk.path_of(p): documents[p].uid for p in ids}
        key_to_asset = {}
        if link_assets:
            from app.models.asset import Asset
            key_to_asset = dict(db.execute(select(Asset.key, Asset.uid).where(Asset.workspace_id == workspace_id)).all())
        key_pattern = re.compile(r"\b[A-Z][A-Z0-9]*[-:_][A-Z0-9][A-Z0-9:_\-]*\b")
        imported = updated = links = pictures = 0
        for n, page_id in enumerate(changed, start=1):
            doc = documents[page_id]
            path = wk.path_of(page_id)
            page = wi.convert(path, folder)
            is_new = doc.current_revision_uid is None
            current = db.get(DocumentRevision, doc.current_revision_uid) if not is_new else None
            doc.title = page.title if page.title != wi.stem(path) else (names.get(page_id) or page.title)
            kind = choose_document_type([], doc.title)
            if is_new or not doc.document_type_uid:
                doc.document_type_uid = type_uids.get(kind) or type_uid(workspace_id, kind)
            revision = DocumentRevision(
                uid=str(uuid.uuid4()), document_uid=doc.uid,
                revision_number=(current.revision_number + 1) if current else 1, state="published",
                body_markdown="", published_at=datetime.now(timezone.utc),
                attributes={**(sources.get(path) or {}), "argus_source": "dokuwiki",
                            "argus_source_version": fingerprint(bodies[page_id]),
                            "argus_source_space": host, "argus_source_updated": datetime.now(timezone.utc).isoformat()})
            db.add(revision)
            db.flush()
            shown = {p: _attach(db, workspace_id, revision.uid, p, folder[p]) for p in page.pictures if p in folder}
            pictures += len(shown)
            _attach(db, workspace_id, revision.uid, path, folder[path])            # the page as the wiki showed it
            revision.body_markdown = wi.finish(page.markdown, shown, by_path)
            if current is not None:
                current.state = "superseded"
                current.superseded_by_uid = revision.uid
            doc.current_revision_uid = revision.uid
            if is_new:
                imported += 1
            else:
                updated += 1
            for key in set(key_pattern.findall(f"{doc.title}\n{revision.body_markdown}")):
                asset_uid = key_to_asset.get(key)
                if asset_uid and _relate(db, workspace_id, doc.uid, "asset", asset_uid, "describes"):
                    links += 1
            if n % 10 == 0:
                _progress(db, job, f"{n} of {len(changed)} changed page(s) imported")
        db.commit()

        # The wiki's tree: a page under another (calorimeter:bgo under calorimeter) is that document's child.
        tree = 0
        for page_id, doc in documents.items():
            parent = page_id.rsplit(":", 1)[0] if ":" in page_id else None
            while parent and parent not in documents:
                parent = parent.rsplit(":", 1)[0] if ":" in parent else None
            if parent and documents[parent].uid != doc.uid and \
                    _relate(db, workspace_id, doc.uid, "document", documents[parent].uid, "child_of"):
                tree += 1
        db.commit()

        unchanged = len(ids) - len(changed)
        _progress(db, job, f"Imported {imported} new and updated {updated} document(s); {unchanged} unchanged",
                  documents=imported, documents_updated=updated, documents_unchanged=unchanged,
                  attachments=pictures, asset_links=links, page_tree_links=tree)
        job.status = "succeeded"
        job.progress = "Import complete"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:  # noqa: BLE001 — whatever went wrong is the job's outcome, said in its words
        db.rollback()
        job = db.get(ImportJob, job_uid)
        job.status = "failed"
        job.error = str(e) if isinstance(e, wk.WikiError) else f"{type(e).__name__}: {e}"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
