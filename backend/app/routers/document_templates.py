"""Document templates and "Rework from raw text" (services/doc_templates.py, template_store.py, reshape.py).

- `/v1/document-templates`: the official templates, the workspace's variants and your personal copies; make,
  edit, check, publish (a new immutable version each time), make the default, compare with the official base.
- `POST /v1/ai/reshape`: a preview — the draft, what is missing or uncertain, the dates, the suggested links —
  that saves nothing.
- `POST /v1/documents/reshape` (a new document) and `POST /v1/documents/{uid}/reshape` (its next revision):
  save the edited draft as a **draft** revision through the documents' own code, with the raw text kept as a
  file of that revision and how it was made (template and exact version, dates, extraction) recorded. Review,
  approval and publication are the documents' usual steps; nothing here approves or publishes.

`/v1/ai/draft-document` (a free draft from a title and notes) and `/v1/ai/review-document` (remarks on a
draft) are unchanged and independent: the reworked draft can be reviewed with the latter like any other.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation
from app.models.document_template import DocumentGeneration
from app.models.schema import Schema
from app.services import doc_templates as dt
from app.services import reshape, template_store
from app.services.template_store import StoreError

router = APIRouter(prefix="/v1/document-templates", tags=["document templates"])
ai_router = APIRouter(prefix="/v1/ai", tags=["ai"])
documents_router = APIRouter(prefix="/v1/documents", tags=["documents"])

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _user_id(identity: Identity) -> Optional[str]:
    return identity.user.id if isinstance(identity, OidcIdentity) else None


def _fail(e: StoreError):
    raise HTTPException(status_code=e.status, detail={"error": str(e), "problems": e.problems} if e.problems
                        else str(e))


def _may(db: Session, identity: Identity, workspace_id: str, action: str) -> bool:
    from app.auth import PatIdentity
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        return identity.may(action, "documents")
    if identity.token is not None and not identity.token.may(action, "documents"):
        return False
    return resolve_permission(db, identity.user, workspace_id, action, "documents")


def _may_edit(db: Session, identity: Identity, workspace_id: str, row) -> None:
    """A workspace variant: those who may approve documents. A personal copy: its owner."""
    if row.scope == "personal":
        if row.owner_user_id != _user_id(identity):
            raise HTTPException(status_code=404, detail="No such template here")
    elif not _may(db, identity, workspace_id, "approve"):
        raise HTTPException(status_code=403, detail="Changing the workspace's templates needs the right to approve "
                                                    "documents")


# --------------------------------------------------------------------------- templates

class TemplateCreate(BaseModel):
    base: str = Field(description="official:<id>, or a variant's uid to copy")
    scope: Literal["workspace", "personal"]
    name: Optional[str] = None


class TemplateSource(BaseModel):
    source: str = Field(max_length=dt.MAX_SOURCE)


class TemplatePublish(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class TemplateActive(BaseModel):
    active: bool


def _row_view(db: Session, row) -> dict:
    base = dt.official_by_id(row.base_template_id)
    _, problems = dt.parse(row.draft_source)
    return {"ref": row.uid, "scope": row.scope, "name": row.name, "document_type": row.document_type,
            "base": {"id": row.base_template_id, "version": row.base_version},
            "official_update": base.version if base and base.version > row.base_version else None,
            "latest_version": row.latest_version, "active": row.active, "draft_source": row.draft_source,
            "draft_problems": [p.view() for p in problems],
            "versions": [{"version": v.version, "note": v.note, "created_at": v.created_at, "created_by": v.created_by}
                         for v in db.scalars(select(template_store.DocumentTemplateVersion).where(
                             template_store.DocumentTemplateVersion.template_uid == row.uid)
                             .order_by(template_store.DocumentTemplateVersion.version))],
            "owner_user_id": row.owner_user_id, "updated_at": row.updated_at}


@router.get("")
def list_templates(document_type: Optional[str] = None,
                   workspace_id: str = Depends(require_permission("read", resource="documents")),
                   identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The templates you may use here: official, the workspace's variants, your personal copies."""
    return template_store.listing(db, workspace_id, _user_id(identity), document_type)


@router.get("/resolve")
def resolve_template(document_type: str, template: Optional[str] = None,
                     workspace_id: str = Depends(require_permission("read", resource="documents")),
                     identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Which template applies for a document type, and why — before anything is generated."""
    try:
        chosen = template_store.resolve(db, workspace_id, _user_id(identity), document_type, template)
    except StoreError as e:
        _fail(e)
    return {**chosen.view(), "template": chosen.template.describe()}


@router.post("/validate")
def validate_template(body: TemplateSource, _ws: str = Depends(require_permission("read", resource="documents"))):
    """What is wrong with a template's text, line by line (nothing saved)."""
    t, problems = dt.parse(body.source)
    return {"valid": t is not None, "problems": [p.view() for p in problems],
            "template": t.describe() if t else None}


@router.get("/{ref}")
def get_template(ref: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                 identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """An official template (read-only) or a variant with its draft, versions and origin."""
    if ref.startswith("official:"):
        t = dt.official_by_id(ref.split(":", 1)[1])
        if t is None:
            raise HTTPException(status_code=404, detail="No such official template")
        return {"ref": ref, "scope": "official", "name": t.title, "document_type": t.document_type,
                "latest_version": t.version, "source": t.source, "template": t.describe()}
    try:
        return _row_view(db, template_store.variant(db, workspace_id, _user_id(identity), ref))
    except StoreError as e:
        _fail(e)


@router.get("/{ref}/versions/{version}")
def get_template_version(ref: str, version: int,
                         workspace_id: str = Depends(require_permission("read", resource="documents")),
                         identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """One published version's exact text."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        v = template_store.version_row(db, row, version)
    except StoreError as e:
        _fail(e)
    return {"ref": ref, "version": v.version, "source": v.source, "sha256": v.sha256, "note": v.note,
            "created_at": v.created_at, "created_by": v.created_by}


@router.post("", status_code=201)
def create_template(body: TemplateCreate, workspace_id: str = Depends(require_permission("read", resource="documents")),
                    identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A workspace variant (needs the right to approve documents) or a personal copy (the right to create them)."""
    user = _user_id(identity)
    if body.scope == "personal":
        if user is None or not _may(db, identity, workspace_id, "create"):
            raise HTTPException(status_code=403, detail="A personal copy needs a person who may create documents")
    elif not _may(db, identity, workspace_id, "approve"):
        raise HTTPException(status_code=403, detail="A workspace variant needs the right to approve documents")
    try:
        row = template_store.create(db, workspace_id, user, base_ref=body.base, scope=body.scope, name=body.name)
    except StoreError as e:
        _fail(e)
    db.commit()
    return _row_view(db, row)


@router.put("/{ref}")
def save_template(ref: str, body: TemplateSource,
                  workspace_id: str = Depends(require_permission("read", resource="documents")),
                  identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Keep the edited draft; the answer lists what is wrong with it. Published versions are untouched."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        _may_edit(db, identity, workspace_id, row)
        template_store.save_draft(row, body.source)
    except StoreError as e:
        _fail(e)
    db.commit()
    return _row_view(db, row)


@router.post("/{ref}/publish")
def publish_template(ref: str, body: TemplatePublish,
                     workspace_id: str = Depends(require_permission("read", resource="documents")),
                     identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The draft as a new, immutable version."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        _may_edit(db, identity, workspace_id, row)
        template_store.publish(db, row, _user_id(identity), body.note)
    except StoreError as e:
        _fail(e)
    db.commit()
    return _row_view(db, row)


@router.put("/{ref}/active")
def set_template_active(ref: str, body: TemplateActive,
                        workspace_id: str = Depends(require_permission("read", resource="documents")),
                        identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Use it by default for its document type: in the workspace (a variant) or for you (a personal copy)."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        _may_edit(db, identity, workspace_id, row)
        template_store.activate(db, row, body.active)
    except StoreError as e:
        _fail(e)
    db.commit()
    return _row_view(db, row)


@router.get("/{ref}/compare")
def compare_template(ref: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                     identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The variant against its official base, and what changed in the official template since."""
    try:
        return template_store.compare(db, template_store.variant(db, workspace_id, _user_id(identity), ref))
    except StoreError as e:
        _fail(e)


@router.post("/{ref}/rebase")
def rebase_template(ref: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                    identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Say the variant now follows the newest official version (its text is not replaced)."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        _may_edit(db, identity, workspace_id, row)
        template_store.rebase(db, row)
    except StoreError as e:
        _fail(e)
    db.commit()
    return _row_view(db, row)


@router.delete("/{ref}", status_code=204)
def archive_template(ref: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                     identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Stop offering it; its versions stay, for the documents made with them."""
    try:
        row = template_store.variant(db, workspace_id, _user_id(identity), ref)
        _may_edit(db, identity, workspace_id, row)
    except StoreError as e:
        _fail(e)
    row.archived, row.active = True, False
    db.commit()


# --------------------------------------------------------------------------- rework from raw text

class SourceIn(BaseModel):
    text: str = Field(max_length=reshape.MAX_SOURCE_CHARS)
    kind: Literal["paste", "email", "intake", "import"] = "paste"
    original_date: Optional[str] = Field(default=None, max_length=60)
    sender: Optional[str] = Field(default=None, max_length=300)
    subject: Optional[str] = Field(default=None, max_length=300)
    text_is_current: bool = False
    filename: Optional[str] = Field(default=None, max_length=200)


class ReshapeIn(BaseModel):
    source: SourceIn
    document_type_uid: str
    template: Optional[str] = Field(default=None, description="official:<id>, a variant's uid or uid@version")
    # A template's text being edited, tried on the source before it is published (its editor's test).
    template_source: Optional[str] = Field(default=None, max_length=dt.MAX_SOURCE)
    title: Optional[str] = Field(default=None, max_length=300)
    confidentiality: Literal["pubblico", "interno", "riservato"] = "interno"
    document_uid: Optional[str] = Field(default=None, description="reworking into a new revision of this one")


def _type_name(db: Session, workspace_id: str, type_uid: str) -> str:
    schema = db.get(Schema, type_uid)
    if schema is None or schema.applies_to != "documents" or schema.workspace_id != workspace_id:
        raise HTTPException(status_code=422, detail="Unknown document type in this workspace")
    return schema.name


def _document_types(db: Session, workspace_id: str) -> list[str]:
    return sorted(db.scalars(select(Schema.name).where(Schema.workspace_id == workspace_id,
                                                       Schema.applies_to == "documents",
                                                       Schema.is_concrete.is_not(False))))


def _meta(s: SourceIn) -> reshape.SourceMeta:
    return reshape.SourceMeta(kind=s.kind, original_date=s.original_date, sender=s.sender, subject=s.subject,
                              text_is_current=s.text_is_current)


def _links(db: Session, identity: Identity, workspace_id: str, text: str) -> list[dict]:
    """Records the text names, offered as links; none is made."""
    import re
    from app.models.issue import Issue
    from app.services.text_links import objects_mentioned
    out = [{"kind": "asset", "uid": a["uid"], "label": f"{a['key']} — {a['name']}", "matched_on": a["matched_on"]}
           for a in objects_mentioned(db, workspace_id, text)[:20]]
    tokens = {t.upper() for t in re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_:][A-Za-z0-9]+)+\b", text)}
    if tokens:
        for d in db.scalars(select(Document).where(Document.workspace_id == workspace_id,
                                                   Document.code.in_(tokens)).limit(20)):
            if d.confidentiality != "riservato":
                out.append({"kind": "document", "uid": d.uid, "label": f"{d.code} — {d.title}", "matched_on": "code"})
        if _may_tickets(db, identity, workspace_id):
            for i in db.scalars(select(Issue).where(Issue.workspace_id == workspace_id, Issue.deleted_at.is_(None),
                                                    Issue.attributes["argus_source_key"].astext.in_(tokens)).limit(20)):
                out.append({"kind": "ticket", "uid": i.uid,
                            "label": f"{i.attributes.get('argus_source_key')} — {i.title}", "matched_on": "key"})
    return out


def _may_tickets(db: Session, identity: Identity, workspace_id: str) -> bool:
    from app.auth import PatIdentity
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        return identity.may("read", "tickets")
    return resolve_permission(db, identity.user, workspace_id, "read", "tickets")


def _ai(db: Session, workspace_id: str, confidentiality: str):
    from app.routers.ai import _usable_config, endpoint_for
    config = _usable_config(db, workspace_id)
    if confidentiality == "riservato" and not config.allow_confidential:
        raise HTTPException(status_code=409, detail="This workspace's AI settings do not allow sending confidential "
                                                    "(riservato) material to the model")
    return config, endpoint_for(config)


def _template_for(db: Session, workspace_id: str, identity: Identity, body: ReshapeIn, type_name: str):
    if body.template_source:
        t, problems = dt.parse(body.template_source)
        if t is None:
            raise HTTPException(status_code=422, detail={"error": "The template has errors",
                                                          "problems": [p.view() for p in problems]})
        if t.document_type != type_name:
            raise HTTPException(status_code=422, detail=f"This template is for {t.document_type}, not {type_name}")
        return template_store.Chosen(t, "draft", "draft", None, "the template being edited")
    try:
        return template_store.resolve(db, workspace_id, _user_id(identity), type_name, body.template)
    except StoreError as e:
        _fail(e)


@ai_router.post("/reshape")
def reshape_preview(body: ReshapeIn,
                    workspace_id: str = Depends(require_permission("create", resource="documents")),
                    identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The draft a template makes of the raw text, with what is missing or uncertain, the dates and the suggested
    links. Nothing is saved: no document, no revision, no file."""
    if body.document_uid:
        from app.routers.documents import _check_confidentiality, _get_owned_document
        doc = _get_owned_document(body.document_uid, workspace_id, db)
        _check_confidentiality(doc, workspace_id, identity, db)
        if doc.confidentiality == "riservato":
            body.confidentiality = "riservato"
    type_name = _type_name(db, workspace_id, body.document_type_uid)
    config, endpoint = _ai(db, workspace_id, body.confidentiality)
    chosen = _template_for(db, workspace_id, identity, body, type_name)
    try:
        out = reshape.preview(endpoint, chosen.template, body.source.text, _meta(body.source),
                              document_types=_document_types(db, workspace_id), title=body.title)
    except reshape.ReshapeError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    db.rollback()                                   # whatever was looked up, nothing is kept
    return {**out, "template": chosen.view(), "model": config.model,
            "links": _links(db, identity, workspace_id, body.source.text)}


class ReshapeSave(BaseModel):
    source: SourceIn
    document_type_uid: str
    template: str = Field(description="the template the preview used: official:<id>, uid or uid@version")
    title: str = Field(min_length=1, max_length=300)
    code: Optional[str] = None
    markdown: str = Field(min_length=1, max_length=500_000)
    confidentiality: Literal["pubblico", "interno", "riservato"] = "interno"
    authority_level: Literal["ufficiale", "informativo", "bozza_interna"] = "bozza_interna"
    # From the preview, as the person settled them: kept in the record of how it was made.
    dates: dict = Field(default_factory=dict)
    extraction: dict = Field(default_factory=dict)
    issues: list = Field(default_factory=list)
    model: Optional[str] = None
    # The date of entry proposed for the document, confirmed by the person (required when it was proposed).
    confirm_document_date: bool = False
    # Links to make, chosen among the suggested ones.
    link_assets: list[str] = Field(default_factory=list, max_length=50)


def _template_version(db: Session, workspace_id: str, identity: Identity, ref: str, type_name: str):
    try:
        chosen = template_store.get(db, workspace_id, _user_id(identity), ref)
    except StoreError as e:
        _fail(e)
    if chosen.template.document_type != type_name:
        raise HTTPException(status_code=422, detail="The template is for another document type")
    if chosen.scope == "official":
        chosen.version_uid = template_store.snapshot_official(db, chosen.template, _user_id(identity)).uid
    return chosen


def _save(db: Session, workspace_id: str, identity: Identity, body: ReshapeSave, document_uid: Optional[str]):
    from app.routers.documents import new_document, new_revision
    from app.schemas.document import DocumentCreate, DocumentRevisionCreate
    type_name = _type_name(db, workspace_id, body.document_type_uid)
    chosen = _template_version(db, workspace_id, identity, body.template, type_name)
    dates = dict(body.dates or {})
    if dates.get("document_date_needs_confirmation") and not body.confirm_document_date:
        raise HTTPException(status_code=422, detail="The document's date was proposed from the date of entry: "
                                                    "confirm it, or give the original date")
    dates["document_date_confirmed"] = bool(body.confirm_document_date) if dates.get(
        "document_date_needs_confirmation") else None
    dates["inserted_at"] = dates.get("inserted_at") or datetime.now(timezone.utc).isoformat()
    attributes = {}
    if document_uid is None:
        doc_body = DocumentCreate(uid=str(uuid.uuid4()), code=body.code, title=body.title.strip(),
                                  document_type_uid=body.document_type_uid, owner_user_id=_user_id(identity),
                                  confidentiality=body.confidentiality, authority_level=body.authority_level,
                                  source="manual", body_markdown=body.markdown, attributes=attributes)
        doc, revision = new_document(db, doc_body, workspace_id, identity)
    else:
        doc = db.get(Document, document_uid)
        if doc is None or doc.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.document_type_uid != body.document_type_uid:
            raise HTTPException(status_code=422, detail="The document is of another type")
        revision = new_revision(db, document_uid, DocumentRevisionCreate(body_markdown=body.markdown,
                                                                         attributes=attributes), workspace_id, identity)
    if doc.confidentiality == "riservato" or body.confidentiality == "riservato":
        _ai(db, workspace_id, "riservato")         # the preview was refused if this would be; so is the save

    # The raw text, kept as a file of this revision: the same access as the document itself.
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    attachment_uid = str(uuid.uuid4())
    path = os.path.join(ATTACHMENTS_DIR, attachment_uid)
    data = body.source.text.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    stem = (body.source.filename or f"source-{body.source.kind}").rsplit(".", 1)[0][:100]
    db.add(Attachment(uid=attachment_uid, workspace_id=workspace_id, document_revision_uid=revision.uid,
                      filename=f"{stem}.txt", mime_type="text/plain; charset=utf-8", file_size=len(data),
                      author=_user_id(identity), storage_path=path))
    for asset_uid in dict.fromkeys(body.link_assets):
        from app.models.asset import Asset
        asset = db.get(Asset, asset_uid)
        if asset is not None and asset.workspace_id == workspace_id:
            exists = db.scalar(select(DocumentRelation).where(DocumentRelation.from_document_uid == doc.uid,
                                                              DocumentRelation.to_uid == asset_uid))
            if exists is None:
                db.add(DocumentRelation(workspace_id=workspace_id, from_document_uid=doc.uid, to_type="asset",
                                        to_uid=asset_uid, relation_type="about"))
    gen = DocumentGeneration(
        uid=str(uuid.uuid4()), workspace_id=workspace_id, document_uid=doc.uid, revision_uid=revision.uid,
        template_version_uid=chosen.version_uid, template_id=chosen.template.id,
        template_version=chosen.template.version, template_scope=chosen.scope,
        source_attachment_uid=attachment_uid, source_kind=body.source.kind,
        source_metadata={k: v for k, v in body.source.model_dump().items() if k != "text"},
        dates=dates, extraction=body.extraction or {}, issues=body.issues or [], model=body.model,
        created_by=_user_id(identity))
    db.add(gen)
    db.commit()
    return {"document_uid": doc.uid, "code": doc.code, "revision_uid": revision.uid,
            "revision_number": revision.revision_number, "state": revision.state, "generation": generation_view(gen)}


def generation_view(g: DocumentGeneration) -> dict:
    return {"uid": g.uid, "revision_uid": g.revision_uid, "template": {"id": g.template_id, "version": g.template_version, "scope": g.template_scope,
                                       "version_uid": g.template_version_uid},
            "source": {"kind": g.source_kind, "attachment_uid": g.source_attachment_uid, **(g.source_metadata or {})},
            "dates": g.dates, "issues": g.issues, "model": g.model, "created_at": g.created_at,
            "created_by": g.created_by}


@documents_router.post("/reshape", status_code=201)
def reshape_save_new(body: ReshapeSave,
                     workspace_id: str = Depends(require_permission("create", resource="documents")),
                     identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Save the reworked draft as a new document, at revision 1, in draft."""
    return _save(db, workspace_id, identity, body, None)


@documents_router.post("/{uid}/reshape", status_code=201)
def reshape_save_revision(uid: str, body: ReshapeSave,
                          workspace_id: str = Depends(require_permission("modify", resource="documents")),
                          identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Save the reworked draft as the document's next revision, in draft."""
    return _save(db, workspace_id, identity, body, uid)


@documents_router.get("/{uid}/generations")
def document_generations(uid: str, workspace_id: str = Depends(require_permission("read", resource="documents")),
                         identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """How the document's revisions were made from raw text, if any were."""
    from app.routers.documents import _get_visible_document
    doc = _get_visible_document(uid, workspace_id, identity, db)
    return [generation_view(g) for g in db.scalars(select(DocumentGeneration).where(
        DocumentGeneration.document_uid == doc.uid).order_by(DocumentGeneration.created_at))]
