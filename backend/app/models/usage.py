"""How ARGUS is used, counted without saying by whom: the Statistics page (services/usage.py).

Nothing here names a person. Requests are counted per day, client, workspace and function; presence is a
keyed hash of the person per five minutes, enough to count who was there at once and on a day, not to find
out who they were; the model's work is counted in calls and tokens. Ask feedback keeps the question, the
answer and what it was built with, never who asked.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class UsageRequest(Base):
    """Requests of a day, by client (web, app, mcp, api), workspace ('' for none) and function (the route)."""
    __tablename__ = "usage_requests"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    client: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    function: Mapped[str] = mapped_column(String, primary_key=True)        # "GET /v1/assets/{uid}"
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    errors: Mapped[int] = mapped_column(BigInteger, default=0)             # 5xx answers
    ms_total: Mapped[int] = mapped_column(BigInteger, default=0)


class UsagePresence(Base):
    """Someone (a keyed hash, not reversible without the installation's key) active in a five-minute slot."""
    __tablename__ = "usage_presence"

    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    client: Mapped[str] = mapped_column(String, primary_key=True)
    person: Mapped[str] = mapped_column(String, primary_key=True)


class UsageLLM(Base):
    """The language model's work of a day: calls and tokens, by workspace, model and purpose."""
    __tablename__ = "usage_llm"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    purpose: Mapped[str] = mapped_column(String, primary_key=True)        # chat, complete, embed, transcribe…
    calls: Mapped[int] = mapped_column(BigInteger, default=0)
    failures: Mapped[int] = mapped_column(BigInteger, default=0)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    # Calls whose provider reported no usage: their tokens are estimated from the text (four characters each).
    estimated_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    ms_total: Mapped[int] = mapped_column(BigInteger, default=0)


class AskFeedback(Base):
    """A rating of an Ask ARGUS answer, anonymous: what was asked and answered and how, never by whom."""
    __tablename__ = "ask_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    rating: Mapped[str] = mapped_column(String)                            # up | down
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    argus_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    client: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # web | app/<version>/<platform>
    tools: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)    # [{tool, arguments, error, seconds}]
    stopped: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ticket_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class UsageStorage(Base):
    """How full each storage area was on a day (the last measurement of the day): its trend over time."""
    __tablename__ = "usage_storage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    area: Mapped[str] = mapped_column(String, primary_key=True)          # attachments | portability | database
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    # The room planned for it (the volume's size), and what the disk under it still has free; None: not known.
    planned_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    disk_free_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    measured_at = mapped_column(DateTime(timezone=True), default=utcnow)
