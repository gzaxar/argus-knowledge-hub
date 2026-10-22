from typing import Optional

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Identity, PatIdentity, get_identity, require_permission
from app.db import get_db
from app.models.group import GroupMember
from app.models.role import RoleBinding
from app.services.permissions import effective_permissions, has_permission, user_group_uids
from app.models.global_value import GlobalValue
from app.models.membership import Membership
from app.models.document import Document
from app.models.icon import Icon
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services.integrity import cleanup_workspace, generate_integrity_report, relink_workspace
from app.services.relations import rebuild_relations_for_schemas
from app.services.ticket_types import DEFAULT_ISSUE_TYPES, ensure_ticket_types
from app.services import asset_keys
from app.services.workspace_ids import rule as id_rule, save_rule, slugify, unique_id
from app.schemas.workspace import (
    CleanupOptions,
    DefaultAccess,
    MemberCandidateOut,
    MemberDirectoryOut,
    MembershipOut,
    MembershipUpdate,
    MeOut,
    MyWorkspaceOut,
    UserAdminUpdate,
    UserOut,
    WorkspaceCreate,
    WorkspaceDetailOut,
    WorkspaceOut,
    WorkspaceUpdate,
    WorkspaceIdRule,
    AssetKeyRule,
    WorkspaceIdSuggestion,
)

# A workspace a portable import is staging is nobody's to pick until the import is finalized.
NOT_STAGED = Workspace.import_state.is_distinct_from("staging")

router = APIRouter(prefix="/v1", tags=["workspaces"])


def seed_default_global_values(db: Session, workspace_id: str) -> None:
    """Seed the starter set of shared enumerations for a new workspace.
    Idempotent: skips any (applies_to, key) that already exists, so this can
    also be run as a one-off backfill against existing workspaces."""
    existing = {
        (gv.applies_to, gv.key)
        for gv in db.scalars(
            select(GlobalValue).where(GlobalValue.workspace_id == workspace_id)
        )
    }

    # From the core-facility package (enumerations.yaml): optional per type (a schema opts in via an
    # attribute), never forced. A later Jira import may overwrite an enumeration's options with the source
    # system's real statuses (same key, upsert-by-key there).
    from app.packages import defaults
    for e in defaults.enumerations():
        if (e["applies_to"], e["key"]) in existing:
            continue
        db.add(GlobalValue(
            uid=str(uuid.uuid4()), workspace_id=workspace_id, key=e["key"], name=e["name"],
            type=e["type"], applies_to=e["applies_to"], is_system_default=True,
            default_value=e["default"], options=e["options"],
        ))


def seed_default_ticket_types(db: Session, workspace_id: str) -> None:
    """The issue types Jira ships with, so an Epic or a Story can be raised
    by hand before anything has been imported. Idempotent — a later import
    reuses these same types rather than creating a second set."""
    ensure_ticket_types(db, workspace_id, set(DEFAULT_ISSUE_TYPES))


def _require_owner_or_admin(workspace_id: str, identity: Identity, db: Session) -> None:
    """Granting access to others is its own authority — held by the Owner
    role, by is_admin, or by a legacy membership with full rights (which is
    what this check used to look for directly)."""
    if isinstance(identity, PatIdentity):
        if identity.workspace_id != workspace_id or not identity.may("admin"):
            raise HTTPException(status_code=403, detail="Not permitted")
        return
    if identity.token is not None and (not identity.token.may("admin") or
                                       identity.token.workspace_id not in (None, workspace_id)):
        raise HTTPException(status_code=403, detail="This token may not administer the workspace")
    if identity.user.is_admin:
        return
    if not has_permission(db, identity.user, workspace_id, "manage_members", "workspace"):
        raise HTTPException(status_code=403, detail="Not permitted")


@router.get("/me", response_model=MeOut)
def get_me(identity: Identity = Depends(get_identity)):
    if isinstance(identity, PatIdentity):
        return MeOut(auth_type="pat", workspace_id=identity.workspace_id)
    user = identity.user
    return MeOut(
        auth_type="oidc", user_id=user.id, email=user.email, name=user.name, is_admin=user.is_admin
    )


@router.get("/me/workspaces", response_model=list[MyWorkspaceOut])
def list_my_workspaces(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    if isinstance(identity, PatIdentity):
        ws = db.get(Workspace, identity.workspace_id)
        if ws is None:
            return []
        return [MyWorkspaceOut(
            id=ws.id, name=ws.name, is_global=ws.is_global, created_at=ws.created_at,
            can_read=True, can_create=True, can_modify=True, can_delete=True,
            can_read_tickets=True, can_create_tickets=True,
            can_modify_tickets=True, can_delete_tickets=True,
            can_read_documents=True, can_create_documents=True,
            can_modify_documents=True, can_delete_documents=True, can_approve_documents=True,
        )]

    user = identity.user
    if user.is_admin:
        return [
            MyWorkspaceOut(
                id=ws.id, name=ws.name, is_global=ws.is_global, created_at=ws.created_at,
                can_read=True, can_create=True, can_modify=True, can_delete=True,
                can_read_tickets=True, can_create_tickets=True,
                can_modify_tickets=True, can_delete_tickets=True,
                can_read_documents=True, can_create_documents=True,
                can_modify_documents=True, can_delete_documents=True, can_approve_documents=True,
            )
            for ws in db.scalars(select(Workspace).where(NOT_STAGED)).all()
        ]

    # Reachability has to follow exactly what require_permission() enforces,
    # or a workspace granted through a group role binding would be usable by
    # URL but missing from the picker. Both a legacy membership and any role
    # binding put a workspace in this list.
    granted_ws_ids = set(
        db.scalars(select(Membership.workspace_id).where(Membership.user_id == user.id))
    )
    group_uids = user_group_uids(db, user.id)
    binding_clause = (RoleBinding.subject_type == "user") & (RoleBinding.subject_id == user.id)
    if group_uids:
        binding_clause = binding_clause | (
            (RoleBinding.subject_type == "group") & (RoleBinding.subject_id.in_(group_uids))
        )
    granted_ws_ids |= set(db.scalars(select(RoleBinding.workspace_id).where(binding_clause)))

    result = []
    for ws in db.scalars(select(Workspace).where(Workspace.id.in_(granted_ws_ids), NOT_STAGED)) if granted_ws_ids else []:
        granted = effective_permissions(db, user, ws.id)
        result.append(MyWorkspaceOut(
            id=ws.id, name=ws.name, is_global=ws.is_global, created_at=ws.created_at,
            can_read="read" in granted["objects"], can_create="create" in granted["objects"],
            can_modify="modify" in granted["objects"], can_delete="delete" in granted["objects"],
            can_read_tickets="read" in granted["tickets"],
            can_create_tickets="create" in granted["tickets"],
            can_modify_tickets="modify" in granted["tickets"],
            can_delete_tickets="delete" in granted["tickets"],
            can_read_documents="read" in granted["documents"],
            can_create_documents="create" in granted["documents"],
            can_modify_documents="modify" in granted["documents"],
            can_delete_documents="delete" in granted["documents"],
            can_approve_documents="approve" in granted["documents"],
        ))

    # Also surface workspaces with no explicit grant but where the
    # workspace's default access grants this authenticated user something —
    # otherwise that default access would be enforced but unreachable, since
    # the user would have no way to pick the workspace in the first place.
    member_ws_ids = granted_ws_ids
    default_accessible = db.scalars(
        select(Workspace).where(
            NOT_STAGED,
            Workspace.id.not_in(member_ws_ids) if member_ws_ids else True,
            (
                Workspace.default_can_read | Workspace.default_can_create
                | Workspace.default_can_modify | Workspace.default_can_delete
                | Workspace.default_can_read_tickets | Workspace.default_can_create_tickets
                | Workspace.default_can_modify_tickets | Workspace.default_can_delete_tickets
                | Workspace.default_can_read_documents | Workspace.default_can_create_documents
                | Workspace.default_can_modify_documents | Workspace.default_can_delete_documents
                | Workspace.default_can_approve_documents
            ),
        )
    ).all()
    result.extend(
        MyWorkspaceOut(
            id=ws.id, name=ws.name, is_global=ws.is_global, created_at=ws.created_at,
            can_read=ws.default_can_read, can_create=ws.default_can_create,
            can_modify=ws.default_can_modify, can_delete=ws.default_can_delete,
            can_read_tickets=ws.default_can_read_tickets,
            can_create_tickets=ws.default_can_create_tickets,
            can_modify_tickets=ws.default_can_modify_tickets,
            can_delete_tickets=ws.default_can_delete_tickets,
            can_read_documents=ws.default_can_read_documents,
            can_create_documents=ws.default_can_create_documents,
            can_modify_documents=ws.default_can_modify_documents,
            can_delete_documents=ws.default_can_delete_documents,
            can_approve_documents=ws.default_can_approve_documents,
        )
        for ws in default_accessible
    )
    return result


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    body: WorkspaceCreate, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    if isinstance(identity, PatIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can create workspaces")

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="A workspace needs a name")

    given = (body.id or "").strip()
    if given:
        workspace_id = given
        if db.get(Workspace, workspace_id) is not None:
            raise HTTPException(status_code=409, detail="Workspace id already exists")
    else:
        # Derived here rather than in the browser, so a form that has not
        # been reloaded since the rule changed cannot create an identifier
        # that does not follow it — and the identifier cannot be changed
        # afterwards.
        workspace_id = unique_id(db, name, id_rule(db))

    from app.packages.install import PackageProblem
    try:
        workspace = make_workspace(db, workspace_id, name, owner_user_id=identity.user.id,
                                   packages=body.packages, catalogue_workspace_id=body.catalogue_workspace_id)
    except PackageProblem as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "package"})
    db.commit()
    db.refresh(workspace)
    return workspace


def make_workspace(db: Session, workspace_id: str, name: str, owner_user_id: Optional[str] = None,
                   packages: Optional[list[str]] = None, catalogue_workspace_id: Optional[str] = None) -> Workspace:
    """A workspace ready to use: the template packages it starts from (core-facility unless others are
    chosen: its global values, ticket and document types; the accelerator catalogue on request) recorded with
    their versions, and, when someone made it, that person with full rights."""
    workspace = Workspace(id=workspace_id, name=name)
    db.add(workspace)
    db.flush()
    if owner_user_id:
        db.add(Membership(
            workspace_id=workspace.id, user_id=owner_user_id,
            can_read=True, can_create=True, can_modify=True, can_delete=True,
            can_read_tickets=True, can_create_tickets=True,
            can_modify_tickets=True, can_delete_tickets=True,
            can_read_documents=True, can_create_documents=True,
            can_modify_documents=True, can_delete_documents=True, can_approve_documents=True,
        ))
    from app.packages.install import install
    install(db, workspace.id, list(dict.fromkeys(["core-facility", *(packages or [])])),
            actor=owner_user_id, catalogue_workspace_id=catalogue_workspace_id)
    return workspace


def ensure_default_workspace(db: Session) -> Optional[str]:
    """An installation with no workspace at all gets one, so the first person signed in has somewhere to
    start (ARGUS_DEFAULT_WORKSPACE, default "main"; empty to turn this off). Never touches an installation
    that has any workspace."""
    import os
    workspace_id = os.environ.get("ARGUS_DEFAULT_WORKSPACE", "main").strip()
    if not workspace_id or db.scalar(select(Workspace.id).limit(1)) is not None:
        return None
    make_workspace(db, workspace_id, os.environ.get("ARGUS_DEFAULT_WORKSPACE_NAME", "Main").strip() or "Main")
    db.commit()
    return workspace_id


@router.get("/workspaces/id-rule", response_model=WorkspaceIdRule)
def get_workspace_id_rule(
    identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    """How identifiers are derived from names, installation-wide."""
    _require_admin(identity)
    return WorkspaceIdRule(**id_rule(db))


@router.put("/workspaces/id-rule", response_model=WorkspaceIdRule)
def put_workspace_id_rule(
    body: WorkspaceIdRule,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_admin(identity)
    return WorkspaceIdRule(**save_rule(db, body.model_dump()))


@router.get("/workspaces/suggest-id", response_model=WorkspaceIdSuggestion)
def suggest_workspace_id(
    name: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """What this name would become — so the form can show it before saving.

    The same function the creation path uses, rather than a second
    implementation in the browser that could disagree with it.
    """
    _require_admin(identity)
    settings = id_rule(db)
    base = slugify(name, settings) or "workspace"
    chosen = unique_id(db, name, settings)
    return WorkspaceIdSuggestion(id=chosen, base=base, taken=chosen != base)

@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetailOut)
def get_workspace(
    workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    _require_owner_or_admin(workspace_id, identity, db)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _key_rule(workspace: Workspace) -> AssetKeyRule:
    pattern = asset_keys.pattern_for(workspace)
    return AssetKeyRule(pattern=pattern, is_default=not workspace.asset_key_pattern,
                        example=asset_keys.example(pattern, workspace.id))


@router.get("/workspaces/{workspace_id}/key-rule", response_model=AssetKeyRule)
def get_asset_key_rule(
    workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    """How keys are made for this workspace's records created without one."""
    _require_owner_or_admin(workspace_id, identity, db)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _key_rule(workspace)


@router.put("/workspaces/{workspace_id}/key-rule", response_model=AssetKeyRule)
def put_asset_key_rule(
    workspace_id: str,
    body: AssetKeyRule,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Only new keys follow a changed pattern: existing ones stay, since
    labels, links and other systems already carry them. An empty pattern
    goes back to the default."""
    _require_owner_or_admin(workspace_id, identity, db)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if (body.pattern or "").strip():
        try:
            workspace.asset_key_pattern = asset_keys.validate_pattern(body.pattern)
        except asset_keys.KeyPatternError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        workspace.asset_key_pattern = None
    db.commit()
    return _key_rule(workspace)


@router.put("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_admin(identity)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    turning_global = body.is_global is True and not workspace.is_global
    if body.name is not None:
        workspace.name = body.name
    if body.is_global is not None:
        workspace.is_global = body.is_global
    db.commit()
    db.refresh(workspace)

    if turning_global:
        schema_uids = list(
            db.scalars(select(Schema.uid).where(Schema.workspace_id == workspace_id))
        )
        db.query(Schema).filter(Schema.workspace_id == workspace_id).update(
            {Schema.is_global: True}, synchronize_session=False
        )
        # Documents too, except confidential ones: sharing a workspace is not
        # a decision to publish what somebody marked riservato.
        db.query(Document).filter(
            Document.workspace_id == workspace_id,
            Document.confidentiality != "riservato",
        ).update({Document.is_global: True}, synchronize_session=False)
        # And icons — otherwise a type's picture silently fails to follow it
        # the next time that type is copied to another workspace.
        db.query(Icon).filter(Icon.workspace_id == workspace_id).update(
            {Icon.is_global: True}, synchronize_session=False
        )
        db.commit()
        rebuild_relations_for_schemas(db, schema_uids)
        db.commit()

    return workspace


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Admin-only: permanently deletes the workspace and, via ON DELETE
    CASCADE, everything scoped to it — schemas, assets, tickets, labels,
    global values, import history, memberships and PATs."""
    _require_admin(identity)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # The one sanctioned purge of append-only audit rows: the workspace's own.
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(workspace)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Could not delete this workspace — it is still referenced elsewhere"
        )


@router.get("/workspaces/{workspace_id}/integrity-report")
def get_integrity_report(
    workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    _require_owner_or_admin(workspace_id, identity, db)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return generate_integrity_report(db, workspace_id)


@router.post("/workspaces/{workspace_id}/relink")
def relink_workspace_endpoint(
    workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    _require_owner_or_admin(workspace_id, identity, db)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    relink_result = relink_workspace(db, workspace_id)
    return {"relink": relink_result, "report": generate_integrity_report(db, workspace_id)}


@router.post("/workspaces/{workspace_id}/cleanup")
def cleanup_workspace_endpoint(
    workspace_id: str,
    body: CleanupOptions,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_owner_or_admin(workspace_id, identity, db)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    cleanup_result = cleanup_workspace(db, workspace_id, body.model_dump())
    return {"cleanup": cleanup_result, "report": generate_integrity_report(db, workspace_id)}


@router.put("/workspaces/{workspace_id}/default-access", response_model=WorkspaceDetailOut)
def set_default_access(
    workspace_id: str,
    body: DefaultAccess,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_owner_or_admin(workspace_id, identity, db)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in body.model_dump().items():
        setattr(workspace, field, value)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/members", response_model=list[MemberDirectoryOut])
def list_member_directory(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    """Lightweight member lookup for "user"-type attribute pickers (assignee,
    etc.) — available to anyone with read access, unlike the full permissions
    listing below which is owner/admin-only.

    Everyone who can reach the workspace belongs here, however they got in:
    by legacy membership, by a role binding of their own, or as a member of
    a group that holds one. Otherwise a ticket couldn't be assigned to most
    of the division the moment access moved to group bindings.
    """
    user_ids = set(
        db.scalars(select(Membership.user_id).where(Membership.workspace_id == workspace_id))
    )
    bindings = db.execute(
        select(RoleBinding.subject_type, RoleBinding.subject_id)
        .where(RoleBinding.workspace_id == workspace_id)
    ).all()
    bound_group_uids = [sid for stype, sid in bindings if stype == "group"]
    user_ids |= {sid for stype, sid in bindings if stype == "user"}
    if bound_group_uids:
        user_ids |= set(
            db.scalars(
                select(GroupMember.user_id).where(GroupMember.group_uid.in_(bound_group_uids))
            )
        )
    if not user_ids:
        return []

    # Someone who has left the directory stays selectable nowhere new, but
    # their existing assignments still resolve through their user row.
    users = db.scalars(select(User).where(User.id.in_(user_ids), User.active.is_(True)))
    return [MemberDirectoryOut(user_id=u.id, email=u.email, name=u.name) for u in users]


@router.get("/workspaces/{workspace_id}/members", response_model=list[MembershipOut])
def list_members(
    workspace_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    _require_owner_or_admin(workspace_id, identity, db)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
    ).all()
    return [
        MembershipOut(
            user_id=u.id, email=u.email, name=u.name,
            can_read=m.can_read, can_create=m.can_create,
            can_modify=m.can_modify, can_delete=m.can_delete,
            can_read_tickets=m.can_read_tickets, can_create_tickets=m.can_create_tickets,
            can_modify_tickets=m.can_modify_tickets, can_delete_tickets=m.can_delete_tickets,
            can_read_documents=m.can_read_documents, can_create_documents=m.can_create_documents,
            can_modify_documents=m.can_modify_documents, can_delete_documents=m.can_delete_documents,
            can_approve_documents=m.can_approve_documents,
        )
        for m, u in rows
    ]


@router.get("/workspaces/{workspace_id}/member-candidates", response_model=list[MemberCandidateOut])
def member_candidates(
    workspace_id: str,
    q: str = Query("", max_length=200),
    limit: int = Query(15, ge=1, le=50),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """People who have signed in at least once, matching every word of `q` in their e-mail or name: whom the
    workspace's owner can add as a member. Those who are members already come back flagged."""
    _require_owner_or_admin(workspace_id, identity, db)
    query = select(User)
    for word in q.lower().split():
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        query = query.where(or_(func.lower(User.email).like(like, escape="\\"),
                                func.lower(func.coalesce(User.name, "")).like(like, escape="\\")))
    users = db.scalars(query.order_by(func.lower(func.coalesce(User.name, User.email))).limit(limit)).all()
    members = set(db.scalars(select(Membership.user_id).where(
        Membership.workspace_id == workspace_id, Membership.user_id.in_([u.id for u in users]))))
    return [MemberCandidateOut(user_id=u.id, email=u.email, name=u.name, member=u.id in members) for u in users]


@router.put("/workspaces/{workspace_id}/members", response_model=MembershipOut)
def upsert_member(
    workspace_id: str,
    body: MembershipUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_owner_or_admin(workspace_id, identity, db)
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    target = db.scalar(select(User).where(User.email == body.email))
    if target is None:
        raise HTTPException(
            status_code=404,
            detail="No user found with that email — they must sign in at least once first",
        )

    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == target.id
        )
    ) or Membership(workspace_id=workspace_id, user_id=target.id)
    membership.can_read = body.can_read
    membership.can_create = body.can_create
    membership.can_modify = body.can_modify
    membership.can_delete = body.can_delete
    membership.can_read_tickets = body.can_read_tickets
    membership.can_create_tickets = body.can_create_tickets
    membership.can_modify_tickets = body.can_modify_tickets
    membership.can_delete_tickets = body.can_delete_tickets
    membership.can_read_documents = body.can_read_documents
    membership.can_create_documents = body.can_create_documents
    membership.can_modify_documents = body.can_modify_documents
    membership.can_delete_documents = body.can_delete_documents
    membership.can_approve_documents = body.can_approve_documents
    db.add(membership)
    db.commit()

    return MembershipOut(
        user_id=target.id, email=target.email, name=target.name,
        can_read=membership.can_read, can_create=membership.can_create,
        can_modify=membership.can_modify, can_delete=membership.can_delete,
        can_read_tickets=membership.can_read_tickets,
        can_create_tickets=membership.can_create_tickets,
        can_modify_tickets=membership.can_modify_tickets,
        can_delete_tickets=membership.can_delete_tickets,
        can_read_documents=membership.can_read_documents,
        can_create_documents=membership.can_create_documents,
        can_modify_documents=membership.can_modify_documents,
        can_delete_documents=membership.can_delete_documents,
        can_approve_documents=membership.can_approve_documents,
    )


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    workspace_id: str,
    user_id: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_owner_or_admin(workspace_id, identity, db)
    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    db.delete(membership)
    db.commit()


def _require_admin(identity: Identity) -> None:
    if isinstance(identity, PatIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")


@router.get("/admin/users", response_model=list[UserOut])
def list_users(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    _require_admin(identity)
    return db.scalars(select(User).order_by(User.email)).all()


@router.put("/admin/users/{user_id}", response_model=UserOut)
def set_user_admin(
    user_id: str,
    body: UserAdminUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _require_admin(identity)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_admin = body.is_admin
    db.commit()
    db.refresh(target)
    return target
