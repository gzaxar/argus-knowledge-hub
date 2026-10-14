"""Where a workspace's AI features point, and whether they work.

The endpoint is configured here rather than in the deployment because
different workspaces are entitled to different gateways, and because a
key typed into a form and encrypted at rest never has to travel through a
values file or a chat window to get there.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.models.llm_config import LLMConfig
from app.models.ai_suggestion import AISuggestion
from app.models.document import Document
from app.models.schema import Schema
from app.schemas.ai import (
    AIStatus,
    AskActionIds,
    AskActionOut,
    AskConversationDetail,
    AskConversationOut,
    AskIn,
    AskMessageOut,
    AskOut,
    ChatIn,
    LLMCheckResult,
    LLMConfigIn,
    LLMConfigOut,
    SuggestionDecision,
    SuggestionDecisionResult,
    DraftDocumentIn,
    DraftDocumentOut,
    DraftTicketIn,
    DraftTicketOut,
    PhotoIdentification,
    ReviewDocumentIn,
    ReviewDocumentOut,
    SuggestionOut,
    SuggestRequest,
    SuggestRunResult,
)
from app.services.ai_authoring import draft_document, draft_ticket_fields, review_document
from app.services.ai_config import installation_problem, resolve as resolve_config
from app.services.ask import ask as run_ask
from app.services.ask import ask_events
from app.services.asset_vision import MAX_IMAGE_BYTES, identify
from app.services.text_links import objects_mentioned
from app.services.ai_suggestions import suggest_document_types
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.llm import Endpoint, LLMError, check

router = APIRouter(prefix="/v1/ai", tags=["ai"])


def endpoint_for(config: LLMConfig) -> Endpoint:
    return Endpoint(
        base_url=config.base_url,
        model=config.model,
        embedding_model=config.embedding_model,
        vision_model=config.vision_model,
        asr_model=config.asr_model,
        tts_model=config.tts_model,
        rerank_model=config.rerank_model,
        api_key=decrypt_secret(config.encrypted_secret) if config.encrypted_secret else None,
        max_output_tokens=config.max_output_tokens,
    )


def _out(config: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        workspace_id=config.workspace_id,
        base_url=config.base_url,
        model=config.model,
        embedding_model=config.embedding_model,
        vision_model=config.vision_model,
        asr_model=config.asr_model,
        tts_model=config.tts_model,
        rerank_model=config.rerank_model,
        has_api_key=bool(config.encrypted_secret),
        enabled=config.enabled,
        allow_confidential=config.allow_confidential,
        max_output_tokens=config.max_output_tokens,
        index_on_publish=config.index_on_publish is not False,
        index_interval_hours=12 if config.index_interval_hours is None else config.index_interval_hours,
        last_checked_at=config.last_checked_at,
        last_check_ok=config.last_check_ok,
        last_check_error=config.last_check_error,
    )


def _get(db: Session, workspace_id: str) -> Optional[LLMConfig]:
    return db.get(LLMConfig, workspace_id)


@router.get("/config", response_model=Optional[LLMConfigOut])
def get_config(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    config = _get(db, workspace_id)
    return _out(config) if config else None


@router.put("/config", response_model=LLMConfigOut)
def put_config(
    body: LLMConfigIn,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    return _save(db, workspace_id, body)


def _save(db: Session, key: str, body: LLMConfigIn) -> LLMConfigOut:
    """Settings for a workspace, or (key INSTALLATION) for the installation."""
    config = _get(db, key)
    if config is None:
        config = LLMConfig(workspace_id=key, base_url="", model="")
        db.add(config)

    config.base_url = body.base_url.strip()
    config.model = body.model.strip()
    config.embedding_model = (body.embedding_model or "").strip() or None
    config.vision_model = (body.vision_model or "").strip() or None
    config.asr_model = (body.asr_model or "").strip() or None
    config.tts_model = (body.tts_model or "").strip() or None
    config.rerank_model = (body.rerank_model or "").strip() or None
    config.enabled = body.enabled
    config.allow_confidential = body.allow_confidential
    config.max_output_tokens = body.max_output_tokens
    if body.index_on_publish is not None:
        config.index_on_publish = body.index_on_publish
    if body.index_interval_hours is not None:
        config.index_interval_hours = body.index_interval_hours

    if body.api_key is not None:
        # An empty string clears it; omitting the field keeps what is stored.
        config.encrypted_secret = encrypt_secret(body.api_key) if body.api_key else None

    # Settings changed, so whatever the last check proved is no longer about
    # this configuration.
    config.last_checked_at = None
    config.last_check_ok = None
    config.last_check_error = None

    db.commit()
    db.refresh(config)
    return _out(config)


@router.delete("/config", status_code=204)
def delete_config(
    workspace_id: str = Depends(require_permission("modify")), db: Session = Depends(get_db)
):
    config = _get(db, workspace_id)
    if config is not None:
        db.delete(config)
        db.commit()


@router.post("/config/check", response_model=LLMCheckResult)
def check_config(
    workspace_id: str = Depends(require_permission("modify")), db: Session = Depends(get_db)
):
    """Ask the endpoint whether it can do what it has been configured for."""
    return _check(db, workspace_id)


def _check(db: Session, key: str) -> LLMCheckResult:
    config = _get(db, key)
    if config is None:
        raise HTTPException(status_code=404, detail="No AI endpoint is configured")

    ok, error, models = check(endpoint_for(config))
    config.last_checked_at = datetime.now(timezone.utc)
    config.last_check_ok = ok
    config.last_check_error = error
    db.commit()
    return LLMCheckResult(ok=ok, error=error, models=models)


@router.get("/status", response_model=AIStatus)
def status(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    """What the application asks before offering an AI action.

    A feature that cannot work should not be presented as if it could, and
    the reason belongs here rather than in a failed request later.
    """
    config, inherited_from = resolve_config(db, workspace_id)
    if config is None:
        return AIStatus(
            configured=False,
            enabled=False,
            validated=False,
            reason=installation_problem(db) or (
                "No AI endpoint is configured for this workspace, and none is set for the installation "
                "(Administration → AI)."),
        )

    shape = dict(
        model=config.model,
        has_embeddings=bool(config.embedding_model),
        has_rerank=bool(config.rerank_model),
        has_vision=bool(config.vision_model),
        has_asr=bool(config.asr_model),
        has_tts=bool(config.tts_model),
        # Shown as "using the shared default from …": the installation's own settings read as such.
        inherited_from=("the installation (Administration → AI)" if inherited_from == "__installation__"
                        else inherited_from),
    )
    if not config.enabled:
        return AIStatus(
            configured=True, enabled=False, validated=bool(config.last_check_ok),
            reason="AI features are switched off for this workspace.", **shape,
        )
    if not config.last_check_ok:
        return AIStatus(
            configured=True, enabled=True, validated=False,
            reason=config.last_check_error
            or "The AI endpoint has not been checked since it was last changed.",
            **shape,
        )
    return AIStatus(configured=True, enabled=True, validated=True, **shape)


def _usable_config(db: Session, workspace_id: str) -> LLMConfig:
    """The endpoint, if it is actually usable. The same gate the status
    endpoint reports, enforced rather than trusted."""
    config, _inherited_from = resolve_config(db, workspace_id)
    if config is None:
        raise HTTPException(status_code=409, detail="No AI endpoint is configured")
    if not config.enabled:
        raise HTTPException(status_code=409, detail="AI features are switched off for this workspace")
    if not config.last_check_ok:
        raise HTTPException(
            status_code=409,
            detail=config.last_check_error
            or "The AI endpoint has not been checked since it was last changed.",
        )
    return config


@router.post("/suggest/document-types", response_model=SuggestRunResult)
def suggest_types(
    body: SuggestRequest,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    """Propose a type for documents that have none worth the name.

    Writes proposals, never a document. Applying one is a separate,
    deliberate act.
    """
    config = _usable_config(db, workspace_id)
    result = suggest_document_types(
        db,
        workspace_id,
        endpoint_for(config),
        config,
        only_untyped=body.only_untyped,
        # Bounded so one request stays well inside an ingress read timeout;
        # a caller with a backlog asks repeatedly rather than waiting on one
        # long request that a proxy will cut off at sixty seconds.
        limit=max(1, min(body.limit, 40)),
    )
    return SuggestRunResult(**result)


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(
    status: str = "proposed",
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    db: Session = Depends(get_db),
):
    rows = list(db.scalars(
        select(AISuggestion)
        .where(AISuggestion.workspace_id == workspace_id, AISuggestion.status == status)
        .order_by(AISuggestion.created_at.desc())
    ))
    # Names rather than uids, so the list reads without a second lookup.
    titles = {
        d.uid: d.title
        for d in db.scalars(select(Document).where(Document.workspace_id == workspace_id))
    }
    schema_names = {
        s.uid: s.name
        for s in db.scalars(select(Schema).where(Schema.workspace_id == workspace_id))
    }
    out = []
    for row in rows:
        item = SuggestionOut.model_validate(row)
        item.target_label = titles.get(row.target_uid)
        item.previous_label = schema_names.get(row.previous_value or "")
        out.append(item)
    return out


@router.post("/suggestions/accept", response_model=SuggestionDecisionResult)
def accept_suggestions(
    body: SuggestionDecision,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    """Apply proposals. This is the only path by which a model's answer
    becomes a value on a record."""
    applied, skipped = 0, []
    for suggestion_id in body.ids:
        row = db.get(AISuggestion, suggestion_id)
        if row is None or row.workspace_id != workspace_id or row.status != "proposed":
            skipped.append(suggestion_id)
            continue
        document = db.get(Document, row.target_uid)
        if document is None or document.workspace_id != workspace_id:
            skipped.append(suggestion_id)
            continue
        if row.field != "document_type_uid":
            skipped.append(suggestion_id)
            continue
        document.document_type_uid = row.suggested_value
        row.status = "accepted"
        row.decided_at = datetime.now(timezone.utc)
        applied += 1
    db.commit()
    return SuggestionDecisionResult(applied=applied, skipped=skipped)


@router.post("/suggestions/reject", response_model=SuggestionDecisionResult)
def reject_suggestions(
    body: SuggestionDecision,
    workspace_id: str = Depends(require_permission("modify", resource="documents")),
    db: Session = Depends(get_db),
):
    rejected, skipped = 0, []
    for suggestion_id in body.ids:
        row = db.get(AISuggestion, suggestion_id)
        if row is None or row.workspace_id != workspace_id or row.status != "proposed":
            skipped.append(suggestion_id)
            continue
        row.status = "rejected"
        row.decided_at = datetime.now(timezone.utc)
        rejected += 1
    db.commit()
    return SuggestionDecisionResult(rejected=rejected, skipped=skipped)


@router.post("/identify-object", response_model=PhotoIdentification)
async def identify_object(
    file: UploadFile = File(description="A photograph of the equipment"),
    workspace_id: str = Depends(require_permission("create")),
    db: Session = Depends(get_db),
):
    """What is in this photograph, as a draft for the new-object form.

    Proposes; does not create. The object types offered are this
    workspace's own, and any key read off a label is checked against the
    inventory rather than believed.
    """
    config = _usable_config(db, workspace_id)
    if not config.vision_model:
        raise HTTPException(
            status_code=409,
            detail="No vision model is configured for this workspace's AI endpoint.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="The photograph was empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That photograph is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

    try:
        return identify(
            db, workspace_id, endpoint_for(config), content,
            file.content_type or "image/jpeg",
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


MAX_AUDIO_BYTES = 25 * 1024 * 1024    # what a Whisper endpoint takes in one request: about 25 minutes of a note


@router.post("/transcribe")
async def transcribe_recording(
    file: UploadFile = File(description="A recording: a dictated note or document"),
    language: Optional[str] = None,
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """What was said in a recording, as text, by the workspace's speech-to-text model. Keeps nothing: the
    person edits the text, and what they save is what is kept."""
    from app.services.llm import transcribe
    config = _usable_config(db, workspace_id)
    if not config.asr_model:
        raise HTTPException(status_code=409, detail="No speech-to-text model is configured for this workspace's "
                                                    "AI endpoint (Administration → AI).")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="The recording was empty.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"That recording is larger than {MAX_AUDIO_BYTES // (1024 * 1024)} MB.")
    try:
        text = transcribe(endpoint_for(config), content, file.filename or "recording.m4a",
                          file.content_type or "audio/mp4", language)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"text": text}


@router.post("/draft-document", response_model=DraftDocumentOut)
def draft_a_document(
    body: DraftDocumentIn,
    workspace_id: str = Depends(require_permission("create", resource="documents")),
    db: Session = Depends(get_db),
):
    """A first draft for the editor. Saves nothing."""
    config = _usable_config(db, workspace_id)
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="Give the document a title first.")
    try:
        markdown = draft_document(
            db, endpoint_for(config), body.title.strip(),
            body.document_type_uid, body.notes,
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return DraftDocumentOut(
        body_markdown=markdown,
        mentioned_objects=objects_mentioned(db, workspace_id, body.title, markdown),
    )


@router.post("/review-document", response_model=ReviewDocumentOut)
def review_a_document(
    body: ReviewDocumentIn,
    workspace_id: str = Depends(require_permission("read", resource="documents")),
    db: Session = Depends(get_db),
):
    """Remarks about a draft, and the objects it names. Changes nothing."""
    config = _usable_config(db, workspace_id)
    if not body.body_markdown.strip():
        raise HTTPException(status_code=422, detail="There is nothing written yet to review.")
    try:
        findings = review_document(
            db, endpoint_for(config), body.title, body.document_type_uid, body.body_markdown
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ReviewDocumentOut(
        findings=findings,
        mentioned_objects=objects_mentioned(
            db, workspace_id, body.title, body.body_markdown
        ),
    )


def _ticket_vocabulary(db: Session, workspace_id: str) -> dict:
    from app.services.ticket_types import options_in, workspace_base_attributes
    attrs = workspace_base_attributes(db, workspace_id)
    return {"category": options_in(attrs, "argus_category"), "impact": options_in(attrs, "argus_impact"),
            "detected_by": options_in(attrs, "argus_detected_by")}


@router.post("/draft-ticket", response_model=DraftTicketOut)
def draft_a_ticket(
    body: DraftTicketIn,
    workspace_id: str = Depends(require_permission("create", resource="tickets")),
    db: Session = Depends(get_db),
):
    """The structured fields a fault report implies, plus the objects it
    names. Fills a form; creates nothing."""
    config = _usable_config(db, workspace_id)
    if not body.title.strip() and not body.description.strip():
        raise HTTPException(status_code=422, detail="Write the report first.")
    try:
        fields = draft_ticket_fields(endpoint_for(config), body.title, body.description,
                                     _ticket_vocabulary(db, workspace_id))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return DraftTicketOut(
        **fields,
        mentioned_objects=objects_mentioned(db, workspace_id, body.title, body.description),
    )


@router.post("/ask", response_model=AskOut)
def ask_the_knowledge(
    body: AskIn,
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """A question answered from this workspace's records, showing its working.

    Read-only, and deliberately so: the tools behind it only retrieve. It
    needs no more permission than reading the same records by hand would.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask something.")
    config = _usable_config(db, workspace_id)
    try:
        return AskOut(**run_ask(db, workspace_id, endpoint_for(config), question))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --------------------------------------------------------------------------- Ask as a chat

def _owner(identity) -> str:
    from app.routers.ledger import actor_of
    return actor_of(identity)


def _sse(event: dict) -> str:
    import json
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _chat_events(workspace_id: str, owner: str, question: str, conversation_id: Optional[str],
                 endpoint: Endpoint, grants, can_propose: bool = False):
    """The chat turn as server-sent events, saved as it ends. Runs after the request's own session is
    gone, so it has its own, and the viewer's restricted-class grants are set again here: the lookups
    must see what the person may see, no more."""
    import uuid
    from app.db import SessionLocal
    from app.models.ask_conversation import AskConversation, AskMessage
    from app.services.visibility import set_current_grants
    set_current_grants(grants)
    db = SessionLocal()
    steps: list = []
    final: Optional[dict] = None
    conversation = None
    try:
        conversation = db.get(AskConversation, conversation_id) if conversation_id else None
        if conversation is None:
            conversation = AskConversation(id=str(uuid.uuid4()), workspace_id=workspace_id, owner=owner,
                                           title=question[:80])
            db.add(conversation)
            db.flush()
        earlier = list(db.scalars(select(AskMessage).where(AskMessage.conversation_id == conversation.id)
                                  .order_by(AskMessage.seq)))
        history = [{"role": m.role, "content": m.content} for m in earlier]
        seq = (earlier[-1].seq + 1) if earlier else 0
        db.add(AskMessage(id=str(uuid.uuid4()), conversation_id=conversation.id, seq=seq, role="user",
                          content=question))
        db.commit()
        yield _sse({"type": "conversation", "id": conversation.id, "title": conversation.title})
        from app.services import ask_actions
        proposer = ask_actions.Proposer(db, workspace_id, conversation.id, seq) if can_propose else None
        try:
            for event in ask_events(db, workspace_id, endpoint, question, history=history, proposer=proposer,
                                    context=ask_actions.context(db, conversation.id)):
                if event["type"] == "step":
                    steps.append({k: event[k] for k in ("tool", "arguments", "result", "error", "seconds")})
                if event["type"] == "done":
                    final = event
                yield _sse(event)
        except LLMError as e:
            final = {"answer": "", "steps": steps, "stopped": "failed", "error": str(e), "seconds": None}
            yield _sse({"type": "done", **final})
    except GeneratorExit:
        # The person stopped it, or closed the page: what was found so far is kept, marked as such.
        final = final or {"answer": "", "steps": steps, "stopped": "cancelled", "error": None, "seconds": None}
        raise
    finally:
        if conversation is not None and final is not None:
            try:
                db.rollback()
                last = db.scalar(select(AskMessage.seq).where(AskMessage.conversation_id == conversation.id)
                                 .order_by(AskMessage.seq.desc()).limit(1))
                db.add(AskMessage(id=str(uuid.uuid4()), conversation_id=conversation.id, seq=(last or 0) + 1,
                                  role="assistant", content=final.get("answer") or "",
                                  steps=final.get("steps") or steps, stopped=final.get("stopped"),
                                  error=final.get("error"), seconds=final.get("seconds")))
                convo = db.get(AskConversation, conversation.id)
                if convo is not None:
                    convo.updated_at = datetime.now(timezone.utc)
                db.commit()
            except Exception:  # noqa: BLE001 — a failed save must not hide the answer already sent
                db.rollback()
        db.close()


@router.post("/chat")
def chat(
    body: ChatIn,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Ask, as a conversation, answered as it is worked out: server-sent events (one JSON object per
    `data:` line) for what the model is doing, each lookup and its result, and the answer as it is
    written. The turn is saved in the conversation, which a follow-up continues. Same permission as
    reading the records by hand: the lookups only retrieve. To somebody who may create or change records it
    can also propose changes, which wait for them to apply (services/ask_actions.py)."""
    from fastapi.responses import StreamingResponse
    from app.models.ask_conversation import AskConversation
    from app.services.visibility import current_grants
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask something.")
    owner = _owner(identity)
    if body.conversation_id:
        conversation = db.get(AskConversation, body.conversation_id)
        if conversation is None or conversation.workspace_id != workspace_id or conversation.owner != owner:
            raise HTTPException(status_code=404, detail="No such conversation")
    config = _usable_config(db, workspace_id)
    return StreamingResponse(
        _chat_events(workspace_id, owner, question, body.conversation_id, endpoint_for(config), current_grants(),
                     can_propose=_may_change(db, identity, workspace_id)),
        media_type="text/event-stream",
        # Proxies (the cluster's ingress, nginx) would otherwise hold the events back until the end.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _may_change(db: Session, identity, workspace_id: str) -> bool:
    """Whether the assistant may offer this person changes to apply: they could make some by hand."""
    from app.auth import OidcIdentity
    from app.services.permissions import resolve_permission
    if not isinstance(identity, OidcIdentity):
        return True
    return any(resolve_permission(db, identity.user, workspace_id, action, "objects") for action in ("create", "modify"))


@router.get("/conversations", response_model=list[AskConversationOut])
def list_conversations(
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Your conversations in this workspace, most recent first."""
    from app.models.ask_conversation import AskConversation
    return list(db.scalars(select(AskConversation).where(
        AskConversation.workspace_id == workspace_id, AskConversation.owner == _owner(identity))
        .order_by(AskConversation.updated_at.desc()).limit(200)))


def _own_conversation(db: Session, workspace_id: str, identity, conversation_id: str):
    from app.models.ask_conversation import AskConversation
    conversation = db.get(AskConversation, conversation_id)
    if conversation is None or conversation.workspace_id != workspace_id or conversation.owner != _owner(identity):
        raise HTTPException(status_code=404, detail="No such conversation")
    return conversation


@router.get("/conversations/{conversation_id}", response_model=AskConversationDetail)
def get_conversation(
    conversation_id: str,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    from app.models.ask_conversation import AskMessage
    conversation = _own_conversation(db, workspace_id, identity, conversation_id)
    messages = list(db.scalars(select(AskMessage).where(AskMessage.conversation_id == conversation.id)
                               .order_by(AskMessage.seq)))
    return AskConversationDetail(id=conversation.id, title=conversation.title, created_at=conversation.created_at,
                                 updated_at=conversation.updated_at,
                                 messages=[AskMessageOut.model_validate(m) for m in messages])


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    db.delete(_own_conversation(db, workspace_id, identity, conversation_id))
    db.commit()


@router.get("/conversations/{conversation_id}/actions", response_model=list[AskActionOut])
def conversation_actions(
    conversation_id: str,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    """The changes the assistant proposed in this conversation, and what became of each."""
    from app.services import ask_actions
    conversation = _own_conversation(db, workspace_id, identity, conversation_id)
    return [ask_actions.view(a) for a in ask_actions.of_conversation(db, conversation.id)]


@router.post("/conversations/{conversation_id}/actions/apply", response_model=list[AskActionOut])
def apply_actions(
    conversation_id: str,
    body: AskActionIds,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Apply proposed changes, in the order they were proposed, as the person confirming them: each needs the
    permission it would by hand, goes through the forms' validation and is written to the ledger in their
    name. Each stands or fails on its own; the list says which."""
    from app.services import ask_actions
    conversation = _own_conversation(db, workspace_id, identity, conversation_id)
    return ask_actions.apply(db, identity, workspace_id, _owner(identity), conversation.id, body.ids)


@router.post("/conversations/{conversation_id}/actions/discard", response_model=list[AskActionOut])
def discard_actions(
    conversation_id: str,
    body: AskActionIds,
    workspace_id: str = Depends(require_permission("read")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    from app.services import ask_actions
    conversation = _own_conversation(db, workspace_id, identity, conversation_id)
    return ask_actions.discard(db, _owner(identity), conversation.id, body.ids)


# --------------------------------------------------------------------------- the written knowledge (RAG)

@router.get("/knowledge")
def knowledge_status(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """What of this workspace's written knowledge is indexed for Ask ARGUS, and whether it can be."""
    from app.services import knowledge_index
    from app.services.ai_config import resolve
    config, _from = resolve(db, workspace_id)
    from app.services import knowledge_schedule
    out = knowledge_index.status(db, workspace_id)
    out["embedding_model"] = config.embedding_model if config else None
    out["schedule"] = knowledge_schedule.schedule(config, (out.get("run") or {}))
    return out


def _index_in_background(workspace_id: str) -> None:
    from app.db import SessionLocal
    from app.services import knowledge_index
    from app.services.ai_config import resolve
    db = SessionLocal()
    try:
        config, _from = resolve(db, workspace_id)
        if config is not None:
            knowledge_index.index_workspace(db, workspace_id, endpoint_for(config))
    except LLMError as e:
        db.rollback()
        from sqlalchemy import text as sql
        import json
        db.execute(sql("UPDATE knowledge_index_runs SET state = 'failed', finished_at = now(), "
                       "result = CAST(:r AS jsonb) WHERE workspace_id = :w"),
                   {"w": workspace_id, "r": json.dumps({"failed": [str(e)]})})
        db.commit()
    finally:
        db.close()


@router.post("/knowledge/reindex", status_code=202)
def knowledge_reindex(
    background: BackgroundTasks,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Brings the index up to date in the background: only what changed since the last run is embedded."""
    from app.services import knowledge_index
    config = _usable_config(db, workspace_id)
    if not config.embedding_model:
        raise HTTPException(status_code=400, detail="Set an embedding model in the AI settings first.")
    try:
        knowledge_index.ensure_store(db)
    except LLMError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    current = knowledge_index.status(db, workspace_id).get("run")
    if current and current.get("state") == "running":
        raise HTTPException(status_code=409, detail="An indexing run is already going.")
    background.add_task(_index_in_background, workspace_id)
    return {"started": True}


# --------------------------------------------------------------------------- the installation's settings

admin_router = APIRouter(prefix="/v1/admin/ai", tags=["ai"])


def _administrator(identity=Depends(get_identity)):
    from app.auth import OidcIdentity
    if not isinstance(identity, OidcIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators set the installation's AI settings")
    return identity


@admin_router.get("/config", response_model=Optional[LLMConfigOut])
def get_installation_config(_admin=Depends(_administrator), db: Session = Depends(get_db)):
    """The AI settings every workspace without its own uses (Administration → AI)."""
    from app.services.ai_config import INSTALLATION
    config = _get(db, INSTALLATION)
    return _out(config) if config else None


@admin_router.put("/config", response_model=LLMConfigOut)
def put_installation_config(body: LLMConfigIn, _admin=Depends(_administrator), db: Session = Depends(get_db)):
    """Set the installation's AI settings. "Send confidential documents" is never inherited, so it is not set here."""
    from app.services.ai_config import INSTALLATION
    return _save(db, INSTALLATION, body.model_copy(update={"allow_confidential": False}))


@admin_router.delete("/config", status_code=204)
def delete_installation_config(_admin=Depends(_administrator), db: Session = Depends(get_db)):
    from app.services.ai_config import INSTALLATION
    config = _get(db, INSTALLATION)
    if config is not None:
        db.delete(config)
        db.commit()


@admin_router.post("/config/check", response_model=LLMCheckResult)
def check_installation_config(_admin=Depends(_administrator), db: Session = Depends(get_db)):
    from app.services.ai_config import INSTALLATION
    return _check(db, INSTALLATION)
