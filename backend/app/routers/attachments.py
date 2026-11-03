import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.models.asset import Asset
from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentOut

router = APIRouter(prefix="/v1/attachments", tags=["attachments"])

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _get_owned_attachment(uid: str, workspace_id: str, db: Session) -> Attachment:
    attachment = db.get(Attachment, uid)
    if attachment is None or attachment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


def _get_readable_attachment(uid: str, workspace_id: str, db: Session) -> Attachment:
    """A file this workspace may read: its own, or one belonging to a record shared with every workspace — a
    global document's revision (never one marked riservato) or global equipment. A shared procedure whose
    pictures and files only its own workspace could open would be shared in name only."""
    attachment = db.get(Attachment, uid)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if attachment.workspace_id == workspace_id:
        return attachment
    from app.models.document import Document, DocumentRevision
    from app.services.visibility import asset_visible_in
    if attachment.document_revision_uid:
        revision = db.get(DocumentRevision, attachment.document_revision_uid)
        doc = db.get(Document, revision.document_uid) if revision else None
        if doc is not None and doc.is_global and doc.confidentiality != "riservato":
            return attachment
    if attachment.asset_uid:
        asset = db.get(Asset, attachment.asset_uid)
        if asset is not None and asset_visible_in(asset, workspace_id):
            return attachment
    raise HTTPException(status_code=404, detail="Attachment not found")


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    asset_uid: str,
    file: UploadFile,
    workspace_id: str = Depends(require_permission("create")),
    db: Session = Depends(get_db),
):
    asset = db.get(Asset, asset_uid)
    if asset is None or asset.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage_path = os.path.join(ATTACHMENTS_DIR, uid)
    contents = await file.read()
    with open(storage_path, "wb") as f:
        f.write(contents)

    attachment = Attachment(
        uid=uid,
        workspace_id=workspace_id,
        asset_uid=asset_uid,
        filename=file.filename or uid,
        mime_type=file.content_type,
        file_size=len(contents),
        storage_path=storage_path,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{uid}")
def download_attachment(
    uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    attachment = _get_readable_attachment(uid, workspace_id, db)
    return FileResponse(
        attachment.storage_path,
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.filename,
    )


@router.get("/{uid}/about")
def about_attachment(uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """What a link to an attachment opens (issue #18): its name, kind and size, and the workspace to read it in —
    its own, for a person who may read there, whatever workspace they are working in now. Not found otherwise,
    as for a file that does not exist."""
    from app.auth import PatIdentity
    from app.services.permissions import resolve_permission
    attachment = db.get(Attachment, uid)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if isinstance(identity, PatIdentity) or (identity.token is not None and identity.token.workspace_id):
        ws = identity.workspace_id if isinstance(identity, PatIdentity) else identity.token.workspace_id
        _get_readable_attachment(uid, ws, db)
        where = ws
    elif resolve_permission(db, identity.user, attachment.workspace_id, "read", "objects"):
        where = attachment.workspace_id
    else:
        raise HTTPException(status_code=404, detail="Attachment not found")
    document_uid = None
    if attachment.document_revision_uid:
        from app.models.document import DocumentRevision
        revision = db.get(DocumentRevision, attachment.document_revision_uid)
        document_uid = revision.document_uid if revision else None
    return {"uid": attachment.uid, "filename": attachment.filename, "mime_type": attachment.mime_type,
            "size_bytes": attachment.file_size, "workspace_id": where,
            "asset_uid": attachment.asset_uid, "document_uid": document_uid}


@router.get("/{uid}/verify")
def verify_attachment(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Whether the stored file still has the checksum recorded when it arrived."""
    from app.models.attachment import file_sha256
    attachment = _get_readable_attachment(uid, workspace_id, db)
    now = file_sha256(attachment.storage_path)
    return {"uid": uid, "recorded": attachment.sha256, "actual": now,
            "ok": now is not None and now == attachment.sha256, "missing": now is None}


@router.delete("/{uid}", status_code=204)
def delete_attachment(
    uid: str, workspace_id: str = Depends(require_permission("delete")), db: Session = Depends(get_db)
):
    attachment = _get_owned_attachment(uid, workspace_id, db)
    if os.path.exists(attachment.storage_path):
        os.remove(attachment.storage_path)
    db.delete(attachment)
    db.commit()


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    asset_uid: str | None = None,
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    stmt = select(Attachment).where(Attachment.workspace_id == workspace_id)
    if asset_uid:
        stmt = stmt.where(Attachment.asset_uid == asset_uid)
    return db.scalars(stmt).all()
