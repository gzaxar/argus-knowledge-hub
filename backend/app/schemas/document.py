from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

AuthorityLevel = Literal["ufficiale", "informativo", "bozza_interna"]
Confidentiality = Literal["pubblico", "interno", "riservato"]
RelationToType = Literal["asset", "schema", "document", "issue"]


class DocumentCreate(BaseModel):
    uid: str
    # Left out, the system assigns one from the document's type. A real
    # controlled-document number, where there is one, is given here and
    # wins.
    code: Optional[str] = None
    title: str
    document_type_uid: Optional[str] = None
    owner_user_id: Optional[str] = None
    responsible_service_asset_uid: Optional[str] = None
    authority_level: AuthorityLevel = "informativo"
    confidentiality: Confidentiality = "interno"
    is_global: bool = False
    source: str = "manual"
    retention_class: str = "5y"
    # Optional location, written atomically with the new draft.
    navigation_parent_document_uid: Optional[str] = None
    navigation_folder_uid: Optional[str] = None
    # Seeds the first Draft revision.
    body_markdown: Optional[str] = None
    steps: list = []
    attributes: dict = {}
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    next_review_due: Optional[date] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    document_type_uid: Optional[str] = None
    owner_user_id: Optional[str] = None
    responsible_service_asset_uid: Optional[str] = None
    authority_level: Optional[AuthorityLevel] = None
    confidentiality: Optional[Confidentiality] = None
    is_global: Optional[bool] = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    workspace_id: str
    code: str
    title: str
    document_type_uid: Optional[str]
    owner_user_id: Optional[str]
    responsible_service_asset_uid: Optional[str]
    authority_level: str
    confidentiality: str
    source: str
    is_global: bool = False
    current_revision_uid: Optional[str]
    retention_class: str = "5y"
    retired_at: Optional[datetime] = None
    superseded_by_uid: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DocumentRevisionCreate(BaseModel):
    body_markdown: Optional[str] = None
    steps: list = []
    attributes: dict = {}
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    next_review_due: Optional[date] = None


class DocumentRevisionUpdate(BaseModel):
    body_markdown: Optional[str] = None
    steps: Optional[list] = None
    attributes: Optional[dict] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    next_review_due: Optional[date] = None


class DocumentRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    document_uid: str
    revision_number: int
    state: str
    body_markdown: Optional[str]
    steps: list
    attributes: dict
    valid_from: Optional[date]
    valid_until: Optional[date]
    next_review_due: Optional[date]
    authored_by: Optional[str]
    approved_by: Optional[str]
    submitted_at: Optional[datetime]
    approved_at: Optional[datetime]
    published_at: Optional[datetime]
    review_comment: Optional[str]
    superseded_by_uid: Optional[str]
    created_at: datetime
    updated_at: datetime


class RejectAction(BaseModel):
    comment: str


class ApproveAction(BaseModel):
    comment: Optional[str] = None


class RetireAction(BaseModel):
    reason: str


class DocumentRelationCreate(BaseModel):
    to_type: RelationToType
    to_uid: str
    relation_type: str


class DocumentRelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_document_uid: str
    to_type: str
    to_uid: str
    relation_type: str
    created_at: datetime


class RetypeRequest(BaseModel):
    """Move several documents onto one type in a single go."""

    uids: list[str]
    document_type_uid: Optional[str] = None


class RetypeResult(BaseModel):
    moved: int
    # Documents named in the request that aren't in this workspace, or that
    # the caller can't see. Reported rather than silently dropped.
    not_found: list[str]


class BulkDeleteRequest(BaseModel):
    uids: list[str]


class BulkDeleteResult(BaseModel):
    deleted: int
    not_found: list[str]


class MarkdownImportResult(BaseModel):
    documents: int
    attachments: int
    relations: int
    # Files that could not be read, named so a partial upload says which
    # part was partial.
    skipped: list[str]
