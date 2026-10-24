"""A web page saved as a folder, imported as documents — one per HTML page (services/web_import.py).

- `POST /v1/documents/import-web/preview` — the pages found, their pictures, the files no page uses: nothing kept.
- `POST /v1/documents/import-web` — a draft document for each page chosen, with its pictures shown where they were,
  its HTML as its original, and the unused files on the first one; with `suggest`, the assistant reads each page's
  text and proposes its type, a summary and keywords (and a title, for a page that has none).

The folder comes as files whose names are their paths in it (the browser's folder picker), or as one .zip.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, get_grants, get_identity, require_permission
from app.db import get_db
from app.models.attachment import Attachment
from app.models.document import DocumentRelation
from app.services import web_import as wi

router = APIRouter(prefix="/v1/documents", tags=["documents"])


async def _folder(files: list[UploadFile]) -> dict[str, bytes]:
    uploads, total = [], 0
    for f in files:
        content = await f.read()
        total += len(content)
        if total > wi.MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"The folder is larger than {wi.MAX_BYTES // (1024 * 1024)} MB.")
        uploads.append((f.filename or "", content))
    try:
        return wi.folder_from(uploads)
    except wi.WebImportError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/import-web/preview")
async def preview_web_folder(files: list[UploadFile] = File(...),
                             _ws: str = Depends(require_permission("create", resource="documents"))):
    """What the folder holds: its pages (the main one first), with their titles and pictures; nothing is kept."""
    folder = await _folder(files)
    pages = wi.pages_of(folder)
    return {"files": len(folder),
            "pages": [{"path": p.path, "title": p.title, "pictures": len(p.pictures), "chars": len(p.markdown),
                       "links_to": p.pages_linked} for p in pages],
            "unused": wi.unused_files(folder, pages)}


def _attach(db: Session, workspace_id: str, revision_uid: str, path: str, content: bytes,
            author: Optional[str]) -> str:
    from app.routers.documents import ATTACHMENTS_DIR
    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage = os.path.join(ATTACHMENTS_DIR, uid)
    with open(storage, "wb") as f:
        f.write(content)
    db.add(Attachment(uid=uid, workspace_id=workspace_id, document_revision_uid=revision_uid,
                      filename=path[-255:], mime_type=wi.mime_of(path), file_size=len(content), author=author,
                      storage_path=storage))
    return uid


@router.post("/import-web", status_code=201)
async def import_web_folder(
    files: list[UploadFile] = File(...),
    pages: str = Form("", description="JSON list of the pages' paths to import; all of them when left out"),
    document_type_uid: str = Form(""),
    confidentiality: str = Form("interno"),
    authority_level: str = Form("informativo"),
    relate_asset: str = Form(""),
    suggest: bool = Form(False, description="the assistant proposes each page's type, summary and keywords"),
    identity: Identity = Depends(get_identity),
    grants=Depends(get_grants),
    workspace_id: str = Depends(require_permission("create", resource="documents")),
    db: Session = Depends(get_db),
):
    """One draft document per page chosen. Its body is the page as Markdown; the pictures it shows are attached
    and shown in place; its HTML is attached as the original; a link to another page imported now points to that
    page's document. The folder's files no page uses go with the first document, so nothing given is lost."""
    folder = await _folder(files)
    try:
        wanted = json.loads(pages) if pages.strip() else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="pages is a JSON list of paths")
    return import_folder(db, workspace_id, identity, grants, folder, wanted, document_type_uid=document_type_uid,
                         confidentiality=confidentiality, authority_level=authority_level, relate_asset=relate_asset,
                         suggest=suggest)


def import_folder(db: Session, workspace_id: str, identity: Identity, grants, folder: dict[str, bytes],
                  wanted: Optional[list[str]], *, document_type_uid: str = "", confidentiality: str = "interno",
                  authority_level: str = "informativo", relate_asset: str = "", suggest: bool = False) -> dict:
    """The import itself: `wanted` the pages' paths (all when None)."""
    from app.models.asset import Asset
    from app.routers.documents import new_document
    from app.schemas.document import DocumentCreate
    if confidentiality not in ("pubblico", "interno", "riservato"):
        raise HTTPException(status_code=422, detail="confidentiality is pubblico, interno or riservato")
    if authority_level not in ("ufficiale", "informativo", "bozza_interna"):
        raise HTTPException(status_code=422, detail="authority_level is ufficiale, informativo or bozza_interna")
    found = wi.pages_of(folder)
    wanted = [p.path for p in found] if wanted is None else wanted
    chosen = [p for p in found if p.path in set(wanted)]
    if not chosen:
        raise HTTPException(status_code=422, detail="None of the pages chosen is in the folder")
    if len(chosen) > 100:
        raise HTTPException(status_code=422, detail="At most 100 pages at a time")
    actor = identity.user.id if isinstance(identity, OidcIdentity) else None
    asset = db.get(Asset, relate_asset) if relate_asset else None
    if relate_asset and (asset is None or asset.workspace_id != workspace_id):
        raise HTTPException(status_code=422, detail="relate_asset: no such asset here")

    proposed = _suggestions(db, workspace_id, identity, grants, chosen, confidentiality) if suggest else {}

    made = []
    for page in chosen:
        fields = proposed.get(page.path, {})
        title = page.title
        if page.title == wi.stem(page.path) and _value(fields, "title"):
            title = str(_value(fields, "title"))[:300]          # a page with no title of its own
        attributes = {}
        if _value(fields, "summary"):
            attributes["argus_summary"] = str(_value(fields, "summary"))
        if _value(fields, "attributes.argus_keywords"):
            attributes["argus_keywords"] = list(_value(fields, "attributes.argus_keywords"))
        type_uid = document_type_uid or _value(fields, "document_type_uid") or None
        doc, revision = new_document(db, DocumentCreate(
            uid=str(uuid.uuid4()), title=title, document_type_uid=type_uid,
            owner_user_id=actor, confidentiality=confidentiality, authority_level=authority_level,
            body_markdown=page.markdown, attributes=attributes), workspace_id, identity)
        made.append((page, doc, revision))
    documents = {page.path: doc.uid for page, doc, _ in made}
    attached: set[str] = set()
    for page, doc, revision in made:
        pictures = {p: _attach(db, workspace_id, revision.uid, p, folder[p], actor) for p in page.pictures}
        attached.update(page.pictures)
        _attach(db, workspace_id, revision.uid, page.path, folder[page.path], actor)       # the original page
        attached.add(page.path)
        for f in page.files_linked:                     # a PDF or a drawing the page links to goes with it
            if f not in attached and not f.lower().endswith(wi.PAGE_EXTENSIONS):
                _attach(db, workspace_id, revision.uid, f, folder[f], actor)
                attached.add(f)
        revision.body_markdown = wi.finish(page.markdown, pictures, documents)
        if asset is not None:
            exists = db.scalar(select(DocumentRelation).where(DocumentRelation.from_document_uid == doc.uid,
                                                              DocumentRelation.to_uid == asset.uid))
            if exists is None:
                db.add(DocumentRelation(workspace_id=workspace_id, from_document_uid=doc.uid, to_type="asset",
                                        to_uid=asset.uid, relation_type="describes"))
    # The rest of the folder (pages not imported, files nothing uses), with the first document: nothing is lost.
    first_revision = made[0][2]
    for f in sorted(folder):
        if f not in attached:
            _attach(db, workspace_id, first_revision.uid, f, folder[f], actor)
    db.commit()
    return {"documents": [{"uid": doc.uid, "code": doc.code, "title": doc.title, "path": page.path,
                           "pictures": len(page.pictures),
                           "suggested": sorted(k for k in ("title", "document_type_uid", "summary",
                                                            "attributes.argus_keywords")
                                               if _value(proposed.get(page.path, {}), k))}
                          for page, doc, _ in made],
            "suggestions_failed": [p for p, f in proposed.items() if f is None],
            "attached_to_first": [f for f in sorted(folder) if f not in attached]}


MAX_SUGGESTED_PAGES = 20


def _value(fields: Optional[dict], key: str):
    f = (fields or {}).get(key)
    return f.get("value") if isinstance(f, dict) else None


def _suggestions(db: Session, workspace_id: str, identity: Identity, grants, pages: list[wi.Page],
                 confidentiality: str) -> dict:
    """{page path: the assistant's fields, or None where it failed}: what it reads is each page's text (its
    pictures are named, not seen). Each reading is recorded as any other (intake runs)."""
    from app.intake import assist
    from app.routers.document_templates import _ai
    from app.routers.intake import _endpoint
    from app.routers.ledger import actor_of
    from app.services.llm import LLMError
    if len(pages) > MAX_SUGGESTED_PAGES:
        raise HTTPException(status_code=422, detail=f"The assistant suggests for at most {MAX_SUGGESTED_PAGES} pages "
                                                    "at a time: choose fewer, or import without suggestions.")
    _ai(db, workspace_id, confidentiality)            # no AI, or riservato where the workspace does not allow it
    _, endpoint, profile_id = _endpoint(db, workspace_id, "document")
    out: dict = {}
    for page in pages:
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[picture: \1]", page.markdown)
        text = re.sub(r"\]\((?:page|file):[^)]+\)", "]", text)
        try:
            result = assist.assist_document(db, workspace_id, actor_of(identity), endpoint,
                                            text=f"{page.title}\n\n{text}"[:20000], draft={"title": page.title},
                                            grants=grants, profile_id=profile_id)
            out[page.path] = result.get("fields") or {}
        except LLMError:
            out[page.path] = None                     # that page is imported without suggestions
    return out
