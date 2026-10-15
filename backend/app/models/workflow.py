"""Ticket workflows, watchers, notifications and escalations (asset-model-revision
§19 item 3).

A **workflow** is the set of states a ticket type moves through and the
transitions allowed between them, each with what it requires (an assignee,
a resolution, a comment). A ticket type (a Schema applying to tickets)
names its workflow in its metadata; a workspace has a default one.
"""
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class Workflow(Base):
    __tablename__ = "ticket_workflows"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    # [{"key": "in_progress", "name": "In Progress", "category": "open|active|waiting|done", "sla_hours": 8,
    #   "escalate_to": "user-or-email"}]
    states: Mapped[list] = mapped_column(JSONB, default=list)
    # [{"from": "new" | "*", "to": "in_progress", "name": "Start work", "requires": ["assignee"]}]
    transitions: Mapped[list] = mapped_column(JSONB, default=list)
    initial: Mapped[str] = mapped_column(String)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)   # e.g. the Jira workflow it came from
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class TicketWatcher(Base):
    __tablename__ = "ticket_watchers"
    __table_args__ = (UniqueConstraint("issue_uid", "user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    issue_uid: Mapped[str] = mapped_column(String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True)
    user: Mapped[str] = mapped_column(String, index=True)          # user id or e-mail
    reason: Mapped[str] = mapped_column(String, default="manual")  # manual | reporter | assignee | mentioned
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecordWatcher(Base):
    """A person following a piece of equipment or a document, in whichever workspace it is: each change to it
    is a notification (tickets have their own watchers, TicketWatcher)."""
    __tablename__ = "record_watchers"
    __table_args__ = (UniqueConstraint("subject", "subject_uid", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String)                   # asset | document
    subject_uid: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    recipient: Mapped[str] = mapped_column(String, index=True)
    issue_uid: Mapped[Optional[str]] = mapped_column(String, ForeignKey("issues.uid", ondelete="CASCADE"),
                                                     nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String)   # assigned | transitioned | commented | mentioned | escalated
    title: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketEscalation(Base):
    """One escalation of one stay in a state: a ticket that entered a state
    at `entered_at` and outstayed its SLA. Re-entering the state starts a
    new stay."""
    __tablename__ = "ticket_escalations"
    __table_args__ = (UniqueConstraint("issue_uid", "state", "entered_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    issue_uid: Mapped[str] = mapped_column(String, ForeignKey("issues.uid", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String)
    entered_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    escalated_to: Mapped[list] = mapped_column(JSONB, default=list)


class NotificationSubscription(Base):
    """What a person wants to hear about in one workspace, beyond the tickets they watch: every new ticket,
    every new or newly published document, every new piece of equipment."""
    __tablename__ = "notification_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    tickets: Mapped[bool] = mapped_column(Boolean, default=False)
    documents: Mapped[bool] = mapped_column(Boolean, default=False)
    assets: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPreference(Base):
    """How a person wants their notifications by e-mail: each one as it happens (`instant`), once a day
    (`digest`), or never (`off`) — and which kinds (services/notify.EMAIL_CATEGORIES) never by e-mail. Without
    a row: each one as it happens. The app (the bell, the phone) always has them all."""
    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email: Mapped[str] = mapped_column(String, default="instant")
    muted: Mapped[list] = mapped_column(JSONB, default=list)
    last_digest_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
