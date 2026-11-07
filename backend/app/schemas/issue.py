from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class IssueCreate(BaseModel):
    uid: str
    asset_uid: Optional[str] = None
    schema_uid: Optional[str] = None
    attributes: dict = {}
    title: str
    description: Optional[str] = None
    state: str = "new"
    priority: Optional[str] = None
    assignee: Optional[str] = None
    labels: list[str] = []
    due_date: Optional[datetime] = None
    created_by: Optional[str] = None


class IssueUpdate(BaseModel):
    asset_uid: Optional[str] = None
    schema_uid: Optional[str] = None
    attributes: Optional[dict] = None
    title: Optional[str] = None
    description: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    labels: Optional[list[str]] = None
    due_date: Optional[datetime] = None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    key: Optional[str] = None
    workspace_id: str
    asset_uid: Optional[str]
    schema_uid: Optional[str]
    attributes: dict
    title: str
    description: Optional[str]
    state: str
    priority: Optional[str]
    assignee: Optional[str]
    labels: list[str]
    due_date: Optional[datetime]
    closed_at: Optional[datetime]
    created_by: Optional[str]
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]


class IssueHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    issue_uid: str
    type: str
    author: str
    field: Optional[str] = None
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    details: Optional[str] = None
    timestamp: datetime


class IssueAssetLinkOut(BaseModel):
    asset_uid: str
    name: str
    key: str
    type: Optional[str] = None
    relation: str


class IssueAssetLinkCreate(BaseModel):
    asset_uid: str
    # What the ticket does to the object: affects it, was caused by it,
    # replaced it. Free text so a workspace isn't boxed in by our guesses.
    relation: str = "affects"


class IssueDocumentLinkOut(BaseModel):
    document_uid: str
    code: str
    title: str
    relation: str
    relation_id: int


class IssueDocumentLinkCreate(BaseModel):
    document_uid: str
    relation: str = "documents"


class IssueTicketLinkOut(BaseModel):
    link_id: int
    issue_uid: str
    title: str
    state: str
    source_key: Optional[str] = None
    relation: str
    # False when this ticket is the target rather than the origin, so the
    # panel can say "epic of" rather than "in epic" for the same row.
    outgoing: bool


class IssueTicketLinkCreate(BaseModel):
    issue_uid: str
    relation: str = "relates"


class IssueLinksOut(BaseModel):
    assets: list[IssueAssetLinkOut]
    documents: list[IssueDocumentLinkOut]
    tickets: list[IssueTicketLinkOut]


class IssueCommentCreate(BaseModel):
    uid: str
    # Ignored for a signed-in person: the comment is theirs. An API token names it.
    author: Optional[str] = None
    body: str


class IssueCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    issue_uid: str
    author: str
    body: str
    created_at: datetime
    updated_at: datetime


class BulkDeleteRequest(BaseModel):
    uids: list[str]


class BulkDeleteResult(BaseModel):
    deleted: int
    not_found: list[str]
