from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMConfigIn(BaseModel):
    base_url: str
    model: str
    embedding_model: Optional[str] = None
    vision_model: Optional[str] = None
    asr_model: Optional[str] = None
    tts_model: Optional[str] = None
    rerank_model: Optional[str] = None
    # Left out on an update, the stored key is kept. Sent empty, it is
    # cleared — for an endpoint that takes none.
    api_key: Optional[str] = None
    enabled: bool = False
    allow_confidential: bool = False
    # Empty: no limit on a reply's length.
    max_output_tokens: Optional[int] = Field(default=None, ge=1)
    # Indexing the written knowledge for Ask ARGUS by itself. Left out on an update, the stored value is kept.
    index_on_publish: Optional[bool] = None
    # Hours between refreshes of the whole index; 0: no timer.
    index_interval_hours: Optional[int] = Field(default=None, ge=0, le=24 * 30)


class LLMConfigOut(BaseModel):
    """What the client may see. The key is never among it — only whether
    one is set, which is all a form needs to render honestly."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    workspace_id: str
    base_url: str
    model: str
    embedding_model: Optional[str]
    vision_model: Optional[str]
    asr_model: Optional[str]
    tts_model: Optional[str]
    rerank_model: Optional[str] = None
    has_api_key: bool
    enabled: bool
    allow_confidential: bool
    max_output_tokens: Optional[int] = None
    index_on_publish: bool = True
    index_interval_hours: int = 12
    last_checked_at: Optional[datetime]
    last_check_ok: Optional[bool]
    last_check_error: Optional[str]


class LLMCheckResult(BaseModel):
    ok: bool
    error: Optional[str] = None
    models: list[str] = []


class AIStatus(BaseModel):
    """What the application asks before offering an AI action, so a feature
    that cannot work is never presented as if it could."""

    model_config = ConfigDict(protected_namespaces=())

    configured: bool
    enabled: bool
    validated: bool
    model: Optional[str] = None
    has_embeddings: bool = False
    has_rerank: bool = False
    has_vision: bool = False
    has_asr: bool = False
    has_tts: bool = False
    # The workspace this endpoint is configured in, when it is not this one.
    # A beamline running on the shared default should be told so rather than
    # shown settings it does not own.
    inherited_from: Optional[str] = None
    # Why it is unavailable, in words a person can act on.
    reason: Optional[str] = None


class SuggestRequest(BaseModel):
    # Only the ones an import had nothing to go on for, by default.
    only_untyped: bool = True
    limit: int = 25


class SuggestRunResult(BaseModel):
    considered: int
    proposed: int
    unchanged: int
    failed_batches: int


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    target_type: str
    target_uid: str
    field: str
    suggested_value: str
    suggested_label: Optional[str]
    previous_value: Optional[str]
    model: str
    status: str
    created_at: datetime
    # Filled in for display so a list does not need a second round of
    # lookups to be readable.
    target_label: Optional[str] = None
    previous_label: Optional[str] = None


class SuggestionDecision(BaseModel):
    ids: list[int]


class SuggestionDecisionResult(BaseModel):
    applied: int = 0
    rejected: int = 0
    skipped: list[int] = []


class AssetMatch(BaseModel):
    uid: str
    key: str
    name: str


class PhotoIdentification(BaseModel):
    """A draft for the new-object form, not a record."""

    model_config = ConfigDict(protected_namespaces=())

    type_uid: Optional[str]
    type_name: Optional[str]
    name: Optional[str]
    manufacturer: Optional[str]
    model: Optional[str]
    serial: Optional[str]
    description: Optional[str]
    visible_text: list[str] = []
    confidence: str = "low"
    # Object keys read from the photo that exist in this inventory, so a
    # link can be proposed rather than invented.
    matches: list[AssetMatch] = []
    unmatched_keys: list[str] = []
    error: Optional[str] = None


class MentionedObject(BaseModel):
    uid: str
    key: Optional[str]
    name: Optional[str]
    # "key" or "name" — a key is something somebody wrote down, a name
    # could be a coincidence of words, and the caller should be able to
    # tell them apart.
    matched_on: str


class DraftDocumentIn(BaseModel):
    title: str
    document_type_uid: Optional[str] = None
    notes: Optional[str] = None


class DraftDocumentOut(BaseModel):
    body_markdown: str
    mentioned_objects: list[MentionedObject] = []


class ReviewDocumentIn(BaseModel):
    title: str = ""
    document_type_uid: Optional[str] = None
    body_markdown: str


class ReviewFinding(BaseModel):
    severity: str
    message: str


class ReviewDocumentOut(BaseModel):
    findings: list[ReviewFinding] = []
    # Objects the text names that are not yet linked — the edges a
    # knowledge graph is missing most often.
    mentioned_objects: list[MentionedObject] = []


class DraftTicketIn(BaseModel):
    title: str
    description: str = ""


class DraftTicketOut(BaseModel):
    category: Optional[str] = None
    impact: Optional[str] = None
    detected_by: Optional[str] = None
    system: Optional[str] = None
    subsystem: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    mentioned_objects: list[MentionedObject] = []


class AskIn(BaseModel):
    question: str


class AskStep(BaseModel):
    """One tool call, shown to whoever asked.

    The point of the Ask page is to see which records an answer came from,
    so the arguments and the raw result are returned rather than a tidy
    summary of them.
    """
    tool: str
    arguments: dict = {}
    result: str = ""
    error: Optional[str] = None
    seconds: float = 0


class ChatIn(BaseModel):
    question: str
    # Omitted to start a conversation; given to continue one.
    conversation_id: Optional[str] = None
    # Spoken (the app's hands-free mode): a short answer first, one clarifying question when ambiguous.
    voice: bool = False


class AskMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    role: str
    content: str = ""
    steps: Optional[list[AskStep]] = None
    stopped: Optional[str] = None
    error: Optional[str] = None
    seconds: Optional[float] = None
    # Its person's rating of an answer, once given: up | down.
    rating: Optional[str] = None
    created_at: Optional[datetime] = None


class AskFeedbackIn(BaseModel):
    """A rating of one of the conversation's answers: the `answer_index`-th (from 0), or the last."""
    answer_index: Optional[int] = Field(default=None, ge=0)
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(default=None, max_length=5000)


class AskFeedbackOut(BaseModel):
    rating: str
    # A ticket was opened for the people who look after Ask ARGUS (an answer rated down).
    reported: bool


class AskConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AskConversationDetail(AskConversationOut):
    messages: list[AskMessageOut] = []


class AskOut(BaseModel):
    answer: str = ""
    steps: list[AskStep] = []
    # "answered" or "exhausted" — an answer produced after the round limit
    # was cut short, and should be read as such.
    stopped: str = "answered"
    error: Optional[str] = None
    seconds: float = 0


class AskActionOut(BaseModel):
    """A change the assistant proposed; nothing is changed until it is applied."""
    id: str
    number: int
    turn_seq: int
    kind: str                       # create | update | relate | unrelate | pull_request
    summary: str
    status: str                     # proposed | applied | failed | discarded
    result: Optional[dict] = None   # what was made: {uid, key, name}, {relation_id} or {url, number, branch, key}
    error: Optional[str] = None
    reason: Optional[str] = None


class AskActionIds(BaseModel):
    ids: list[str]
