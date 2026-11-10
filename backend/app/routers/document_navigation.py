"""Document browser: visible metadata, lazy revision preview and folder placement."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.auth import Identity, get_identity, require_permission
from app.db import get_db
from app.models.document import Document, DocumentRevision
from app.models.document_navigation import DocumentFolder, DocumentPlacement
from app.routers.documents import _get_visible_document
from app.schemas.document import DocumentOut, DocumentRevisionOut
from app.services import document_navigation as nav

router = APIRouter(prefix="/v1/document-navigation", tags=["document-navigation"])


class FolderInput(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    parent_uid: str | None = None


class LocationInput(BaseModel):
    folder_uid: str | None = None
    parent_document_uid: str | None = None


def visible(db, workspace_id, identity):
    candidates = db.scalars(select(Document).where(or_(
        Document.workspace_id == workspace_id,
        and_(Document.is_global.is_(True), Document.confidentiality != "riservato"),
    ))).all()
    result = []
    for candidate in candidates:
        try:
            result.append(_get_visible_document(candidate.uid, workspace_id, identity, db))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    return result


def owned_visible(uid, workspace_id, identity, db):
    doc = _get_visible_document(uid, workspace_id, identity, db)
    if doc.workspace_id != workspace_id:
        raise HTTPException(404, "Document not found in this workspace")
    return doc


@router.get("")
def snapshot(workspace_id=Depends(require_permission("read", resource="documents")),
             identity: Identity = Depends(get_identity), db=Depends(get_db)):
    docs = [DocumentOut.model_validate(d).model_dump(mode="json") for d in visible(db, workspace_id, identity)]
    folders, nodes, warnings = nav.graph(db, workspace_id, docs)
    return {"documents": docs, "folders": [nav.folder_dict(f) for f in folders], "nodes": nodes, "warnings": warnings}


@router.get("/documents/{uid}/preview")
def preview(uid: str, revision_uid: str | None = None,
            workspace_id=Depends(require_permission("read", resource="documents")),
            identity: Identity = Depends(get_identity), db=Depends(get_db)):
    doc = _get_visible_document(uid, workspace_id, identity, db)
    stmt = select(DocumentRevision.uid, DocumentRevision.revision_number, DocumentRevision.state).where(DocumentRevision.document_uid == uid)
    # Shared documents expose their published revision in this browser, never a foreign draft.
    if doc.workspace_id != workspace_id:
        stmt = stmt.where(DocumentRevision.uid == doc.current_revision_uid, DocumentRevision.state == "published")
    revisions = db.execute(stmt.order_by(DocumentRevision.revision_number.desc())).all()
    selected = next((r for r in revisions if r.uid == revision_uid), None) if revision_uid else (
        next((r for r in revisions if r.state in ("draft", "in_review", "approved")), None)
        or next((r for r in revisions if r.uid == doc.current_revision_uid), None)
        or next(iter(revisions), None))
    if revision_uid and selected is None:
        raise HTTPException(404, "Revision not found")
    selected_revision = db.get(DocumentRevision, selected.uid) if selected else None
    return {"document": DocumentOut.model_validate(doc).model_dump(mode="json"),
            "revision": DocumentRevisionOut.model_validate(selected_revision).model_dump(mode="json") if selected_revision else None,
            "revisions": [{"uid": r.uid, "revision_number": r.revision_number, "state": r.state} for r in revisions]}


@router.post("/folders", status_code=201)
def create_folder(body: FolderInput, workspace_id=Depends(require_permission("create", resource="documents")),
                  db=Depends(get_db)):
    try:
        nav.lock_workspace(db, workspace_id)
        folder = DocumentFolder(uid=str(uuid.uuid4()), workspace_id=workspace_id)
        nav.write_folder(db, workspace_id, folder, body.name, body.parent_uid)
        db.commit()
        return nav.folder_dict(folder)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.put("/folders/{uid}")
def update_folder(uid: str, body: FolderInput,
                  workspace_id=Depends(require_permission("modify", resource="documents")), db=Depends(get_db)):
    try:
        nav.lock_workspace(db, workspace_id)
        folder = nav.owned_folder(db, workspace_id, uid)
        nav.write_folder(db, workspace_id, folder, body.name, body.parent_uid)
        db.commit()
        return nav.folder_dict(folder)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.delete("/folders/{uid}", status_code=204)
def delete_folder(uid: str, workspace_id=Depends(require_permission("delete", resource="documents")), db=Depends(get_db)):
    try:
        nav.lock_workspace(db, workspace_id)
        folder = nav.owned_folder(db, workspace_id, uid)
        if (db.scalar(select(DocumentFolder.uid).where(DocumentFolder.parent_uid == uid).limit(1))
                or db.scalar(select(DocumentPlacement.document_uid).join(Document, Document.uid == DocumentPlacement.document_uid)
                             .where(DocumentPlacement.folder_uid == uid, Document.workspace_id == workspace_id).limit(1))):
            raise HTTPException(409, "The folder is not empty. Move its contents before deleting it.")
        db.delete(folder)
        db.commit()
        return Response(status_code=204)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.put("/documents/{uid}/location")
def set_location(uid: str, body: LocationInput,
                 workspace_id=Depends(require_permission("modify", resource="documents")),
                 identity: Identity = Depends(get_identity), db=Depends(get_db)):
    owned_visible(uid, workspace_id, identity, db)
    if body.parent_document_uid:
        owned_visible(body.parent_document_uid, workspace_id, identity, db)
    try:
        nav.lock_workspace(db, workspace_id)
        nav.set_document_location(db, workspace_id, uid, body.folder_uid, body.parent_document_uid)
        db.commit()
        return {"ok": True}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.delete("/documents/{uid}/location", status_code=204)
def reset_location(uid: str, workspace_id=Depends(require_permission("modify", resource="documents")),
                   identity: Identity = Depends(get_identity), db=Depends(get_db)):
    owned_visible(uid, workspace_id, identity, db)
    nav.lock_workspace(db, workspace_id)
    placement = db.get(DocumentPlacement, uid)
    if placement is not None:
        if placement.workspace_id != workspace_id:
            raise HTTPException(404, "Placement not found")
        db.delete(placement)
    db.commit()
    return Response(status_code=204)
