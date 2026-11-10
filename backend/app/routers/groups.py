from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, PatIdentity, get_identity, require_permission
from app.db import get_db
from app.models.group import Group, GroupMember, GroupAdministrator
from app.models.user import User
from app.schemas.group import (DirectoryStatusOut, GroupCreate, GroupMemberOut, GroupMembersIn, GroupOut,
                               GroupUpdate, GroupAdministratorOut, GroupAdministratorIn)
from app.services import local_groups, site_group_grants
from app.services.directory import provider_name
from app.services.directory_sync import sync_directory
from app.services.permissions import resolve_permission

router = APIRouter(prefix="/v1", tags=["directory"])


def _may_read_group(db: Session, identity: Identity, group: Group, workspace_id: Optional[str]) -> None:
    if local_groups.is_group_administrator(db, identity, group) and getattr(identity, "token", None) is None:
        return
    if isinstance(identity, PatIdentity):
        if identity.workspace_id == workspace_id and identity.may("read"):
            return
    elif workspace_id and (identity.token is None or
                           identity.token.workspace_id in (None, workspace_id)) and \
            (identity.token is None or identity.token.may("read")) and \
            resolve_permission(db, identity.user, workspace_id, "read", "objects"):
        return
    raise HTTPException(status_code=403, detail="Not permitted")


@router.get("/groups/mine", response_model=list[GroupOut])
def my_groups(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    if not isinstance(identity, OidcIdentity) or identity.token is not None:
        raise HTTPException(status_code=403, detail="Sign in to manage groups")
    groups = db.scalars(select(Group).join(GroupAdministrator, GroupAdministrator.group_uid == Group.uid).where(
        GroupAdministrator.user_id == identity.user.id, Group.source == "local").order_by(Group.name)).all()
    return [_out(db, g) for g in groups]


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
            home_site_id=g.home_site_id, site_grants=site_group_grants.of_group(db, g.uid),
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
    from app.services import site_group_grants
    return GroupOut(uid=g.uid, dn=g.dn, name=g.name, description=g.description, email=g.email, source=g.source,
                    active=g.active, member_count=count, workspaces=local_groups.workspaces_of(db, g.uid),
                    home_site_id=g.home_site_id, site_grants=site_group_grants.of_group(db, g.uid))


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(body: GroupCreate, workspace_id: str = Depends(require_permission("read")),
                 identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A group made here, by whoever manages the current workspace; or owned by a site, by an administrator of that
    site. Making it, or putting people in it, gives nobody access: a role is given to it on Access."""
    from app.routers.workspaces import _require_owner_or_admin
    if body.home_site_id:
        from app.routers.sites import _site_manager
        _site_manager(identity, db, body.home_site_id)
    else:
        _require_owner_or_admin(workspace_id, identity, db)
    group = local_groups.create(db, body.name, body.description, body.home_site_id)
    if isinstance(identity, OidcIdentity):
        db.add(GroupAdministrator(group_uid=group.uid, user_id=identity.user.id))
    db.commit()
    return _out(db, group)


@router.get("/groups/{uid}/administrators", response_model=list[GroupAdministratorOut])
def list_group_administrators(uid: str, workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
                              identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    _may_read_group(db, identity, _group(db, uid), workspace_id)
    rows = db.execute(select(User).join(GroupAdministrator, GroupAdministrator.user_id == User.id).where(
        GroupAdministrator.group_uid == uid).order_by(User.email)).scalars().all()
    return [GroupAdministratorOut(user_id=u.id, email=u.email, name=u.name) for u in rows]


@router.post("/groups/{uid}/administrators", response_model=GroupAdministratorOut, status_code=201)
def add_group_administrator(uid: str, body: GroupAdministratorIn,
                            workspace_id: str = Depends(require_permission("read")),
                            identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    group = _group(db, uid)
    local_groups.require_manage(db, identity, group, workspace_id)
    from app.services.invitations import person
    email = body.email.strip().lower()
    from app.services.invitations import ADDRESS
    if not ADDRESS.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    user, _ = person(db, email)
    if db.scalar(select(GroupAdministrator.id).where(
        GroupAdministrator.group_uid == uid, GroupAdministrator.user_id == user.id)):
        raise HTTPException(status_code=409, detail="Already a group administrator")
    db.add(GroupAdministrator(group_uid=uid, user_id=user.id))
    db.commit()
    return GroupAdministratorOut(user_id=user.id, email=user.email, name=user.name)


@router.delete("/groups/{uid}/administrators/{user_id}", status_code=204)
def remove_group_administrator(uid: str, user_id: str,
                               workspace_id: str = Depends(require_permission("read")),
                               identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    group = _group(db, uid)
    local_groups.require_manage(db, identity, group, workspace_id)
    row = db.scalar(select(GroupAdministrator).where(
        GroupAdministrator.group_uid == uid, GroupAdministrator.user_id == user_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Group administrator not found")
    db.delete(row)
    db.commit()


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
def add_group_members(uid: str, body: GroupMembersIn, workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
                      identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """People into a local group by e-mail address, added first when nobody knows them yet; told by e-mail when
    asked. They have, here and wherever the group holds a role, what the group has."""
    from app.services import invitations
    group = _group(db, uid)
    local_groups.require_manage_members(db, identity, group, workspace_id)
    bound_workspaces = local_groups.workspaces_of(db, uid)
    invite_workspace = workspace_id if workspace_id in bound_workspaces else next(iter(bound_workspaces), None)
    user = identity.user if isinstance(identity, OidcIdentity) else None
    try:
        if invite_workspace:
            out = invitations.invite(db, invite_workspace, body.emails, None, created_by=user.id if user else None,
                                     inviter=(user.name or user.email) if user else None, send_email=body.send_email,
                                     note=body.message, group=group)
        else:
            out = invitations.invite_group_only(db, group, body.emails,
                                                inviter=(user.name or user.email) if user else None,
                                                send_email=body.send_email, note=body.message)
    except invitations.InviteError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()
    return out


@router.delete("/groups/{uid}/members/{user_id}", status_code=204)
def remove_group_member(uid: str, user_id: str, workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
                        identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    group = _group(db, uid)
    local_groups.require_manage_members(db, identity, group, workspace_id)
    if not local_groups.remove_member(db, group, user_id):
        raise HTTPException(status_code=404, detail="Not a member of this group")
    db.commit()


@router.get("/groups/{uid}/members", response_model=list[GroupMemberOut])
def list_group_members(
    uid: str,
    workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _may_read_group(db, identity, _group(db, uid), workspace_id)
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
