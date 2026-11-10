"""Workspace navigation, separate from controlled documents and source relations."""
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, WorkspaceScopedMixin


class DocumentFolder(Base, WorkspaceScopedMixin, TimestampMixin):
    __tablename__ = "document_folders"
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    parent_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_folders.uid", ondelete="CASCADE"), nullable=True, index=True,
    )
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="document_folder_name_not_empty"),)


class DocumentPlacement(Base, WorkspaceScopedMixin, TimestampMixin):
    """One optional navigation override; no row means use the source child_of link.

    Both targets null explicitly places the document in Unfiled documents.
    Navigation overrides do not rewrite imported knowledge-graph relations.
    """
    __tablename__ = "document_navigation_placements"
    document_uid: Mapped[str] = mapped_column(
        String, ForeignKey("documents.uid", ondelete="CASCADE"), primary_key=True,
    )
    folder_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_folders.uid", ondelete="CASCADE"), nullable=True, index=True,
    )
    parent_document_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("documents.uid", ondelete="CASCADE"), nullable=True, index=True,
    )
    __table_args__ = (
        CheckConstraint("folder_uid IS NULL OR parent_document_uid IS NULL", name="document_placement_one_parent"),
        CheckConstraint("parent_document_uid IS NULL OR document_uid <> parent_document_uid", name="document_placement_not_self"),
    )
