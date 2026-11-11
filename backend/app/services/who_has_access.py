"""Who can get into a workspace, and how.

Access has seven routes and no page used to show them together: administrator of the installation, a role of
one's own, a group's role here, a group's role site-wide at the workspace's site, the per-person area permissions
(legacy memberships), administering the site, and the workspace's defaults for anyone signed in. This lists every
person any route reaches, with what they may do — computed by `effective_permissions`, the very function that
decides each request, so the list cannot disagree with what happens — and why (`explain`).

Shown on Access to those who manage it, and behind Ask ARGUS's `workspace_access` lookup: there the asker is the
`Viewer` bound for the request, and whoever does not manage access hears only about themselves.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.models.membership import Membership
from app.models.role import RoleBinding, SiteGroupRoleBinding
from app.models.user import User
from app.models.workspace import SiteAdministrator, Workspace
from app.services.permissions import RESOURCES, current_site, effective_permissions, explain

FULL = {"objects": ["read", "create", "modify", "delete"], "tickets": ["read", "create", "modify", "delete"],
        "documents": ["read", "create", "modify", "delete", "approve"], "workspace": ["manage_members"]}
ORDER = ("read", "create", "modify", "delete", "approve", "manage_members")


@dataclass(frozen=True)
class Viewer:
    """Who is asking, for lookups that answer differently per person. `user_id` is None for a token that is not a
    person; `may_manage` is whether they manage access to the workspace being asked about."""
    user_id: Optional[str]
    may_manage: bool


_VIEWER: ContextVar[Optional[Viewer]] = ContextVar("argus_viewer", default=None)


def set_viewer(viewer: Optional[Viewer]) -> None:
    _VIEWER.set(viewer)


def current_viewer() -> Optional[Viewer]:
    return _VIEWER.get()


def viewer_for(db: Session, identity, workspace_id: str) -> Viewer:
    """The Viewer an identity is in a workspace: the same check as the Access page's own."""
    from fastapi import HTTPException
    from app.routers.workspaces import _require_owner_or_admin
    user = getattr(identity, "user", None)
    try:
        _require_owner_or_admin(workspace_id, identity, db)
        manages = True
    except HTTPException:
        manages = False
    return Viewer(user_id=user.id if user is not None else None, may_manage=manages)


def _sorted(rights: dict) -> dict[str, list[str]]:
    return {r: sorted(rights.get(r) or [], key=lambda a: ORDER.index(a) if a in ORDER else 99) for r in RESOURCES
            if rights.get(r)}


def _candidates(db: Session, workspace_id: str, site_id: Optional[str]) -> set[str]:
    ids: set[str] = set(db.scalars(select(User.id).where(User.is_admin.is_(True))))
    ids |= set(db.scalars(select(RoleBinding.subject_id).where(
        RoleBinding.workspace_id == workspace_id, RoleBinding.subject_type == "user")))
    groups = set(db.scalars(select(RoleBinding.subject_id).where(
        RoleBinding.workspace_id == workspace_id, RoleBinding.subject_type == "group")))
    if site_id:
        groups |= set(db.scalars(select(SiteGroupRoleBinding.group_uid).where(SiteGroupRoleBinding.site_id == site_id)))
        ids |= set(db.scalars(select(SiteAdministrator.user_id).join(Workspace, Workspace.id == SiteAdministrator.site_id)
                              .where(SiteAdministrator.site_id == site_id, Workspace.role == "site")))
    if groups:
        ids |= set(db.scalars(select(GroupMember.user_id).join(Group, Group.uid == GroupMember.group_uid).where(
            GroupMember.group_uid.in_(groups), Group.active.is_(True))))
    ids |= set(db.scalars(select(Membership.user_id).where(Membership.workspace_id == workspace_id)))
    return ids


def _signed_in(user: User) -> bool:
    return not (user.oidc_sub is None and user.last_login_at is None and user.source == "oidc")


def person_access(db: Session, user: User, workspace_id: str) -> Optional[dict]:
    """One person's rights here and the routes that give them; None when no route reaches them (the workspace's
    defaults for anyone signed in are reported apart)."""
    rights = FULL if user.is_admin else _sorted({r: set(a) for r, a in effective_permissions(db, user, workspace_id).items()})
    if not any(rights.values()):
        return None
    return {"user_id": user.id, "email": user.email, "name": user.name, "signed_in": _signed_in(user), "active": bool(user.active),
            "installation_administrator": bool(user.is_admin), "rights": dict(rights),
            "routes": explain(db, user, workspace_id)}


def defaults(workspace: Workspace) -> dict[str, list[str]]:
    """What anyone signed in gets here when no route gives them anything (resolve_permission's fallback)."""
    from app.services.permissions import RESOURCE_SUFFIX
    out: dict[str, list[str]] = {}
    for resource, suffix in RESOURCE_SUFFIX.items():
        actions = [a for a in ("read", "create", "modify", "delete") if getattr(workspace, f"default_can_{a}{suffix}")]
        if resource == "documents" and workspace.default_can_approve_documents:
            actions.append("approve")
        if actions:
            out[resource] = actions
    return out


def who_has_access(db: Session, workspace_id: str) -> dict:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise KeyError(workspace_id)
    site_id = current_site(db, workspace_id)
    people = []
    for user in db.scalars(select(User).where(User.id.in_(_candidates(db, workspace_id, site_id)))):
        entry = person_access(db, user, workspace_id)
        if entry is not None:
            people.append(entry)
    # Those who reach it by their own grants first, the installation's administrators after: there are many of
    # them, and they reach every workspace.
    people.sort(key=lambda p: (p["installation_administrator"] and len(p["routes"]) == 1,
                               (p["email"] or p["name"] or "").lower()))
    anyone = defaults(workspace)
    return {
        "workspace_id": workspace.id, "workspace_name": workspace.name, "site_id": site_id,
        "people": people, "anyone_signed_in": anyone,
        "counts": {"people": len(people),
                   "installation_administrators": sum(1 for p in people if p["installation_administrator"]),
                   "manage_access": sum(1 for p in people if "manage_members" in p["rights"].get("workspace", [])),
                   "anyone_signed_in": bool(anyone)},
    }
