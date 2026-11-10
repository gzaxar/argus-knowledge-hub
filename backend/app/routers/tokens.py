"""Who am I, and the tokens that call the API on someone's behalf.

`GET /v1/me/profile` is the full picture of the person asking: the account, how they signed in, their groups,
and what each workspace's roles let them do.

**Personal access tokens** (`/v1/me/tokens`) act as the person who made them, narrowed by scopes. **Robot
tokens** (`/v1/workspaces/{id}/robot-tokens`) act for a workspace: a facility's daily-logbook uploader, a
script, an instrument. Both are made only by a person signed in — a token cannot make another token — and the
token itself is shown once, when it is made.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (Identity, OidcIdentity, PatIdentity, _new_token_secret, get_identity, hash_token,
                      token_scope)
from app.db import get_db
from app.models.api_token import RESOURCES, SCOPES, ApiToken
from app.models.group import Group, GroupMember
from app.models.role import Role, RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.services.permissions import effective_permissions, user_group_uids

router = APIRouter(prefix="/v1", tags=["tokens"])

# A personal token lives at most a year: a person's access changes, and a forgotten token should not outlive it.
PERSONAL_MAX_DAYS = 365
ROBOT_MAX_DAYS = 3 * 365

Scope = Literal["read", "create", "modify", "delete", "approve", "admin"]
Resource = Literal["objects", "tickets", "documents"]


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Scope] = Field(min_length=1)
    resources: list[Resource] = []
    # A personal token: the one workspace it is fixed to, or none for all its owner's.
    workspace_id: Optional[str] = None
    # Days until it stops working. Required for a personal token; a robot may run without expiry (None).
    expires_in_days: Optional[int] = Field(default=90, ge=1)
    restricted_grants: list[str] = []


class TokenOut(BaseModel):
    id: int
    kind: str
    name: Optional[str]
    prefix: Optional[str]
    workspace_id: Optional[str]
    user_id: Optional[str] = None
    owner_email: Optional[str] = None
    scopes: list[str]
    resources: list[str]
    restricted_grants: list[str]
    created_by: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    status: str                                   # active | expired | revoked


class TokenCreated(TokenOut):
    # The token itself: shown this once, never stored.
    token: str


def _status(t: ApiToken) -> str:
    if t.revoked_at is not None:
        return "revoked"
    if t.expires_at is not None and t.expires_at <= datetime.now(timezone.utc):
        return "expired"
    return "active"


def _out(db: Session, t: ApiToken) -> TokenOut:
    owner = db.get(User, t.user_id) if t.user_id else None
    return TokenOut(id=t.id, kind=t.kind or "robot", name=t.label, prefix=t.prefix, workspace_id=t.workspace_id,
                    user_id=t.user_id, owner_email=owner.email if owner else None,
                    scopes=list(t.scopes if t.scopes is not None else SCOPES), resources=list(t.resources or []),
                    restricted_grants=list(t.restricted_grants or []), created_by=t.created_by,
                    created_at=t.created_at, expires_at=t.expires_at, last_used_at=t.last_used_at,
                    revoked_at=t.revoked_at, status=_status(t))


def _signed_in_person(identity: Identity) -> User:
    """A person who signed in: tokens are made and revoked only by a sign-in, never by another token."""
    if not isinstance(identity, OidcIdentity) or identity.token is not None:
        raise HTTPException(status_code=403, detail="Tokens are managed by a person signed in, not by a token")
    return identity.user


def _make(db: Session, kind: str, body: TokenIn, *, user_id: Optional[str], workspace_id: Optional[str],
          created_by: str, max_days: Optional[int]) -> TokenCreated:
    if body.expires_in_days is None and kind == "personal":
        raise HTTPException(status_code=422, detail="A personal token has to expire")
    if body.expires_in_days is not None and max_days is not None and body.expires_in_days > max_days:
        raise HTTPException(status_code=422, detail=f"At most {max_days} days")
    raw = _new_token_secret(kind)
    token = ApiToken(
        kind=kind, user_id=user_id, workspace_id=workspace_id, token_hash=hash_token(raw), prefix=raw[:14],
        label=body.name.strip(), scopes=sorted(set(body.scopes), key=SCOPES.index),
        resources=sorted(set(body.resources), key=RESOURCES.index),
        restricted_grants=sorted(set(g.strip() for g in body.restricted_grants if g.strip())),
        created_by=created_by,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
                    if body.expires_in_days is not None else None),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return TokenCreated(**_out(db, token).model_dump(), token=raw)


# --------------------------------------------------------------------------- who am I

class ProfileWorkspace(BaseModel):
    id: str
    name: str
    is_global: bool
    roles: list[dict]                             # {id, name, via: "direct" | "group:<name>" | "membership"}
    permissions: dict[str, list[str]]


class Profile(BaseModel):
    auth_type: str                                # oidc | personal_token | robot_token
    user: Optional[dict] = None
    session: dict
    token: Optional[dict] = None
    groups: list[dict] = []
    workspaces: list[ProfileWorkspace] = []
    counts: dict = {}


def _workspace_view(db: Session, user: User, ws: Workspace, group_names: dict[str, str]) -> ProfileWorkspace:
    roles = []
    clause = (RoleBinding.subject_type == "user") & (RoleBinding.subject_id == user.id)
    if group_names:
        clause = clause | ((RoleBinding.subject_type == "group") & RoleBinding.subject_id.in_(list(group_names)))
    for binding, role in db.execute(select(RoleBinding, Role).join(Role, Role.id == RoleBinding.role_id)
                                    .where(RoleBinding.workspace_id == ws.id, clause)):
        via = "direct" if binding.subject_type == "user" else f"group:{group_names.get(binding.subject_id)}"
        roles.append({"id": role.id, "name": role.name, "via": via})
    # Site-wide grants of its current site, and administering that site (issue #26).
    from app.services.permissions import explain
    for src in explain(db, user, ws.id):
        if src["source"] == "site":
            roles.append({"id": src["role"].lower(), "name": src["role"], "via": f"site:{src['site']}:{src['group']}"})
        elif src["source"] == "site_administrator":
            roles.append({"id": "site_administrator", "name": "Site administrator", "via": f"site:{src['site']}"})
    from app.models.membership import Membership
    if db.scalar(select(Membership.id).where(Membership.workspace_id == ws.id, Membership.user_id == user.id)):
        roles.append({"id": "membership", "name": "Membership (before roles)", "via": "membership"})
    granted = effective_permissions(db, user, ws.id)
    if user.is_admin:
        granted = {"objects": {"read", "create", "modify", "delete"}, "tickets": {"read", "create", "modify", "delete"},
                   "documents": {"read", "create", "modify", "delete", "approve"}, "workspace": {"manage_members"}}
    order = ["read", "create", "modify", "delete", "approve", "manage_members"]
    return ProfileWorkspace(id=ws.id, name=ws.name, is_global=ws.is_global, roles=roles,
                            permissions={k: sorted(v, key=lambda a: order.index(a) if a in order else 99)
                                         for k, v in granted.items() if v})


@router.get("/me/profile", response_model=Profile)
def my_profile(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Everything about the caller: the account, the sign-in or token, groups, and each workspace's roles and
    what they allow."""
    scope = token_scope(identity)
    token_view = None
    if scope is not None and scope.token_id:
        t = db.get(ApiToken, scope.token_id)
        token_view = _out(db, t).model_dump(mode="json") if t else None
    if isinstance(identity, PatIdentity):
        ws = db.get(Workspace, identity.workspace_id)
        return Profile(auth_type="robot_token", session={"workspace_id": identity.workspace_id}, token=token_view,
                       workspaces=[ProfileWorkspace(id=ws.id, name=ws.name, is_global=ws.is_global, roles=[],
                                                    permissions={"token": sorted(scope.scopes)})] if ws else [])
    user = db.get(User, identity.user.id) or identity.user
    claims = identity.claims or {}
    session = {"issuer": claims.get("iss"), "subject": claims.get("sub"), "client": claims.get("azp"),
               "auth_time": claims.get("auth_time"), "expires": claims.get("exp"),
               "identity_provider": claims.get("identity_provider") or claims.get("idp"),
               "scopes": claims.get("scope"),
               "realm_roles": ((claims.get("realm_access") or {}).get("roles")) or []}
    group_uids = user_group_uids(db, user.id)
    groups = db.scalars(select(Group).where(Group.uid.in_(group_uids))).all() if group_uids else []
    group_names = {g.uid: g.name for g in groups}
    from app.routers.workspaces import list_my_workspaces
    reachable = {w.id for w in list_my_workspaces(identity, db)}
    if scope is not None and scope.workspace_id:
        reachable &= {scope.workspace_id}
    workspaces = [_workspace_view(db, identity.user, ws, group_names)
                  for ws in db.scalars(select(Workspace).where(Workspace.id.in_(reachable)).order_by(Workspace.name))]
    from app.models.device import Device
    counts = {
        "personal_tokens": db.query(ApiToken).filter(ApiToken.user_id == user.id, ApiToken.kind == "personal",
                                                     ApiToken.revoked_at.is_(None)).count(),
        "devices": db.query(Device).filter(Device.principal == user.id, Device.revoked_at.is_(None)).count(),
    }
    return Profile(
        auth_type="personal_token" if scope is not None else "oidc",
        user={"id": user.id, "email": user.email, "name": user.name, "username": user.username,
              "is_admin": bool(user.is_admin), "acting_as_admin": bool(identity.user.is_admin),
              "source": user.source, "active": user.active, "directory_dn": user.dn, "oidc_subject": user.oidc_sub,
              "created_at": user.created_at, "last_login_at": user.last_login_at, "synced_at": user.synced_at},
        session=session, token=token_view,
        groups=[{"uid": g.uid, "name": g.name, "source": g.source, "email": g.email,
                 "member_since": db.scalar(select(GroupMember.created_at).where(GroupMember.group_uid == g.uid,
                                                                                GroupMember.user_id == user.id))}
                for g in groups],
        workspaces=workspaces, counts=counts)


# --------------------------------------------------------------------------- personal access tokens

@router.get("/me/tokens", response_model=list[TokenOut])
def my_tokens(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    user = _signed_in_person(identity)
    return [_out(db, t) for t in db.scalars(select(ApiToken).where(ApiToken.user_id == user.id,
                                                                   ApiToken.kind == "personal")
                                            .order_by(ApiToken.created_at.desc()))]


@router.post("/me/tokens", response_model=TokenCreated, status_code=201)
def make_my_token(body: TokenIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A personal access token: it acts as you, with only the scopes chosen, never beyond your own roles."""
    user = _signed_in_person(identity)
    if "admin" in body.scopes and not user.is_admin:
        raise HTTPException(status_code=422, detail="Only an administrator's token may have the admin scope")
    if body.workspace_id:
        from app.routers.workspaces import list_my_workspaces
        if body.workspace_id not in {w.id for w in list_my_workspaces(identity, db)}:
            raise HTTPException(status_code=403, detail=f"You have no access to {body.workspace_id}")
    if body.restricted_grants:
        raise HTTPException(status_code=422, detail="A personal token sees what its owner may see")
    return _make(db, "personal", body, user_id=user.id, workspace_id=body.workspace_id, created_by=user.email,
                 max_days=PERSONAL_MAX_DAYS)


@router.delete("/me/tokens/{token_id}", status_code=204)
def revoke_my_token(token_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    user = _signed_in_person(identity)
    t = db.get(ApiToken, token_id)
    if t is None or t.user_id != user.id or t.kind != "personal":
        raise HTTPException(status_code=404, detail="No such token")
    _revoke(db, t, user.email)


def _revoke(db: Session, t: ApiToken, by: str) -> None:
    if t.revoked_at is None:
        t.revoked_at, t.revoked_by = datetime.now(timezone.utc), by
        db.commit()


# --------------------------------------------------------------------------- robot tokens

def _workspace_manager(db: Session, identity: Identity, workspace_id: str) -> User:
    user = _signed_in_person(identity)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="No such workspace")
    from app.services.permissions import has_permission
    if not has_permission(db, user, workspace_id, "manage_members", "workspace"):
        raise HTTPException(status_code=403, detail="Robot tokens are managed by the workspace's owners")
    return user


@router.get("/workspaces/{workspace_id}/robot-tokens", response_model=list[TokenOut])
def robot_tokens(workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    _workspace_manager(db, identity, workspace_id)
    return [_out(db, t) for t in db.scalars(select(ApiToken).where(ApiToken.workspace_id == workspace_id,
                                                                   ApiToken.kind == "robot")
                                            .order_by(ApiToken.created_at.desc()))]


@router.post("/workspaces/{workspace_id}/robot-tokens", response_model=TokenCreated, status_code=201)
def make_robot_token(workspace_id: str, body: TokenIn, identity: Identity = Depends(get_identity),
                     db: Session = Depends(get_db)):
    """A token for a machine that works for this workspace: a facility's daily-logbook uploader, a script."""
    user = _workspace_manager(db, identity, workspace_id)
    if body.workspace_id and body.workspace_id != workspace_id:
        raise HTTPException(status_code=422, detail="A robot token belongs to the workspace it is made in")
    return _make(db, "robot", body, user_id=None, workspace_id=workspace_id, created_by=user.email,
                 max_days=ROBOT_MAX_DAYS)


@router.delete("/workspaces/{workspace_id}/robot-tokens/{token_id}", status_code=204)
def revoke_robot_token(workspace_id: str, token_id: int, identity: Identity = Depends(get_identity),
                       db: Session = Depends(get_db)):
    user = _workspace_manager(db, identity, workspace_id)
    t = db.get(ApiToken, token_id)
    if t is None or t.workspace_id != workspace_id or t.kind != "robot":
        raise HTTPException(status_code=404, detail="No such token")
    _revoke(db, t, user.email)


# --------------------------------------------------------------------------- every token, for administrators

@router.get("/admin/tokens", response_model=list[TokenOut])
def all_tokens(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    user = _signed_in_person(identity)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrators only")
    return [_out(db, t) for t in db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc()))]


@router.delete("/admin/tokens/{token_id}", status_code=204)
def admin_revoke(token_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    user = _signed_in_person(identity)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrators only")
    t = db.get(ApiToken, token_id)
    if t is None:
        raise HTTPException(status_code=404, detail="No such token")
    _revoke(db, t, user.email)
