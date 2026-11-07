from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.group import (DirectoryStatusOut, GroupCreate, GroupMemberOut, GroupMembersIn, GroupOut,
                               GroupUpdate)
from app.services import local_groups
from app.services.directory import provider_name
from app.services.directory_sync import sync_directory

router = APIRouter(prefix="/v1", tags=["directory"])


@router.get("/groups", response_model=list[GroupOut])
def list_groups(
    search: Optional[str] = None,
    include_inactive: bool = False,
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """Groups are organisation-wide, not workspace-scoped — an INFN service
    exists once and is referenced from wherever it's relevant. Anyone who
    can read may list them, since they feed the assignment pickers."""
    stmt = select(Group)
    if not include_inactive:
        stmt = stmt.where(Group.active.is_(True))
    if search:
        stmt = stmt.where(Group.name.ilike(f"%{search}%"))
    groups = db.scalars(stmt.order_by(Group.name)).all()

    counts = dict(
        db.execute(
            select(GroupMember.group_uid, func.count())
            .group_by(GroupMember.group_uid)
        ).all()
    )
    return [
        GroupOut(
            uid=g.uid, dn=g.dn, name=g.name, description=g.description, email=g.email,
            source=g.source, active=g.active, member_count=counts.get(g.uid, 0),
            workspaces=local_groups.workspaces_of(db, g.uid),
        )
        for g in groups
    ]


def _group(db: Session, uid: str) -> Group:
    group = db.get(Group, uid)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def _out(db: Session, g: Group) -> GroupOut:
    count = db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.group_uid == g.uid)) or 0
    return GroupOut(uid=g.uid, dn=g.dn, name=g.name, description=g.description, email=g.email, source=g.source,
                    active=g.active, member_count=count, workspaces=local_groups.workspaces_of(db, g.uid))


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(body: GroupCreate, workspace_id: str = Depends(require_permission("read")),
                 identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A group made here, by whoever manages the current workspace. Give it a role on Access."""
    from app.routers.workspaces import _require_owner_or_admin
    _require_owner_or_admin(workspace_id, identity, db)
    group = local_groups.create(db, body.name, body.description)
    db.commit()
    return _out(db, group)


@router.patch("/groups/{uid}", response_model=GroupOut)
def update_group(uid: str, body: GroupUpdate, workspace_id: str = Depends(require_permission("read")),
                 identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Rename a local group, describe it, or deactivate it (its roles then stop applying; nothing is deleted)."""
    group = _group(db, uid)
    local_groups.require_manage(db, identity, group, workspace_id)
    if body.name is not None and body.name.strip():
        group.name = body.name.strip()
    if body.description is not None:
        group.description = body.description.strip() or None
    if body.active is not None:
        group.active = body.active
    db.commit()
    return _out(db, group)


@router.post("/groups/{uid}/members")
def add_group_members(uid: str, body: GroupMembersIn, workspace_id: str = Depends(require_permission("read")),
                      identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """People into a local group by e-mail address, added first when nobody knows them yet; told by e-mail when
    asked. They have, here and wherever the group holds a role, what the group has."""
    from app.services import invitations
    group = _group(db, uid)
    local_groups.require_manage(db, identity, group, workspace_id)
    user = identity.user if isinstance(identity, OidcIdentity) else None
    try:
        out = invitations.invite(db, workspace_id, body.emails, None, created_by=user.id if user else None,
                                 inviter=(user.name or user.email) if user else None, send_email=body.send_email,
                                 note=body.message, group=group)
    except invitations.InviteError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()
    return out


@router.delete("/groups/{uid}/members/{user_id}", status_code=204)
def remove_group_member(uid: str, user_id: str, workspace_id: str = Depends(require_permission("read")),
                        identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    group = _group(db, uid)
    local_groups.require_manage(db, identity, group, workspace_id)
    if not local_groups.remove_member(db, group, user_id):
        raise HTTPException(status_code=404, detail="Not a member of this group")
    db.commit()


@router.get("/groups/{uid}/members", response_model=list[GroupMemberOut])
def list_group_members(
    uid: str,
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    if db.get(Group, uid) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    rows = db.execute(
        select(User, GroupMember)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_uid == uid)
        .order_by(User.name)
    ).all()
    return [
        GroupMemberOut(
            user_id=u.id, email=u.email, name=u.name, username=u.username,
            active=u.active, source=m.source,
        )
        for u, m in rows
    ]


@router.get("/directory/status", response_model=DirectoryStatusOut)
def directory_status(
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    provider = provider_name()
    return DirectoryStatusOut(
        provider=provider,
        # The embedded directory is fictional; say so plainly wherever it's
        # in use so nobody mistakes it for INFN's real organisation.
        is_test_data=provider == "embedded",
        groups=db.scalar(select(func.count()).select_from(Group)) or 0,
        active_groups=db.scalar(
            select(func.count()).select_from(Group).where(Group.active.is_(True))
        ) or 0,
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        last_synced_at=db.scalar(select(Group.synced_at).order_by(Group.synced_at.desc())),
    )


@router.post("/directory/sync")
def trigger_directory_sync(
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Admin-only: a sync rewrites people and groups for the whole instance,
    which is wider than any single workspace's authority."""
    if not isinstance(identity, OidcIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Directory sync is restricted to admins")
    return sync_directory(db)
