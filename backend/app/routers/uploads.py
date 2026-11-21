"""Resumable uploads (flutter-app-design §5.5, revision §24.3 item 7).

1. `POST /v1/uploads` with the file name, type, size and SHA-256. Anything over the limit for its
   type, or of a type not accepted, is refused here, before a byte is sent (413 `too_large` with
   the limit, or 422).
2. `PUT /v1/uploads/{uid}?offset=N` with the next piece as the raw body. A piece is accepted only
   at the current offset; `GET /v1/uploads/{uid}` says where to resume.
3. `POST /v1/uploads/{uid}/complete`: the server checks the size and recomputes the SHA-256. A
   mismatch discards the bytes, so the client starts again. Location metadata (EXIF GPS) is
   removed from images.
4. `POST /v1/uploads/{uid}/attach/ticket/{issue_uid}`, `.../attach/asset/{asset_uid}` or
   `.../attach/document/{doc_uid}/revision/{rev_uid}` makes it an attachment of the record. A photo,
   a video, a recorded note, or a place (`application/geo+json`, where the person was when they sent it).

The limits are decision U23. Until it is taken, they are set per environment:
- `ARGUS_UPLOAD_MAX_IMAGE`, 25 MB by default;
- `ARGUS_UPLOAD_MAX_VIDEO`, 200 MB by default;
- `ARGUS_UPLOAD_MAX_AUDIO`, 100 MB by default (a recorded note);
- `ARGUS_UPLOAD_MAX_OTHER`, 50 MB by default;
- `ARGUS_UPLOAD_TYPES`, the accepted types.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user_id, get_identity, require_permission
from app.db import get_db
from app.models.device import Upload

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])

MB = 1024 * 1024
CHUNK = 8 * MB
DEFAULT_TYPES = ("image/jpeg,image/png,image/heic,image/heif,image/webp,video/mp4,video/quicktime,video/3gpp,"
                 "audio/mp4,audio/m4a,audio/x-m4a,audio/aac,audio/mpeg,audio/ogg,audio/webm,audio/wav,"
                 "application/geo+json,application/pdf,text/plain,text/csv")


def _limit(content_type: str) -> int:
    kind = content_type.split("/", 1)[0]
    env, default = {"image": ("ARGUS_UPLOAD_MAX_IMAGE", 25 * MB),
                    "video": ("ARGUS_UPLOAD_MAX_VIDEO", 200 * MB),
                    "audio": ("ARGUS_UPLOAD_MAX_AUDIO", 100 * MB)}.get(kind, ("ARGUS_UPLOAD_MAX_OTHER", 50 * MB))
    return int(os.environ.get(env, default))


def _accepted() -> set[str]:
    return {t.strip().lower() for t in os.environ.get("ARGUS_UPLOAD_TYPES", DEFAULT_TYPES).split(",") if t.strip()}


def _dir() -> str:
    from app.routers.issues import ATTACHMENTS_DIR
    path = os.path.join(ATTACHMENTS_DIR, ".uploads")
    os.makedirs(path, exist_ok=True)
    return path


def _principal(identity) -> str:
    from app.routers.field import principal_of
    return principal_of(identity)


def _view(u: Upload) -> dict:
    return {"uid": u.uid, "filename": u.filename, "content_type": u.content_type, "size": u.size,
            "sha256": u.sha256, "offset": u.received, "state": u.state, "chunk_size": CHUNK,
            "limit": _limit(u.content_type), "gps_removed": u.gps_removed, "attachment_uid": u.attachment_uid,
            "expires_at": u.expires_at}


def _own(db: Session, uid: str, identity, workspace_id: str) -> Upload:
    u = db.get(Upload, uid)
    if u is None or u.workspace_id != workspace_id or u.principal != _principal(identity):
        raise HTTPException(status_code=404, detail={"error": "No such upload.", "code": "not_found"})
    return u


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


@router.post("", status_code=201)
def create_upload(body: UploadIn, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    ctype = body.content_type.split(";")[0].strip().lower()
    if ctype not in _accepted():
        raise HTTPException(status_code=422, detail={
            "error": f"Files of type {ctype} are not accepted.", "code": "invalid", "field": "content_type"})
    limit = _limit(ctype)
    if body.size > limit:
        raise HTTPException(status_code=413, detail={
            "error": f"The file is {body.size // MB} MB; the limit for this type is {limit // MB} MB.",
            "code": "too_large", "limit": limit, "field": "size"})
    from app.services import quotas
    quotas.check_file(db, workspace_id, body.size)
    from app import idempotency
    uid = str(uuid.uuid4())
    u = Upload(uid=uid, workspace_id=workspace_id, principal=_principal(identity),
               filename=os.path.basename(body.filename), content_type=ctype, size=body.size,
               sha256=body.sha256.lower(), received=0, state="open",
               storage_path=os.path.join(_dir(), uid),
               expires_at=datetime.now(timezone.utc) + idempotency.retention())
    open(u.storage_path, "wb").close()
    db.add(u)
    db.commit()
    return _view(u)


@router.get("/{uid}")
def upload_status(uid: str, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    return _view(_own(db, uid, identity, workspace_id))


@router.put("/{uid}", openapi_extra={"requestBody": {"required": True, "content": {
    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
async def upload_piece(uid: str, request: Request, offset: int = Query(..., ge=0), identity=Depends(get_identity),
                       workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The next piece, as the raw body, at `offset`."""
    u = _own(db, uid, identity, workspace_id)
    if u.state != "open":
        raise HTTPException(status_code=409, detail={"error": "This upload is already complete.", "code": "conflict",
                                                     "current": {"offset": u.received, "state": u.state}})
    if offset != u.received:
        raise HTTPException(status_code=409, detail={
            "error": f"The upload is at byte {u.received}; send the piece that starts there.",
            "code": "conflict", "current": {"offset": u.received}})
    piece = await request.body()
    if len(piece) > CHUNK:
        raise HTTPException(status_code=413, detail={"error": f"A piece may be at most {CHUNK // MB} MB.",
                                                     "code": "too_large", "limit": CHUNK})
    if u.received + len(piece) > u.size:
        raise HTTPException(status_code=413, detail={
            "error": "This piece goes past the size declared for the file.", "code": "too_large", "limit": u.size})
    with open(u.storage_path, "r+b") as f:
        f.seek(u.received)
        f.write(piece)
        f.truncate()
    u.received += len(piece)
    db.commit()
    return _view(u)


def strip_gps(data: bytes, content_type: str) -> tuple[bytes, bool]:
    """Remove EXIF GPS from a JPEG, PNG or WebP image; other data is returned as it is."""
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        return data, False
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
    except Exception:
        return data, False
    if 0x8825 not in exif:
        return data, False
    del exif[0x8825]
    out = io.BytesIO()
    kwargs = {"exif": exif.tobytes()}
    if img.format == "JPEG":
        kwargs["quality"] = "keep"
    img.save(out, format=img.format, **kwargs)
    return out.getvalue(), True


@router.post("/{uid}/complete")
def complete_upload(uid: str, identity=Depends(get_identity),
                    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    u = _own(db, uid, identity, workspace_id)
    if u.state != "open":
        return _view(u)
    if u.received != u.size:
        raise HTTPException(status_code=409, detail={
            "error": f"{u.received} of {u.size} bytes received.", "code": "conflict",
            "current": {"offset": u.received}})
    with open(u.storage_path, "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != u.sha256:
        # What arrived is not what was hashed on the device: start again.
        open(u.storage_path, "wb").close()
        u.received = 0
        db.commit()
        raise HTTPException(status_code=422, detail={
            "error": "The file received does not match its SHA-256. Send it again.", "code": "invalid",
            "field": "sha256", "current": {"offset": 0}})
    cleaned, removed = strip_gps(data, u.content_type)
    if removed:
        with open(u.storage_path, "wb") as f:
            f.write(cleaned)
    u.gps_removed = removed
    u.state = "complete"
    db.commit()
    return _view(u)


def _attach(db: Session, u: Upload, workspace_id: str, author: Optional[str], **target) -> dict:
    from app.models.attachment import Attachment
    from app.routers.issues import ATTACHMENTS_DIR
    if u.state == "attached":
        return _view(u)
    if u.state != "complete":
        raise HTTPException(status_code=409, detail={"error": "Complete the upload first.", "code": "conflict",
                                                     "current": {"state": u.state, "offset": u.received}})
    attachment_uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    final = os.path.join(ATTACHMENTS_DIR, attachment_uid)
    os.replace(u.storage_path, final)
    size = os.path.getsize(final)
    db.add(Attachment(uid=attachment_uid, workspace_id=workspace_id, filename=u.filename, mime_type=u.content_type,
                      file_size=size, storage_path=final, author=author, **target))
    u.storage_path, u.state, u.attachment_uid = final, "attached", attachment_uid
    return _view(u)


@router.post("/{uid}/attach/ticket/{issue_uid}")
def attach_to_ticket(uid: str, issue_uid: str, identity=Depends(get_identity),
                     workspace_id: str = Depends(require_permission("modify", resource="tickets")),
                     current_user_id: Optional[str] = Depends(get_current_user_id), db: Session = Depends(get_db)):
    from app.models.issue import IssueHistory
    from app.routers.issues import _get_owned_issue
    u = _own(db, uid, identity, workspace_id)
    issue = _get_owned_issue(issue_uid, workspace_id, db)
    already = u.state == "attached"
    out = _attach(db, u, workspace_id, current_user_id, issue_uid=issue.uid)
    if not already:
        db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=issue.uid, type="updated",
                            author=current_user_id or "api", field="Attachment", to_value=u.filename,
                            timestamp=datetime.now(timezone.utc)))
    db.commit()
    return out


@router.post("/{uid}/attach/asset/{asset_uid}")
def attach_to_asset(uid: str, asset_uid: str, identity=Depends(get_identity),
                    workspace_id: str = Depends(require_permission("modify")),
                    current_user_id: Optional[str] = Depends(get_current_user_id), db: Session = Depends(get_db)):
    from app.routers.assets import _get_owned_asset
    u = _own(db, uid, identity, workspace_id)
    asset = _get_owned_asset(asset_uid, workspace_id, db)
    already = u.state == "attached"
    out = _attach(db, u, workspace_id, current_user_id, asset_uid=asset.uid)
    if not already:
        from app.models.asset_subresources import AssetHistory
        from app.routers.ledger import actor_of
        now = datetime.now(timezone.utc)
        db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=asset.uid, type="attachment", author=actor_of(identity),
                            details=f"Attached {u.filename}", timestamp=now))
        asset.updated_at = now
        from app.services import notify
        notify.asset_changed(db, asset.uid, f"Attached {u.filename}", actor_of(identity))
    db.commit()
    return out


@router.post("/{uid}/attach/document/{doc_uid}/revision/{rev_uid}")
def attach_to_document(uid: str, doc_uid: str, rev_uid: str, identity=Depends(get_identity),
                       workspace_id: str = Depends(require_permission("modify", resource="documents")),
                       current_user_id: Optional[str] = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """A file of one revision of a document, while that revision is still being written: a published one is
    what was approved, figures included (documents.upload_revision_attachment)."""
    from app.routers.documents import _get_owned_document, _get_revision
    u = _own(db, uid, identity, workspace_id)
    doc = _get_owned_document(doc_uid, workspace_id, db)
    revision = _get_revision(doc.uid, rev_uid, db)
    if u.state != "attached" and revision.state in ("published", "superseded", "retired"):
        raise HTTPException(status_code=409, detail={
            "error": "That revision is closed — start a new revision to add files.", "code": "conflict"})
    out = _attach(db, u, workspace_id, current_user_id, document_revision_uid=revision.uid)
    db.commit()
    return out


def purge(db: Session) -> int:
    """Remove unfinished uploads past their expiry, with their bytes."""
    from sqlalchemy import select
    n = 0
    for u in db.scalars(select(Upload).where(Upload.state != "attached",
                                             Upload.expires_at < datetime.now(timezone.utc))):
        try:
            os.remove(u.storage_path)
        except OSError:
            pass
        db.delete(u)
        n += 1
    return n

