"""Groups made in ARGUS (source "local"), beside the ones a directory brings: who may change them, and the changes.

A group is installation-wide and may hold roles in several workspaces, so whoever changes its members changes
who may do what in all of them. A local group is therefore changed by an administrator, or by someone who manages
every workspace where it holds a role (a new group, holding none yet, by whoever manages the workspace they are
in). A directory's group is the directory's: read here, changed there.
"""
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember, GroupAdministrator
from app.models.role import RoleBinding


def workspaces_of(db: Session, group_uid: str) -> list[str]:
    return sorted(set(db.scalars(select(RoleBinding.workspace_id).where(
        RoleBinding.subject_type == "group", RoleBinding.subject_id == group_uid))))


def sites_of(db: Session, group_uid: str) -> list[str]:
    """The sites where it holds a role site-wide (issue #26)."""
    from app.models.role import SiteGroupRoleBinding
    return sorted(set(db.scalars(select(SiteGroupRoleBinding.site_id).where(
        SiteGroupRoleBinding.group_uid == group_uid))))


def require_manage(db: Session, identity, group: Group, workspace_id: Optional[str]) -> None:
    from app.routers.workspaces import _require_owner_or_admin
    if group.source != "local":
        raise HTTPException(status_code=409, detail=f"{group.name} comes from the directory ({group.source}): "
                                                    "change its members there")
    user = getattr(identity, "user", None)
    if user is not None and user.is_admin and getattr(identity, "token", None) is None:
        return
    # Whoever changes its members changes access wherever it holds a role, directly or site-wide; a group that
    # holds none yet is governed where it belongs: its site, or the workspace it is changed from.
    where = sorted(set(workspaces_of(db, group.uid)) | set(sites_of(db, group.uid))) or (
        [group.home_site_id] if group.home_site_id else [workspace_id] if workspace_id else [])
    if not where:
        raise HTTPException(status_code=403, detail="Not permitted")
    for ws in where:
        try:
            _require_owner_or_admin(ws, identity, db)
        except HTTPException:
            raise HTTPException(status_code=403, detail=f"{group.name} holds a role in workspace {ws}, which you do "
                                                        "not manage: an administrator can change it")


def is_group_administrator(db: Session, identity, group: Group) -> bool:
    user = getattr(identity, "user", None)
    return user is not None and db.scalar(select(GroupAdministrator.id).where(
        GroupAdministrator.group_uid == group.uid, GroupAdministrator.user_id == user.id)) is not None


def require_manage_members(db: Session, identity, group: Group, workspace_id: Optional[str]) -> None:
    if group.source != "local":
        raise HTTPException(status_code=409, detail=f"{group.name} is directory-managed: change its members there")
    if getattr(identity, "token", None) is None and is_group_administrator(db, identity, group):
        return
    require_manage(db, identity, group, workspace_id)


def create(db: Session, name: str, description: Optional[str], home_site_id: Optional[str] = None) -> Group:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="A group needs a name")
    if db.scalar(select(Group.uid).where(Group.name == name, Group.active.is_(True))) is not None:
        raise HTTPException(status_code=409, detail=f"There is already a group called {name}")
    group = Group(uid=str(uuid.uuid4()), name=name, description=(description or "").strip() or None, source="local",
                  active=True, home_site_id=home_site_id or None)
    db.add(group)
    db.flush()
    return group


def remove_member(db: Session, group: Group, user_id: str) -> bool:
    row = db.scalar(select(GroupMember).where(GroupMember.group_uid == group.uid, GroupMember.user_id == user_id))
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
