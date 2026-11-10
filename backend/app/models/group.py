from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, utcnow


class Group(Base, TimestampMixin):
    """A group of people, mirrored from the directory (LDAP today, a Keycloak
    claim later) or created locally.

    Deliberately *not* workspace-scoped: an INFN service exists once and is
    referenced from several workspaces, the same way a global type is. What
    a group may do is expressed separately, by a role binding per workspace.
    """

    __tablename__ = "groups"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    # The directory's own identifier. Unique where present, so a re-sync
    # updates a group instead of duplicating it; null for local groups.
    dn: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # "ldap" | "embedded" | "local" — which authority owns this row. A sync
    # only ever touches rows of its own source, so a locally-created group
    # survives a directory sync untouched.
    source: Mapped[str] = mapped_column(String, default="local")
    # A group that has left the directory is deactivated, never deleted:
    # deleting it would silently drop every role binding and every group
    # reference recorded on an object.
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    # A local group owned by one site (issue #26): its site administrators govern it, and it may hold direct
    # grants only at that site and its current facilities. Null: owned by the installation.
    home_site_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workspaces.id", ondelete="SET NULL"),
                                                        nullable=True, index=True)


class GroupMember(Base):
    """Who is in a group. Rows carry their own source so a hand-added member
    isn't removed by the next directory sync."""

    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_uid", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_uid: Mapped[str] = mapped_column(
        String, ForeignKey("groups.uid", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String, default="local")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupAdministrator(Base):
    """A person entrusted with membership of one locally managed group."""

    __tablename__ = "group_administrators"
    __table_args__ = (UniqueConstraint("group_uid", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_uid: Mapped[str] = mapped_column(String, ForeignKey("groups.uid", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
