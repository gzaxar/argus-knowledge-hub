from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.models.group import Group
from app.models.role import Role, RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.role import (
    EffectivePermissionsOut,
    InvitationIn,
    InvitationOut,
    RoleBindingCreate,
    RoleBindingOut,
    RoleOut,
)
from app.services.permissions import effective_permissions
from app.services.roles import ensure_system_roles

router = APIRouter(prefix="/v1", tags=["roles"])


def _require_manage_members(workspace_id: str, identity: Identity, db: Session) -> None:
    from app.routers.workspaces import _require_owner_or_admin

    _require_owner_or_admin(workspace_id, identity, db)


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    workspace_id: str = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """Anyone who can read may see the catalogue — a binding shows a role
    name, so the name has to be resolvable by whoever can see the binding."""
    ensure_system_roles(db)
    db.commit()
    return db.scalars(select(Role).order_by(Role.rank)).all()


def _subject_label(db: Session, binding: RoleBinding) -> tuple[str, bool]:
    if binding.subject_type == "user":
        user = db.get(User, binding.subject_id)
        if user is None:
            return binding.subject_id, False
        return user.name or user.email, user.active
    group = db.get(Group, binding.subject_id)
    if group is None:
        return binding.subject_id, False
    return group.name, group.active


@router.get("/workspaces/{workspace_id}/bindings", response_model=list[RoleBindingOut])
def list_bindings(
    workspace_id: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_manage_members(workspace_id, identity, db)
    rows = db.execute(
        select(RoleBinding, Role)
        .join(Role, Role.id == RoleBinding.role_id)
        .where(RoleBinding.workspace_id == workspace_id)
    ).all()
    out = []
    for binding, role in rows:
        label, active = _subject_label(db, binding)
        out.append(RoleBindingOut(
            id=binding.id,
            workspace_id=binding.workspace_id,
            subject_type=binding.subject_type,
            subject_id=binding.subject_id,
            subject_label=label,
            subject_active=active,
            subject_pending=_pending(db, binding),
            role_id=role.id,
            role_name=role.name,
            created_at=binding.created_at,
        ))
    return out


def _pending(db: Session, binding: RoleBinding) -> bool:
    """A person added by e-mail who has not signed in yet."""
    if binding.subject_type != "user":
        return False
    user = db.get(User, binding.subject_id)
    return user is not None and user.oidc_sub is None and user.last_login_at is None and user.source == "oidc"


@router.get("/workspaces/{workspace_id}/access-events")
def access_events(
    workspace_id: str,
    limit: int = 100,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """The recorded changes to access here, with those at this workspace's site that reach it (issue #26)."""
    from app.services import access_log
    _require_manage_members(workspace_id, identity, db)
    return access_log.for_workspace(db, workspace_id, limit)


@router.get("/workspaces/{workspace_id}/inherited-grants")
def inherited_grants(
    workspace_id: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """The roles groups have here because they have them site-wide at this workspace's current site. Listed with
    the workspace's own grants, removable only at the site (issue #26)."""
    from app.services import site_group_grants
    _require_manage_members(workspace_id, identity, db)
    return site_group_grants.inherited(db, workspace_id)


@router.post("/workspaces/{workspace_id}/invitations", response_model=InvitationOut)
def invite_people(
    workspace_id: str,
    body: InvitationIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Give people this role here by their e-mail address, before they have ever signed in: each one not known yet
    is added, and their first sign-in with that address claims the account and the access. With `send_email` they
    are told, with a link to ARGUS; what could not be sent is said per address and stops nothing."""
    from app.models.group import Group
    from app.services import invitations, local_groups
    _require_manage_members(workspace_id, identity, db)
    user = identity.user if isinstance(identity, OidcIdentity) else None
    group = None
    if body.group_uid:
        group = db.get(Group, body.group_uid)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found")
        local_groups.require_manage(db, identity, group, workspace_id)
        if body.role_id:
            from app.services.site_group_grants import check_direct_grant
            check_direct_grant(db, group, workspace_id)
    elif body.new_group and body.new_group.strip():
        group = local_groups.create(db, body.new_group, None)
    try:
        out = invitations.invite(db, workspace_id, body.emails, body.role_id,
                                 created_by=user.id if user else None,
                                 inviter=(user.name or user.email) if user else None,
                                 send_email=body.send_email, note=body.message, group=group)
    except invitations.InviteError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    from app.services import access_log
    actor = access_log.actor_of(identity)
    if group is not None and out.get("group_granted"):
        access_log.record(db, "role.granted", actor, workspace_id=workspace_id, subject_type="group",
                          subject_id=group.uid, role_id=out.get("role_id"))
    for p in out["people"]:
        if p.get("added"):
            access_log.record(db, "person.invited", actor, workspace_id=workspace_id, subject_type="user",
                              subject_id=p["user_id"], email=p["email"])
        if group is not None and p.get("joined"):
            access_log.record(db, "group.member_added", actor, group_uid=group.uid, subject_type="user",
                              subject_id=p["user_id"])
        elif group is None and p.get("granted"):
            access_log.record(db, "role.granted", actor, workspace_id=workspace_id, subject_type="user",
                              subject_id=p["user_id"], role_id=out.get("role_id"))
    db.commit()
    return out


@router.post("/workspaces/{workspace_id}/bindings", response_model=RoleBindingOut, status_code=201)
def create_binding(
    workspace_id: str,
    body: RoleBindingCreate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_manage_members(workspace_id, identity, db)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ensure_system_roles(db)
    role = db.get(Role, body.role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    if body.subject_type == "user":
        if db.get(User, body.subject_id) is None:
            raise HTTPException(status_code=404, detail="User not found")
    elif body.subject_type == "group":
        group = db.get(Group, body.subject_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found")
        from app.services.site_group_grants import check_direct_grant
        check_direct_grant(db, group, workspace_id)
    else:
        raise HTTPException(status_code=422, detail="subject_type must be 'user' or 'group'")

    existing = db.scalar(
        select(RoleBinding).where(
            RoleBinding.workspace_id == workspace_id,
            RoleBinding.subject_type == body.subject_type,
            RoleBinding.subject_id == body.subject_id,
            RoleBinding.role_id == body.role_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="That role is already granted to this subject")

    binding = RoleBinding(
        workspace_id=workspace_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        role_id=body.role_id,
        created_at=datetime.now(timezone.utc),
        created_by=identity.user.id if isinstance(identity, OidcIdentity) else None,
    )
    db.add(binding)
    from app.services import access_log
    access_log.record(db, "role.granted", access_log.actor_of(identity), workspace_id=workspace_id,
                      subject_type=body.subject_type, subject_id=body.subject_id, role_id=body.role_id)
    db.commit()
    db.refresh(binding)
    label, active = _subject_label(db, binding)
    return RoleBindingOut(
        id=binding.id, workspace_id=workspace_id, subject_type=binding.subject_type,
        subject_id=binding.subject_id, subject_label=label, subject_active=active,
        subject_pending=_pending(db, binding),
        role_id=role.id, role_name=role.name, created_at=binding.created_at,
    )


@router.delete("/workspaces/{workspace_id}/bindings/{binding_id}", status_code=204)
def delete_binding(
    workspace_id: str,
    binding_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_manage_members(workspace_id, identity, db)
    binding = db.get(RoleBinding, binding_id)
    if binding is None or binding.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Binding not found")

    # Removing the last thing that grants member management would lock the
    # workspace so only an instance admin could rescue it.
    if isinstance(identity, OidcIdentity) and not identity.user.is_admin:
        role = db.get(Role, binding.role_id)
        grants_management = "manage_members" in ((role.permissions or {}).get("workspace") or [])
        if grants_management and _is_last_manager(db, workspace_id, binding):
            raise HTTPException(
                status_code=409,
                detail="This is the last grant that can manage access to this workspace",
            )

    db.delete(binding)
    from app.services import access_log
    access_log.record(db, "role.revoked", access_log.actor_of(identity), workspace_id=workspace_id,
                      subject_type=binding.subject_type, subject_id=binding.subject_id, role_id=binding.role_id)
    db.commit()


def _is_last_manager(db: Session, workspace_id: str, binding: RoleBinding) -> bool:
    rows = db.execute(
        select(RoleBinding, Role)
        .join(Role, Role.id == RoleBinding.role_id)
        .where(RoleBinding.workspace_id == workspace_id)
    ).all()
    others = [
        b for b, r in rows
        if b.id != binding.id and "manage_members" in ((r.permissions or {}).get("workspace") or [])
    ]
    return not others


@router.get("/workspaces/{workspace_id}/my-permissions", response_model=EffectivePermissionsOut)
def my_permissions(
    workspace_id: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """What the caller may actually do here, after roles, groups and any
    legacy membership are resolved — so the UI can hide what would 403 and
    an operator can answer "why can't I?" without reading the database."""
    if isinstance(identity, OidcIdentity):
        from app.services.permissions import explain
        sources = explain(db, identity.user, workspace_id)
        if identity.user.is_admin:
            return EffectivePermissionsOut(
                workspace_id=workspace_id, is_admin=True, sources=sources,
                objects=["read", "create", "modify", "delete"],
                tickets=["read", "create", "modify", "delete"],
                documents=["read", "create", "modify", "delete", "approve"],
                workspace=["manage_members"],
            )
        granted = effective_permissions(db, identity.user, workspace_id)
        return EffectivePermissionsOut(
            workspace_id=workspace_id,
            is_admin=False,
            sources=sources,
            objects=sorted(granted["objects"]),
            tickets=sorted(granted["tickets"]),
            documents=sorted(granted["documents"]),
            workspace=sorted(granted["workspace"]),
        )

    # A token carries the rights of the workspace it was minted for.
    return EffectivePermissionsOut(
        workspace_id=identity.workspace_id, is_admin=False,
        objects=["read", "create", "modify", "delete"],
        tickets=["read", "create", "modify", "delete"],
        documents=["read", "create", "modify", "delete", "approve"],
        workspace=["manage_members"],
    )
