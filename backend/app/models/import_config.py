from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, WorkspaceScopedMixin


class ImportConfig(Base, WorkspaceScopedMixin, TimestampMixin):
    """A saved, named import setup — parameters plus a merge strategy — that
    can be re-run with one click instead of re-entering everything."""

    __tablename__ = "import_configs"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)  # "jira" | "git"
    merge_strategy: Mapped[str] = mapped_column(String, default="override")
    # Non-secret parameters (base_url/jira_schema_id, or provider/repo_url/branch).
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    # The source PAT, Fernet-encrypted — see app/services/crypto.py. Never
    # returned to the client once set. Null for a public repository, which
    # needs no credential and must not be given an empty one.
    encrypted_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_run_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_import_job_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # A schedule (services/import_schedule.py): "off", "hours" (every `schedule_every_hours`), "daily" at
    # `schedule_time`, or "weekly" on `schedule_weekday` (0 = Monday) at `schedule_time`, in `schedule_timezone`.
    schedule_kind: Mapped[str] = mapped_column(String, default="off", server_default="off")
    schedule_every_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schedule_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)         # "02:30"
    schedule_weekday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schedule_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Who set it: a scheduled run acts as them (their permissions), and they hear when it fails.
    scheduled_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    next_run_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    running_since: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_outcome: Mapped[Optional[str]] = mapped_column(String, nullable=True)        # succeeded | failed | skipped
    last_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
