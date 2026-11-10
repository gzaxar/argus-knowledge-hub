from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AccessEvent(Base):
    """One change to who may do what (issue #26): a role given or taken away, directly or site-wide; someone put in
    or taken out of a group; an administrator named or removed; a group moved to a site; a facility moved between
    sites. Append-only. Not foreign-keyed, so the record outlives what it names."""

    __tablename__ = "access_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    site_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    group_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
