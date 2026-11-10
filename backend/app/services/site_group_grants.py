"""Site-wide group grants and site-owned groups (issue #26, docs/administration-scopes.md).

A site-wide grant gives a group one role for a site: its members have it in the site workspace and in every
facility whose current site that is, those added later included. It is never copied into a facility's role
bindings: services/permissions.py works it out from the site relationship, so a facility joining a site has the
site's grants at once and one leaving loses them at once.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.models.role import Role, RoleBinding, SiteGroupRoleBinding
from app.models.user import User
from app.models.workspace import Workspace

# General access levels only. Workspace administrator and Owner stay separate administrative assignments; a custom
# or package role is not given site-wide until it has been reviewed (it may reach restricted classes).
SITE_ROLES = ("viewer", "reporter", "agent", "approver", "contributor", "curator")


def scope(db: Session, site_id: str) -> list[str]:
    """The workspaces a site-wide grant reaches now: the site and its current facilities."""
    return [site_id, *db.scalars(select(Workspace.id).where(Workspace.site_id == site_id).order_by(Workspace.id))]


def in_site_scope(db: Session, site_id: str, workspace_id: str) -> bool:
    ws = db.get(Workspace, workspace_id)
    return ws is not None and (ws.id == site_id or ws.site_id == site_id)


def check_direct_grant(db: Session, group: Group, workspace_id: str) -> None:
    """A site-owned group is given direct roles only at its site and the site's current facilities."""
    if group.home_site_id and not in_site_scope(db, group.home_site_id, workspace_id):
        raise HTTPException(status_code=422, detail=f"{group.name} belongs to the site {group.home_site_id}: it can "
                                                    f"have roles only there and in its facilities, not in {workspace_id}")


def _out(db: Session, g: SiteGroupRoleBinding) -> dict:
    group, role = db.get(Group, g.group_uid), db.get(Role, g.role_id)
    return {"id": g.id, "site_id": g.site_id, "group_uid": g.group_uid, "group_name": group.name if group else g.group_uid,
            "group_active": bool(group and group.active), "group_source": group.source if group else None,
            "role_id": g.role_id, "role_name": role.name if role else g.role_id, "created_by": g.created_by,
            "created_at": g.created_at}


def of_site(db: Session, site_id: str) -> list[dict]:
    rows = db.scalars(select(SiteGroupRoleBinding).where(SiteGroupRoleBinding.site_id == site_id)
                      .order_by(SiteGroupRoleBinding.id))
    return [_out(db, g) for g in rows]


def of_group(db: Session, group_uid: str) -> list[dict]:
    return [_out(db, g) for g in db.scalars(select(SiteGroupRoleBinding).where(
        SiteGroupRoleBinding.group_uid == group_uid).order_by(SiteGroupRoleBinding.id))]


def inherited(db: Session, workspace_id: str) -> list[dict]:
    """What a workspace has from its current site: shown on its Access page, removable only at the site."""
    from app.services.permissions import current_site
    site_id = current_site(db, workspace_id)
    return of_site(db, site_id) if site_id else []


def preview(db: Session, site_id: str, group_uid: str, role_id: str) -> dict:
    """Who would have the role, and where, before it is given or taken away."""
    group, role = _valid(db, site_id, group_uid, role_id)
    people = db.execute(select(User.id, User.email, User.name).join(GroupMember, GroupMember.user_id == User.id)
                        .where(GroupMember.group_uid == group_uid).order_by(User.email)).all()
    return {"site_id": site_id, "group_uid": group_uid, "group_name": group.name, "group_active": group.active,
            "role_id": role.id, "role_name": role.name, "workspaces": scope(db, site_id),
            "people": [{"user_id": u, "email": e, "name": n} for u, e, n in people]}


def _valid(db: Session, site_id: str, group_uid: str, role_id: str) -> tuple[Group, Role]:
    group = db.get(Group, group_uid)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.home_site_id and group.home_site_id != site_id:
        raise HTTPException(status_code=422, detail=f"{group.name} belongs to the site {group.home_site_id}")
    if role_id not in SITE_ROLES:
        raise HTTPException(status_code=422, detail=f"Only these roles can be given site-wide: {', '.join(SITE_ROLES)}. "
                                                    "Workspace administrator and Owner are given workspace by workspace.")
    from app.services.roles import ensure_system_roles
    ensure_system_roles(db)
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return group, role


def grant(db: Session, site_id: str, group_uid: str, role_id: str, actor: Optional[str]) -> dict:
    group, role = _valid(db, site_id, group_uid, role_id)
    if not group.active:
        raise HTTPException(status_code=422, detail=f"{group.name} is deactivated: it grants nothing")
    if db.scalar(select(SiteGroupRoleBinding.id).where(SiteGroupRoleBinding.site_id == site_id,
                                                       SiteGroupRoleBinding.group_uid == group_uid,
                                                       SiteGroupRoleBinding.role_id == role_id)) is not None:
        raise HTTPException(status_code=409, detail=f"{group.name} already has {role.name} at this site")
    row = SiteGroupRoleBinding(site_id=site_id, group_uid=group_uid, role_id=role_id, created_by=actor,
                               created_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    return _out(db, row)


def revoke(db: Session, site_id: str, grant_id: int) -> None:
    row = db.get(SiteGroupRoleBinding, grant_id)
    if row is None or row.site_id != site_id:
        raise HTTPException(status_code=404, detail="No such site-wide grant")
    db.delete(row)
    db.flush()


def out_of_scope_after_move(db: Session, workspace_id: str, new_site_id: Optional[str]) -> list[dict]:
    """Direct grants in a facility to groups owned by a site it would no longer be at: settled before it moves."""
    rows = db.execute(select(RoleBinding, Group).join(Group, Group.uid == RoleBinding.subject_id).where(
        RoleBinding.workspace_id == workspace_id, RoleBinding.subject_type == "group",
        Group.home_site_id.isnot(None), Group.home_site_id != (new_site_id or ""))).all()
    return [{"binding_id": b.id, "group_uid": g.uid, "group_name": g.name, "home_site_id": g.home_site_id,
             "role_id": b.role_id} for b, g in rows]


def _members(db: Session, group_uid: str) -> list[str]:
    return list(db.scalars(select(User.email).join(GroupMember, GroupMember.user_id == User.id)
                           .where(GroupMember.group_uid == group_uid).order_by(User.email)))


def move_preview(db: Session, workspace_id: str, new_site_id: Optional[str]) -> dict:
    """What moving a facility to another site (or to none) does to access, before it is done: the site-wide grants it
    stops inheriting and those it starts to, with the people they reach, and the direct grants to groups of its old
    site that block the move until they are settled."""
    ws = db.get(Workspace, workspace_id)
    old = ws.site_id if ws is not None else None

    def grants(site_id: Optional[str]) -> list[dict]:
        if not site_id:
            return []
        out = []
        for g in of_site(db, site_id):
            if g["group_active"]:
                out.append({**g, "people": _members(db, g["group_uid"])})
        return out

    key = lambda g: (g["group_uid"], g["role_id"])  # noqa: E731
    before, after = grants(old), grants(new_site_id)
    kept = {key(g) for g in before} & {key(g) for g in after}
    return {"workspace_id": workspace_id, "from_site": old, "to_site": new_site_id or None,
            "loses": [g for g in before if key(g) not in kept], "gains": [g for g in after if key(g) not in kept],
            "blocked": out_of_scope_after_move(db, workspace_id, new_site_id)}


def move_group_preview(db: Session, group: Group, new_site_id: Optional[str]) -> dict:
    """Moving a local group to a site, or back to the installation: which of its grants would be out of the new scope
    (they block the move), and who would govern it from then on."""
    blocked = []
    if new_site_id:
        for b in db.scalars(select(RoleBinding).where(RoleBinding.subject_type == "group",
                                                      RoleBinding.subject_id == group.uid)):
            if not in_site_scope(db, new_site_id, b.workspace_id):
                blocked.append({"kind": "direct", "workspace_id": b.workspace_id, "role_id": b.role_id})
        for g in db.scalars(select(SiteGroupRoleBinding).where(SiteGroupRoleBinding.group_uid == group.uid,
                                                               SiteGroupRoleBinding.site_id != new_site_id)):
            blocked.append({"kind": "site", "site_id": g.site_id, "role_id": g.role_id})
    return {"group_uid": group.uid, "group_name": group.name, "from_site": group.home_site_id,
            "to_site": new_site_id or None, "blocked": blocked,
            "governed_by": f"the administrators of the site {new_site_id}" if new_site_id
            else "the installation's administrators, and those who manage every workspace where it has a role"}
