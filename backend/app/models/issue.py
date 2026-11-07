from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, WorkspaceScopedMixin


class Issue(Base, WorkspaceScopedMixin, TimestampMixin):
    __tablename__ = "issues"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    # Deleting the linked asset just detaches the ticket from it (SET NULL) —
    # the ticket itself is independent and shouldn't be destroyed by that.
    asset_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("assets.uid", ondelete="SET NULL"), nullable=True, index=True
    )
    # Optional ticket type (a Schema with applies_to="tickets") giving this
    # issue configurable, searchable attributes — same mechanism as Asset
    # types, just scoped to tickets instead of objects. Deleting the type
    # deletes its tickets too (CASCADE), same as it does for object types.
    schema_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("schemas.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    # The ticket's key ({WS}-TCK-0042), from the workspace's Record keys pattern; given when it is created.
    key: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # "new" | "in_progress" | "pending" | "resolved" | "closed" — see the
    # workspace's ticket-scoped "status" Global Value for the responsible
    # party + meaning behind each one.
    state: Mapped[str] = mapped_column(String, default="new")
    priority: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    labels: Mapped[list] = mapped_column(JSONB, default=list)
    due_date: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Per field, the version that last changed it, so an edit made against an older version is
    # refused only when it touches what changed since (app.services.versions).
    field_versions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)


class IssueLink(Base):
    """An edge between two tickets: an epic and its stories, a parent and
    its sub-tasks, a fault that blocks another.

    A link table rather than an attribute holding a key, for the same
    reason objects and documents are linked this way — the graph is walked
    from both ends. "What is in this epic" and "what epic is this in" are
    the same row read in two directions.
    """

    __tablename__ = "issue_links"
    __table_args__ = (UniqueConstraint("from_issue_uid", "to_issue_uid", "relation_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_issue_uid: Mapped[str] = mapped_column(
        String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True
    )
    to_issue_uid: Mapped[str] = mapped_column(
        String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True
    )
    # "epic" | "parent" | "blocks" | "relates" | "duplicates" — the direction
    # is from -> to, so "epic" means: from is in the epic to.
    relation_type: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True))


class IssueHistory(Base):
    """What happened to a ticket and when.

    Recorded for changes made here, and filled from Jira's changelog on
    import, so a ticket's past doesn't stop at the moment it was imported.
    """

    __tablename__ = "issue_history"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    issue_uid: Mapped[str] = mapped_column(
        String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True
    )
    # "created" | "updated" | "imported" — coarse on purpose; the detail is
    # in field/from/to.
    type: Mapped[str] = mapped_column(String)
    author: Mapped[str] = mapped_column(String)
    field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    from_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp: Mapped[object] = mapped_column(DateTime(timezone=True))
    # Jira's changelog item id, so a re-import doesn't duplicate entries.
    backend_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)


class IssueComment(Base, TimestampMixin):
    __tablename__ = "issue_comments"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    issue_uid: Mapped[str] = mapped_column(
        String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)


@event.listens_for(Session, "before_flush")
def _key_new_tickets(session, _context, _instances) -> None:
    """Every new ticket gets its key, whatever made it: the form, an import, an e-mail, Ask ARGUS."""
    new = [o for o in session.new if isinstance(o, Issue) and not o.key and o.workspace_id]
    if not new:
        return
    from app.services.asset_keys import allocate, ticket_type
    for issue in new:
        issue.key = allocate(session, issue.workspace_id, ticket_type())
