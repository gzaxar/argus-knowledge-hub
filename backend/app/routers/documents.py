import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.auth import Identity, OidcIdentity, PatIdentity, get_identity, require_permission
from app.db import get_db
from app.services import knowledge_schedule, markdown_export, notify, pdf_export
from app.services.permissions import has_permission
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.schemas.attachment import AttachmentOut
from app.schemas.document import (
    ApproveAction,
    BulkDeleteRequest,
    BulkDeleteResult,
    DocumentCreate,
    DocumentOut,
    DocumentRelationCreate,
    DocumentRelationOut,
    DocumentRevisionCreate,
    DocumentRevisionOut,
    DocumentRevisionUpdate,
    DocumentUpdate,
    RejectAction,
    RetireAction,
    MarkdownImportResult,
    RetypeRequest,
    RetypeResult,
)
from app.services.attribute_validation import check_attributes
from app.services import document_control
from app.services.document_codes import next_code
from app.services.drawings import (
    dwg_to_dxf,
    needs_conversion,
    render_sheets,
    sheet_filename,
    sheet_marker,
    suffix_of,
)
from app.services.markdown_import import import_markdown
from app.services.current_user_attrs import stamp_current_user_attributes

router = APIRouter(prefix="/v1/documents", tags=["documents"])

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _get_owned_document(uid: str, workspace_id: str, db: Session) -> Document:
    doc = db.get(Document, uid)
    if doc is None or doc.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _actor_user_id(identity: Identity) -> Optional[str]:
    return identity.user.id if isinstance(identity, OidcIdentity) else None


def _can_approve(workspace_id: str, identity: Identity, db: Session) -> bool:
    """Approval authority, resolved the same way as everything else — so the
    Approver role grants it, not only a legacy membership flag."""
    if isinstance(identity, PatIdentity):
        return identity.may("approve", "documents")
    if identity.token is not None and not identity.token.may("approve", "documents"):
        return False
    return has_permission(db, identity.user, workspace_id, "approve", "documents")


def _check_confidentiality(doc: Document, workspace_id: str, identity: Identity, db: Session) -> None:
    if doc.confidentiality != "riservato":
        return
    if isinstance(identity, PatIdentity):
        if identity.may("approve", "documents"):
            return
        raise HTTPException(status_code=404, detail="Document not found")
    if identity.user.is_admin or identity.user.id == doc.owner_user_id:
        return
    if _can_approve(workspace_id, identity, db):
        return
    raise HTTPException(status_code=404, detail="Document not found")


def _get_visible_document(
    uid: str, workspace_id: str, identity: Identity, db: Session
) -> Document:
    doc = db.get(Document, uid)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.workspace_id != workspace_id:
        # Shared across workspaces, but never something marked riservato:
        # "confidential" and "readable by every workspace" cannot both be
        # true, and the safe reading of that contradiction is the strict one.
        if not doc.is_global or doc.confidentiality == "riservato":
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    _check_confidentiality(doc, workspace_id, identity, db)
    return doc


def _get_revision(document_uid: str, revision_uid: str, db: Session) -> DocumentRevision:
    rev = db.get(DocumentRevision, revision_uid)
    if rev is None or rev.document_uid != document_uid:
        raise HTTPException(status_code=404, detail="Revision not found")
    return rev


def _validate_revision_attributes(
    db: Session, doc: Document, attributes: dict, workspace_id: str, exclude_uid: Optional[str]
) -> None:
    schema = db.get(Schema, doc.document_type_uid) if doc.document_type_uid else None
    violations = check_attributes(
        db, schema, attributes, workspace_id, Document, exclude_uid=exclude_uid,
        schema_uid_attr="document_type_uid", skip_unique=True,
    )
    if violations:
        raise HTTPException(status_code=422, detail=violations[0])


@router.get("", response_model=list[DocumentOut])
def list_documents(
    document_type_uid: Optional[str] = None,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    db: Session = Depends(get_db),
):
    stmt = select(Document).where(
        or_(
            Document.workspace_id == workspace_id,
            and_(
                Document.is_global.is_(True),
                Document.confidentiality != "riservato",
            ),
        )
    )
    if document_type_uid:
        stmt = stmt.where(Document.document_type_uid == document_type_uid)
    return db.scalars(stmt).all()


@router.post("", response_model=DocumentOut, status_code=201)
def create_document(
    body: DocumentCreate,
    workspace_id: str = Depends(require_permission("create", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doc, _ = new_document(db, body, workspace_id, identity)
    db.commit()
    db.refresh(doc)
    return doc


def new_document(db: Session, body: DocumentCreate, workspace_id: str, identity: Identity
                 ) -> tuple[Document, DocumentRevision]:
    """A document and its first, draft revision, checked and announced; not committed (the caller does, so
    another flow — a draft reworked from raw text — can add to the same transaction)."""
    if db.get(Document, body.uid) is not None:
        raise HTTPException(status_code=409, detail="Document uid already exists")

    workspace = db.get(Workspace, workspace_id)
    code = (body.code or "").strip() or next_code(db, workspace_id, body.document_type_uid)
    if db.scalar(select(Document).where(Document.code == code)) is not None:
        raise HTTPException(
            status_code=409, detail=f"A document with the code {code} already exists"
        )

    if body.retention_class not in document_control.RETENTION_YEARS:
        raise HTTPException(status_code=422, detail="Unknown retention class")
    doc = Document(
        uid=body.uid, workspace_id=workspace_id, code=code, title=body.title,
        document_type_uid=body.document_type_uid, owner_user_id=body.owner_user_id,
        responsible_service_asset_uid=body.responsible_service_asset_uid,
        authority_level=body.authority_level, confidentiality=body.confidentiality,
        source=body.source, retention_class=body.retention_class,
        # A globally-shared workspace shares what is written in it, including
        # documents created after the flag was set — the same rule types
        # already follow, so the workspace-level flag doesn't decay.
        is_global=bool(workspace is not None and workspace.is_global),
    )
    doc_schema = db.get(Schema, doc.document_type_uid) if doc.document_type_uid else None
    stamp_current_user_attributes(db, doc_schema, body.attributes, _actor_user_id(identity))
    _validate_revision_attributes(db, doc, body.attributes, workspace_id, exclude_uid=None)
    db.add(doc)
    db.flush()

    revision = DocumentRevision(
        uid=f"{body.uid}-r1", document_uid=doc.uid, revision_number=1, state="draft",
        body_markdown=body.body_markdown, steps=body.steps, attributes=body.attributes,
        valid_from=body.valid_from, valid_until=body.valid_until,
        next_review_due=body.next_review_due, authored_by=_actor_user_id(identity),
    )
    db.add(revision)
    notify.follow(db, "document", doc.uid, _actor_user_id(identity))
    if doc.confidentiality != "riservato":
        notify.announce(db, workspace_id, "documents", "new_document", f"New document: {doc.code} {doc.title}",
                        _actor_user_id(identity), doc.uid)
    db.flush()
    return doc, revision


@router.post("/retype", response_model=RetypeResult)
def retype_documents(
    body: RetypeRequest,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    """Move a batch of documents onto another type.

    Typing a library correctly is done in hindsight, after an import has
    guessed: it is a sorting job over dozens of documents at a time, and
    doing it one document at a time through the edit form is the reason it
    doesn't get done.
    """
    if body.document_type_uid:
        schema = db.get(Schema, body.document_type_uid)
        if schema is None or schema.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Document type not found")
        if schema.applies_to != "documents":
            raise HTTPException(
                status_code=422, detail="That type doesn't apply to documents"
            )

    moved = 0
    missing: list[str] = []
    for uid in body.uids:
        doc = db.get(Document, uid)
        if doc is None or doc.workspace_id != workspace_id:
            missing.append(uid)
            continue
        doc.document_type_uid = body.document_type_uid
        moved += 1
    db.commit()
    return RetypeResult(moved=moved, not_found=missing)


@router.post("/import", response_model=MarkdownImportResult)
async def import_markdown_documents(
    files: list[UploadFile] = File(description="Markdown files, resources, or a zip of both"),
    document_type_uid: Optional[str] = Form(None),
    workspace_id: str = Depends(require_permission("create", resource="documents")),
    db: Session = Depends(get_db),
):
    """Markdown files, and the images they refer to, as documents.

    Accepts loose files or a zip, because the unit people actually have is
    a folder: a few `.md` files with an `images/` beside them. Uploading
    only the text would produce documents whose every figure is a broken
    link.
    """
    if document_type_uid:
        schema = db.get(Schema, document_type_uid)
        if schema is None or schema.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Document type not found")

    payload = [(f.filename or "untitled.md", await f.read()) for f in files]
    if not any(name.lower().endswith((".md", ".markdown", ".mdown", ".zip"))
               for name, _ in payload):
        raise HTTPException(
            status_code=422,
            detail="No Markdown file in the upload — add the .md files, or a zip containing them.",
        )
    return import_markdown(db, workspace_id, payload, document_type_uid)


@router.get("/{uid}", response_model=DocumentOut)
def get_document(
    uid: str,
    response: Response,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    from app.services import versions
    doc = _get_visible_document(uid, workspace_id, identity, db)
    revision = db.get(DocumentRevision, doc.current_revision_uid) if doc.current_revision_uid else None
    response.headers["ETag"] = versions.etag(versions.document_version(doc, revision))
    return doc


@router.get("/{uid}/markdown", **markdown_export.OPENAPI)
def export_document_markdown(
    uid: str,
    revision_uid: Optional[str] = None,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """The document as Markdown: the revision asked for, or the one its page
    opens on (the current one, else the latest)."""
    doc, text = _document_markdown(uid, revision_uid, workspace_id, identity, db)
    return markdown_export.response(text, doc.code)


@router.get("/{uid}/pdf", **pdf_export.OPENAPI)
def export_document_pdf(
    uid: str,
    revision_uid: Optional[str] = None,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """The same document as an A4 PDF, its pictures included."""
    doc, text = _document_markdown(uid, revision_uid, workspace_id, identity, db)
    files = db.scalars(select(Attachment).join(DocumentRevision, DocumentRevision.uid == Attachment.document_revision_uid)
                       .where(DocumentRevision.document_uid == doc.uid))
    return pdf_export.response(pdf_export.render(text, f"{doc.code} — {doc.title}", files), doc.code)


def _document_markdown(uid: str, revision_uid: Optional[str], workspace_id: str, identity: Identity,
                       db: Session) -> tuple[Document, str]:
    doc = _get_visible_document(uid, workspace_id, identity, db)
    if revision_uid:
        revision = _get_revision(doc.uid, revision_uid, db)
    else:
        revision = (db.get(DocumentRevision, doc.current_revision_uid) if doc.current_revision_uid else None) \
            or db.scalar(select(DocumentRevision).where(DocumentRevision.document_uid == doc.uid)
                         .order_by(DocumentRevision.revision_number.desc()).limit(1))
    access = markdown_export.access_for(db, identity, workspace_id)
    return doc, markdown_export.document(db, workspace_id, doc, revision, access)


@router.put("/{uid}", response_model=DocumentOut)
def update_document(
    uid: str,
    body: DocumentUpdate,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    doc = _get_owned_document(uid, workspace_id, db)
    patch = body.model_dump(exclude_unset=True)
    # Sharing something marked riservato is a contradiction, and the reader
    # of a 404 would have no idea why. Say it.
    confidentiality = patch.get("confidentiality", doc.confidentiality)
    if patch.get("is_global", doc.is_global) and confidentiality == "riservato":
        raise HTTPException(
            status_code=422,
            detail="A confidential document cannot be shared with other workspaces. "
                   "Change its confidentiality first, or leave it unshared.",
        )
    for field, value in patch.items():
        setattr(doc, field, value)
    notify.document_changed(db, doc, f"details changed ({', '.join(sorted(patch))})", _actor_user_id(identity))
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{uid}", status_code=204)
def delete_document(
    uid: str,
    workspace_id: str = Depends(require_permission("delete", resource="documents")),
    db: Session = Depends(get_db),
):
    doc = _get_owned_document(uid, workspace_id, db)
    try:
        document_control.assert_deletable(db, doc)
    except document_control.ControlError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "retention"})
    db.delete(doc)
    db.commit()


@router.post("/bulk-delete", response_model=BulkDeleteResult)
def bulk_delete_documents(
    body: BulkDeleteRequest,
    workspace_id: str = Depends(require_permission("delete", resource="documents")),
    db: Session = Depends(get_db),
):
    deleted = 0
    missing: list[str] = []
    retained = []
    for uid in body.uids:
        doc = db.get(Document, uid)
        if doc is None or doc.workspace_id != workspace_id:
            missing.append(uid)
            continue
        if not document_control.retention_view(db, doc)["deletable"]:
            retained.append(doc.code)
    if retained:
        # All or nothing: a partial delete of a controlled set is worse than none.
        raise HTTPException(status_code=409, detail={
            "error": f"under retention, retire them instead: {', '.join(retained)}", "invariant": "retention"})
    for uid in body.uids:
        doc = db.get(Document, uid)
        if doc is None or doc.workspace_id != workspace_id:
            continue
        db.delete(doc)
        deleted += 1
    db.commit()
    return BulkDeleteResult(deleted=deleted, not_found=missing)


@router.post("/{uid}/retire", response_model=DocumentOut)
def retire_document(
    uid: str,
    body: RetireAction,
    workspace_id: str = Depends(require_permission("delete", resource="documents")),
    db: Session = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    doc = _get_owned_document(uid, workspace_id, db)
    if doc.current_revision_uid:
        current = db.get(DocumentRevision, doc.current_revision_uid)
        if current and current.state == "published":
            current.state = "retired"
            current.review_comment = body.reason
    doc.current_revision_uid = None
    doc.retired_at = datetime.now(timezone.utc)
    notify.document_changed(db, doc, "retired" + (f": {body.reason}" if getattr(body, "reason", None) else ""), _actor_user_id(identity))
    db.commit()
    db.refresh(doc)
    knowledge_schedule.after_document_change(db, workspace_id)
    return doc


@router.get("/{uid}/current", response_model=DocumentRevisionOut)
def get_current_revision(
    uid: str,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """ARGUS-facing: the single currently-published, currently-visible
    revision, or 404 — never a draft, never anything the caller can't see."""
    doc = _get_visible_document(uid, workspace_id, identity, db)
    if not doc.current_revision_uid:
        raise HTTPException(status_code=404, detail="No published revision")
    return db.get(DocumentRevision, doc.current_revision_uid)


@router.get("/{uid}/revisions", response_model=list[DocumentRevisionOut])
def list_revisions(
    uid: str,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _get_visible_document(uid, workspace_id, identity, db)
    return db.scalars(
        select(DocumentRevision)
        .where(DocumentRevision.document_uid == uid)
        .order_by(DocumentRevision.revision_number)
    ).all()


@router.post("/{uid}/revisions", response_model=DocumentRevisionOut, status_code=201)
def create_revision(
    uid: str,
    body: DocumentRevisionCreate,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    revision = new_revision(db, uid, body, workspace_id, identity)
    db.commit()
    db.refresh(revision)
    return revision


def new_revision(db: Session, uid: str, body: DocumentRevisionCreate, workspace_id: str,
                 identity: Identity) -> DocumentRevision:
    """The document's next revision, as a draft; refused while another is open. Not committed."""
    doc = _get_owned_document(uid, workspace_id, db)
    _check_confidentiality(doc, workspace_id, identity, db)
    open_revision = db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_uid == uid,
            DocumentRevision.state.in_(("draft", "in_review", "approved")),
        )
    )
    if open_revision is not None:
        raise HTTPException(
            status_code=409, detail="A draft/review/approved revision is already open"
        )
    doc_schema = db.get(Schema, doc.document_type_uid) if doc.document_type_uid else None
    stamp_current_user_attributes(db, doc_schema, body.attributes, _actor_user_id(identity))
    _validate_revision_attributes(db, doc, body.attributes, workspace_id, exclude_uid=doc.uid)

    last_number = db.scalar(
        select(DocumentRevision.revision_number)
        .where(DocumentRevision.document_uid == uid)
        .order_by(DocumentRevision.revision_number.desc())
    ) or 0
    revision = DocumentRevision(
        uid=f"{uid}-r{last_number + 1}", document_uid=uid, revision_number=last_number + 1,
        state="draft", body_markdown=body.body_markdown, steps=body.steps,
        attributes=body.attributes, valid_from=body.valid_from, valid_until=body.valid_until,
        next_review_due=body.next_review_due, authored_by=_actor_user_id(identity),
    )
    db.add(revision)
    notify.document_changed(db, doc, f"revision {revision.revision_number} started", _actor_user_id(identity))
    db.flush()
    return revision


@router.get("/{uid}/revisions/{rev_uid}", response_model=DocumentRevisionOut)
def get_revision(
    uid: str,
    rev_uid: str,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _get_visible_document(uid, workspace_id, identity, db)
    return _get_revision(uid, rev_uid, db)


@router.put("/{uid}/revisions/{rev_uid}", response_model=DocumentRevisionOut)
def update_revision(
    uid: str,
    rev_uid: str,
    body: DocumentRevisionUpdate,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doc = _get_owned_document(uid, workspace_id, db)
    revision = _get_revision(uid, rev_uid, db)
    if revision.state != "draft":
        raise HTTPException(status_code=409, detail="Only a draft revision can be edited")
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(revision, field, value)

    doc_schema = db.get(Schema, doc.document_type_uid) if doc.document_type_uid else None
    stamp_current_user_attributes(db, doc_schema, revision.attributes, _actor_user_id(identity))
    flag_modified(revision, "attributes")

    if "attributes" in patch:
        _validate_revision_attributes(db, doc, revision.attributes, workspace_id, exclude_uid=doc.uid)
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{uid}/revisions/{rev_uid}/submit", response_model=DocumentRevisionOut)
def submit_revision(
    uid: str,
    rev_uid: str,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    doc = _get_owned_document(uid, workspace_id, db)
    revision = _get_revision(uid, rev_uid, db)
    if revision.state != "draft":
        raise HTTPException(status_code=409, detail="Only a draft revision can be submitted")
    revision.state = "in_review"
    revision.submitted_at = datetime.now(timezone.utc)
    notify.review_requested(db, doc, revision, _actor_user_id(identity))
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{uid}/revisions/{rev_uid}/approve", response_model=DocumentRevisionOut)
def approve_revision(
    uid: str,
    rev_uid: str,
    body: ApproveAction,
    workspace_id: str = Depends(require_permission("approve", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doc = _get_owned_document(uid, workspace_id, db)
    revision = _get_revision(uid, rev_uid, db)
    if revision.state != "in_review":
        raise HTTPException(status_code=409, detail="Only an in-review revision can be approved")
    try:
        document_control.assert_not_author(revision, _actor_user_id(identity))
    except document_control.ControlError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "separation-of-duties"})
    revision.state = "approved"
    revision.approved_by = _actor_user_id(identity)
    revision.approved_at = datetime.now(timezone.utc)
    revision.review_comment = body.comment
    notify.document_changed(db, doc, f"revision {revision.revision_number} approved", _actor_user_id(identity))
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{uid}/revisions/{rev_uid}/reject", response_model=DocumentRevisionOut)
def reject_revision(
    uid: str,
    rev_uid: str,
    body: RejectAction,
    workspace_id: str = Depends(require_permission("approve", resource="documents")),
    db: Session = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    doc = _get_owned_document(uid, workspace_id, db)
    revision = _get_revision(uid, rev_uid, db)
    if revision.state != "in_review":
        raise HTTPException(status_code=409, detail="Only an in-review revision can be rejected")
    revision.state = "draft"
    revision.review_comment = body.comment
    notify.document_changed(db, doc, f"revision {revision.revision_number} sent back to draft", _actor_user_id(identity))
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{uid}/revisions/{rev_uid}/publish", response_model=DocumentRevisionOut)
def publish_revision(
    uid: str,
    rev_uid: str,
    workspace_id: str = Depends(require_permission("approve", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doc = _get_owned_document(uid, workspace_id, db)
    revision = _get_revision(uid, rev_uid, db)
    if revision.state != "approved":
        raise HTTPException(status_code=409, detail="Only an approved revision can be published")

    if doc.current_revision_uid:
        previous = db.get(DocumentRevision, doc.current_revision_uid)
        if previous is not None:
            previous.state = "superseded"
            previous.superseded_by_uid = revision.uid

    revision.state = "published"
    revision.published_at = datetime.now(timezone.utc)
    doc.current_revision_uid = revision.uid
    if doc.confidentiality != "riservato":
        notify.announce(db, workspace_id, "documents", "document_published",
                        f"Published: {doc.code} {doc.title} (revision {revision.revision_number})",
                        _actor_user_id(identity), doc.uid)
    notify.document_changed(db, doc, f"revision {revision.revision_number} published", _actor_user_id(identity))
    db.commit()
    db.refresh(revision)
    knowledge_schedule.after_document_change(db, workspace_id)
    return revision


@router.get("/{uid}/relations", response_model=list[DocumentRelationOut])
def list_relations(
    uid: str,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _get_visible_document(uid, workspace_id, identity, db)
    return db.scalars(
        select(DocumentRelation).where(DocumentRelation.from_document_uid == uid)
    ).all()


@router.post("/{uid}/relations", response_model=DocumentRelationOut, status_code=201)
def create_relation(
    uid: str,
    body: DocumentRelationCreate,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    _get_owned_document(uid, workspace_id, db)
    relation = DocumentRelation(
        workspace_id=workspace_id, from_document_uid=uid,
        to_type=body.to_type, to_uid=body.to_uid, relation_type=body.relation_type,
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


@router.delete("/{uid}/relations/{relation_id}", status_code=204)
def delete_relation(
    uid: str,
    relation_id: int,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    _get_owned_document(uid, workspace_id, db)
    relation = db.get(DocumentRelation, relation_id)
    if relation is None or relation.from_document_uid != uid or relation.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(relation)
    db.commit()


@router.get("/{uid}/revisions/{rev_uid}/attachments", response_model=list[AttachmentOut])
def list_revision_attachments(
    uid: str,
    rev_uid: str,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doc = _get_visible_document(uid, workspace_id, identity, db)
    _get_revision(doc.uid, rev_uid, db)
    return db.scalars(
        select(Attachment).where(Attachment.document_revision_uid == rev_uid)
    ).all()


@router.post("/{uid}/revisions/{rev_uid}/attachments", response_model=AttachmentOut,
             status_code=201)
async def upload_revision_attachment(
    uid: str,
    rev_uid: str,
    file: UploadFile,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """A file belonging to one revision of a document.

    Revision-scoped rather than document-scoped because a published revision
    is immutable: the figure a procedure was approved with has to stay the
    figure that revision shows, whatever a later one replaces it with.
    """
    doc = _get_visible_document(uid, workspace_id, identity, db)
    revision = _get_revision(doc.uid, rev_uid, db)
    if revision.state in ("published", "superseded", "retired"):
        raise HTTPException(
            status_code=409,
            detail="That revision is closed — start a new revision to add files.",
        )

    attachment_uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage_path = os.path.join(ATTACHMENTS_DIR, attachment_uid)
    contents = await file.read()
    with open(storage_path, "wb") as f:
        f.write(contents)

    attachment = Attachment(
        uid=attachment_uid,
        workspace_id=workspace_id,
        document_revision_uid=rev_uid,
        filename=file.filename or attachment_uid,
        mime_type=file.content_type,
        file_size=len(contents),
        author=_actor_user_id(identity),
        storage_path=storage_path,
    )
    db.add(attachment)

    # A drawing gets viewable sheets alongside it, because nothing renders
    # DWG in a browser and the browser DXF renderers do not draw paper
    # space. The original stays exactly as uploaded and stays the file
    # people download; if this fails the upload still succeeds, since a
    # drawing with no preview beats no drawing.
    if needs_conversion(attachment.filename) or suffix_of(attachment.filename) == ".dxf":
        dxf, error = (
            dwg_to_dxf(contents) if needs_conversion(attachment.filename) else (contents, None)
        )
        sheets, render_error = render_sheets(dxf) if dxf else ([], None)
        for sheet_name, svg in sheets:
            sheet_uid = str(uuid.uuid4())
            sheet_path = os.path.join(ATTACHMENTS_DIR, sheet_uid)
            with open(sheet_path, "wb") as f:
                f.write(svg)
            db.add(Attachment(
                uid=sheet_uid,
                workspace_id=workspace_id,
                document_revision_uid=rev_uid,
                filename=sheet_filename(attachment.filename, sheet_name),
                mime_type="image/svg+xml",
                file_size=len(svg),
                author=_actor_user_id(identity),
                storage_path=sheet_path,
                backend_id=sheet_marker(attachment.uid),
            ))
        if not sheets:
            # Recorded on the attachment itself so the page can say why
            # there is no preview instead of silently offering none.
            attachment.backend_url = f"preview-failed: {error or render_error}"

    db.commit()
    db.refresh(attachment)
    return attachment


# --------------------------------------------------------------------------- control (§19 item 4)

@router.get("/{uid}/retention")
def get_retention(uid: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                  identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    doc = _get_visible_document(uid, workspace_id, identity, db)
    return document_control.retention_view(db, doc)


class RetentionIn(BaseModel):
    retention_class: str


@router.put("/{uid}/retention")
def set_retention(uid: str, body: RetentionIn,
                  workspace_id: str = Depends(require_permission("approve", resource="documents")),
                  db: Session = Depends(get_db)):
    doc = _get_owned_document(uid, workspace_id, db)
    try:
        document_control.set_retention(db, doc, body.retention_class)
    except document_control.ControlError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "retention"})
    db.commit()
    return document_control.retention_view(db, doc)


class SupersedeIn(BaseModel):
    by_document_uid: str
    reason: str


@router.post("/{uid}/supersede", response_model=DocumentOut)
def supersede_document(uid: str, body: SupersedeIn,
                       workspace_id: str = Depends(require_permission("approve", resource="documents")),
                       db: Session = Depends(get_db)):
    """`by_document_uid` replaces this document, which retires and points to it."""
    old = _get_owned_document(uid, workspace_id, db)
    new = _get_owned_document(body.by_document_uid, workspace_id, db)
    try:
        document_control.supersede(db, old, new, body.reason)
    except document_control.ControlError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "supersession"})
    db.commit()
    db.refresh(old)
    return old
