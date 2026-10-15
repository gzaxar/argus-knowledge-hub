"""Ticket workflows and notifications (asset-model-revision §19 item 3)."""
import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.models.workflow import Notification, Workflow
from app.services import notify, workflows

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])
notifications_router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


def _fail(exc: Exception):
    raise HTTPException(status_code=422, detail={"error": str(exc)})


@router.get("")
def list_workflows(workspace_id: str = Depends(require_permission("read", resource="tickets")),
                   db: Session = Depends(get_db)):
    rows = [workflows.as_dict(w) for w in db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id)
                                                      .order_by(Workflow.name))]
    return {"workflows": rows, "builtin": workflows.BUILTIN,
            "default": next((w["uid"] for w in rows if w["is_default"]), None)}


class WorkflowIn(BaseModel):
    name: str
    states: list[dict[str, Any]]
    transitions: list[dict[str, Any]] = []
    initial: str
    is_default: bool = False


@router.post("", status_code=201)
def create_workflow(body: WorkflowIn, workspace_id: str = Depends(require_permission("approve", resource="tickets")),
                    db: Session = Depends(get_db)):
    try:
        wf = workflows.save(db, workspace_id, body.model_dump())
    except workflows.WorkflowError as exc:
        _fail(exc)
    db.commit()
    return workflows.as_dict(wf)


@router.put("/{uid}")
def update_workflow(uid: str, body: WorkflowIn,
                    workspace_id: str = Depends(require_permission("approve", resource="tickets")),
                    db: Session = Depends(get_db)):
    if db.get(Workflow, uid) is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        wf = workflows.save(db, workspace_id, body.model_dump(), uid)
    except workflows.WorkflowError as exc:
        _fail(exc)
    db.commit()
    return workflows.as_dict(wf)


class JiraWorkflowIn(BaseModel):
    definition: dict[str, Any]
    is_default: bool = False


@router.post("/import-jira", status_code=201)
def import_jira_workflow(body: JiraWorkflowIn,
                         workspace_id: str = Depends(require_permission("approve", resource="tickets")),
                         db: Session = Depends(get_db)):
    """A Jira workflow, as it is: its statuses (with their category) and its
    transitions. The status map it records is what the rehearsal uses."""
    try:
        wf = workflows.save(db, workspace_id, {**workflows.from_jira(body.definition), "is_default": body.is_default})
    except (workflows.WorkflowError, KeyError) as exc:
        _fail(exc)
    db.commit()
    return workflows.as_dict(wf)


class BindIn(BaseModel):
    schema_uid: str


@router.post("/{uid}/bind")
def bind_workflow(uid: str, body: BindIn, workspace_id: str = Depends(require_permission("approve", resource="tickets")),
                  db: Session = Depends(get_db)):
    try:
        workflows.bind(db, workspace_id, body.schema_uid, uid)
    except workflows.WorkflowError as exc:
        _fail(exc)
    db.commit()
    return {"ok": True}


@router.get("/{uid}/rehearsal")
def rehearse(uid: str, workspace_id: str = Depends(require_permission("read", resource="tickets")),
             db: Session = Depends(get_db)):
    """Replay the migrated tickets' Jira status history against this workflow."""
    wf = db.get(Workflow, uid)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflows.rehearse(db, wf, workspace_id)


@router.post("/escalate")
def escalate(workspace_id: str = Depends(require_permission("approve", resource="tickets")),
             db: Session = Depends(get_db)):
    """Run the escalation timers now (normally `python -m app.ledger escalate`)."""
    n = notify.escalate_overdue(db, workspace_id=workspace_id)
    db.commit()
    return {"escalated": n}


# --------------------------------------------------------------------------- notifications

def _me(db: Session, identity, recipient: Optional[str]) -> list[str]:
    if isinstance(identity, OidcIdentity):
        return [x for x in (identity.user.id, identity.user.email) if x]
    if not recipient:
        raise HTTPException(status_code=422, detail="an API token names the recipient (?recipient=)")
    return [recipient]


@notifications_router.get("")
def my_notifications(unread: bool = False, recipient: Optional[str] = Query(None), identity=Depends(get_identity),
                     workspace_id: str = Depends(require_permission("read", resource="tickets")),
                     db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.workspace_id == workspace_id,
                                   Notification.recipient.in_(_me(db, identity, recipient)))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = list(db.scalars(q.order_by(Notification.id.desc()).limit(100)))
    return [{"id": n.id, "kind": n.kind, "title": n.title, "issue_uid": n.issue_uid, "detail": n.detail,
             "actor": n.actor, "created_at": n.created_at, "read": n.read_at is not None} for n in rows]


@notifications_router.post("/{nid}/read")
def mark_read(nid: int, recipient: Optional[str] = Query(None), identity=Depends(get_identity),
              workspace_id: str = Depends(require_permission("read", resource="tickets")),
              db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None or n.workspace_id != workspace_id or n.recipient not in _me(db, identity, recipient):
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read_at = n.read_at or notify.now()
    db.commit()
    return {"ok": True}


@notifications_router.post("/read-all")
def mark_all_read(recipient: Optional[str] = Query(None), identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("read", resource="tickets")),
                  db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.workspace_id == workspace_id,
                                                   Notification.recipient.in_(_me(db, identity, recipient)),
                                                   Notification.read_at.is_(None))):
        n.read_at = notify.now()
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- what a person wants to hear about

class SubscriptionIn(BaseModel):
    tickets: bool = False
    documents: bool = False
    assets: bool = False


@notifications_router.get("/subscriptions")
def my_subscriptions(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """For each workspace this person can open, what they hear about there: every new ticket, every new or
    newly published document, every new piece of equipment. Off until chosen."""
    from app.models.workflow import NotificationSubscription
    from app.routers.workspaces import list_my_workspaces
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="Subscriptions belong to a person, not an API token.")
    mine = {s.workspace_id: s for s in db.scalars(select(NotificationSubscription).where(
        NotificationSubscription.user_id == identity.user.id))}
    return [{"workspace_id": w.id, "workspace_name": w.name,
             "tickets": bool(mine.get(w.id) and mine[w.id].tickets),
             "documents": bool(mine.get(w.id) and mine[w.id].documents),
             "assets": bool(mine.get(w.id) and mine[w.id].assets)}
            for w in list_my_workspaces(identity, db)]


@notifications_router.put("/subscriptions/{workspace_id}")
def set_subscription(workspace_id: str, body: SubscriptionIn, identity=Depends(get_identity),
                     db: Session = Depends(get_db)):
    from app.models.workflow import NotificationSubscription
    from app.services.permissions import resolve_permission
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="Subscriptions belong to a person, not an API token.")
    if not resolve_permission(db, identity.user, workspace_id, "read", "objects") and \
            not resolve_permission(db, identity.user, workspace_id, "read", "tickets"):
        raise HTTPException(status_code=404, detail="Workspace not found")
    sub = db.scalar(select(NotificationSubscription).where(NotificationSubscription.user_id == identity.user.id,
                                                           NotificationSubscription.workspace_id == workspace_id))
    if sub is None:
        sub = NotificationSubscription(user_id=identity.user.id, workspace_id=workspace_id)
        db.add(sub)
    sub.tickets, sub.documents, sub.assets = body.tickets, body.documents, body.assets
    sub.updated_at = notify.now()
    db.commit()
    return {"workspace_id": workspace_id, **body.model_dump()}


# --------------------------------------------------------------------------- e-mail

class EmailPreferenceIn(BaseModel):
    email: Literal["instant", "digest", "off"] = "instant"
    muted: list[str] = []


def _person(identity) -> "OidcIdentity":
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="E-mail preferences belong to a person, not an API token.")
    return identity


def _preference_view(db: Session, user) -> dict:
    pref = notify.preference(db, user)
    return {"email": pref.email if pref else "instant", "muted": list(pref.muted or []) if pref else [],
            "address": user.email, "email_configured": notify.email_configured(),
            "digest_hour": int(os.environ.get("NOTIFY_DIGEST_HOUR", "7")),
            "categories": [{"key": k, "label": label} for k, (label, _) in notify.EMAIL_CATEGORIES.items()]}


@notifications_router.get("/preferences")
def my_email_preferences(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """How this person gets their notifications by e-mail: each as it happens (`instant`, the default), once a
    day (`digest`) or never (`off`), and the categories they never want by e-mail. Whether this installation
    sends e-mail at all, and to which address."""
    return _preference_view(db, _person(identity).user)


@notifications_router.put("/preferences")
def set_email_preferences(body: EmailPreferenceIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    from app.models.workflow import NotificationPreference
    user = _person(identity).user
    unknown = sorted(set(body.muted) - set(notify.EMAIL_CATEGORIES))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown categories: {', '.join(unknown)}")
    pref = db.get(NotificationPreference, user.id)
    if pref is None:
        pref = NotificationPreference(user_id=user.id)
        db.add(pref)
    if body.email == "digest" and pref.email != "digest":
        pref.last_digest_at = notify.now()        # the first digest gathers from now, not from long ago
    pref.email, pref.muted, pref.updated_at = body.email, sorted(set(body.muted)), notify.now()
    db.commit()
    return _preference_view(db, user)


@notifications_router.post("/preferences/test")
def send_test_email(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """A test message to this person's address now: checks the mail server and the address."""
    try:
        return {"sent_to": notify.send_test(_person(identity).user)}
    except notify.MailError as exc:
        raise HTTPException(status_code=409 if not notify.email_configured() else 502, detail=str(exc))


@notifications_router.get("/everywhere")
def my_notifications_everywhere(after: int = 0, include_read: bool = Query(False), identity=Depends(get_identity),
                                db: Session = Depends(get_db)):
    """This person's notifications in every workspace they can still open. Unread and newer than `after` (the
    last id the phone has shown): what a background check turns into phone notifications. With
    `include_read`: the latest hundred, read or not, newest first — the inbox."""
    from app.models.workspace import Workspace
    from app.services.permissions import resolve_permission
    if not isinstance(identity, OidcIdentity):
        return []
    q = select(Notification).where(Notification.recipient.in_(_me(db, identity, None)), Notification.id > after)
    if include_read:
        q = q.order_by(Notification.id.desc()).limit(100)
    else:
        q = q.where(Notification.read_at.is_(None)).order_by(Notification.id).limit(50)
    rows = list(db.scalars(q))
    out, names, allowed = [], {}, {}
    for n in rows:
        if n.workspace_id not in allowed:
            allowed[n.workspace_id] = resolve_permission(db, identity.user, n.workspace_id, "read", "tickets") or \
                resolve_permission(db, identity.user, n.workspace_id, "read", "objects")
            ws = db.get(Workspace, n.workspace_id)
            names[n.workspace_id] = ws.name if ws else n.workspace_id
        if allowed[n.workspace_id] or _shared_subject(db, identity, n):
            out.append({"id": n.id, "workspace_id": n.workspace_id, "workspace_name": names[n.workspace_id],
                        "kind": n.kind, "title": n.title, "issue_uid": n.issue_uid, "detail": n.detail,
                        "actor": n.actor, "created_at": n.created_at, "read": n.read_at is not None})
    return out


def _shared_subject(db: Session, identity, n) -> bool:
    """A notification about shared equipment or a shared document this person may read, from a workspace they
    have no role in."""
    from app.models.asset import Asset
    from app.models.document import Document
    subject, uid = (n.detail or {}).get("subject"), (n.detail or {}).get("uid")
    if subject not in ("asset", "document") or not uid:
        return False
    record = db.get(Asset if subject == "asset" else Document, uid)
    return record is not None and notify.may_read_record(db, identity.user, subject, record)


@notifications_router.post("/everywhere/{nid}/read")
def mark_read_everywhere(nid: int, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """One of this person's notifications read, whichever workspace it is from."""
    n = db.get(Notification, nid)
    if n is None or not isinstance(identity, OidcIdentity) or n.recipient not in _me(db, identity, None):
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read_at = n.read_at or notify.now()
    db.commit()
    return {"ok": True}


@notifications_router.post("/everywhere/read-all")
def mark_all_read_everywhere(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Every one of this person's notifications read, in every workspace."""
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="Notifications belong to a person, not an API token.")
    for n in db.scalars(select(Notification).where(Notification.recipient.in_(_me(db, identity, None)),
                                                   Notification.read_at.is_(None))):
        n.read_at = notify.now()
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- following equipment and documents

_FOLLOWABLE = {"asset", "document"}


def _followable(db: Session, identity, subject: str, uid: str):
    from app.models.asset import Asset
    from app.models.document import Document
    if subject not in _FOLLOWABLE:
        raise HTTPException(status_code=404, detail="Only equipment and documents are followed here; a ticket has watchers.")
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="Following belongs to a person, not an API token.")
    record = db.get(Asset if subject == "asset" else Document, uid)
    if record is None or getattr(record, "deleted_at", None) is not None or \
            not notify.may_read_record(db, identity.user, subject, record):
        raise HTTPException(status_code=404, detail="Not found")
    return record


@notifications_router.get("/following/{subject}/{uid}")
def following_state(subject: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Whether this person follows this piece of equipment or document, and how many do."""
    _followable(db, identity, subject, uid)
    people = notify.followers(db, subject, uid)
    return {"subject": subject, "uid": uid, "following": identity.user.id in people, "followers": len(people)}


@notifications_router.put("/following/{subject}/{uid}")
def follow_record(subject: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Follow a piece of equipment or a document: each change to it becomes a notification, in whichever
    workspace it is."""
    _followable(db, identity, subject, uid)
    notify.follow(db, subject, uid, identity.user.id)
    db.commit()
    return following_state(subject, uid, identity, db)


@notifications_router.delete("/following/{subject}/{uid}")
def unfollow_record(subject: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _followable(db, identity, subject, uid)
    notify.unfollow(db, subject, uid, identity.user.id)
    db.commit()
    return following_state(subject, uid, identity, db)


@notifications_router.get("/following")
def my_following(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """What this person follows: equipment and documents, in every workspace."""
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.workflow import RecordWatcher
    if not isinstance(identity, OidcIdentity):
        return []
    out = []
    for w in db.scalars(select(RecordWatcher).where(RecordWatcher.user_id == identity.user.id)
                        .order_by(RecordWatcher.id.desc())):
        record = db.get(Asset if w.subject == "asset" else Document, w.subject_uid)
        if record is None or not notify.may_read_record(db, identity.user, w.subject, record):
            continue
        out.append({"subject": w.subject, "uid": record.uid, "workspace_id": record.workspace_id,
                    "key": record.key if w.subject == "asset" else record.code,
                    "name": record.name if w.subject == "asset" else record.title})
    return out
