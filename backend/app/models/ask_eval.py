"""Ask ARGUS evaluation runs and the evaluation's settings (app/ask_eval, docs/ask-eval.md)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class AskEvalRun(Base):
    """One evaluation run of one ARGUS release: started here, or uploaded from a CI job. Its report is written
    once, with its SHA-256, and never changed: a re-run is another row."""
    __tablename__ = "ask_eval_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)             # the run id in the report
    kind: Mapped[str] = mapped_column(String)                             # release | benchmark | configurations | simulated
    release: Mapped[str] = mapped_column(String, index=True)              # the ARGUS version it tested
    commit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")         # queued | running | finished | incomplete | failed
    source: Mapped[str] = mapped_column(String, default="server")         # server | upload
    requested_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    models: Mapped[list] = mapped_column(JSONB, default=list)
    progress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # the release table's rows
    report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    report_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    public_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AskEvalSettings(Base):
    """The model server an evaluation started from Administration uses. One row. The keys are kept encrypted
    (services/crypto) and never returned."""
    __tablename__ = "ask_eval_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    encrypted_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    models: Mapped[list] = mapped_column(JSONB, default=list)             # the approved chat models
    release_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # the production candidate
    embedding_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rerank_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    judge_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    judge_base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    encrypted_judge_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_hosts: Mapped[list] = mapped_column(JSONB, default=list)
    repeats: Mapped[int] = mapped_column(Integer, default=3)
    case_timeout_s: Mapped[int] = mapped_column(Integer, default=300)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
