import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, Union

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_oidc import oidc_configured, verify_oidc_token
from app.db import get_db
from app.models.api_token import RESOURCES as TOKEN_RESOURCES, SCOPES, ApiToken
from app.models.user import User
from app.services.permissions import resolve_permission

TOKEN_PEPPER = os.environ["TOKEN_PEPPER"]

# auto_error=False: HTTPBearer's own auto_error path returns 403 on a
# missing header, which is inconsistent with the 401 an invalid/revoked
# token gets below. Handle the missing-header case ourselves so every
# auth failure is a 401.
security = HTTPBearer(auto_error=False)

Action = Literal["read", "create", "modify", "delete", "approve"]
Resource = Literal["objects", "tickets", "documents"]


def hash_token(raw_token: str) -> str:
    return hashlib.sha256((TOKEN_PEPPER + raw_token).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenScope:
    """What an API token was allowed when it was made: its scopes and the kinds of record it may touch."""
    token_id: Optional[int] = None
    name: Optional[str] = None
    kind: str = "robot"
    scopes: frozenset = frozenset(SCOPES)
    resources: frozenset = frozenset()          # empty: every kind of record
    workspace_id: Optional[str] = None

    def may(self, action: str, resource: str = "objects") -> bool:
        if action not in self.scopes:
            return False
        return not self.resources or resource not in TOKEN_RESOURCES or resource in self.resources


@dataclass
class PatIdentity:
    """A robot token: it acts for its workspace, with the scopes it was given."""
    workspace_id: str
    restricted_grants: tuple = ()
    token: TokenScope = TokenScope()

    @property
    def name(self) -> Optional[str]:
        return self.token.name

    def may(self, action: str, resource: str = "objects") -> bool:
        return self.token.may(action, resource)


@dataclass
class OidcIdentity:
    user: User
    # The verified token's claims, for decisions that need more than who: `auth_time` for step-up
    # authentication (portable exports and imports, docs/export-import-design.md §15).
    claims: Optional[dict] = None
    # Set when a personal access token, not a sign-in, brought this person: what the token was allowed.
    token: Optional[TokenScope] = None


def _new_token_secret(kind: str) -> str:
    import secrets
    # A recognisable prefix lets secret scanners (GitHub, GitLab) and people tell an ARGUS token at a glance.
    return f"argus_{'pat' if kind == 'personal' else 'bot'}_{secrets.token_urlsafe(32)}"


def find_token(db: Session, raw_token: str) -> Optional[ApiToken]:
    """The live token with this value: not revoked, not expired."""
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw_token),
                                             ApiToken.revoked_at.is_(None)))
    if token is None:
        return None
    if token.expires_at is not None and token.expires_at <= datetime.now(timezone.utc):
        return None
    return token


def _scope_of(token: ApiToken) -> TokenScope:
    return TokenScope(token_id=token.id, name=token.label, kind=token.kind or "robot",
                      scopes=frozenset(token.scopes if token.scopes is not None else SCOPES),
                      resources=frozenset(token.resources or ()), workspace_id=token.workspace_id)


def _as_token_user(user: User, scope: TokenScope) -> User:
    """The person a personal token acts as, detached from the session so nothing about it is written back,
    and an administrator only if the token was given the `admin` scope."""
    return User(id=user.id, oidc_sub=user.oidc_sub, dn=user.dn, email=user.email, name=user.name,
                username=user.username, is_admin=bool(user.is_admin and "admin" in scope.scopes),
                source=user.source, active=user.active, created_at=user.created_at,
                last_login_at=user.last_login_at, synced_at=user.synced_at)


def identity_for_token(db: Session, token: ApiToken) -> Optional["Identity"]:
    scope = _scope_of(token)
    if token.kind == "personal":
        owner = db.get(User, token.user_id) if token.user_id else None
        if owner is None or not owner.active:
            return None
        return OidcIdentity(user=_as_token_user(owner, scope), claims=None, token=scope)
    if not token.workspace_id:
        return None
    return PatIdentity(workspace_id=token.workspace_id, restricted_grants=tuple(token.restricted_grants or ()),
                       token=scope)


def token_scope(identity) -> Optional[TokenScope]:
    """The token's scope behind this request, or None for a person signed in."""
    if isinstance(identity, PatIdentity):
        return identity.token
    return getattr(identity, "token", None)


# What an HTTP method needs from a token at least, whatever the endpoint checks after it: a token without
# a write scope can only read, one without `read` can only write.
_WRITES = {"create", "modify", "delete", "approve", "admin"}


# POSTs that only read: the MCP server takes every request, tools/list and
# tools/call alike, as a POST, and all its tools are read-only — a read-only
# token is exactly what an assistant such as LibreChat should be given.
_READ_ONLY_POSTS = ("/mcp", "/mcp/")


def _method_allowed(scope: TokenScope, method: str, path: str = "") -> bool:
    if method in ("GET", "HEAD", "OPTIONS") or (method == "POST" and path in _READ_ONLY_POSTS):
        return "read" in scope.scopes
    return bool(scope.scopes & _WRITES)


Identity = Union[PatIdentity, OidcIdentity]


def bootstrap_admins() -> set[str]:
    """ARGUS_BOOTSTRAP_ADMINS: the emails (comma-separated) made administrators when they first sign in. A new
    instance has no administrator and nobody to make one in the web app; every later one is granted there."""
    return {e.strip().lower() for e in os.environ.get("ARGUS_BOOTSTRAP_ADMINS", "").split(",") if e.strip()}


def _resolve_oidc_user(db: Session, claims: dict) -> User:
    """Find the person behind a verified token, in the order that avoids
    creating a second row for someone who already exists:

    1. by the subject we recorded at their last sign-in;
    2. by the id, for accounts created before subjects were stored
       separately — their id *is* the subject, and every "user"-type
       attribute value in the database already points at it;
    3. by email, which is how someone the directory imported before they
       ever signed in gets claimed rather than duplicated.
    """
    sub = claims["sub"]
    email = claims.get("email", "")

    user = db.scalar(select(User).where(User.oidc_sub == sub))
    if user is None:
        user = db.get(User, sub)
    if user is None and email:
        user = db.scalar(select(User).where(User.email == email))

    if user is None:
        user = User(id=str(uuid.uuid4()), oidc_sub=sub, email=email, name=claims.get("name"),
                    is_admin=bool(email) and email.lower() in bootstrap_admins())
        db.add(user)
        db.flush()
        return user

    user.oidc_sub = sub
    if email:
        user.email = email
    # A bootstrap administrator whose account existed before they were named one (a directory sync, a
    # seeding script, a sign-in before the setting) is made one, but only while the installation has no
    # administrator: after that, administrators are granted in the web app, and revoking one sticks.
    if (not user.is_admin and email and email.lower() in bootstrap_admins()
            and db.scalar(select(User.id).where(User.is_admin.is_(True), User.active.is_(True)).limit(1)) is None):
        user.is_admin = True
    user.name = claims.get("name", user.name)
    # Signing in is proof the account is live, whatever a stale directory
    # sync may have concluded.
    user.active = True
    return user


def _note_usage(identity) -> None:
    """Who is asking, for the anonymous usage counts (kept only as a keyed hash, services/usage.py)."""
    from app.services import usage
    user = getattr(identity, "user", None)
    usage.note_user(getattr(user, "id", None), getattr(identity, "workspace_id", None))


def get_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Identity:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    raw_token = credentials.credentials

    token = find_token(db, raw_token)
    if token is not None:
        identity = identity_for_token(db, token)
        if identity is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked token")
        if not _method_allowed(token_scope(identity), request.method, request.url.path):
            raise HTTPException(status_code=403, detail=(
                "This token may only read"
                if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path not in _READ_ONLY_POSTS
                else "This token has no read scope"))
        token.last_used_at = datetime.now(timezone.utc)
        db.commit()
        _note_usage(identity)
        return identity

    if oidc_configured():
        try:
            claims = verify_oidc_token(raw_token)
        except jwt.PyJWTError:
            pass
        else:
            user = _resolve_oidc_user(db, claims)
            user.last_login_at = datetime.now(timezone.utc)
            db.commit()
            identity = OidcIdentity(user=user, claims=claims)
            _note_usage(identity)
            return identity

    raise HTTPException(status_code=401, detail="Invalid or revoked token")


def get_current_user_id(identity: Identity = Depends(get_identity)) -> Optional[str]:
    """The acting OIDC user's id, or None for a PAT (which has no person
    behind it) — used to stamp "current_user"-type attributes on write."""
    return identity.user.id if isinstance(identity, OidcIdentity) else None


def require_permission(action: Action, resource: Resource = "objects"):
    def dependency(
        identity: Identity = Depends(get_identity),
        db: Session = Depends(get_db),
        x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
    ) -> str:
        if isinstance(identity, PatIdentity):
            if not identity.may(action, resource):
                raise HTTPException(status_code=403, detail=f"This token may not {action} {resource}")
            return identity.workspace_id

        scope = identity.token
        if scope is not None:
            # A personal token: its owner's rights, narrowed by its scopes and, if it has one, its workspace.
            if not scope.may(action, resource):
                raise HTTPException(status_code=403, detail=f"This token may not {action} {resource}")
            if scope.workspace_id:
                if x_workspace_id and x_workspace_id != scope.workspace_id:
                    raise HTTPException(status_code=403, detail=f"This token is for {scope.workspace_id} only")
                x_workspace_id = scope.workspace_id
        if not x_workspace_id:
            raise HTTPException(status_code=400, detail="Missing X-Workspace-Id header")
        if not resolve_permission(db, identity.user, x_workspace_id, action, resource):
            raise HTTPException(status_code=403, detail="Not permitted")
        return x_workspace_id

    return dependency


def grants_of(db: Session, identity: Identity, workspace_id: str):
    """The restricted classes this viewer may see in this workspace (§4.3):
    a token's own grants, a person's `restricted` role permissions, or
    everything for an administrator."""
    from app.services.permissions import effective_permissions
    from app.services.visibility import Grants
    if isinstance(identity, PatIdentity):
        return Grants(identity.restricted_grants)
    if identity.token is not None and identity.token.workspace_id and identity.token.workspace_id != workspace_id:
        return Grants(())
    if identity.user.is_admin:
        return Grants.all()
    return Grants(effective_permissions(db, identity.user, workspace_id).get("restricted", set()))


def get_grants(
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
):
    if isinstance(identity, PatIdentity):
        workspace_id = identity.workspace_id
    else:
        workspace_id = x_workspace_id or (identity.token.workspace_id if identity.token else None)
    return grants_of(db, identity, workspace_id or "")


def _lenient_grants(authorization: Optional[str], workspace_id: Optional[str]):
    """Grants for whoever the bearer token names, or none. Never raises:
    authentication itself is each endpoint's own dependency."""
    from app.db import SessionLocal
    from app.services.visibility import NONE, Grants
    if not authorization or not authorization.lower().startswith("bearer "):
        return NONE
    raw = authorization.split(" ", 1)[1].strip()
    db = SessionLocal()
    try:
        token = find_token(db, raw)
        if token is not None:
            identity = identity_for_token(db, token)
            if identity is None:
                return NONE
            if isinstance(identity, PatIdentity):
                return Grants(identity.restricted_grants)
            return grants_of(db, identity, workspace_id or identity.token.workspace_id or "")
        if oidc_configured():
            try:
                claims = verify_oidc_token(raw)
            except jwt.PyJWTError:
                return NONE
            user = db.scalar(select(User).where(User.oidc_sub == claims["sub"])) or db.get(User, claims["sub"])
            if user is not None and workspace_id:
                return grants_of(db, OidcIdentity(user=user), workspace_id)
            if user is not None and user.is_admin:
                return Grants.all()
        return NONE
    finally:
        db.close()


async def bind_grants(
    authorization: Optional[str] = Header(default=None),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
) -> None:
    """App-wide: record the viewer's restricted-class grants for this request
    (I-ACL-1). Async on purpose — a value set here is inherited by the
    endpoint, which runs in a copy of this context."""
    from starlette.concurrency import run_in_threadpool
    from app.services.visibility import set_current_grants
    set_current_grants(await run_in_threadpool(_lenient_grants, authorization, x_workspace_id))
