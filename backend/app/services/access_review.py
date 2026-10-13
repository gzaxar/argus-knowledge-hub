"""Role model per domain and signed access reviews (asset-model-revision
§19 item 1).

* **Role templates** give each domain its roles (stewards, operators, the
  service desk, document control, safety investigators, procurement,
  auditors) with the permissions and restricted classes they need. They are
  ordinary roles: bind them to people or groups as usual.
* **An access review** is a snapshot of every grant in a workspace — people
  (directly and through groups), groups, API tokens, the workspace's open
  defaults and the administrators — with what changed since the previous
  review. Its owners sign it; it is complete once enough distinct people
  have. Stored with a hash, never edited.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.access_review import AccessReview
from app.models.api_token import ApiToken
from app.models.group import Group, GroupMember
from app.models.membership import Membership
from app.models.role import Role, RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.services.permissions import RESOURCES, effective_permissions

ALL = ["read", "create", "modify", "delete", "approve"]
TEMPLATES = {
    "inventory-steward": ("Inventory steward", "Equipment, locations and the catalogue; merges and bulk changes",
                          {"objects": ALL, "tickets": ["read", "create"], "documents": ["read"]}),
    "it-steward": ("IT steward", "IT equipment, ports, addressing and IT installations",
                   {"objects": ALL, "tickets": ["read", "create"], "documents": ["read"]}),
    "beamline-operator": ("Beamline operator", "Positions and installations of a beamline; reports faults",
                          {"objects": ["read", "modify"], "tickets": ["read", "create", "modify"],
                           "documents": ["read"]}),
    "service-desk-agent": ("Service desk agent", "Works tickets through their workflows",
                           {"objects": ["read"], "tickets": ["read", "create", "modify", "approve"],
                            "documents": ["read"]}),
    "document-controller": ("Document controller", "Reviews, approves and releases controlled documents",
                            {"objects": ["read"], "tickets": ["read"], "documents": ALL}),
    "safety-investigator": ("Safety investigator", "Sees and works safety and security investigations",
                            {"objects": ["read"], "tickets": ["read", "create", "modify"], "documents": ["read"],
                             "restricted": ["safety_investigation", "security_incident"]}),
    "procurement-officer": ("Procurement officer", "Sees costs and procurement records",
                            {"objects": ["read", "modify"], "tickets": ["read"], "documents": ["read"],
                             "restricted": ["costs"]}),
    "auditor": ("Auditor", "Reads everything, changes nothing; verifies the audit log",
                {"objects": ["read"], "tickets": ["read"], "documents": ["read"]}),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def package_templates(db: Session, workspace_id: Optional[str] = None) -> dict:
    """The roles the template packages recommend (`roles:`) — of the packages this workspace has, or of every
    shipped one — in TEMPLATES' shape, each with the package it comes from."""
    from app.packages.install import installed
    from app.packages.loader import available
    ids = list(installed(db, workspace_id)) if workspace_id else list(available())
    out = {}
    for pid in ids:
        p = available().get(pid)
        for r in (p.section("roles") or []) if p else []:
            perms = {res: list(r.get(res) or []) for res in ("objects", "tickets", "documents") if r.get(res)}
            if r.get("restricted"):
                perms["restricted"] = list(r["restricted"])
            if r.get("manage_members"):
                perms["workspace"] = ["manage_members"]
            out[r["id"]] = (r["name"], r["description"], perms, pid)
    return out


def all_templates(db: Session, workspace_id: Optional[str] = None) -> dict:
    """key -> (name, description, permissions, package or None): ARGUS's own, then the packages'."""
    return {**{k: (*v, None) for k, v in TEMPLATES.items()}, **package_templates(db, workspace_id)}


def install_templates(db: Session, workspace_id: Optional[str] = None) -> list[str]:
    """Create the template roles that do not exist yet (ids `argus-<key>`): ARGUS's own and those the
    packages of this workspace recommend. A template is a role to grant; installing it grants nothing."""
    added = []
    for key, (name, description, permissions, _package) in all_templates(db, workspace_id).items():
        rid = f"argus-{key}"
        if db.get(Role, rid) is None:
            db.add(Role(id=rid, name=name, description=description, permissions=permissions, is_system=False,
                        rank=10))
            added.append(rid)
    db.flush()
    return added


def _perm_map(granted: dict) -> dict:
    return {r: sorted(granted.get(r) or []) for r in RESOURCES if granted.get(r)}


def snapshot(db: Session, workspace_id: str) -> dict:
    ws = db.get(Workspace, workspace_id)
    bindings = list(db.scalars(select(RoleBinding).where(RoleBinding.workspace_id == workspace_id)))
    roles = {r.id: r for r in db.scalars(select(Role))}
    user_ids = {b.subject_id for b in bindings if b.subject_type == "user"}
    group_ids = {b.subject_id for b in bindings if b.subject_type == "group"}
    for gid in group_ids:
        user_ids |= set(db.scalars(select(GroupMember.user_id).where(GroupMember.group_uid == gid)))
    user_ids |= set(db.scalars(select(Membership.user_id).where(Membership.workspace_id == workspace_id)))
    people = []
    for uid in sorted(user_ids):
        user = db.get(User, uid)
        if user is None:
            continue
        via = sorted({roles[b.role_id].name for b in bindings if b.subject_type == "user" and b.subject_id == uid
                      and b.role_id in roles}
                     | {f"{roles[b.role_id].name} (via group {b.subject_id})" for b in bindings
                        if b.subject_type == "group" and b.role_id in roles and uid in set(
                            db.scalars(select(GroupMember.user_id).where(GroupMember.group_uid == b.subject_id)))})
        if db.scalar(select(Membership.id).where(Membership.workspace_id == workspace_id, Membership.user_id == uid)):
            via.append("legacy membership")
        people.append({"user": user.id, "email": user.email, "name": user.name, "active": getattr(user, "active", True),
                       "roles": via, "permissions": _perm_map(effective_permissions(db, user, workspace_id))})
    groups = [{"group": g, "name": (db.get(Group, g).name if db.get(Group, g) else g),
               "roles": sorted(roles[b.role_id].name for b in bindings
                               if b.subject_type == "group" and b.subject_id == g and b.role_id in roles)}
              for g in sorted(group_ids)]
    tokens = [{"token": t.id, "label": t.label, "restricted_grants": sorted(t.restricted_grants or []),
               "created_at": t.created_at.isoformat() if t.created_at else None,
               "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
               "revoked": t.revoked_at is not None}
              for t in db.scalars(select(ApiToken).where(ApiToken.workspace_id == workspace_id).order_by(ApiToken.id))]
    defaults = sorted(k for k in dir(ws) if k.startswith("default_can_") and getattr(ws, k)) if ws else []
    admins = sorted(u.email for u in db.scalars(select(User).where(User.is_admin.is_(True))))
    return {"workspace": workspace_id, "people": people, "groups": groups, "tokens": tokens,
            "open_defaults": defaults, "administrators": admins}


def _index(snap: dict) -> dict:
    out = {}
    for p in snap.get("people", []):
        out[f"user:{p['email'] or p['user']}"] = {"permissions": p["permissions"], "roles": p["roles"]}
    for t in snap.get("tokens", []):
        if not t["revoked"]:
            out[f"token:{t['token']}:{t['label'] or ''}"] = {"restricted_grants": t["restricted_grants"]}
    for d in snap.get("open_defaults", []):
        out[f"default:{d}"] = True
    for a in snap.get("administrators", []):
        out[f"admin:{a}"] = True
    return out


def diff(previous: Optional[dict], current: dict) -> dict:
    before, after = _index(previous or {}), _index(current)
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
            "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def create(db: Session, workspace_id: str, actor: str, required_signers: int = 2) -> AccessReview:
    snap = snapshot(db, workspace_id)
    previous = db.scalar(select(AccessReview).where(AccessReview.workspace_id == workspace_id)
                         .order_by(AccessReview.created_at.desc()).limit(1))
    body = json.dumps(snap, sort_keys=True, default=str)
    review = AccessReview(id=str(uuid.uuid4()), workspace_id=workspace_id, created_by=actor, created_at=now(),
                          snapshot=snap, snapshot_hash=hashlib.sha256(body.encode()).hexdigest(),
                          changes=diff(previous.snapshot if previous else None, snap),
                          signatures=[], required_signers=max(1, required_signers))
    db.add(review)
    db.flush()
    return review


class ReviewError(ValueError):
    pass


def sign(db: Session, review: AccessReview, signer: str, comment: Optional[str] = None) -> AccessReview:
    if review.completed_at is not None:
        raise ReviewError("this review is already complete")
    if any(s["signer"] == signer for s in review.signatures):
        raise ReviewError("each owner signs once")
    # The grants must still be what was reviewed (usage times may move).
    if _index(snapshot(db, review.workspace_id)) != _index(review.snapshot):
        raise ReviewError("access has changed since this review was taken; take a new one")
    review.signatures = [*review.signatures, {"signer": signer, "at": now().isoformat(), "comment": comment}]
    if len(review.signatures) >= review.required_signers:
        review.completed_at = now()
    db.flush()
    return review


def view(review: AccessReview, full: bool = True) -> dict:
    out = {"id": review.id, "workspace_id": review.workspace_id, "created_by": review.created_by,
           "created_at": review.created_at, "snapshot_hash": review.snapshot_hash, "changes": review.changes,
           "signatures": review.signatures, "required_signers": review.required_signers,
           "completed_at": review.completed_at,
           "summary": {"people": len(review.snapshot.get("people", [])), "groups": len(review.snapshot.get("groups", [])),
                       "tokens": len([t for t in review.snapshot.get("tokens", []) if not t["revoked"]]),
                       "open_defaults": len(review.snapshot.get("open_defaults", []))}}
    if full:
        out["snapshot"] = review.snapshot
    return out
