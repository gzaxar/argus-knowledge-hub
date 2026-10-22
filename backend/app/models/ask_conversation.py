"""Ask ARGUS as a conversation: one person's questions in one workspace and the answers they got.

A follow-up ("and which of those are in AC1?") is answered with the earlier turns as context, so the
turns are kept. Each answer keeps the lookups it was built from, which are what make it checkable. A
conversation is its author's alone: the answers carry whatever that person was allowed to read.
"""
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class AskConversation(Base):
    __tablename__ = "ask_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AskMessage(Base):
    __tablename__ = "ask_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("ask_conversations.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)                  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    # An answer's lookups (tool, arguments, result, error, seconds), how it ended and how long it took.
    steps: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    stopped: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # answered | exhausted | failed | cancelled
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The model that wrote an answer, and the rating its person gave it (up | down), once: the rating itself
    # is kept apart, without them (models/usage.py AskFeedback).
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class AskAction(Base):
    """A change the assistant proposed in a conversation: nothing until its person applies it.

    Ask is read-only by construction (its lookups only retrieve); a person may still ask it to create a record,
    change one or relate two. The model can only propose: the proposal is checked, kept here, shown under the
    answer, and applied — through the same code as the forms, with the person's permissions and in their name
    in the ledger — only when they confirm it."""
    __tablename__ = "ask_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("ask_conversations.id", ondelete="CASCADE"), index=True)
    # The question it answered (its AskMessage seq): the answer that proposed it is the next message.
    turn_seq: Mapped[int] = mapped_column(Integer)
    # Its handle in the conversation: A1, A2… and, for a record to be created, the `new:N` others refer to it by.
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)               # create | update | relate | unrelate | pull_request
    payload: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="proposed")   # proposed | applied | failed | discarded
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    decided_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
