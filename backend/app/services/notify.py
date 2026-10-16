"""Watchers, notifications and escalation timers (asset-model-revision §19 item 3).

* The reporter and each assignee watch a ticket automatically; anyone can
  watch or stop watching it; a person @mentioned in a comment is notified
  and starts watching.
* A notification goes to the watchers and the assignee — never to the
  person who acted, and never to someone who may not see the ticket
  (a restricted ticket, I-ACL-1).
* A state with `sla_hours` escalates a ticket that stays in it too long:
  once per stay, to the state's `escalate_to`, the assignee and the
  watchers. `python -m app.ledger escalate` runs it, and then e-mails what
  is waiting when `SMTP_HOST` is set: as it happens or in a daily digest,
  as each person chose (NotificationPreference).
"""
from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.issue import Issue
from app.models.user import User
from app.models.workflow import Notification, TicketEscalation, TicketWatcher
from app.services import workflows
from app.services.visibility import restricted_class

MENTION = re.compile(r"@([\w.+-]+@[\w-]+\.[\w.-]+|[\w-]{3,})")


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- watchers

def watch(db: Session, issue: Issue, user: Optional[str], reason: str = "manual") -> None:
    if not user:
        return
    if db.scalar(select(TicketWatcher).where(TicketWatcher.issue_uid == issue.uid, TicketWatcher.user == user)):
        return
    db.add(TicketWatcher(issue_uid=issue.uid, user=user, reason=reason, created_at=now()))
    db.flush()


def unwatch(db: Session, issue: Issue, user: str) -> None:
    row = db.scalar(select(TicketWatcher).where(TicketWatcher.issue_uid == issue.uid, TicketWatcher.user == user))
    if row is not None:
        db.delete(row)
        db.flush()


def watchers(db: Session, issue: Issue) -> list[str]:
    return list(db.scalars(select(TicketWatcher.user).where(TicketWatcher.issue_uid == issue.uid)
                           .order_by(TicketWatcher.id)))


# --------------------------------------------------------------------------- notifications

def _user(db: Session, who: str) -> Optional[User]:
    return db.get(User, who) or db.scalar(select(User).where(User.email == who))


def may_see(db: Session, issue: Issue, who: str) -> bool:
    """A recipient is told only about what they may read (I-ACL-1)."""
    cls = restricted_class(issue)
    if cls is None:
        return True
    user = _user(db, who)
    if user is None:
        return False
    from app.auth import OidcIdentity, grants_of
    return grants_of(db, OidcIdentity(user=user), issue.workspace_id).allows(cls)


def notify(db: Session, issue: Issue, kind: str, title: str, actor: Optional[str],
           recipients: Iterable[Optional[str]], detail: Optional[dict] = None) -> list[Notification]:
    out = []
    actor_ids = {actor}
    if actor:
        u = _user(db, actor)
        if u is not None:
            actor_ids |= {u.id, u.email}
    for who in dict.fromkeys(r for r in recipients if r):
        if who in actor_ids or not may_see(db, issue, who):
            continue
        n = Notification(workspace_id=issue.workspace_id, recipient=who, issue_uid=issue.uid, kind=kind, title=title,
                         detail=detail or {}, actor=actor, created_at=now())
        db.add(n)
        out.append(n)
    db.flush()
    return out


def audience(db: Session, issue: Issue) -> list[str]:
    return [*watchers(db, issue), *([issue.assignee] if issue.assignee else [])]


def on_created(db: Session, issue: Issue, actor: Optional[str]) -> None:
    watch(db, issue, issue.created_by or actor, "reporter")
    if issue.assignee:
        watch(db, issue, issue.assignee, "assignee")
        notify(db, issue, "assigned", f"Assigned to you: {issue.title}", actor, [issue.assignee])


def on_assigned(db: Session, issue: Issue, actor: Optional[str], previous: Optional[str]) -> None:
    if not issue.assignee or issue.assignee == previous:
        return
    watch(db, issue, issue.assignee, "assignee")
    notify(db, issue, "assigned", f"Assigned to you: {issue.title}", actor, [issue.assignee],
           {"previous": previous})


def on_transition(db: Session, issue: Issue, actor: Optional[str], before: str, after: str) -> None:
    if before == after:
        return
    notify(db, issue, "transitioned", f"{issue.title}: {before} → {after}", actor, audience(db, issue),
           {"from": before, "to": after})


EDIT_FIELDS = {"title": "title", "description": "description", "priority": "priority", "due_date": "due date",
               "asset_uid": "equipment", "attributes": "fields"}


def on_edited(db: Session, issue: Issue, actor: Optional[str], before: dict, previous_assignee: Optional[str]) -> None:
    """A ticket's title, description, priority, due date, equipment or fields changed: told to its watchers.
    A new assignee is told on their own ("Assigned to you"), and a new state on its own."""
    changed = [label for field, label in EDIT_FIELDS.items() if before.get(field) != getattr(issue, field, None)]
    if not changed:
        return
    newly_assigned = issue.assignee if issue.assignee != previous_assignee else None
    notify(db, issue, "updated", f"{issue.title}: {', '.join(changed)} changed", actor,
           [w for w in audience(db, issue) if w != newly_assigned], {"changed": changed})


def on_comment(db: Session, issue: Issue, actor: Optional[str], body: str) -> None:
    mentioned = []
    for m in MENTION.findall(body or ""):
        user = _user(db, m)
        if user is not None:
            mentioned.append(user.email or user.id)
    for who in mentioned:
        watch(db, issue, who, "mentioned")
    notify(db, issue, "mentioned", f"You were mentioned on {issue.title}", actor, mentioned,
           {"excerpt": (body or "")[:200]})
    others = [w for w in audience(db, issue) if w not in mentioned]
    notify(db, issue, "commented", f"New comment on {issue.title}", actor, others, {"excerpt": (body or "")[:200]})


# --------------------------------------------------------------------------- escalation

def _entered(issue: Issue) -> datetime:
    raw = (issue.attributes or {}).get("argus_state_entered_at")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return issue.updated_at or issue.created_at


def escalate_overdue(db: Session, at: Optional[datetime] = None, workspace_id: Optional[str] = None) -> int:
    """Escalate every open ticket that has outstayed its state's SLA, once
    per stay in that state."""
    at = at or now()
    q = select(Issue).where(Issue.deleted_at.is_(None), Issue.closed_at.is_(None))
    if workspace_id:
        q = q.where(Issue.workspace_id == workspace_id)
    n = 0
    for issue in db.scalars(q):
        wf = workflows.workflow_for(db, issue.workspace_id, issue.schema_uid)
        state = workflows.state_of(wf, issue.state) or {}
        hours = state.get("sla_hours")
        if not hours or state.get("category") == "done":
            continue
        entered = _entered(issue)
        due = entered + timedelta(hours=float(hours))
        if at < due:
            continue
        exists = db.scalar(select(TicketEscalation).where(TicketEscalation.issue_uid == issue.uid,
                                                          TicketEscalation.state == issue.state,
                                                          TicketEscalation.entered_at == entered))
        if exists is not None:
            continue
        targets = [t for t in [state.get("escalate_to"), *audience(db, issue)] if t]
        db.add(TicketEscalation(issue_uid=issue.uid, state=issue.state, entered_at=entered, due_at=due,
                                escalated_at=at, escalated_to=list(dict.fromkeys(targets))))
        notify(db, issue, "escalated",
               f"Overdue: {issue.title} has been {state.get('name', issue.state)} for more than {hours} h", None,
               targets, {"state": issue.state, "entered_at": entered.isoformat(), "due_at": due.isoformat()})
        n += 1
    db.flush()
    return n


# --------------------------------------------------------------------------- e-mail

# What a person may choose not to receive by e-mail, by notification kind. The app always has them all.
EMAIL_CATEGORIES: dict[str, tuple[str, frozenset]] = {
    "direct": ("Assigned to you, mentions, and documents waiting for your review",
               frozenset({"assigned", "mentioned", "review_requested"})),
    "tickets": ("Changes to tickets you watch: state, fields, comments",
                frozenset({"transitioned", "updated", "commented"})),
    "escalations": ("Overdue tickets and review items",
                    frozenset({"escalated", "review_escalated"})),
    "following": ("Changes to equipment and documents you follow",
                  frozenset({"asset_changed", "document_changed"})),
    "workspace": ("New tickets, documents and equipment in the workspaces you subscribed to",
                  frozenset({"new_ticket", "new_document", "document_published", "new_asset"})),
}
EMAIL_MODES = ("instant", "digest", "off")


def category_of(kind: str) -> str:
    return next((key for key, (_, kinds) in EMAIL_CATEGORIES.items() if kind in kinds), "direct")


class MailError(RuntimeError):
    pass


def email_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def web_url() -> str:
    return (os.environ.get("ARGUS_WEB_URL") or os.environ.get("ARGUS_URL") or "").rstrip("/")


def _sender() -> str:
    from email.utils import formataddr
    address = os.environ.get("SMTP_FROM", "")
    if not address:
        username = os.environ.get("SMTP_USERNAME", "")
        domain = os.environ.get("SMTP_HOST", "localhost").split(".", 1)[-1]
        address = username if "@" in username else f"{username or 'argus'}@{domain}"
    return address if "<" in address else formataddr(("ARGUS", address))


def _connect() -> smtplib.SMTP:
    """The configured relay: STARTTLS (the default), SSL, or plain; signed in when an account is given."""
    import ssl
    host = os.environ["SMTP_HOST"]
    security = os.environ.get("SMTP_SECURITY", "starttls").lower()
    port = int(os.environ.get("SMTP_PORT") or (465 if security == "ssl" else 587 if security == "starttls" else 25))
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            smtp = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=30)
            smtp.ehlo()
            if security == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
        username = os.environ.get("SMTP_USERNAME")
        if username:
            smtp.login(username, os.environ.get("SMTP_PASSWORD", ""))
        return smtp
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"The mail server {host}:{port} refused the connection: {exc}") from exc


def _message(to: str, subject: str, body: str) -> EmailMessage:
    from email.utils import formatdate, make_msgid
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = _sender(), to, subject
    msg["Date"], msg["Message-ID"] = formatdate(localtime=False), make_msgid(domain="argus")
    # Automatic: no out-of-office replies to it.
    msg["Auto-Submitted"], msg["X-Auto-Response-Suppress"] = "auto-generated", "All"
    msg.set_content(body)
    return msg


def notification_path(n: Notification) -> Optional[str]:
    """Where a notification leads in the web app, as the bell links it."""
    detail = n.detail or {}
    uid = detail.get("uid")
    if n.issue_uid:
        return f"/tickets/{n.issue_uid}"
    if detail.get("subject") in ("asset", "document", "ticket") and uid:
        return {"asset": "/assets/", "document": "/documents/", "ticket": "/tickets/"}[detail["subject"]] + uid
    return detail.get("path")


def notification_link(n: Notification) -> Optional[str]:
    """The notification's page, opened in its workspace (`?ws=`, read by the web app)."""
    from urllib.parse import quote
    path, base = notification_path(n), web_url()
    if not path or not base:
        return None
    return f"{base}{path}{'&' if '?' in path else '?'}ws={quote(n.workspace_id)}"


def _who(db: Session, actor: Optional[str]) -> Optional[str]:
    if not actor:
        return None
    user = _user(db, actor)
    return (user.name or user.email or actor) if user else actor


def _footer() -> str:
    where = f" on {web_url()}/account" if web_url() else " on your My account page"
    return f"\n-- \nARGUS. Choose what ARGUS e-mails you, and how often,{where}.\n"


def _instant_body(db: Session, n: Notification, workspace: str) -> str:
    lines = [n.title, ""]
    by = _who(db, n.actor)
    lines.append(f"Workspace: {workspace}" + (f" · by {by}" if by else ""))
    excerpt = (n.detail or {}).get("excerpt")
    if excerpt:
        lines += ["", f"> {excerpt}"]
    link = notification_link(n)
    if link:
        lines += ["", f"Open: {link}"]
    return "\n".join(lines) + "\n" + _footer()


def _digest_body(db: Session, items: list[Notification], names: dict[str, str]) -> str:
    lines = [f"{len(items)} notification(s) since your last digest.", ""]
    for ws in dict.fromkeys(n.workspace_id for n in items):
        lines += [names.get(ws, ws), "-" * len(names.get(ws, ws))]
        for n in (x for x in items if x.workspace_id == ws):
            by = _who(db, n.actor)
            lines.append(f"* {n.title}" + (f" (by {by})" if by else ""))
            link = notification_link(n)
            if link:
                lines.append(f"  {link}")
        lines.append("")
    return "\n".join(lines) + _footer()


def _digest_due(pref, at: datetime) -> bool:
    """Once a day, at NOTIFY_DIGEST_HOUR (Europe/Rome; 7 by default) or the first run after it."""
    from zoneinfo import ZoneInfo
    local = at.astimezone(ZoneInfo(os.environ.get("NOTIFY_TIMEZONE", "Europe/Rome")))
    hour = int(os.environ.get("NOTIFY_DIGEST_HOUR", "7"))
    slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if local < slot:
        slot -= timedelta(days=1)
    return pref.last_digest_at is None or pref.last_digest_at < slot


def preference(db: Session, user: Optional[User]):
    from app.models.workflow import NotificationPreference
    if user is None:
        return None
    return db.get(NotificationPreference, user.id)


_REFUSED = (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError, smtplib.SMTPSenderRefused)


class _Deferred(Exception):
    pass


def _temporary(exc: smtplib.SMTPException) -> bool:
    """A 4xx answer: try again later (a relay refusing until it is signed in to says 454). A 5xx is final."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return all(code < 500 for code, _ in exc.recipients.values())
    return getattr(exc, "smtp_code", 500) < 500


def deliver_pending(db: Session, at: Optional[datetime] = None) -> int:
    """E-mail the notifications not yet sent, when SMTP is configured: each one as it happens, or together in
    a person's daily digest, as they chose (none of what they muted). A recipient with no e-mail address, or
    one who wants none, keeps it in the app only. What is older than NOTIFY_EMAIL_MAX_AGE_HOURS (48) is not
    e-mailed late — a mail server set up today does not send a year of history. A recipient refused for good
    (5xx) does not stop the others; a mail server that cannot be reached, or defers (4xx, as a relay does until
    it is signed in to), leaves the rest for the next run."""
    import logging
    if not email_configured():
        return 0
    from app.models.workspace import Workspace
    log = logging.getLogger("argus.notify")
    at = at or now()
    oldest = at - timedelta(hours=float(os.environ.get("NOTIFY_EMAIL_MAX_AGE_HOURS", "48")))
    pending = list(db.scalars(select(Notification).where(Notification.delivered_at.is_(None))
                              .order_by(Notification.id)))
    names: dict[str, str] = {}

    def workspace(ws: str) -> str:
        if ws not in names:
            row = db.get(Workspace, ws)
            names[ws] = row.name if row else ws
        return names[ws]

    instant: list[tuple[Notification, str]] = []
    digests: dict[str, tuple[object, str, list[Notification]]] = {}
    for n in pending:
        user = _user(db, n.recipient)
        address = (user.email if user else None) or (n.recipient if "@" in n.recipient else "")
        pref = preference(db, user)
        mode = pref.email if pref is not None else "instant"
        if n.created_at < oldest or "@" not in address or mode == "off" or \
                category_of(n.kind) in ((pref.muted or []) if pref is not None else []):
            n.delivered_at = at
        elif mode == "digest" and pref is not None:
            digests.setdefault(user.id, (pref, address, []))[2].append(n)
        else:
            instant.append((n, address))
    sendable = [d for d in digests.values() if _digest_due(d[0], at)]
    sent = 0
    if not instant and not sendable:
        db.flush()
        return 0
    try:
        smtp = _connect()
    except MailError as exc:
        log.error("%s", exc)
        db.flush()
        return 0
    try:
        for n, address in instant:
            try:
                smtp.send_message(_message(address, f"[ARGUS] {n.title}"[:250],
                                           _instant_body(db, n, workspace(n.workspace_id))))
                sent += 1
            except _REFUSED as exc:
                if _temporary(exc):
                    raise _Deferred(exc) from exc
                log.warning("notification %s to %s not sent: %s", n.id, address, exc)
            n.delivered_at = at
        for pref, address, items in sendable:
            for n in items:
                workspace(n.workspace_id)
            try:
                smtp.send_message(_message(address, f"[ARGUS] Your daily digest: {len(items)} notification(s)",
                                           _digest_body(db, items, names)))
                sent += 1
            except _REFUSED as exc:
                if _temporary(exc):
                    raise _Deferred(exc) from exc
                log.warning("digest to %s not sent: %s", address, exc)
            for n in items:
                n.delivered_at = at
            pref.last_digest_at = at
    except _Deferred as exc:
        log.error("the mail server deferred delivery after %s message(s), the rest wait for the next run "
                  "(a relay that needs its account, SMTP_USERNAME?): %s", sent, exc.__cause__)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("the mail server stopped answering after %s message(s): %s", sent, exc)
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass
    db.flush()
    return sent


def send_test(user: User) -> str:
    """A message to this person now, to check the mail server and their address."""
    if not email_configured():
        raise MailError("E-mail is not configured on this installation (SMTP_HOST).")
    if not user.email or "@" not in user.email:
        raise MailError("Your account has no e-mail address.")
    smtp = _connect()
    try:
        smtp.send_message(_message(user.email, "[ARGUS] Test message",
                                   "This is a test from ARGUS: notifications by e-mail reach you here.\n"
                                   + _footer()))
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"The mail server did not take the message: {exc}") from exc
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass
    return user.email


# --------------------------------------------------------------------------- subscriptions

SUBJECTS = {"tickets": "ticket", "documents": "document", "assets": "asset"}


def announce(db: Session, workspace_id: str, what: str, kind: str, title: str, actor: Optional[str], uid: str,
             issue: Optional[Issue] = None, record=None) -> list[Notification]:
    """Something new in a workspace, told to everyone who asked to hear about that kind of thing there
    (`what`: tickets, documents or assets) — never to the person who made it, and only to those who may
    read it: the resource's read permission, and a restricted record's class (I-ACL-1)."""
    from app.auth import OidcIdentity, grants_of
    from app.models.workflow import NotificationSubscription
    from app.services.permissions import resolve_permission
    from app.services.visibility import can_see
    column = getattr(NotificationSubscription, what)
    actor_user = _user(db, actor) if actor else None
    resource = {"tickets": "tickets", "documents": "documents", "assets": "objects"}[what]
    out = []
    for sub in db.scalars(select(NotificationSubscription).where(
            NotificationSubscription.workspace_id == workspace_id, column.is_(True))):
        user = db.get(User, sub.user_id)
        if user is None or (actor_user is not None and user.id == actor_user.id) or actor in (user.id, user.email):
            continue
        if not resolve_permission(db, user, workspace_id, "read", resource):
            continue
        if issue is not None and not may_see(db, issue, user.id):
            continue
        if record is not None and not can_see(record, grants_of(db, OidcIdentity(user=user), workspace_id)):
            continue
        n = Notification(workspace_id=workspace_id, recipient=user.id, issue_uid=issue.uid if issue else None,
                         kind=kind, title=title, detail={"subject": SUBJECTS[what], "uid": uid}, actor=actor,
                         created_at=now())
        db.add(n)
        out.append(n)
    db.flush()
    return out


# --------------------------------------------------------------------------- following equipment and documents

def follow(db: Session, subject: str, uid: str, user_id: Optional[str]) -> None:
    from app.models.workflow import RecordWatcher
    if not user_id or db.get(User, user_id) is None:
        return
    if db.scalar(select(RecordWatcher).where(RecordWatcher.subject == subject, RecordWatcher.subject_uid == uid,
                                             RecordWatcher.user_id == user_id)) is None:
        db.add(RecordWatcher(subject=subject, subject_uid=uid, user_id=user_id, created_at=now()))
        db.flush()


def unfollow(db: Session, subject: str, uid: str, user_id: str) -> None:
    from app.models.workflow import RecordWatcher
    row = db.scalar(select(RecordWatcher).where(RecordWatcher.subject == subject, RecordWatcher.subject_uid == uid,
                                                RecordWatcher.user_id == user_id))
    if row is not None:
        db.delete(row)
        db.flush()


def followers(db: Session, subject: str, uid: str) -> list[str]:
    from app.models.workflow import RecordWatcher
    return list(db.scalars(select(RecordWatcher.user_id).where(RecordWatcher.subject == subject,
                                                               RecordWatcher.subject_uid == uid)))


def may_read_record(db: Session, user: User, subject: str, record) -> bool:
    """Whether this person may read this piece of equipment or document: in its workspace, or anywhere when it
    is shared (global) — and a restricted one only with its class (I-ACL-1)."""
    from app.auth import OidcIdentity, grants_of
    from app.services.permissions import resolve_permission
    from app.services.visibility import can_see
    resource = "objects" if subject == "asset" else "documents"
    ws = record.workspace_id
    if not resolve_permission(db, user, ws, "read", resource):
        if not getattr(record, "is_global", False):
            return False
        if subject == "document" and getattr(record, "confidentiality", None) == "riservato":
            return False
    if subject == "asset":
        return can_see(record, grants_of(db, OidcIdentity(user=user), ws))
    return True


def tell_followers(db: Session, subject: str, record, kind: str, title: str, actor: Optional[str],
                   detail: Optional[dict] = None, people: Optional[Iterable[str]] = None,
                   exclude: Iterable[str] = ()) -> list[Notification]:
    """A change to a piece of equipment or a document, told to the people following it (or to `people`) —
    never to the person who made it, and only to those who may read it."""
    actor_user = _user(db, actor) if actor else None
    out = []
    skip = set(exclude)
    for user_id in dict.fromkeys(people if people is not None else followers(db, subject, record.uid)):
        if user_id in skip:
            continue
        user = db.get(User, user_id)
        if user is None or (actor_user is not None and user.id == actor_user.id) or actor in (user.id, user.email):
            continue
        if not may_read_record(db, user, subject, record):
            continue
        n = Notification(workspace_id=record.workspace_id, recipient=user.id, issue_uid=None, kind=kind, title=title,
                         detail={"subject": subject, "uid": record.uid, **(detail or {})}, actor=actor,
                         created_at=now())
        db.add(n)
        out.append(n)
    db.flush()
    return out


def asset_changed(db: Session, asset_uid: str, what: str, actor: Optional[str]) -> None:
    """A history line on a piece of equipment (an edit, a label, a file, a comment), told to its followers."""
    from app.models.asset import Asset
    asset = db.get(Asset, asset_uid)
    if asset is None:
        return
    tell_followers(db, "asset", asset, "asset_changed", f"{asset.name} ({asset.key}): {what}"[:300], actor)


def document_changed(db: Session, doc, what: str, actor: Optional[str], exclude: Iterable[str] = ()) -> None:
    """A step in a document's life (a new revision, a review, a publication, a retirement), told to its
    followers."""
    tell_followers(db, "document", doc, "document_changed", f"{doc.code} {doc.title}: {what}"[:300], actor,
                   exclude=exclude)


def document_approvers(db: Session, workspace_id: str) -> list[str]:
    """The people given the right to approve documents in this workspace — by a role bound to them or to a
    group of theirs, or by a membership — not administrators, who may approve everywhere but review nothing in
    particular."""
    from app.models.group import GroupMember
    from app.models.membership import Membership
    from app.models.role import Role, RoleBinding
    from app.services.roles import membership_permissions
    ids: dict[str, None] = {}
    for binding, role in db.execute(select(RoleBinding, Role).join(Role, Role.id == RoleBinding.role_id)
                                    .where(RoleBinding.workspace_id == workspace_id)):
        if "approve" not in ((role.permissions or {}).get("documents") or []):
            continue
        if binding.subject_type == "user":
            ids[binding.subject_id] = None
        elif binding.subject_type == "group":
            ids.update(dict.fromkeys(db.scalars(select(GroupMember.user_id)
                                                .where(GroupMember.group_uid == binding.subject_id))))
    for m in db.scalars(select(Membership).where(Membership.workspace_id == workspace_id)):
        if "approve" in membership_permissions(m).get("documents", []):
            ids[m.user_id] = None
    return list(ids)


def review_requested(db: Session, doc, revision, actor: Optional[str]) -> list[str]:
    """A revision sent for review, told to whoever can approve it — the document's owner and the workspace's
    approvers, never its author (who may not approve their own revision) — and then to its followers as a
    step in its life. Says who was asked."""
    author = getattr(revision, "authored_by", None)
    people = [p for p in [getattr(doc, "owner_user_id", None), *document_approvers(db, doc.workspace_id)]
              if p and p != author]
    asked = tell_followers(db, "document", doc, "review_requested",
                           f"Review requested: {doc.code} {doc.title}, revision {revision.revision_number}"[:300],
                           actor, {"revision": revision.uid}, people=people)
    reviewers = [n.recipient for n in asked]
    document_changed(db, doc, f"revision {revision.revision_number} sent for review", actor, exclude=reviewers)
    return reviewers
