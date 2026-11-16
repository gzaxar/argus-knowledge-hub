from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    # A stable internal id, NOT the identity provider's subject. Every
    # "user"-type attribute value in the database stores this string, so it
    # has to survive a person moving between identity providers (Firebase
    # today, Keycloak once INFN's AAI lands) and has to exist for someone the
    # directory knows about who has never signed in.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    # The token's `sub` claim, recorded on first sign-in and matched on every
    # later one. Rows created before this column existed used the sub as
    # their id, which the migration backfills here.
    oidc_sub: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    # The directory's own identifier, when this person came from one.
    dn: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # "oidc" | "ldap" | "embedded" | "local" — the authority that owns this
    # row, so a sync only rewrites what it created.
    source: Mapped[str] = mapped_column(String, default="oidc")
    # Someone who has left the directory is deactivated, never deleted:
    # deleting the row would cascade through every attribute value and
    # comment naming them, erasing history.
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whether the identity provider vouches for the address (its `email_verified` claim) at the last sign-in; None
    # when it did not say. A group by e-mail domain only counts a verified address (services/domain_groups.py).
    email_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Removed from ARGUS by an administrator (services/user_removal.py): no sign-in, no token, no access. The row
    # stays, so what they did keeps their name.
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
