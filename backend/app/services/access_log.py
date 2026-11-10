"""The record of changes to access (issue #26). Written in the same transaction as the change, so a change that
is rolled back leaves no record and a committed one always has one."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.access_event import AccessEvent
from app.models.user import User


def actor_of(identity) -> Optional[str]:
    user = getattr(identity, "user", None)
    return getattr(user, "id", None)


def record(db: Session, kind: str, actor: Optional[str], *, workspace_id: Optional[str] = None,
           site_id: Optional[str] = None, group_uid: Optional[str] = None, subject_type: Optional[str] = None,
           subject_id: Optional[str] = None, role_id: Optional[str] = None, **detail) -> None:
    db.add(AccessEvent(at=datetime.now(timezone.utc), actor=actor, kind=kind, workspace_id=workspace_id,
                       site_id=site_id, group_uid=group_uid, subject_type=subject_type, subject_id=subject_id,
                       role_id=role_id, detail={k: v for k, v in detail.items() if v is not None} or None))


def _who(db: Session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return (user.name or user.email) if user else user_id


def view(db: Session, e: AccessEvent) -> dict:
    subject = None
    if e.subject_type == "user":
        subject = _who(db, e.subject_id)
    elif e.subject_type == "group" and e.subject_id:
        from app.models.group import Group
        g = db.get(Group, e.subject_id)
        subject = g.name if g else e.subject_id
    return {"id": e.id, "at": e.at, "actor": _who(db, e.actor), "kind": e.kind, "workspace_id": e.workspace_id,
            "site_id": e.site_id, "group_uid": e.group_uid, "subject_type": e.subject_type, "subject": subject,
            "role_id": e.role_id, "detail": e.detail or {}}


def for_workspace(db: Session, workspace_id: str, limit: int = 100) -> list[dict]:
    """The changes to access in a workspace, and those at its current site that reach it."""
    from app.services.permissions import current_site
    site_id = current_site(db, workspace_id)
    where = AccessEvent.workspace_id == workspace_id
    if site_id:
        where = or_(where, AccessEvent.site_id == site_id)
    rows = db.scalars(select(AccessEvent).where(where).order_by(AccessEvent.at.desc(), AccessEvent.id.desc())
                      .limit(min(limit, 500)))
    return [view(db, e) for e in rows]


def for_group(db: Session, group_uid: str, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(AccessEvent).where(or_(AccessEvent.group_uid == group_uid, (
        (AccessEvent.subject_type == "group") & (AccessEvent.subject_id == group_uid))))
        .order_by(AccessEvent.at.desc(), AccessEvent.id.desc()).limit(min(limit, 500)))
    return [view(db, e) for e in rows]
