"""Which template packages a workspace uses, at which exact version, and how it got them."""
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class WorkspacePackage(Base):
    """A package a workspace has: its version and the checksum of exactly what was applied."""
    __tablename__ = "workspace_packages"
    __table_args__ = (UniqueConstraint("workspace_id", "package_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    checksum: Mapped[str] = mapped_column(String)
    # how it was put in: for the object catalogue, the scope and the catalogue workspace it hangs from
    options: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    installed_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    installed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class PackageInstallation(Base):
    """One step in a workspace's package history: an install, an upgrade, what an import seeded, or a
    package found already in place when the record began."""
    __tablename__ = "package_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)          # install | upgrade | seeded | detected
    from_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_version: Mapped[str] = mapped_column(String)
    checksum: Mapped[str] = mapped_column(String)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)   # what it created and extended
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class PackageSnapshot(Base):
    """A package's definitions exactly as a workspace was given them: what an upgrade compares the newer
    version with (and the workspace's own edits against)."""
    __tablename__ = "package_snapshots"
    __table_args__ = (UniqueConstraint("package_id", "checksum"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    checksum: Mapped[str] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSONB)
    sections: Mapped[dict] = mapped_column(JSONB)
    recorded_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
