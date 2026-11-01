from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # When set, every schema owned by this workspace (any applies_to) is
    # cascaded to is_global=True too — see seed_default_global_values's
    # sibling, _cascade_global_to_workspace, in this router.
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)
    # §13 S5: record facts and relations change only through the fact ledger (a trigger enforces it).
    ledger_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # §13 S7: the relation registry warns (reports) or enforces (refuses new edges that break it).
    registry_mode: Mapped[str] = mapped_column(String, default="warn", server_default="warn")
    # Set while a portable import is staged into this workspace (`staging`: nobody but the import
    # sees it), or when it holds read-only evidence (`evidence`). See app/portability.
    import_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # How keys are made for records created without one; null is the default
    # pattern. See app/services/asset_keys.py.
    asset_key_pattern: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # `catalogue` for the one workspace that is the installation's catalogue of Vendors and Product Models
    # (docs/system-catalogue.md); null for every other.
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # A facility workspace's site: the laboratory whose places it uses (docs/sites.md); that workspace has
    # role `site`. One level: a site is at no site.
    site_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workspaces.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)

    # Fallback rights for any authenticated user with no explicit Membership
    # row in this workspace. All unchecked by default — a workspace stays
    # invite-only until an admin/owner opts in to some level of open access.
    default_can_read: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_create: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_modify: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_read_tickets: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_create_tickets: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_modify_tickets: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_delete_tickets: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_read_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_create_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_modify_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_delete_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    default_can_approve_documents: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
