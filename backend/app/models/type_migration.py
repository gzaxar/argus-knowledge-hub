"""Governed migrations of records from a custom or shared type to a versioned package's type
(app/services/type_migration.py, docs/type-migration.md)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TypeMigration(Base):
    """A plan: which records (a source type, possibly with the types below it, in the workspaces chosen) go
    to which package type (by package, version and the type's identity in it), with what mapping, why, and
    what happened. Its log is the audit trail: every decision, apply batch, verification and revert."""
    __tablename__ = "type_migrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                       # objects | tickets | documents
    source_schema_uid: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[dict] = mapped_column(JSONB, default=dict)       # name, owner workspace, family, attributes
    include_descendants: Mapped[bool] = mapped_column(default=False)
    workspaces: Mapped[list] = mapped_column(JSONB, default=list)   # the owning workspaces chosen
    target: Mapped[dict] = mapped_column(JSONB, default=dict)       # package_id, type, area, version
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)      # attributes, states, defaults, decisions
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    # draft | applying | applied | partially_applied | verified | reverted
    inventory: Mapped[dict] = mapped_column(JSONB, default=dict)    # counts per record before the first batch
    verification: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    log: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class TypeMigrationItem(Base):
    """One record of a migration: where it lives, what it was, what it became, and how it went. One row per
    record and migration, so running the migration again never moves a record twice."""
    __tablename__ = "type_migration_items"
    __table_args__ = (UniqueConstraint("migration_id", "record_uid", name="uq_type_migration_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String, ForeignKey("type_migrations.id", ondelete="CASCADE"), index=True)
    record_uid: Mapped[str] = mapped_column(String, index=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    # applied | failed | reverted
    batch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)   # old values kept, not carried to a field
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
