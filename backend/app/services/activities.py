"""Activities: who sees them, what a range holds, and how they change (models/activity.py).

**Seeing.** A `workspace` activity is seen by the workspace's members who may read its tickets; a `private` one
by its owner and its assignee only — no one else, administrators included. Either way, an activity that refers
to an asset, ticket or document its viewer may not see is not shown to them, and is not counted.

**Changing.** Its owner and its assignee may change and complete it; for a workspace activity, so may those who
may modify the workspace's tickets.

**A range.** `in_range` gives the activities of [start, end) by their **planned** time (an activity spanning
the boundary is in) or by their **actual** time (when the work was done, which may be long after it was
recorded); a series is expanded only over the range, at most `recurrence.MAX_EXPANSION` occurrences each, and
an occurrence that has been stored (done, skipped, moved, edited) replaces its computed self. Counts are of the
whole range under the same filters except status, and include only what the viewer may see.

**Workspaces.** An activity is in its own workspace and in any it was added to (models/activity.py): in each it
is seen and changed under that workspace's rules, as above. Its links stay records of its own workspace; one
without links may leave its own workspace, and the next of its workspaces becomes its own.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from app.models.activity import STATUSES, VISIBILITIES, Activity, ActivitySeries, ActivityWorkspace
from app.services import recurrence

MAX_ITEMS = 5000                 # a range never returns more than this, before paging (with `truncated`)


class ActivityError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Viewer:
    user_id: Optional[str]
    read_tickets: bool = False
    modify_tickets: bool = False
    # Linked records: whether this viewer may see them (callbacks; the router knows the rules).
    sees_asset: callable = field(default=lambda uid: True)
    sees_ticket: callable = field(default=lambda uid: True)
    sees_document: callable = field(default=lambda uid: True)


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- an item, as shown

@dataclass
class Item:
    """An activity as a viewer sees it: a stored one, or a series occurrence (stored or computed)."""
    id: str
    uid: Optional[str]
    series_uid: Optional[str]
    occurrence_key: Optional[str]
    workspace_id: str
    owner_user_id: Optional[str]
    assignee_user_id: Optional[str]
    title: str
    description: Optional[str]
    visibility: str
    status: str
    timezone: str
    all_day: bool
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    due_at: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    asset_uid: Optional[str] = None
    ticket_uid: Optional[str] = None
    document_uid: Optional[str] = None
    note: Optional[str] = None
    recurrence: Optional[str] = None
    created_at: Optional[datetime] = None
    provenance: Optional[dict] = None
    workspace_ids: list = field(default_factory=list)     # its own first, then the others (fill_workspaces)

    def overdue(self, at: datetime) -> bool:
        if self.status not in ("planned", "in_progress"):
            return False
        limit = self.due_at or self.planned_end or (self.planned_start if self.status == "planned" else None)
        if limit is None:
            return False
        if self.all_day and self.due_at is None and self.planned_end is None:
            limit = limit + timedelta(days=1)                # an all-day item is overdue the day after
        return limit < at

    def view(self, at: Optional[datetime] = None, with_provenance: bool = False) -> dict:
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        out = {k: getattr(self, k) for k in ("id", "uid", "series_uid", "occurrence_key", "workspace_id",
                                              "owner_user_id", "assignee_user_id", "title", "description",
                                              "visibility", "status", "timezone", "all_day", "asset_uid",
                                              "ticket_uid", "document_uid", "note", "recurrence")}
        for k in ("planned_start", "planned_end", "due_at", "actual_start", "actual_end", "created_at"):
            out[k] = iso(getattr(self, k))
        out["workspace_ids"] = self.workspace_ids or [self.workspace_id]
        out["recurring"] = self.series_uid is not None
        out["overdue"] = self.overdue(at or now())
        if with_provenance:
            out["provenance"] = self.provenance
        return out


def _series_text(s: ActivitySeries) -> str:
    try:
        return recurrence.describe(recurrence.parse(s.rrule), datetime.fromisoformat(s.first_local))
    except (recurrence.RuleError, ValueError):
        return s.rrule


def from_activity(a: Activity, series: Optional[ActivitySeries] = None) -> Item:
    s = series
    return Item(
        id=a.uid, uid=a.uid, series_uid=a.series_uid, occurrence_key=a.occurrence_key, workspace_id=a.workspace_id,
        owner_user_id=a.owner_user_id or (s.owner_user_id if s else None),
        assignee_user_id=a.assignee_user_id if a.assignee_user_id is not None else (s.assignee_user_id if s else None),
        title=a.title or (s.title if s else ""), description=a.description if a.description is not None else
        (s.description if s else None), visibility=a.visibility or (s.visibility if s else "workspace"),
        status=a.status, timezone=a.timezone, all_day=a.all_day, planned_start=a.planned_start,
        planned_end=a.planned_end, due_at=a.due_at, actual_start=a.actual_start, actual_end=a.actual_end,
        asset_uid=a.asset_uid or (s.asset_uid if s else None), ticket_uid=a.ticket_uid or (s.ticket_uid if s else None),
        document_uid=a.document_uid or (s.document_uid if s else None), note=a.note,
        recurrence=_series_text(s) if s else None, created_at=a.created_at, provenance=a.provenance)


def from_occurrence(s: ActivitySeries, local: datetime, at: datetime) -> Item:
    key = recurrence.occurrence_key(local)
    end = at + timedelta(minutes=s.duration_minutes) if s.duration_minutes else None
    return Item(id=f"{s.uid}@{key}", uid=None, series_uid=s.uid, occurrence_key=key, workspace_id=s.workspace_id,
                owner_user_id=s.owner_user_id, assignee_user_id=s.assignee_user_id, title=s.title,
                description=s.description, visibility=s.visibility, status="planned", timezone=s.timezone,
                all_day=s.all_day, planned_start=at, planned_end=end, asset_uid=s.asset_uid, ticket_uid=s.ticket_uid,
                document_uid=s.document_uid, recurrence=_series_text(s), created_at=s.created_at,
                provenance=s.provenance)


# --------------------------------------------------------------------------- workspaces

def _shared_series(workspace_id: str):
    return select(ActivityWorkspace.series_uid).where(ActivityWorkspace.workspace_id == workspace_id,
                                                      ActivityWorkspace.series_uid.is_not(None))


def _shared_activities(workspace_id: str):
    return select(ActivityWorkspace.activity_uid).where(ActivityWorkspace.workspace_id == workspace_id,
                                                        ActivityWorkspace.activity_uid.is_not(None))


def series_in(workspace_id: str):
    return or_(ActivitySeries.workspace_id == workspace_id, ActivitySeries.uid.in_(_shared_series(workspace_id)))


def activities_in(workspace_id: str):
    """Stored activities in the workspace: their own, added to it, or occurrences of a series that is."""
    return or_(Activity.workspace_id == workspace_id, Activity.uid.in_(_shared_activities(workspace_id)),
               Activity.series_uid.in_(_shared_series(workspace_id)))


def workspaces_of(db: Session, target) -> list[str]:
    """An Activity's or a series' workspaces, its own first (an occurrence: its series')."""
    if isinstance(target, Activity) and target.series_uid:
        target = db.get(ActivitySeries, target.series_uid) or target
    col = ActivityWorkspace.series_uid if isinstance(target, ActivitySeries) else ActivityWorkspace.activity_uid
    others = sorted(db.scalars(select(ActivityWorkspace.workspace_id).where(col == target.uid)))
    return [target.workspace_id, *[w for w in others if w != target.workspace_id]]


def fill_workspaces(db: Session, items: list[Item]) -> list[Item]:
    """Each item's workspaces, in one query for a whole list."""
    series = {i.series_uid for i in items if i.series_uid}
    single = {i.uid for i in items if not i.series_uid and i.uid}
    extra: dict[str, list[str]] = {}
    if series or single:
        for row in db.execute(select(ActivityWorkspace.workspace_id, ActivityWorkspace.series_uid,
                                     ActivityWorkspace.activity_uid).where(or_(
                ActivityWorkspace.series_uid.in_(series) if series else false(),
                ActivityWorkspace.activity_uid.in_(single) if single else false()))):
            extra.setdefault(row.series_uid or row.activity_uid, []).append(row.workspace_id)
    for i in items:
        others = sorted(extra.get(i.series_uid or i.uid or "", []))
        i.workspace_ids = [i.workspace_id, *[w for w in others if w != i.workspace_id]]
    return items


def set_workspaces(db: Session, target, workspace_ids: list[str], here: str) -> None:
    """The workspaces an activity or a series is in, as a whole. Leaving its own workspace needs it to have no
    links (they are records of that workspace); the one it is changed from becomes its own if it stays in it,
    otherwise the first listed."""
    wanted = list(dict.fromkeys(w for w in workspace_ids if w))
    if not wanted:
        raise ActivityError("an activity is in at least one workspace")
    if len(wanted) > 50:
        raise ActivityError("an activity is in at most 50 workspaces")
    if target.workspace_id not in wanted:
        if target.asset_uid or target.ticket_uid or target.document_uid:
            raise ActivityError("it refers to an asset, ticket or document of its own workspace: remove that link "
                                "before taking it out of that workspace", 409)
        target.workspace_id = here if here in wanted else wanted[0]
        if isinstance(target, ActivitySeries):
            for a in db.scalars(select(Activity).where(Activity.series_uid == target.uid)):
                a.workspace_id = target.workspace_id
    is_series = isinstance(target, ActivitySeries)
    col = ActivityWorkspace.series_uid if is_series else ActivityWorkspace.activity_uid
    for row in db.scalars(select(ActivityWorkspace).where(col == target.uid)):
        db.delete(row)
    db.flush()
    for w in wanted:
        if w != target.workspace_id:
            db.add(ActivityWorkspace(workspace_id=w, **({"series_uid": target.uid} if is_series
                                                        else {"activity_uid": target.uid})))
    db.flush()


def _copy_workspaces(db: Session, source: ActivitySeries, to: ActivitySeries) -> None:
    for w in db.scalars(select(ActivityWorkspace.workspace_id).where(ActivityWorkspace.series_uid == source.uid)):
        db.add(ActivityWorkspace(workspace_id=w, series_uid=to.uid))


def series_belongs(db: Session, s: ActivitySeries, workspace_id: str) -> bool:
    return s.workspace_id == workspace_id or db.scalar(select(ActivityWorkspace.id).where(
        ActivityWorkspace.series_uid == s.uid, ActivityWorkspace.workspace_id == workspace_id)) is not None


def _activity_belongs(db: Session, a: Activity, workspace_id: str) -> bool:
    if a.series_uid:
        s = db.get(ActivitySeries, a.series_uid)
        return s is not None and series_belongs(db, s, workspace_id)
    return a.workspace_id == workspace_id or db.scalar(select(ActivityWorkspace.id).where(
        ActivityWorkspace.activity_uid == a.uid, ActivityWorkspace.workspace_id == workspace_id)) is not None


# --------------------------------------------------------------------------- who sees, who changes

def sees(viewer: Viewer, item: Item) -> bool:
    mine = viewer.user_id is not None and viewer.user_id in (item.owner_user_id, item.assignee_user_id)
    if item.visibility == "private" and not mine:
        return False
    if item.visibility != "private" and not (mine or viewer.read_tickets):
        return False
    if item.asset_uid and not viewer.sees_asset(item.asset_uid):
        return False
    if item.ticket_uid and not viewer.sees_ticket(item.ticket_uid):
        return False
    if item.document_uid and not viewer.sees_document(item.document_uid):
        return False
    return True


def may_change(viewer: Viewer, item: Item) -> bool:
    if viewer.user_id is not None and viewer.user_id in (item.owner_user_id, item.assignee_user_id):
        return True
    return item.visibility != "private" and viewer.modify_tickets and sees(viewer, item)


def _series_clause(viewer: Viewer):
    """The SQL side of `sees` for series (the linked-record checks follow in Python)."""
    mine = or_(ActivitySeries.owner_user_id == viewer.user_id, ActivitySeries.assignee_user_id == viewer.user_id) \
        if viewer.user_id else false()
    return or_(mine, ActivitySeries.visibility != "private") if viewer.read_tickets else mine


# --------------------------------------------------------------------------- a range

@dataclass
class Filters:
    statuses: Optional[set] = None
    owner: Optional[str] = None
    assignee: Optional[str] = None
    asset_uid: Optional[str] = None
    ticket_uid: Optional[str] = None
    recurring: Optional[bool] = None
    visibility: Optional[str] = None
    text: Optional[str] = None

    def keep(self, i: Item, with_status: bool = True) -> bool:
        if with_status and self.statuses and i.status not in self.statuses:
            return False
        if self.owner and i.owner_user_id != self.owner:
            return False
        if self.assignee and i.assignee_user_id != self.assignee:
            return False
        if self.asset_uid and i.asset_uid != self.asset_uid:
            return False
        if self.ticket_uid and i.ticket_uid != self.ticket_uid:
            return False
        if self.recurring is not None and (i.series_uid is not None) != self.recurring:
            return False
        if self.visibility and i.visibility != self.visibility:
            return False
        if self.text and self.text.lower() not in f"{i.title} {i.description or ''}".lower():
            return False
        return True


def _planned_window(item: Item) -> tuple[Optional[datetime], Optional[datetime]]:
    start = item.planned_start or item.due_at
    end = item.planned_end or item.due_at or item.planned_start
    if item.all_day and start is not None and (item.planned_end is None):
        end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start, end


def _actual_window(item: Item, at: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    start = item.actual_start or item.actual_end
    end = item.actual_end or (at if item.status == "in_progress" else item.actual_start)
    return start, end


def overlaps(item: Item, start: datetime, end: datetime, basis: str, at: datetime) -> bool:
    s, e = _planned_window(item) if basis == "planned" else _actual_window(item, at)
    if s is None:
        return False
    return s < end and (e or s) >= start


def in_range(db: Session, workspace_id: str, viewer: Viewer, start: datetime, end: datetime, *,
             basis: str = "planned", filters: Optional[Filters] = None, at: Optional[datetime] = None) -> dict:
    """{items (sorted), counts, truncated} for the viewer: see the module's description."""
    if basis not in ("planned", "actual"):
        raise ActivityError("basis is planned or actual")
    if end <= start:
        raise ActivityError("the range ends before it starts")
    if end - start > timedelta(days=400):
        raise ActivityError("a range is at most 400 days")
    filters = filters or Filters()
    at = at or now()
    items: list[Item] = []

    series = {s.uid: s for s in db.scalars(select(ActivitySeries).where(
        series_in(workspace_id), _series_clause(viewer)))}

    # Stored activities and occurrences whose own times may fall in the range.
    q = select(Activity).where(activities_in(workspace_id))
    if basis == "planned":
        q = q.where(or_(Activity.planned_start < end, Activity.due_at < end))
    else:
        q = q.where(or_(Activity.actual_start < end, Activity.actual_end < end))
    stored = list(db.scalars(q.limit(MAX_ITEMS * 2)))
    stored_keys: dict[str, set] = {}
    for a in db.scalars(select(Activity).where(Activity.series_uid.in_(list(series)) if series else false())):
        stored_keys.setdefault(a.series_uid, set()).add(a.occurrence_key)
    for a in stored:
        s = series.get(a.series_uid) if a.series_uid else None
        if a.series_uid and s is None:
            s = db.get(ActivitySeries, a.series_uid)
        items.append(from_activity(a, s))

    # The series' computed occurrences: by planned time only (nothing has been done in one not stored).
    if basis == "planned":
        for s in series.values():                            # an ended series stops at its UNTIL
            try:
                rule = recurrence.parse(s.rrule)
                first = datetime.fromisoformat(s.first_local)
                # An occurrence starting before the range but running into it is in the range too.
                reach = timedelta(minutes=s.duration_minutes or 0) + (timedelta(days=1) if s.all_day else timedelta(0))
                for local, utc in recurrence.between(rule, first, s.timezone, start - reach, end):
                    if recurrence.occurrence_key(local) in stored_keys.get(s.uid, ()):
                        continue
                    items.append(from_occurrence(s, local, utc))
            except (recurrence.RuleError, ValueError):
                continue

    seen = [i for i in items if overlaps(i, start, end, basis, at) and sees(viewer, i)]
    in_filter = [i for i in seen if filters.keep(i, with_status=False)]
    counts = {k: 0 for k in ("planned", "in_progress", "completed", "cancelled", "skipped", "overdue", "total")}
    for i in in_filter:
        counts[i.status] = counts.get(i.status, 0) + 1
        counts["overdue"] += 1 if i.overdue(at) else 0
        counts["total"] += 1
    kept = [i for i in in_filter if filters.keep(i)]

    def when(i: Item):
        w = _planned_window(i)[0] if basis == "planned" else _actual_window(i, at)[0]
        return (w or datetime.max.replace(tzinfo=timezone.utc), i.title)
    kept.sort(key=when)
    return {"items": fill_workspaces(db, kept[:MAX_ITEMS]), "counts": counts, "truncated": len(kept) > MAX_ITEMS}


# --------------------------------------------------------------------------- reading one

def resolve_id(db: Session, workspace_id: str, activity_id: str) -> tuple[Optional[Activity], Optional[ActivitySeries],
                                                                             Optional[datetime]]:
    """(stored activity, its series, the occurrence's local start) for an id: an activity's uid, or
    `<series uid>@<occurrence key>` for an occurrence (stored or not)."""
    if "@" in activity_id:
        series_uid, _, key = activity_id.partition("@")
        s = db.get(ActivitySeries, series_uid)
        if s is None or not series_belongs(db, s, workspace_id):
            return None, None, None
        try:
            local = datetime.fromisoformat(key)
        except ValueError:
            return None, None, None
        a = db.scalar(select(Activity).where(Activity.series_uid == s.uid, Activity.occurrence_key == key))
        if a is None and not recurrence.is_occurrence(recurrence.parse(s.rrule), datetime.fromisoformat(s.first_local),
                                                      local):
            return None, None, None
        return a, s, local
    a = db.get(Activity, activity_id)
    if a is None or not _activity_belongs(db, a, workspace_id):
        return None, None, None
    s = db.get(ActivitySeries, a.series_uid) if a.series_uid else None
    return a, s, datetime.fromisoformat(a.occurrence_key) if a.occurrence_key else None


def item_of(db: Session, workspace_id: str, activity_id: str) -> Optional[Item]:
    a, s, local = resolve_id(db, workspace_id, activity_id)
    if a is not None:
        return fill_workspaces(db, [from_activity(a, s)])[0]
    if s is not None and local is not None:
        return fill_workspaces(db, [from_occurrence(s, local, recurrence.to_utc(local, recurrence.zone(s.timezone)))])[0]
    return None


# --------------------------------------------------------------------------- creating

TIME_FIELDS = ("planned_start", "planned_end", "due_at", "actual_start", "actual_end")


def _check(fields: dict) -> None:
    status = fields.get("status", "planned")
    if status not in STATUSES:
        raise ActivityError(f"status is one of {', '.join(STATUSES)}")
    if fields.get("visibility", "workspace") not in VISIBILITIES:
        raise ActivityError("visibility is workspace or private")
    recurrence.zone(fields.get("timezone") or "UTC")
    if not (fields.get("title") or "").strip():
        raise ActivityError("an activity has a title")
    for a, b in (("planned_start", "planned_end"), ("actual_start", "actual_end")):
        if fields.get(a) and fields.get(b) and fields[b] < fields[a]:
            raise ActivityError(f"{b} is before {a}")
    if status == "completed" and not (fields.get("actual_end") or fields.get("actual_start")):
        raise ActivityError("a completed activity says when it was done")
    if status == "in_progress" and not fields.get("actual_start"):
        raise ActivityError("an activity in progress says when it started")
    when = fields.get("actual_end") or fields.get("actual_start")
    if when and when > now() + timedelta(minutes=5):
        raise ActivityError("work that was done cannot be in the future")


def create(db: Session, workspace_id: str, fields: dict, *, author: Optional[str], rrule: Optional[str] = None,
           uid: Optional[str] = None, workspace_ids: Optional[list[str]] = None) -> Item:
    """A single activity, or a series when `rrule` is given (its first start is `planned_start`, read in
    `timezone`), in `workspace_id` and any further `workspace_ids`. A `uid` the client chose makes a retry find
    what it made rather than make it twice."""
    if uid:
        existing = db.get(Activity, uid) or db.get(ActivitySeries, uid)
        if existing is not None:
            if existing.workspace_id != workspace_id:
                raise ActivityError("that uid is taken", 409)
            return item_of(db, workspace_id, uid) if isinstance(existing, Activity) else \
                series_item(existing)
    fields = {k: v for k, v in fields.items() if v is not None}
    fields.setdefault("visibility", "workspace")
    fields.setdefault("timezone", "UTC")
    if rrule:
        rule = recurrence.parse(rrule)
        if not fields.get("planned_start"):
            raise ActivityError("a recurring activity has a first start")
        tz = recurrence.zone(fields["timezone"])
        first = fields["planned_start"].astimezone(tz).replace(tzinfo=None, second=0, microsecond=0)
        if fields.get("all_day"):
            first = first.replace(hour=0, minute=0)
        duration = None
        if fields.get("planned_end"):
            duration = int((fields["planned_end"] - fields["planned_start"]).total_seconds() // 60) or None
        if not (fields.get("title") or "").strip():
            raise ActivityError("an activity has a title")
        s = ActivitySeries(uid=uid or str(uuid.uuid4()), workspace_id=workspace_id,
                           owner_user_id=fields.get("owner_user_id") or author,
                           assignee_user_id=fields.get("assignee_user_id"), title=fields["title"].strip()[:300],
                           description=fields.get("description"), visibility=fields["visibility"],
                           rrule=rule.text(), first_local=first.isoformat(timespec="minutes"),
                           timezone=fields["timezone"], all_day=bool(fields.get("all_day")), duration_minutes=duration,
                           asset_uid=fields.get("asset_uid"), ticket_uid=fields.get("ticket_uid"),
                           document_uid=fields.get("document_uid"), provenance=fields.get("provenance"),
                           created_by=author)
        db.add(s)
        db.flush()
        if workspace_ids:
            set_workspaces(db, s, [workspace_id, *workspace_ids], workspace_id)
        return fill_workspaces(db, [series_item(s)])[0]
    _check(fields)
    a = Activity(uid=uid or str(uuid.uuid4()), workspace_id=workspace_id,
                 owner_user_id=fields.get("owner_user_id") or author, assignee_user_id=fields.get("assignee_user_id"),
                 title=fields["title"].strip()[:300], description=fields.get("description"),
                 visibility=fields["visibility"], status=fields.get("status", "planned"), timezone=fields["timezone"],
                 all_day=bool(fields.get("all_day")), **{k: fields.get(k) for k in TIME_FIELDS},
                 asset_uid=fields.get("asset_uid"), ticket_uid=fields.get("ticket_uid"),
                 document_uid=fields.get("document_uid"), note=fields.get("note"), provenance=fields.get("provenance"),
                 created_by=author)
    db.add(a)
    db.flush()
    if workspace_ids:
        set_workspaces(db, a, [workspace_id, *workspace_ids], workspace_id)
    return fill_workspaces(db, [from_activity(a)])[0]


def series_item(s: ActivitySeries) -> Item:
    first = datetime.fromisoformat(s.first_local)
    item = from_occurrence(s, first, recurrence.to_utc(first, recurrence.zone(s.timezone)))
    item.id = s.uid
    return item


# --------------------------------------------------------------------------- changing

EDITABLE = ("title", "description", "visibility", "assignee_user_id", "asset_uid", "ticket_uid", "document_uid",
            "note", "all_day", *TIME_FIELDS)
SERIES_EDITABLE = ("title", "description", "visibility", "assignee_user_id", "asset_uid", "ticket_uid", "document_uid")


def _materialise(db: Session, s: ActivitySeries, local: datetime, author: Optional[str]) -> Activity:
    """The occurrence as a stored activity (its overrides still empty), to record something about it."""
    key = recurrence.occurrence_key(local)
    a = db.scalar(select(Activity).where(Activity.series_uid == s.uid, Activity.occurrence_key == key))
    if a is not None:
        return a
    at = recurrence.to_utc(local, recurrence.zone(s.timezone))
    a = Activity(uid=str(uuid.uuid4()), workspace_id=s.workspace_id, series_uid=s.uid, occurrence_key=key,
                 owner_user_id=s.owner_user_id, status="planned", timezone=s.timezone, all_day=s.all_day,
                 planned_start=at,
                 planned_end=at + timedelta(minutes=s.duration_minutes) if s.duration_minutes else None,
                 created_by=author)
    db.add(a)
    db.flush()
    return a


def update(db: Session, workspace_id: str, activity_id: str, changes: dict, *, scope: str = "this",
           author: Optional[str] = None, rrule: Optional[str] = None,
           workspace_ids: Optional[list[str]] = None) -> Item:
    """Change an activity. For a series occurrence, `scope` says what: `this` occurrence, `future` (this one
    and the ones after it: the series is split), or `series` (all of them: the series itself). The workspaces
    of a series' occurrence are the series': they change for the future ones or the whole series."""
    a, s, local = resolve_id(db, workspace_id, activity_id)
    if a is None and s is None:
        raise ActivityError("no such activity", 404)
    if workspace_ids is not None and s is not None and scope == "this":
        raise ActivityError("an occurrence is in its series' workspaces: change them for this and the future "
                            "occurrences, or for the whole series")
    changes = {k: v for k, v in changes.items() if k in EDITABLE}
    if "visibility" in changes and changes["visibility"] not in VISIBILITIES:
        raise ActivityError("visibility is workspace or private")
    if s is None or scope == "this":
        if a is None:
            a = _materialise(db, s, local, author)
        for k, v in changes.items():
            setattr(a, k, v)
        merged = from_activity(a, s)
        _check({**{k: getattr(merged, k) for k in ("title", "status", "visibility", "timezone", *TIME_FIELDS)}})
        if workspace_ids is not None:
            set_workspaces(db, a, workspace_ids, workspace_id)
        db.flush()
        return fill_workspaces(db, [from_activity(a, s)])[0]
    if scope == "series":
        for k, v in changes.items():
            if k in SERIES_EDITABLE:
                setattr(s, k, v)
        if rrule:
            s.rrule = recurrence.parse(rrule).text()
        if "planned_start" in changes and changes["planned_start"]:
            tz = recurrence.zone(s.timezone)
            new_time = changes["planned_start"].astimezone(tz).time().replace(second=0, microsecond=0)
            s.first_local = datetime.combine(datetime.fromisoformat(s.first_local).date(), new_time).isoformat(
                timespec="minutes")
        if workspace_ids is not None:
            set_workspaces(db, s, workspace_ids, workspace_id)
        db.flush()
        return fill_workspaces(db, [series_item(s)])[0]
    if scope != "future":
        raise ActivityError("scope is this, future or series")
    return split(db, s, local, changes, author=author, rrule=rrule, workspace_ids=workspace_ids, here=workspace_id)


def split(db: Session, s: ActivitySeries, local: datetime, changes: dict, *, author: Optional[str],
          rrule: Optional[str] = None, workspace_ids: Optional[list[str]] = None, here: Optional[str] = None) -> Item:
    """This occurrence and the ones after it become a new series (with the changes); the old one ends before it.
    Occurrences already stored from there on move to the new series."""
    rule = recurrence.parse(s.rrule)
    first = datetime.fromisoformat(s.first_local)
    if local == first:                                        # from the first: it is the whole series
        return update(db, here or s.workspace_id, f"{s.uid}@{recurrence.occurrence_key(local)}", changes,
                      scope="series", author=author, rrule=rrule, workspace_ids=workspace_ids)
    remaining = recurrence.remaining_after(rule, first, local)
    old = recurrence.Rule(freq=rule.freq, interval=rule.interval, byday=list(rule.byday), bymonthday=rule.bymonthday)
    if rule.count is not None:
        old.count = rule.count - remaining
    else:
        old.until = (local - timedelta(days=1)).date()
    new_rule = recurrence.parse(rrule) if rrule else recurrence.Rule(
        freq=rule.freq, interval=rule.interval, byday=list(rule.byday), bymonthday=rule.bymonthday,
        count=remaining, until=rule.until)
    start = local
    if changes.get("planned_start"):
        tz = recurrence.zone(s.timezone)
        start = changes["planned_start"].astimezone(tz).replace(tzinfo=None, second=0, microsecond=0)
    n = ActivitySeries(uid=str(uuid.uuid4()), workspace_id=s.workspace_id, owner_user_id=s.owner_user_id,
                       assignee_user_id=s.assignee_user_id, title=s.title, description=s.description,
                       visibility=s.visibility, rrule=new_rule.text(), first_local=start.isoformat(timespec="minutes"),
                       timezone=s.timezone, all_day=s.all_day, duration_minutes=s.duration_minutes,
                       asset_uid=s.asset_uid, ticket_uid=s.ticket_uid, document_uid=s.document_uid,
                       provenance=s.provenance, created_by=author)
    for k, v in changes.items():
        if k in SERIES_EDITABLE:
            setattr(n, k, v)
    db.add(n)
    db.flush()
    _copy_workspaces(db, s, n)
    db.flush()
    s.rrule = old.text()
    s.continued_by_uid = n.uid
    key = recurrence.occurrence_key(local)
    for a in db.scalars(select(Activity).where(Activity.series_uid == s.uid, Activity.occurrence_key >= key)):
        if a.status in ("completed", "skipped", "cancelled"):
            # Done work keeps the words it was done under, not the new series'.
            a.title = a.title or s.title
            a.description = a.description if a.description is not None else s.description
        a.series_uid = n.uid
    db.flush()
    if workspace_ids is not None:
        set_workspaces(db, n, workspace_ids, here or n.workspace_id)
    return fill_workspaces(db, [series_item(n)])[0]


def act(db: Session, workspace_id: str, activity_id: str, action: str, *, author: Optional[str],
        at: Optional[datetime] = None, start: Optional[datetime] = None, end: Optional[datetime] = None,
        note: Optional[str] = None) -> Item:
    """start | complete | skip | cancel | reopen, on an activity or one occurrence (stored as it happens)."""
    a, s, local = resolve_id(db, workspace_id, activity_id)
    if a is None and s is None:
        raise ActivityError("no such activity", 404)
    if a is None:
        a = _materialise(db, s, local, author)
    moment = at or now()
    if (start and start > now() + timedelta(minutes=5)) or (end and end > now() + timedelta(minutes=5)):
        raise ActivityError("work that was done cannot be in the future")
    if action == "start":
        if a.status not in ("planned",):
            raise ActivityError(f"an activity {a.status.replace('_', ' ')} cannot be started", 409)
        a.status, a.actual_start = "in_progress", start or moment
    elif action == "complete":
        if a.status in ("completed", "cancelled", "skipped"):
            raise ActivityError(f"this activity is {a.status} already", 409)
        a.status = "completed"
        a.actual_start = start or a.actual_start
        a.actual_end = end or moment
        if a.actual_start and a.actual_end < a.actual_start:
            raise ActivityError("it ended before it started")
    elif action in ("skip", "cancel"):
        if a.status in ("completed",):
            raise ActivityError("a completed activity is not skipped or cancelled", 409)
        if action == "skip" and a.series_uid is None and a.planned_start is None:
            raise ActivityError("only a planned activity is skipped")
        a.status = "skipped" if action == "skip" else "cancelled"
    elif action == "reopen":
        a.status, a.actual_end = ("in_progress" if a.actual_start else "planned"), None
    else:
        raise ActivityError("action is start, complete, skip, cancel or reopen")
    if note is not None:
        a.note = note
    db.flush()
    return fill_workspaces(db, [from_activity(a, s)])[0]


def end_series(db: Session, s: ActivitySeries, *, at: Optional[datetime] = None) -> None:
    """No occurrences after today (local); what was stored stays."""
    rule = recurrence.parse(s.rrule)
    tz = recurrence.zone(s.timezone)
    today = (at or now()).astimezone(tz).date()
    rule.count, rule.until = None, today
    s.rrule = rule.text()
    s.ended = True
    db.flush()
