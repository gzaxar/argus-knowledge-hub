"""Editorial templates for documents reworked from raw text (services/doc_templates.py, services/reshape.py).

The official templates ship with ARGUS as files and cannot be changed here. A workspace makes **variants** of
them, and a person **personal copies** that only they use. Each is edited as a draft and published: every
publication is a new, immutable version (DocumentTemplateVersion), never overwritten, so a document can always
say exactly which text it was made with. Official templates get a version row too, the first time one is used
(or a variant is made from it), so their text at that version is kept after ARGUS ships a newer one.
"""
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class DocumentTemplate(Base):
    """A workspace variant or a personal copy of an official template."""
    __tablename__ = "document_templates"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String)                 # workspace | personal
    # The author: for a personal copy, the only person who sees and uses it.
    owner_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"),
                                                         nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    # Where it comes from: the official template and the version it was made from.
    base_template_id: Mapped[str] = mapped_column(String)
    base_version: Mapped[int] = mapped_column(Integer)
    # What is being edited, not yet published; checked on every save, published as a new version.
    draft_source: Mapped[str] = mapped_column(Text)
    latest_version: Mapped[int] = mapped_column(Integer, default=0)      # 0: never published
    # The one used by default for its document type: in the workspace (a workspace variant), or by its owner
    # (a personal copy). At most one each.
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DocumentTemplateVersion(Base):
    """One published text of a template, never changed: a variant's (template_uid) or an official one's
    (official_id, as shipped)."""
    __tablename__ = "document_template_versions"
    __table_args__ = (UniqueConstraint("template_uid", "version", name="uq_template_version"),
                      UniqueConstraint("official_id", "version", "sha256", name="uq_official_version"))

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    template_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_templates.uid", ondelete="CASCADE"), nullable=True, index=True)
    official_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # what changed, from the publisher
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentGeneration(Base):
    """How a draft revision was made from raw text: the exact template version, the source kept, the dates
    told apart, what was extracted and what was left to check."""
    __tablename__ = "document_generations"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    document_uid: Mapped[str] = mapped_column(String, ForeignKey("documents.uid", ondelete="CASCADE"), index=True)
    revision_uid: Mapped[str] = mapped_column(String, ForeignKey("document_revisions.uid", ondelete="CASCADE"),
                                              index=True)
    template_version_uid: Mapped[str] = mapped_column(String, ForeignKey("document_template_versions.uid"))
    template_id: Mapped[str] = mapped_column(String)
    template_version: Mapped[int] = mapped_column(Integer)
    template_scope: Mapped[str] = mapped_column(String)         # official | workspace | personal
    # The raw text, kept as a file of the revision (same access as the document), and what is known about it.
    source_attachment_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_kind: Mapped[str] = mapped_column(String)            # paste | email | intake | import
    source_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    # inserted_at, source_date, event_date, document_date and on what basis each was set.
    dates: Mapped[dict] = mapped_column(JSONB, default=dict)
    extraction: Mapped[dict] = mapped_column(JSONB, default=dict)
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
