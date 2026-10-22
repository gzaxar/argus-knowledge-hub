"""Activities: what a person plans, is doing or has done — distinct from tickets (services/activities.py).

An **Activity** is one piece of work: planned (a future start, end or due time), in progress (started), completed
(actual start and end, which are not when it was recorded), or cancelled / skipped. It may refer to an asset, a
ticket or a document; it changes none of them.

A **series** is a recurring activity: a rule (an RRULE subset, services/recurrence.py) from a first local start
in a time zone. Its occurrences are computed when a range is asked for; an occurrence becomes a stored Activity
only when something happens to it — done, skipped, rescheduled, edited — named by its original local start
(`occurrence_key`). "This and future" splits the series in two; "the entire series" changes the series.

Visibility: `workspace` (members who may read the workspace's tickets see it) or `private` (its owner and its
assignee only). An activity referring to a record its viewer may not see is not shown to them either.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow

STATUSES = ("planned", "in_progress", "completed", "cancelled", "skipped")
VISIBILITIES = ("workspace", "private")


class ActivitySeries(Base):
    __tablename__ = "activity_series"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"),
                                                         nullable=True, index=True)
    assignee_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"),
                                                            nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String, default="workspace")
    rrule: Mapped[str] = mapped_column(String)
    # The first occurrence's local start ("2026-10-26T09:00"), in `timezone`; a time of 00:00 with `all_day`.
    first_local: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    # How long each occurrence is planned to take, when said: never made up.
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    asset_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    ticket_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # A series cut by "this and future" points to the one that continues it.
    continued_by_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("series_uid", "occurrence_key", name="uq_activity_occurrence"),)

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    series_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("activity_series.uid", ondelete="CASCADE"), nullable=True, index=True)
    occurrence_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"),
                                                         nullable=True, index=True)
    assignee_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"),
                                                            nullable=True, index=True)
    # For an occurrence, None means "as the series says".
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="planned", index=True)
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    planned_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    asset_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    ticket_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # what was found, on completion
    # The AI proposal it came from, if any: the transcript, the model, what was proposed and what was changed.
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
