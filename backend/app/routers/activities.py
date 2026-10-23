"""Activities and quick capture (services/activities.py, services/capture.py, services/recurrence.py).

- `GET /v1/activities?from=&to=&basis=planned|actual&…` — the activities of a range the person may see, with
  counts; a `view` of today / upcoming / completed for the phone's lists, or `attention` for the cockpit (under
  way, overdue, planned today; and how many were done today).
- `POST /v1/activities` — one activity, or a recurring series (`rrule`); a client `uid` (and the
  Idempotency-Key header) makes a retry find what it made.
- `GET /v1/activities/{id}`, `PATCH /v1/activities/{id}?scope=this|future|series`,
  `POST /v1/activities/{id}/start|complete|skip|cancel|reopen` — an id is an activity's uid, or
  `<series uid>@<occurrence key>` for one occurrence of a series.
- `GET /v1/activity-series/{uid}`, `DELETE /v1/activity-series/{uid}` (ends it: what was done stays).
- `POST /v1/capture/classify` — what was said, proposed as a ticket or an activity. Nothing is written: the
  person confirms, then the ticket is created by `POST /v1/issues` (or the words added to an existing ticket
  as a comment), the activity by `POST /v1/activities`.

Activities need the right to read the workspace (any of its objects, tickets or documents): everyone works.
An activity may be in several workspaces (`workspace_ids`, its own first): it is added only to workspaces the
person may read, and its links are records of its own workspace, seen under that workspace's rules.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, PatIdentity, get_identity
from app.db import get_db
from app.models.activity import ActivitySeries
from app.services import activities as svc
from app.services import capture, recurrence
from app.services.activities import ActivityError

router = APIRouter(prefix="/v1", tags=["activities"])


def _user_id(identity: Identity) -> Optional[str]:
    return identity.user.id if isinstance(identity, OidcIdentity) else None


def _may(db: Session, identity: Identity, workspace_id: str, action: str, resource: str) -> bool:
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        return identity.workspace_id == workspace_id and identity.may(action, resource)
    if identity.token is not None and not identity.token.may(action, resource):
        return False
    if identity.token is not None and identity.token.workspace_id and identity.token.workspace_id != workspace_id:
        return False
    return resolve_permission(db, identity.user, workspace_id, action, resource)


def _workspace(identity: Identity, db: Session, header: Optional[str]) -> str:
    if isinstance(identity, PatIdentity):
        return identity.workspace_id
    ws = (identity.token.workspace_id if identity.token is not None and identity.token.workspace_id else None) or header
    if not ws:
        raise HTTPException(status_code=400, detail="X-Workspace-Id header required")
    if not any(_may(db, identity, ws, "read", r) for r in ("objects", "tickets", "documents")):
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return ws


def _may_cached(db: Session, identity: Identity):
    known: dict = {}

    def may(workspace_id: str, action: str, resource: str) -> bool:
        key = (workspace_id, action, resource)
        if key not in known:
            known[key] = _may(db, identity, workspace_id, action, resource)
        return known[key]
    return may


def _viewer(db: Session, identity: Identity, ws: str) -> svc.Viewer:
    """Who is looking, from workspace `ws`. A linked record is judged in its own workspace — an activity added to
    `ws` from another may refer to records there, seen only by those who may see them there."""
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    from app.services.visibility import asset_visible_in, can_see
    may = _may_cached(db, identity)
    uid = _user_id(identity)

    def asset(a_uid: str) -> bool:
        a = db.get(Asset, a_uid)
        if a is None:
            return True
        here = may(ws, "read", "objects") and asset_visible_in(a, ws)
        return can_see(a) and (here or may(a.workspace_id, "read", "objects"))

    def ticket(t_uid: str) -> bool:
        t = db.get(Issue, t_uid)
        return t is None or may(t.workspace_id, "read", "tickets")

    def document(d_uid: str) -> bool:
        d = db.get(Document, d_uid)
        if d is None:
            return True
        if not may(d.workspace_id, "read", "documents") or d.confidentiality == "riservato" and \
                d.owner_user_id != uid and not may(d.workspace_id, "approve", "documents"):
            return False
        return True
    read_tickets = may(ws, "read", "tickets")
    return svc.Viewer(user_id=uid, read_tickets=read_tickets, modify_tickets=may(ws, "modify", "tickets"),
                      sees_asset=asset, sees_ticket=ticket, sees_document=document)


def _fail(e: Exception):
    raise HTTPException(status_code=getattr(e, "status", 422), detail=str(e))


def _aware(v: Optional[datetime]) -> Optional[datetime]:
    if v is None:
        return None
    if v.tzinfo is None:
        raise HTTPException(status_code=422, detail="times carry their offset (e.g. 2026-10-22T09:00:00+02:00)")
    return v.astimezone(timezone.utc)


# --------------------------------------------------------------------------- reading

def _list(db: Session, identity: Identity, ws: str, *, start, end, basis, view, tz, status, owner, assignee,
          asset_uid, ticket_uid, recurring, visibility, mine, q, limit, offset) -> dict:
    zone = recurrence.zone(tz)
    at = datetime.now(timezone.utc)
    viewer = _viewer(db, identity, ws)
    me = viewer.user_id
    statuses = {x for x in (status or "").split(",") if x} or None
    filters = svc.Filters(statuses=statuses, owner=owner, assignee=assignee, asset_uid=asset_uid,
                          ticket_uid=ticket_uid, recurring=recurring, visibility=visibility, text=q)
    if view:
        local_today = at.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = recurrence.to_utc(local_today.replace(tzinfo=None), zone)
        day_end = recurrence.to_utc((local_today + timedelta(days=1)).replace(tzinfo=None), zone)
        if view == "today":
            planned = svc.in_range(db, ws, viewer, day_start, day_end, basis="planned", filters=filters, at=at)
            done = svc.in_range(db, ws, viewer, day_start, day_end, basis="actual", filters=filters, at=at)
            merged = {i.id: i for i in planned["items"] + done["items"]}
            items = sorted(merged.values(), key=lambda i: (i.planned_start or i.actual_start or i.actual_end or at))
            result = {"items": items, "counts": planned["counts"], "truncated": planned["truncated"]}
        elif view == "attention":
            reach = day_start - timedelta(days=60)
            planned = svc.in_range(db, ws, viewer, reach, day_end, basis="planned", filters=filters, at=at)
            started = svc.in_range(db, ws, viewer, reach, day_end, basis="actual", filters=filters, at=at)
            merged = {i.id: i for i in planned["items"] + started["items"]}

            def today(i):
                return i.planned_start is not None and day_start <= i.planned_start < day_end
            wanted = [i for i in merged.values()
                      if i.status == "in_progress" or (i.status == "planned" and (i.overdue(at) or today(i)))]
            wanted.sort(key=lambda i: (i.status != "in_progress", not i.overdue(at),
                                       i.planned_start or i.actual_start or at))
            counts = {"in_progress": sum(i.status == "in_progress" for i in wanted),
                      "overdue": sum(i.overdue(at) for i in wanted),
                      "today": sum(i.status == "planned" and today(i) for i in wanted),
                      "done_today": sum(1 for i in merged.values() if i.status == "completed" and i.actual_end
                                        and day_start <= i.actual_end < day_end),
                      "total": len(wanted)}
            result = {"items": wanted, "counts": counts, "truncated": planned["truncated"] or started["truncated"]}
        elif view == "upcoming":
            result = svc.in_range(db, ws, viewer, day_end, day_end + timedelta(days=30), basis="planned",
                                  filters=filters, at=at)
        else:
            filters.statuses = {"completed"}
            result = svc.in_range(db, ws, viewer, day_start - timedelta(days=30), day_end, basis="actual",
                                  filters=filters, at=at)
            result["items"].reverse()
        start, end, basis = None, None, ("actual" if view == "completed" else "planned")
    else:
        if start is None or end is None:
            raise HTTPException(status_code=422, detail="from and to, or a view, are needed")
        result = svc.in_range(db, ws, viewer, _aware(start), _aware(end), basis=basis, filters=filters, at=at)
    items = result["items"]
    if mine and me:
        items = [i for i in items if me in (i.owner_user_id, i.assignee_user_id)]
    page = items[offset:offset + limit]
    return {"items": [dict(i.view(at), may_change=svc.may_change(viewer, i)) for i in page],
            "counts": result["counts"], "total": len(items), "offset": offset, "limit": limit,
            "next_offset": offset + limit if offset + limit < len(items) else None,
            "truncated": result["truncated"], "basis": basis, "timezone": tz}


@router.get("/activities")
def list_activities(
    start: Optional[datetime] = Query(None, alias="from"),
    end: Optional[datetime] = Query(None, alias="to"),
    basis: Literal["planned", "actual"] = "planned",
    view: Optional[Literal["today", "upcoming", "completed", "attention"]] = None,
    tz: str = "UTC",
    status: Optional[str] = Query(None, description="comma-separated statuses"),
    owner: Optional[str] = None,
    assignee: Optional[str] = None,
    asset_uid: Optional[str] = None,
    ticket_uid: Optional[str] = None,
    recurring: Optional[bool] = None,
    visibility: Optional[Literal["workspace", "private"]] = None,
    mine: bool = False,
    q: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
):
    """The activities of a range the person may see, by planned or actual time, filtered, with counts. A `view`
    sets the range: `today` (planned today, under way, or done today), `upcoming` (the next 30 days) or
    `completed` (done in the last 30 days), or `attention` (under way, overdue or planned today: the cockpit), in
    the time zone `tz`. Counts are of the whole range under the same
    filters except status, and never include what the person may not see."""
    ws = _workspace(identity, db, x_workspace_id)
    try:
        return _list(db, identity, ws, start=start, end=end, basis=basis, view=view, tz=tz, status=status,
                     owner=owner, assignee=assignee, asset_uid=asset_uid, ticket_uid=ticket_uid, recurring=recurring,
                     visibility=visibility, mine=mine, q=q, limit=limit, offset=offset)
    except (ActivityError, recurrence.RuleError) as e:
        _fail(e)


def _visible_item(db: Session, identity: Identity, ws: str, activity_id: str):
    item = svc.item_of(db, ws, activity_id)
    viewer = _viewer(db, identity, ws)
    if item is None or not svc.sees(viewer, item):
        raise HTTPException(status_code=404, detail="No such activity")
    return item, viewer


@router.get("/activities/{activity_id}")
def get_activity(activity_id: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
                 x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """One activity or occurrence, with where it came from (an AI proposal's transcript, if it did)."""
    ws = _workspace(identity, db, x_workspace_id)
    item, viewer = _visible_item(db, identity, ws, activity_id)
    out = item.view(with_provenance=True)
    out["may_change"] = svc.may_change(viewer, item)
    if item.series_uid:
        s = db.get(ActivitySeries, item.series_uid)
        out["series"] = {"uid": s.uid, "rrule": s.rrule, "first_local": s.first_local, "timezone": s.timezone,
                         "text": item.recurrence, "ended": s.ended}
    return out


@router.get("/activity-series/{uid}")
def get_series(uid: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
               x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    ws = _workspace(identity, db, x_workspace_id)
    s = db.get(ActivitySeries, uid)
    if s is None or not svc.series_belongs(db, s, ws):
        raise HTTPException(status_code=404, detail="No such series")
    item = svc.fill_workspaces(db, [svc.series_item(s)])[0]
    viewer = _viewer(db, identity, ws)
    if not svc.sees(viewer, item):
        raise HTTPException(status_code=404, detail="No such series")
    return {**item.view(), "rrule": s.rrule, "first_local": s.first_local, "ended": s.ended,
            "continued_by_uid": s.continued_by_uid, "may_change": svc.may_change(viewer, item)}


# --------------------------------------------------------------------------- writing

class ActivityIn(BaseModel):
    uid: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=10000)
    status: Literal["planned", "in_progress", "completed", "cancelled"] = "planned"
    visibility: Literal["workspace", "private"] = "workspace"
    timezone: str = "UTC"
    all_day: bool = False
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    due_at: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    assignee_user_id: Optional[str] = None
    asset_uid: Optional[str] = None
    ticket_uid: Optional[str] = None
    document_uid: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=10000)
    rrule: Optional[str] = Field(default=None, max_length=300)
    # Further workspaces it is in, besides the one it is created in.
    workspace_ids: Optional[list[str]] = Field(default=None, max_length=50)
    # The AI proposal it came from: the transcript, the model, what was proposed — kept with it.
    provenance: Optional[dict] = None


class ActivityChange(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=10000)
    visibility: Optional[Literal["workspace", "private"]] = None
    all_day: Optional[bool] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    due_at: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    assignee_user_id: Optional[str] = None
    asset_uid: Optional[str] = None
    ticket_uid: Optional[str] = None
    document_uid: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=10000)
    rrule: Optional[str] = Field(default=None, max_length=300)
    # All the workspaces it is to be in (its own first is kept if listed); see services/activities.set_workspaces.
    workspace_ids: Optional[list[str]] = Field(default=None, min_length=1, max_length=50)


class ActivityAction(BaseModel):
    at: Optional[datetime] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=10000)


def _check_links(db: Session, viewer: svc.Viewer, fields: dict, ws: str, workspaces: Optional[list[str]] = None) -> None:
    """A link to a record of another workspace than the activity's own (`ws`), or to one the person may not see,
    is refused; an assignee is someone of one of the activity's `workspaces`."""
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    for key, model, sees in (("asset_uid", Asset, viewer.sees_asset), ("ticket_uid", Issue, viewer.sees_ticket),
                             ("document_uid", Document, viewer.sees_document)):
        uid = fields.get(key)
        if not uid:
            continue
        row = db.get(model, uid)
        if row is None or row.workspace_id != ws or not sees(uid):
            raise HTTPException(status_code=422, detail=f"{key}: no such record here")
    assignee = fields.get("assignee_user_id")
    if assignee:
        from app.models.user import User
        from app.services.permissions import resolve_permission
        user = db.get(User, assignee)
        if user is None or not any(resolve_permission(db, user, w, "read", r) for w in (workspaces or [ws])
                                   for r in ("objects", "tickets", "documents")):
            raise HTTPException(status_code=422, detail="assignee: not someone of the activity's workspaces")


def _check_workspaces(db: Session, identity: Identity, wanted: Optional[list[str]], already: list[str]) -> None:
    """A workspace is added only by someone who may read it."""
    for w in wanted or []:
        if w not in already and not any(_may(db, identity, w, "read", r) for r in ("objects", "tickets", "documents")):
            raise HTTPException(status_code=422, detail=f"workspace_ids: {w} is not a workspace of yours")


@router.post("/activities", status_code=201)
def create_activity(body: ActivityIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
                    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """One activity, or a recurring series (`rrule`, from `planned_start` read in `timezone`)."""
    ws = _workspace(identity, db, x_workspace_id)
    viewer = _viewer(db, identity, ws)
    if viewer.user_id is None and body.visibility == "private":
        raise HTTPException(status_code=422, detail="a private activity belongs to a person")
    fields = body.model_dump(exclude={"uid", "rrule", "workspace_ids"})
    for k in svc.TIME_FIELDS:
        fields[k] = _aware(fields[k])
    _check_links(db, viewer, fields, ws, [ws, *(body.workspace_ids or [])])
    _check_workspaces(db, identity, body.workspace_ids, [ws])
    try:
        item = svc.create(db, ws, fields, author=viewer.user_id, rrule=body.rrule, uid=body.uid,
                          workspace_ids=body.workspace_ids)
    except (ActivityError, recurrence.RuleError) as e:
        db.rollback()
        _fail(e)
    db.commit()
    return dict(item.view(), may_change=True)


@router.patch("/activities/{activity_id}")
def change_activity(activity_id: str, body: ActivityChange, scope: Literal["this", "future", "series"] = "this",
                    identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
                    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """Change it; for an occurrence, `this` one, this and the `future` ones (the series is split), or the whole
    `series`."""
    ws = _workspace(identity, db, x_workspace_id)
    item, viewer = _visible_item(db, identity, ws, activity_id)
    if not svc.may_change(viewer, item):
        raise HTTPException(status_code=403, detail="You may not change this activity")
    changes = body.model_dump(exclude_unset=True, exclude={"rrule", "workspace_ids"})
    for k in svc.TIME_FIELDS:
        if k in changes:
            changes[k] = _aware(changes[k])
    _check_links(db, viewer, changes, item.workspace_id, body.workspace_ids or item.workspace_ids)
    _check_workspaces(db, identity, body.workspace_ids, item.workspace_ids)
    try:
        out = svc.update(db, ws, activity_id, changes, scope=scope, author=viewer.user_id, rrule=body.rrule,
                         workspace_ids=body.workspace_ids)
    except (ActivityError, recurrence.RuleError) as e:
        db.rollback()
        _fail(e)
    db.commit()
    return dict(out.view(), may_change=True)


@router.post("/activities/{activity_id}/{action}")
def act_on_activity(activity_id: str, action: Literal["start", "complete", "skip", "cancel", "reopen"],
                    body: Optional[ActivityAction] = None, identity: Identity = Depends(get_identity),
                    db: Session = Depends(get_db), x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """Start, complete, skip, cancel or reopen it (one occurrence of a series, on its own)."""
    ws = _workspace(identity, db, x_workspace_id)
    item, viewer = _visible_item(db, identity, ws, activity_id)
    if not svc.may_change(viewer, item):
        raise HTTPException(status_code=403, detail="You may not change this activity")
    body = body or ActivityAction()
    try:
        out = svc.act(db, ws, activity_id, action, author=viewer.user_id, at=_aware(body.at),
                      start=_aware(body.start), end=_aware(body.end), note=body.note)
    except ActivityError as e:
        db.rollback()
        _fail(e)
    db.commit()
    return dict(out.view(), may_change=True)


@router.delete("/activity-series/{uid}", status_code=204)
def end_series(uid: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
               x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """No more occurrences after today; what was done stays."""
    ws = _workspace(identity, db, x_workspace_id)
    s = db.get(ActivitySeries, uid)
    viewer = _viewer(db, identity, ws)
    if s is None or not svc.series_belongs(db, s, ws) or not svc.sees(viewer, svc.series_item(s)):
        raise HTTPException(status_code=404, detail="No such series")
    if not svc.may_change(viewer, svc.series_item(s)):
        raise HTTPException(status_code=403, detail="You may not change this series")
    svc.end_series(db, s)
    db.commit()


# --------------------------------------------------------------------------- quick capture

class CaptureIn(BaseModel):
    transcript: str = Field(min_length=1, max_length=capture.MAX_TRANSCRIPT)
    captured_at: datetime
    timezone: str = "UTC"
    asset_uid: Optional[str] = None
    clarification: Optional[dict] = Field(default=None, description="{question, answer}: the earlier question")


@router.post("/capture/classify")
def classify_capture(body: CaptureIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
                     x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id")):
    """What was said, proposed as a ticket or an activity (or uncertain), with what it rests on, what is unsure,
    one clarifying question when needed and open tickets that look the same. Nothing is written."""
    from app.models.asset import Asset
    from app.routers.ai import _usable_config, endpoint_for
    from app.services.visibility import can_see
    ws = _workspace(identity, db, x_workspace_id)
    if body.captured_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="captured_at carries its offset")
    captured = body.captured_at.astimezone(recurrence.zone(body.timezone))
    asset = None
    if body.asset_uid:
        a = db.get(Asset, body.asset_uid)
        if a is None or a.workspace_id != ws or not can_see(a):
            raise HTTPException(status_code=422, detail="asset_uid: no such record here")
        asset = {"uid": a.uid, "key": a.key, "name": a.name}
    config = _usable_config(db, ws)
    try:
        out = capture.classify(db, ws, endpoint_for(config), body.transcript, captured, asset=asset,
                               clarification=body.clarification)
    except capture.CaptureError as e:
        _fail(e)
    if not _may(db, identity, ws, "read", "tickets"):
        out["similar_tickets"] = []
    out["model"] = config.model
    db.rollback()                                   # nothing is written
    return out
