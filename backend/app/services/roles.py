"""The seeded role catalogue, and the mapping from the older per-user
permission flags onto it."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.membership import Membership
from app.models.role import Role

READ = ["read"]
CONTRIBUTE = ["read", "create", "modify"]
FULL = ["read", "create", "modify", "delete"]

# (id, name, description, permissions, rank)
SYSTEM_ROLES = [
    (
        "viewer", "Viewer", "Can see everything in the workspace, change nothing.",
        {"objects": READ, "tickets": READ, "documents": READ},
        10,
    ),
    (
        "reporter", "Reporter", "Can see everything and raise tickets.",
        {"objects": READ, "tickets": ["read", "create"], "documents": READ},
        20,
    ),
    (
        "agent", "Agent", "Works the ticket queue: can take and update tickets.",
        {"objects": READ, "tickets": CONTRIBUTE, "documents": READ},
        30,
    ),
    (
        "approver", "Approver", "Can approve and publish controlled documents.",
        {"objects": READ, "tickets": READ, "documents": ["read", "approve"]},
        35,
    ),
    (
        "contributor", "Contributor", "Can create and edit, but not delete.",
        {"objects": CONTRIBUTE, "tickets": CONTRIBUTE, "documents": CONTRIBUTE},
        40,
    ),
    (
        "curator", "Curator",
        "Full control of the content: also deletes, and manages types, global values and imports.",
        {"objects": FULL, "tickets": FULL, "documents": FULL},
        50,
    ),
    (
        "workspace_admin", "Workspace administrator",
        "Manages workspace access and group role grants; can read workspace content.",
        {"objects": READ, "tickets": READ, "documents": READ,
         "workspace": ["manage_members"]},
        55,
    ),
    (
        "owner", "Owner", "Everything a curator can do, plus granting access to others.",
        {
            "objects": FULL,
            "tickets": FULL,
            "documents": FULL + ["approve"],
            "workspace": ["manage_members"],
        },
        60,
    ),
]


def ensure_system_roles(db: Session) -> None:
    """Idempotent: creates any missing system role and keeps the permissions
    of existing ones current, so a release that widens a role takes effect
    without a migration. Never touches a role someone defined locally."""
    existing = {r.id: r for r in db.scalars(select(Role).where(Role.is_system.is_(True)))}
    for role_id, name, description, permissions, rank in SYSTEM_ROLES:
        role = existing.get(role_id)
        if role is None:
            db.add(Role(
                id=role_id, name=name, description=description,
                permissions=permissions, is_system=True, rank=rank,
            ))
        else:
            role.name = name
            role.description = description
            role.permissions = permissions
            role.rank = rank


def membership_permissions(membership: Membership) -> dict:
    """The permission map a legacy Membership row stands for.

    The old model had no owner: full create/modify/delete on objects was
    exactly what member management checked for, so that combination carries
    the right to grant access here too. Without it, whoever set everyone
    else up would lose the ability to do it again — and the full-rights rows
    in production would have no matching role to convert into.
    """
    def actions(suffix: str, extra: list[str] | None = None) -> list[str]:
        out = [
            action
            for action in ("read", "create", "modify", "delete")
            if getattr(membership, f"can_{action}{suffix}")
        ]
        return out + (extra or [])

    documents_extra = ["approve"] if membership.can_approve_documents else []
    permissions = {
        "objects": actions(""),
        "tickets": actions("_tickets"),
        "documents": actions("_documents", documents_extra),
    }
    if membership.can_create and membership.can_modify and membership.can_delete:
        permissions["workspace"] = ["manage_members"]
    return permissions


def matching_system_role_id(permissions: dict) -> str | None:
    """The system role that grants exactly this, or None when the
    combination isn't expressible as one role — in which case the legacy row
    has to keep resolving on its own rather than be converted into something
    that grants more or less than it did."""
    def normalise(mapping: dict) -> dict:
        return {
            resource: sorted(mapping.get(resource) or [])
            for resource in ("objects", "tickets", "documents", "workspace")
        }

    wanted = normalise(permissions)
    for role_id, _name, _description, role_permissions, _rank in SYSTEM_ROLES:
        if normalise(role_permissions) == wanted:
            return role_id
    return None
