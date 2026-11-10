"""What a person may do in a workspace.

One function answers it, and require_permission() is the only caller that
matters — every router keeps the call it already had. Grants come from
three places and are unioned, never intersected:

* role bindings on the user,
* role bindings on any group the user belongs to,
* a legacy Membership row, which still resolves so that access granted
  before roles existed doesn't quietly disappear at deploy time.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.models.membership import Membership
from app.models.role import Role, RoleBinding, SiteGroupRoleBinding
from app.models.user import User
from app.models.workspace import Workspace, SiteAdministrator
from app.services.roles import membership_permissions

# "restricted" holds class names rather than actions (§4.3): {"restricted": ["costs"]}.
RESOURCES = ("objects", "tickets", "documents", "workspace", "restricted")

RESOURCE_SUFFIX = {"objects": "", "tickets": "_tickets", "documents": "_documents"}


def user_group_uids(db: Session, user_id: str) -> list[str]:
    return list(db.scalars(select(GroupMember.group_uid).join(Group, Group.uid == GroupMember.group_uid).where(
        GroupMember.user_id == user_id, Group.active.is_(True))))


def current_site(db: Session, workspace_id: str) -> "str | None":
    """The site a workspace is in now: itself when it is a site, its site when it is a facility of one."""
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return None
    if workspace.role == "site":
        return workspace.id
    if workspace.site_id:
        site = db.get(Workspace, workspace.site_id)
        return site.id if site is not None and site.role == "site" else None
    return None


def administers_site(db: Session, user_id: str, workspace_id: str) -> bool:
    """Site authority follows a facility's current site, never an old placement."""
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return False
    site_id = workspace.id if workspace.role == "site" else workspace.site_id
    return bool(site_id) and db.scalar(select(SiteAdministrator.id).join(
        Workspace, Workspace.id == SiteAdministrator.site_id).where(
        SiteAdministrator.site_id == site_id, SiteAdministrator.user_id == user_id,
        Workspace.role == "site")) is not None


def _merge(into: dict[str, set[str]], permissions: dict) -> None:
    for resource in RESOURCES:
        for action in permissions.get(resource) or []:
            into[resource].add(action)


def effective_permissions(db: Session, user: User, workspace_id: str) -> dict[str, set[str]]:
    granted: dict[str, set[str]] = {resource: set() for resource in RESOURCES}

    group_uids = user_group_uids(db, user.id)
    subject_clause = RoleBinding.subject_type == "user"
    subject_clause = subject_clause & (RoleBinding.subject_id == user.id)
    if group_uids:
        subject_clause = subject_clause | (
            (RoleBinding.subject_type == "group") & (RoleBinding.subject_id.in_(group_uids))
        )

    roles = db.scalars(
        select(Role)
        .join(RoleBinding, RoleBinding.role_id == Role.id)
        .where(RoleBinding.workspace_id == workspace_id, subject_clause)
    ).all()
    for role in roles:
        _merge(granted, role.permissions or {})

    # Site-wide group grants (issue #26): those of the workspace's *current* site, to an active group of theirs.
    site_id = current_site(db, workspace_id)
    if site_id and group_uids:
        for role in db.scalars(select(Role).join(SiteGroupRoleBinding, SiteGroupRoleBinding.role_id == Role.id)
                               .where(SiteGroupRoleBinding.site_id == site_id,
                                      SiteGroupRoleBinding.group_uid.in_(group_uids))):
            _merge(granted, role.permissions or {})

    legacy = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    )
    if legacy is not None:
        # membership_permissions() owns the reading of those flags, including
        # which combination counted as an owner before roles existed.
        _merge(granted, membership_permissions(legacy))

    if administers_site(db, user.id, workspace_id):
        # Access management needs read access to the workspace's access UI.
        _merge(granted, {"objects": ["read"], "tickets": ["read"],
                         "documents": ["read"], "workspace": ["manage_members"]})

    return granted


def has_permission(db: Session, user: User, workspace_id: str, action: str, resource: str) -> bool:
    if user.is_admin:
        return True
    return action in effective_permissions(db, user, workspace_id).get(resource, set())


def resolve_permission(db: Session, user: User, workspace_id: str, action: str, resource: str) -> bool:
    """Whether `user` may do `action` on `resource` in `workspace_id`,
    including the workspace's own default-access fallback for anyone with no
    explicit role/membership grant there. This is the full check
    `require_permission`'s dependency runs for the X-Workspace-Id header;
    factored out here so a second workspace (e.g. a transfer's target) can
    be checked with the exact same semantics."""
    staged = db.get(Workspace, workspace_id)
    if staged is not None and staged.import_state == "staging":
        return False            # a portable import is staging it: nobody works in it until it is finalized
    if staged is not None and staged.import_state == "evidence" and action != "read":
        return False            # read-only evidence
    if user.is_admin:
        return True

    granted = effective_permissions(db, user, workspace_id)
    if action in granted.get(resource, set()):
        return True
    if granted[resource] or granted["workspace"]:
        # Held something here, just not this — a definite "no", rather than
        # falling through to the workspace's open-door defaults.
        return False

    workspace = db.get(Workspace, workspace_id)
    default_flag_name = f"default_can_{action}{RESOURCE_SUFFIX[resource]}"
    return workspace is not None and bool(getattr(workspace, default_flag_name, False))
