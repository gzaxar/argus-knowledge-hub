"""A site's service portal (docs/service-portal.md): the services it offers, the request types people choose, and
who asked for each ticket the portal made.

A service is an offering ("Network and connectivity"), not a group, a ticket type or a workspace. Its tickets are
ordinary ARGUS tickets created in the service's provider workspace, the site itself or one of its facilities;
`SupportRequest` only records whose request a ticket is, so the requester can follow it without any ticket right
in that workspace.

References to workspaces, groups, types and services from outside the site's own tables are checked by the
application rather than by foreign keys: a portable archive of one facility carries its tickets without the site's
catalogue, and must still load.
"""
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, utcnow


class SiteServiceSettings(Base):
    """One site's portal: whether it is open, what it says, and where "I'm not sure" goes."""

    __tablename__ = "site_service_settings"

    site_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    headline: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    welcome: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Shown on every portal page, whatever a model says: whom to call in an emergency.
    emergency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The request type "I'm not sure" files under: the site's helpdesk. The portal cannot open without it.
    helpdesk_request_type_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Optional help while choosing (knowledge suggestions, and AI where the requester's workspace allows it).
    assistance: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ServiceOffering(Base, TimestampMixin):
    __tablename__ = "service_offerings"
    __table_args__ = (UniqueConstraint("site_id", "slug"),)

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hours: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Where its tickets are made: the site or one of its current facilities.
    provider_workspace_id: Mapped[str] = mapped_column(String, index=True)
    # The team whose queue they enter. Membership alone grants nothing: the team works under its ticket rights.
    team_group_uid: Mapped[str] = mapped_column(String, index=True)
    # Published: taking requests. Publishing records who authorised the destination, and is checked again on use.
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    authorized_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ServiceRequestType(Base, TimestampMixin):
    """What a person asks a service for ("Wi-Fi or network problem", "New account"), and the form it takes."""

    __tablename__ = "service_request_types"
    __table_args__ = (UniqueConstraint("service_uid", "slug"),)

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    service_uid: Mapped[str] = mapped_column(String, ForeignKey("service_offerings.uid", ondelete="CASCADE"),
                                             index=True)
    slug: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Help shown above the form: what to check first, what to include.
    guidance: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The ticket type its tickets get in the provider workspace (null: a plain ticket).
    schema_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The ticket type's fields a requester fills in: [{"key", "label", "help", "required"}]. Nothing else of the
    # type is shown to, or accepted from, a requester.
    fields: Mapped[list] = mapped_column(JSONB, default=list)
    allow_attachments: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SupportRequest(Base):
    """Whose request a ticket is: the requester follows it here, with no right on the ticket's workspace."""

    __tablename__ = "support_requests"
    __table_args__ = (UniqueConstraint("requester_id", "submission_uid"),)

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    origin_workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requester_id: Mapped[str] = mapped_column(String, index=True)
    issue_uid: Mapped[str] = mapped_column(String, ForeignKey("issues.uid", ondelete="CASCADE"), unique=True)
    service_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    request_type_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # What the requester saw when they sent it, kept as it was even if the catalogue changes later.
    service_name: Mapped[str] = mapped_column(String)
    request_type_name: Mapped[str] = mapped_column(String)
    # The requester-facing fields they filled in, by label: what "what you sent" shows them.
    submitted: Mapped[list] = mapped_column(JSONB, default=list)
    # How it was routed: {"reason", "version", "helpdesk"}.
    route: Mapped[dict] = mapped_column(JSONB, default=dict)
    # The client's id for this submission, and a hash of what it sent: a retry returns the same request.
    submission_uid: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    # The last thing the requester can see happening (a public reply, a status change), and when they last looked.
    public_activity_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    requester_seen_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
