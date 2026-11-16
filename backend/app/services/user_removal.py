"""Removing a person from ARGUS (docs/dangerous-actions.md): an administrator's action, confirmed by typing the
person's e-mail address, never with a token.

Removing is not deleting. The person's row stays, so every record, ticket, comment, revision and approval keeps the
name of who did it; what goes is everything that lets them in or acts for them:

- signing in (refused from then on, whatever identity provider they come from) and every personal token;
- every role they hold themselves, in each workspace and site-wide, the older per-workspace memberships, site and
  group administration, being an administrator of the installation;
- their place in local groups and groups by e-mail domain (a directory group keeps them: the directory says who is
  in it, but they can no longer sign in);
- what waits on them: open tickets assigned to them and planned activities they own or are given are left for
  someone else to take; their subscriptions, watches and notification settings.

`preview` says all of it before anything changes, with what stays (documents they own, robot tokens they made).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity, ActivitySeries
from app.models.api_token import ApiToken
from app.models.document import Document
from app.models.group import Group, GroupAdministrator, GroupMember
from app.models.issue import Issue
from app.models.membership import Membership
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workflow import NotificationPreference, NotificationSubscription, RecordWatcher, TicketWatcher
from app.models.workspace import SiteAdministrator

CLOSED = {"closed", "resolved", "done", "cancelled", "canceled", "rejected"}
OPEN_ACTIVITY = ("planned", "in_progress")


class RemovalError(ValueError):
    pass


def _mine(user: User):
    return or_(Issue.assignee == user.id, func.lower(Issue.assignee) == (user.email or "").lower())


def preview(db: Session, user: User) -> dict:
    """What removing this person would change, and what would stay."""
    bindings = db.scalars(select(RoleBinding).where(RoleBinding.subject_type == "user",
                                                    RoleBinding.subject_id == user.id)).all()
    groups = db.execute(select(Group.name, Group.source, GroupMember.source).join(
        GroupMember, GroupMember.group_uid == Group.uid).where(GroupMember.user_id == user.id)
        .order_by(Group.name)).all()
    tickets = db.scalars(select(Issue).where(_mine(user), func.lower(Issue.state).notin_(CLOSED))).all()
    activities = db.scalars(select(Activity).where(
        or_(Activity.owner_user_id == user.id, Activity.assignee_user_id == user.id),
        Activity.status.in_(OPEN_ACTIVITY))).all()
    personal = db.scalar(select(func.count()).select_from(ApiToken).where(
        ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))) or 0
    robots = db.scalar(select(func.count()).select_from(ApiToken).where(
        ApiToken.kind == "robot", ApiToken.created_by == user.id, ApiToken.revoked_at.is_(None))) or 0
    documents = db.scalar(select(func.count()).select_from(Document).where(Document.owner_user_id == user.id)) or 0
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin),
                 "removed_at": user.removed_at},
        "roles": sorted({f"{b.workspace_id}" for b in bindings}),
        "memberships": sorted(db.scalars(select(Membership.workspace_id).where(Membership.user_id == user.id))),
        "site_administrator_of": sorted(db.scalars(select(SiteAdministrator.site_id).where(
            SiteAdministrator.user_id == user.id))),
        "group_administrator_of": sorted(db.scalars(select(Group.name).join(
            GroupAdministrator, GroupAdministrator.group_uid == Group.uid).where(GroupAdministrator.user_id == user.id))),
        "groups_left": [name for name, gsrc, msrc in groups if gsrc == "local"],
        "directory_groups": [name for name, gsrc, msrc in groups if gsrc != "local"],
        "personal_tokens": personal,
        "open_tickets_unassigned": [{"uid": t.uid, "workspace_id": t.workspace_id, "title": t.title, "state": t.state}
                                    for t in tickets[:50]],
        "open_tickets_count": len(tickets),
        "activities_released": [{"uid": a.uid, "workspace_id": a.workspace_id, "title": a.title, "status": a.status}
                                for a in activities[:50]],
        "activities_count": len(activities),
        "stays": {"documents_owned": documents, "robot_tokens_made": robots,
                  "history": "records, tickets, comments, revisions and approvals keep their name"},
        "blocked": None,
    }


def check(db: Session, user: User, actor: User) -> Optional[str]:
    """Why this removal may not be done, or None."""
    if user.removed_at is not None:
        return f"{user.email} was already removed."
    if user.id == actor.id:
        return "You cannot remove yourself: ask another administrator."
    if user.is_admin and (db.scalar(select(func.count()).select_from(User).where(
            User.is_admin.is_(True), User.active.is_(True), User.removed_at.is_(None))) or 0) <= 1:
        return f"{user.email} is the last administrator of the installation: name another one first."
    return None


def remove(db: Session, user: User, actor: User) -> dict:
    """Remove the person (see the module). The caller has checked who asks and the confirmation, and commits."""
    from app.services import access_log
    why = check(db, user, actor)
    if why:
        raise RemovalError(why)
    out = preview(db, user)
    now = datetime.now(timezone.utc)

    for b in db.scalars(select(RoleBinding).where(RoleBinding.subject_type == "user", RoleBinding.subject_id == user.id)):
        access_log.record(db, "role.revoked", actor.id, workspace_id=b.workspace_id, subject_type="user",
                          subject_id=user.id, role_id=b.role_id, reason="person removed")
        db.delete(b)
    db.execute(delete(Membership).where(Membership.user_id == user.id))
    db.execute(delete(SiteAdministrator).where(SiteAdministrator.user_id == user.id))
    db.execute(delete(GroupAdministrator).where(GroupAdministrator.user_id == user.id))
    for m in db.scalars(select(GroupMember).join(Group, Group.uid == GroupMember.group_uid).where(
            GroupMember.user_id == user.id, Group.source == "local")):
        access_log.record(db, "group.member_removed", actor.id, group_uid=m.group_uid, subject_type="user",
                          subject_id=user.id, reason="person removed")
        db.delete(m)
    db.execute(update(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
               .values(revoked_at=now, revoked_by=actor.id))

    for t in db.scalars(select(Issue).where(_mine(user), func.lower(Issue.state).notin_(CLOSED))):
        t.assignee = None
    db.execute(update(Activity).where(Activity.owner_user_id == user.id, Activity.status.in_(OPEN_ACTIVITY))
               .values(owner_user_id=None))
    db.execute(update(Activity).where(Activity.assignee_user_id == user.id, Activity.status.in_(OPEN_ACTIVITY))
               .values(assignee_user_id=None))
    db.execute(update(ActivitySeries).where(ActivitySeries.assignee_user_id == user.id).values(assignee_user_id=None))
    db.execute(delete(NotificationSubscription).where(NotificationSubscription.user_id == user.id))
    db.execute(delete(NotificationPreference).where(NotificationPreference.user_id == user.id))
    db.execute(delete(RecordWatcher).where(RecordWatcher.user_id == user.id))
    db.execute(delete(TicketWatcher).where(or_(TicketWatcher.user == user.id,
                                               func.lower(TicketWatcher.user) == (user.email or "").lower())))

    user.is_admin = False
    user.active = False
    user.removed_at = now
    user.removed_by = actor.id
    access_log.record(db, "person.removed", actor.id, subject_type="user", subject_id=user.id, email=user.email,
                      tickets_unassigned=out["open_tickets_count"], activities_released=out["activities_count"])
    db.flush()
    return out
