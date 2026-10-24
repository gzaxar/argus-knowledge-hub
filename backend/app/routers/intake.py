"""Guided and AI-assisted entry (asset-model-revision §23).

`/guide/{kind}` checks a draft and says what to do next; it needs no model
and works everywhere. `/assist/{kind}` fills a draft from a description or
a photograph and records the run; it needs a working AI endpoint, and when
there is none the form still works (§23.13). `/runs/{id}/outcome` records,
after the save, which suggestions the person kept.
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_grants, get_identity, require_permission
from app.db import get_db
from app.intake import assist, files, guide, outcome, profiles, proposals
from app.ledger.engine import LedgerError
from app.routers.ai import _usable_config, endpoint_for
from app.routers.ledger import actor_of
from app.services.asset_vision import MAX_IMAGE_BYTES
from app.services.llm import LLMError

router = APIRouter(prefix="/v1/intake", tags=["intake"])

RESOURCE = {"asset": "objects", "ticket": "tickets", "document": "documents"}


class GuideIn(BaseModel):
    draft: dict = {}


class AssistIn(BaseModel):
    text: str = ""
    draft: dict = {}


class OutcomeIn(BaseModel):
    record_uid: str
    final: dict = {}


@router.post("/guide/asset")
def guide_asset(body: GuideIn, workspace_id: str = Depends(require_permission("read")),
                grants=Depends(get_grants), db: Session = Depends(get_db)):
    """What is missing or wrong in this asset draft, and the next question."""
    out = guide.guide_asset(db, workspace_id, body.draft, grants)
    db.rollback()                                   # checking writes nothing
    return out


@router.post("/guide/ticket")
def guide_ticket(body: GuideIn, workspace_id: str = Depends(require_permission("read", resource="tickets")),
                 grants=Depends(get_grants), db: Session = Depends(get_db)):
    out = guide.guide_ticket(db, workspace_id, body.draft, grants)
    db.rollback()
    return out


@router.post("/guide/document")
def guide_document(body: GuideIn, workspace_id: str = Depends(require_permission("read", resource="documents")),
                   grants=Depends(get_grants), db: Session = Depends(get_db)):
    out = guide.guide_document(db, workspace_id, body.draft, grants)
    db.rollback()
    return out


def _run(db: Session, fn):
    try:
        out = fn()
    except LLMError as exc:
        db.commit()                                 # the failed run is recorded; nothing else was written
        raise HTTPException(status_code=502, detail=f"The assistant is unavailable: {exc}. Fill in the form "
                                                    "by hand; nothing is lost.")
    except (proposals.ProposalError, files.UnreadableFile) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return out


def _endpoint(db: Session, workspace_id: str, kind: str):
    """The workspace's endpoint, with the active model profile for this kind if there is one (§23.8)."""
    config = _usable_config(db, workspace_id)
    profile = profiles.active(db, workspace_id, kind)
    return config, profiles.endpoint_for(endpoint_for(config), profile), (profile.id if profile else None)


def _draft(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _read(file: UploadFile, limit: int = 20 * 1024 * 1024) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="The file was empty.")
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"That file is larger than {limit // (1024 * 1024)} MB.")
    return content


@router.post("/assist/asset")
def assist_asset(body: AssistIn, identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
                 grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Fill an asset draft from a description. Saves nothing but the run's audit row."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Describe the equipment first.")
    _, ep, profile_id = _endpoint(db, workspace_id, "asset")
    return _run(db, lambda: assist.assist_asset(db, workspace_id, actor_of(identity), ep, text=body.text,
                                                draft=body.draft, grants=grants, profile_id=profile_id))


@router.post("/assist/ticket")
def assist_ticket(body: AssistIn, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("create", resource="tickets")),
                  grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Turn a report, in the person's own words, into a ticket draft."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Say what happened first.")
    _, ep, profile_id = _endpoint(db, workspace_id, "ticket")
    return _run(db, lambda: assist.assist_ticket(db, workspace_id, actor_of(identity), ep, text=body.text,
                                                 draft=body.draft, grants=grants, profile_id=profile_id))


@router.post("/assist/document")
def assist_document(body: AssistIn, identity=Depends(get_identity),
                    workspace_id: str = Depends(require_permission("create", resource="documents")),
                    grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Title, type, summary and keywords from a description or the document's text."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Describe the document, or paste its text, first.")
    _, ep, profile_id = _endpoint(db, workspace_id, "document")
    return _run(db, lambda: assist.assist_document(db, workspace_id, actor_of(identity), ep, text=body.text,
                                                   draft=body.draft, grants=grants, profile_id=profile_id))


def _file_input(content: bytes, file: UploadFile, text: str) -> tuple[str, list, Optional[bytes]]:
    """(text for the model, file references, image bytes if it is a picture)."""
    if files.kind_of(file.filename or "", file.content_type) == "image":
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail=f"That photograph is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
        return text, [{"kind": "file", "format": "image", "name": file.filename}], content
    try:
        extracted, refs = files.extract(content, file.filename or "", file.content_type)
    except files.UnreadableFile as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    for r in refs:
        r["name"] = file.filename
    return ((text.strip() + "\n\n") if text.strip() else "") + extracted, refs, None


@router.post("/assist/{kind}/file")
async def assist_from_file(kind: str, file: UploadFile = File(...), text: str = Form(""), draft: str = Form("{}"),
                           identity=Depends(get_identity), grants=Depends(get_grants), db: Session = Depends(get_db),
                           x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id")):
    """Fill a draft from a file: a nameplate photo, a datasheet, a Word or Excel file, an email."""
    if kind not in RESOURCE:
        raise HTTPException(status_code=404, detail="Unknown kind")
    workspace_id = _allowed(db, identity, x_workspace_id, "create", RESOURCE[kind])
    content = await _read(file)
    body, refs, image = _file_input(content, file, text)
    config, ep, profile_id = _endpoint(db, workspace_id, kind)
    if image is not None and (kind != "asset" or not config.vision_model):
        raise HTTPException(status_code=409, detail="Pictures can be read only for assets, with a vision model configured.")
    actor = actor_of(identity)
    if kind == "asset":
        return _run(db, lambda: assist.assist_asset(db, workspace_id, actor, ep, text=body, image=image,
                                                    mime_type=file.content_type or "image/jpeg", draft=_draft(draft),
                                                    grants=grants, profile_id=profile_id, file_refs=refs))
    fn = assist.assist_ticket if kind == "ticket" else assist.assist_document
    return _run(db, lambda: fn(db, workspace_id, actor, ep, text=body, draft=_draft(draft), grants=grants,
                               profile_id=profile_id, file_refs=refs))


@router.post("/extract")
async def extract_text(file: UploadFile = File(...), identity=Depends(get_identity), db: Session = Depends(get_db),
                       x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id")):
    """A file's text, whole — a PDF, a Word or Excel file, an e-mail, a text file — to keep as a document's body
    or to rework with a template. Nothing is stored and no model reads it; a picture has no text here (the phone
    reads photos on the device)."""
    _allowed(db, identity, x_workspace_id, "create", "documents")
    content = await _read(file)
    if files.kind_of(file.filename or "", file.content_type) == "image":
        raise HTTPException(status_code=422, detail="A picture's text is not read here: use a PDF, Word, Excel, "
                                                    "e-mail or text file, or the phone's Text from a photo.")
    try:
        out = files.extract_document(content, file.filename or "", file.content_type)
    except files.UnreadableFile as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**out, "filename": file.filename}


# Kept for the old photo button: a photograph is one kind of file.
@router.post("/assist/asset/photo")
async def assist_asset_photo(file: UploadFile = File(...), text: str = Form(""), draft: str = Form("{}"),
                             identity=Depends(get_identity), grants=Depends(get_grants), db: Session = Depends(get_db),
                             x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id")):
    return await assist_from_file("asset", file, text, draft, identity, grants, db, x_workspace_id)


def _allowed(db: Session, identity, x_workspace_id: Optional[str], action: str, resource: str) -> str:
    from app.auth import PatIdentity, resolve_permission
    if isinstance(identity, PatIdentity):
        if not identity.may(action, resource):
            raise HTTPException(status_code=403, detail=f"This token may not {action} {resource}")
        return identity.workspace_id
    if identity.token is not None:
        if not identity.token.may(action, resource):
            raise HTTPException(status_code=403, detail=f"This token may not {action} {resource}")
        x_workspace_id = identity.token.workspace_id or x_workspace_id
    if not x_workspace_id:
        raise HTTPException(status_code=400, detail="Missing X-Workspace-Id header")
    if not resolve_permission(db, identity.user, x_workspace_id, action, resource):
        raise HTTPException(status_code=403, detail="Not permitted")
    return x_workspace_id


# --------------------------------------------------------------------------- proposals on existing records

@router.post("/propose/asset/{uid}")
async def propose_for_asset(uid: str, file: Optional[UploadFile] = File(None), text: str = Form(""),
                            identity=Depends(get_identity), grants=Depends(get_grants),
                            workspace_id: str = Depends(require_permission("modify")), db: Session = Depends(get_db)):
    """What a datasheet, a photo or a note says about an existing asset, as proposals for its owner's review."""
    image, refs, body = None, [], text
    if file is not None:
        content = await _read(file)
        body, refs, image = _file_input(content, file, text)
    if not (body or "").strip() and image is None:
        raise HTTPException(status_code=422, detail="Add a file or describe what you know.")
    _, ep, profile_id = _endpoint(db, workspace_id, "asset")
    return _run(db, lambda: proposals.propose_asset(db, workspace_id, actor_of(identity), ep, uid, text=body,
                                                    image=image, mime_type=(file.content_type if file else None) or "image/jpeg",
                                                    file_refs=refs, profile_id=profile_id, grants=grants))


class DecideIn(BaseModel):
    action: str
    value: Any = None
    reason: Optional[str] = None


@router.post("/proposals/{claim_id}")
def decide_proposal(claim_id: str, body: DecideIn, identity=Depends(get_identity),
                    workspace_id: str = Depends(require_permission("modify")), db: Session = Depends(get_db)):
    """Confirm, correct or reject an AI proposal. Confirming makes it the owner's own statement."""
    try:
        out = proposals.decide(db, workspace_id, actor_of(identity), claim_id, body.action, value=body.value,
                               reason=body.reason)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=409 if getattr(exc, "code", None) else 422, detail={"error": str(exc)})
    db.commit()
    return out


# --------------------------------------------------------------------------- model profiles (§23.12)

class ProfileIn(BaseModel):
    kind: str
    model: str
    vision_model: Optional[str] = None


class ActivateIn(BaseModel):
    reason: str
    exception: Optional[str] = None


@router.get("/profiles")
def list_profiles(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    from app.models.intake import IntakeProfile
    rows = db.scalars(select(IntakeProfile).where(IntakeProfile.workspace_id == workspace_id)
                      .order_by(IntakeProfile.created_at.desc()))
    return {"profiles": [profiles.view(p) for p in rows], "gates": {k: v for k, v in profiles.GATES.items()},
            "prompt_version": assist.PROMPT_VERSION,
            "datasets": {k: {"version": profiles.dataset(k)[1], "cases": len(profiles.dataset(k)[0])}
                         for k in profiles.KINDS}}


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    try:
        p = profiles.create(db, workspace_id, actor_of(identity), body.kind, body.model, body.vision_model)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    db.commit()
    return profiles.view(p)


@router.post("/profiles/{profile_id}/evaluate")
def evaluate_profile(profile_id: str, identity=Depends(get_identity),
                     workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    """Run the candidate on the golden dataset. Nothing of the run stays but its report."""
    from app.models.intake import IntakeProfile
    p = db.get(IntakeProfile, profile_id)
    if p is None or p.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="No such profile")
    config = _usable_config(db, workspace_id)
    report = profiles.evaluate(db, workspace_id, actor_of(identity), p, endpoint_for(config))
    db.commit()
    return report


@router.post("/profiles/{profile_id}/activate")
def activate_profile(profile_id: str, body: ActivateIn, identity=Depends(get_identity),
                     workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    try:
        p = profiles.activate(db, workspace_id, actor_of(identity), profile_id, body.reason, body.exception)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    db.commit()
    return profiles.view(p)


@router.post("/profiles/{profile_id}/retire")
def retire_profile(profile_id: str, body: ActivateIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    try:
        p = profiles.retire(db, workspace_id, actor_of(identity), profile_id, body.reason)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    db.commit()
    return profiles.view(p)


@router.get("/status")
def intake_status(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Per kind: the active, evaluated model profile, or none (the endpoint's default model, unevaluated)."""
    out = {}
    for kind in profiles.KINDS:
        p = profiles.active(db, workspace_id, kind)
        out[kind] = {"profile_id": p.id, "model": p.model, "passed": (p.evaluation or {}).get("passed"),
                     "exception": p.exception_reason} if p else None
    return out


@router.post("/runs/{run_id}/outcome", status_code=201)
def record_outcome(run_id: str, body: OutcomeIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """After the save: which suggestions the person kept, corrected or left out."""
    from app.models.intake import IntakeRun
    run = db.get(IntakeRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="No such intake run")
    # Recording the outcome needs the right to create what the run was for.
    from app.auth import PatIdentity, resolve_permission
    if isinstance(identity, PatIdentity):
        allowed = identity.may("create", RESOURCE[run.kind])
    else:
        allowed = resolve_permission(db, identity.user, workspace_id, "create", RESOURCE[run.kind]) and (
            identity.token is None or identity.token.may("create", RESOURCE[run.kind]))
    if not allowed:
        raise HTTPException(status_code=403, detail="Not permitted")
    try:
        out = outcome.record(db, workspace_id, actor_of(identity), run_id, body.record_uid, body.final)
    except outcome.OutcomeError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    db.commit()
    return out


@router.get("/provenance/{record_uid}")
def provenance(record_uid: str, workspace_id: str = Depends(require_permission("read")),
               db: Session = Depends(get_db)):
    """Which of a record's values a model suggested, and what the person did with them."""
    return outcome.provenance(db, workspace_id, record_uid)
