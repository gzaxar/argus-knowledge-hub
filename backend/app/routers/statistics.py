"""The Statistics page: how ARGUS is used, without saying by whom (services/usage.py). Administrators.

Everything is counted: requests per day and client, people per day and at the same time (from keyed hashes),
the language model's calls and tokens, what is done in each workspace, the functions used most, the slowest
and the failing ones, how Ask ARGUS answers and how its answers are rated, and how full the storage is.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.orm import Session

from app.auth import PatIdentity, get_identity
from app.db import get_db
from app.models.ask_conversation import AskConversation, AskMessage
from app.models.asset import Asset
from app.models.document import Document
from app.models.issue import Issue
from app.models.usage import AskFeedback, UsageLLM, UsagePresence, UsageRequest
from app.models.user import User
from app.models.workspace import Workspace
from app.services import usage

router = APIRouter(prefix="/v1/admin/statistics", tags=["statistics"])

CLIENTS = ("web", "app", "mcp", "api")


def _admin(identity) -> None:
    if isinstance(identity, PatIdentity) or not getattr(getattr(identity, "user", None), "is_admin", False):
        raise HTTPException(status_code=403, detail="Admins only")


_RECORD_ROUTES = (("/v1/assets", "objects"), ("/v1/issues", "tickets"), ("/v1/documents", "documents"))
_CREATES = {"POST /v1/assets", "POST /v1/issues", "POST /v1/documents", "POST /v1/documents/reshape",
            "POST /v1/documents/import"}


def record_operation(function: str) -> tuple:
    """(kind, new | changed | deleted) of a counted route on objects, tickets or documents; (None, None) else.
    Reading routes and searches (a POST that changes nothing) are not operations on records."""
    method, _, path = function.partition(" ")
    kind = next((k for prefix, k in _RECORD_ROUTES if path == prefix or path.startswith(prefix + "/")), None)
    if kind is None or method in ("GET", "HEAD", "OPTIONS"):
        return None, None
    if path.endswith(("/search", "/query", "/markdown", "/pdf", "/export", "/preview", "/suggest", "/check")):
        return None, None
    if "/watchers" in path:
        return None, None                       # following a ticket is not changing it
    if function in _CREATES:
        return kind, "new"
    # The record itself deleted or retired; deleting a label, a link or a location changes it.
    if (method == "DELETE" and path.count("/") == 3) or path.endswith(("/bulk-delete", "/retire")):
        return kind, "deleted"
    return kind, "changed"


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


@router.get("")
def statistics(days: int = Query(30, ge=1, le=366), refresh_storage: bool = False, identity=Depends(get_identity),
               db: Session = Depends(get_db)):
    """Usage over the last `days` days, anonymous, and the storage (`refresh_storage`: measured again now)."""
    _admin(identity)
    usage.flush()                                    # what this process counted so far is in
    now = datetime.now(timezone.utc)
    end = now.date()
    start = end - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    names = dict(db.execute(select(Workspace.id, Workspace.name)).all())

    # ---------------------------------------------------------------- requests and people
    per_day = {d: {c: 0 for c in CLIENTS} for d in _days(start, end)}
    for day, client, n in db.execute(select(UsageRequest.day, UsageRequest.client, func.sum(UsageRequest.count))
                                     .where(UsageRequest.day >= start).group_by(UsageRequest.day, UsageRequest.client)):
        per_day.setdefault(day.isoformat(), {c: 0 for c in CLIENTS})[client] = int(n)

    people_day = {d: {c: 0 for c in CLIENTS} | {"all": 0} for d in _days(start, end)}
    bucket_day = cast(func.timezone("UTC", UsagePresence.bucket), Date)
    for day, client, n in db.execute(select(bucket_day, UsagePresence.client, func.count(func.distinct(UsagePresence.person)))
                                     .where(UsagePresence.bucket >= since).group_by(bucket_day, UsagePresence.client)):
        people_day.setdefault(day.isoformat(), {c: 0 for c in CLIENTS} | {"all": 0})[client] = int(n)
    for day, n in db.execute(select(bucket_day, func.count(func.distinct(UsagePresence.person)))
                             .where(UsagePresence.bucket >= since).group_by(bucket_day)):
        people_day[day.isoformat()]["all"] = int(n)

    # At the same time: the most people active in one five-minute slot, each day.
    slots = (select(UsagePresence.bucket.label("bucket"), func.count(func.distinct(UsagePresence.person)).label("n"))
             .where(UsagePresence.bucket >= since).group_by(UsagePresence.bucket).subquery())
    peak = {d: 0 for d in _days(start, end)}
    peak_at: dict[str, str] = {}
    for bucket, n in db.execute(select(slots.c.bucket, slots.c.n)):
        d = bucket.astimezone(timezone.utc).date().isoformat()
        if n > peak.get(d, 0):
            peak[d], peak_at[d] = int(n), bucket.isoformat()
    distinct = lambda since_: int(db.scalar(select(func.count(func.distinct(UsagePresence.person))).where(  # noqa: E731
        UsagePresence.bucket >= since_)) or 0)

    # ---------------------------------------------------------------- functions
    fn_rows = db.execute(
        select(UsageRequest.function, func.sum(UsageRequest.count), func.sum(UsageRequest.errors),
               func.sum(UsageRequest.ms_total))
        .where(UsageRequest.day >= start).group_by(UsageRequest.function)).all()
    functions = [{"function": f, "count": int(c), "errors": int(e), "avg_ms": round(int(ms) / int(c)) if c else 0}
                 for f, c, e, ms in fn_rows]
    top = sorted(functions, key=lambda r: -r["count"])[:30]
    slowest = sorted([r for r in functions if r["count"] >= 20 and "/chat" not in r["function"]],
                     key=lambda r: -r["avg_ms"])[:10]
    failing = sorted([r for r in functions if r["errors"]], key=lambda r: -r["errors"])[:10]
    by_client_fn: dict[str, list] = {}
    for client in CLIENTS:
        rows = db.execute(select(UsageRequest.function, func.sum(UsageRequest.count)).where(
            UsageRequest.day >= start, UsageRequest.client == client).group_by(UsageRequest.function)
            .order_by(func.sum(UsageRequest.count).desc()).limit(8)).all()
        by_client_fn[client] = [{"function": f, "count": int(c)} for f, c in rows]

    # ---------------------------------------------------------------- workspaces
    ws_rows = db.execute(
        select(UsageRequest.workspace_id,
               func.sum(UsageRequest.count),
               func.sum(UsageRequest.count).filter(~UsageRequest.function.like("GET %")))
        .where(UsageRequest.day >= start, UsageRequest.workspace_id != "").group_by(UsageRequest.workspace_id)).all()
    workspaces = {w: {"workspace": w, "name": names.get(w, w), "requests": int(r), "writes": int(wr or 0),
                      "objects_created": 0, "tickets_created": 0, "documents_created": 0, "ask_questions": 0}
                  for w, r, wr in ws_rows}

    def created(model, key):
        for w, n in db.execute(select(model.workspace_id, func.count()).where(model.created_at >= since)
                               .group_by(model.workspace_id)):
            workspaces.setdefault(w, {"workspace": w, "name": names.get(w, w), "requests": 0, "writes": 0,
                                      "objects_created": 0, "tickets_created": 0, "documents_created": 0,
                                      "ask_questions": 0})[key] = int(n)
    created(Asset, "objects_created")
    created(Issue, "tickets_created")
    created(Document, "documents_created")
    for w, n in db.execute(select(AskConversation.workspace_id, func.count()).join(
            AskMessage, AskMessage.conversation_id == AskConversation.id).where(
            AskMessage.role == "user", AskMessage.created_at >= since).group_by(AskConversation.workspace_id)):
        workspaces.setdefault(w, {"workspace": w, "name": names.get(w, w), "requests": 0, "writes": 0,
                                  "objects_created": 0, "tickets_created": 0, "documents_created": 0,
                                  "ask_questions": 0})["ask_questions"] = int(n)

    # ---------------------------------------------------------------- records: new and changed
    # New: from the records themselves (imports included, the whole period). Changed and deleted: the operations
    # made through ARGUS on them (the web, the app, scripts), from the request counts.
    kinds = {"objects": Asset, "tickets": Issue, "documents": Document}
    records_day = {d: {f"{k}_{op}": 0 for k in kinds for op in ("new", "changed", "deleted")}
                   for d in _days(start, end)}
    for kind, model in kinds.items():
        created_day = cast(func.timezone("UTC", model.created_at), Date)
        for day, n in db.execute(select(created_day, func.count()).where(model.created_at >= since)
                                 .group_by(created_day)):
            if day.isoformat() in records_day:
                records_day[day.isoformat()][f"{kind}_new"] = int(n)
    for day, ws, function, n in db.execute(
            select(UsageRequest.day, UsageRequest.workspace_id, UsageRequest.function, func.sum(UsageRequest.count))
            .where(UsageRequest.day >= start, ~UsageRequest.function.like("GET %"))
            .group_by(UsageRequest.day, UsageRequest.workspace_id, UsageRequest.function)):
        kind, op = record_operation(function)
        if kind is None or op == "new":
            continue
        records_day.setdefault(day.isoformat(), {})[f"{kind}_{op}"] = \
            records_day.get(day.isoformat(), {}).get(f"{kind}_{op}", 0) + int(n)
        if ws and op == "changed":
            row = workspaces.setdefault(ws, {"workspace": ws, "name": names.get(ws, ws), "requests": 0, "writes": 0,
                                             "objects_created": 0, "tickets_created": 0, "documents_created": 0,
                                             "ask_questions": 0})
            row[f"{kind}_changed"] = row.get(f"{kind}_changed", 0) + int(n)
    for row in workspaces.values():
        for k in kinds:
            row.setdefault(f"{k}_changed", 0)

    # ---------------------------------------------------------------- trends
    # Each workspace's activity per day (changes through ARGUS plus records created), for a sparkline; and the
    # period before this one, of the same length, to say whether things are going up or down.
    activity: dict[str, dict[str, int]] = {}
    for day, ws, n in db.execute(
            select(UsageRequest.day, UsageRequest.workspace_id, func.sum(UsageRequest.count))
            .where(UsageRequest.day >= start, UsageRequest.workspace_id != "", ~UsageRequest.function.like("GET %"))
            .group_by(UsageRequest.day, UsageRequest.workspace_id)):
        activity.setdefault(ws, {})[day.isoformat()] = activity.get(ws, {}).get(day.isoformat(), 0) + int(n)
    for model in kinds.values():
        created_day = cast(func.timezone("UTC", model.created_at), Date)
        for day, ws, n in db.execute(select(created_day, model.workspace_id, func.count())
                                     .where(model.created_at >= since).group_by(created_day, model.workspace_id)):
            activity.setdefault(ws, {})[day.isoformat()] = activity.get(ws, {}).get(day.isoformat(), 0) + int(n)
    for ws, row in workspaces.items():
        row["activity_per_day"] = [activity.get(ws, {}).get(d, 0) for d in _days(start, end)]

    prev_start, prev_since = start - timedelta(days=days), since - timedelta(days=days)

    def previous_requests() -> int:
        return int(db.scalar(select(func.coalesce(func.sum(UsageRequest.count), 0)).where(
            UsageRequest.day >= prev_start, UsageRequest.day < start)) or 0)

    def previous_people() -> int:
        return int(db.scalar(select(func.count(func.distinct(UsagePresence.person))).where(
            UsagePresence.bucket >= prev_since, UsagePresence.bucket < since)) or 0)

    def previous_created(model) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(
            model.created_at >= prev_since, model.created_at < since)) or 0)

    def previous_changes() -> int:
        total = 0
        for function, n in db.execute(select(UsageRequest.function, func.sum(UsageRequest.count)).where(
                UsageRequest.day >= prev_start, UsageRequest.day < start, ~UsageRequest.function.like("GET %"))
                .group_by(UsageRequest.function)):
            if record_operation(function)[1] == "changed":
                total += int(n)
        return total

    previous = {
        "requests": previous_requests(), "people": previous_people(),
        "records_new": sum(previous_created(m) for m in kinds.values()), "records_changed": previous_changes(),
        "ask_questions": int(db.scalar(select(func.count()).select_from(AskMessage).where(
            AskMessage.role == "user", AskMessage.created_at >= prev_since, AskMessage.created_at < since)) or 0),
        "tokens": int(db.scalar(select(func.coalesce(func.sum(UsageLLM.prompt_tokens + UsageLLM.completion_tokens), 0))
                                .where(UsageLLM.day >= prev_start, UsageLLM.day < start)) or 0),
    }
    current = {
        "requests": sum(sum(v.values()) for v in per_day.values()), "people": distinct(since),
        "records_new": sum(r.get(f"{k}_new", 0) for r in records_day.values() for k in kinds),
        "records_changed": sum(r.get(f"{k}_changed", 0) for r in records_day.values() for k in kinds),
    }

    # ---------------------------------------------------------------- the language model
    llm_day = {d: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0} for d in _days(start, end)}
    for day, calls, pt, ct in db.execute(select(UsageLLM.day, func.sum(UsageLLM.calls), func.sum(UsageLLM.prompt_tokens),
                                                func.sum(UsageLLM.completion_tokens))
                                         .where(UsageLLM.day >= start).group_by(UsageLLM.day)):
        llm_day[day.isoformat()] = {"calls": int(calls), "prompt_tokens": int(pt), "completion_tokens": int(ct)}

    def llm_by(column, label):
        rows = db.execute(select(column, func.sum(UsageLLM.calls), func.sum(UsageLLM.failures),
                                 func.sum(UsageLLM.prompt_tokens), func.sum(UsageLLM.completion_tokens),
                                 func.sum(UsageLLM.estimated_calls), func.sum(UsageLLM.ms_total))
                          .where(UsageLLM.day >= start).group_by(column)
                          .order_by(func.sum(UsageLLM.prompt_tokens + UsageLLM.completion_tokens).desc())).all()
        return [{label: (names.get(k, k) if label == "workspace" else k) or "(no workspace)", "calls": int(c),
                 "failures": int(f), "prompt_tokens": int(p), "completion_tokens": int(o), "estimated_calls": int(e),
                 "avg_seconds": round(int(ms) / int(c) / 1000, 1) if c else 0} for k, c, f, p, o, e, ms in rows]

    # ---------------------------------------------------------------- Ask ARGUS
    answers = select(AskMessage).where(AskMessage.role == "assistant", AskMessage.created_at >= since).subquery()
    ask_outcomes = {k or "answered": int(n) for k, n in db.execute(
        select(answers.c.stopped, func.count()).group_by(answers.c.stopped))}
    ask_seconds = db.scalar(select(func.avg(answers.c.seconds)))
    tools = [{"tool": t, "count": int(n)} for t, n in db.execute(text(
        "SELECT s->>'tool' AS tool, count(*) FROM ask_messages m, jsonb_array_elements(coalesce(m.steps, '[]'::jsonb)) s "
        "WHERE m.role = 'assistant' AND m.created_at >= :since GROUP BY tool ORDER BY count(*) DESC LIMIT 15"),
        {"since": since})]
    questions_day = {d: 0 for d in _days(start, end)}
    q_day = cast(func.timezone("UTC", AskMessage.created_at), Date)
    for day, n in db.execute(select(q_day, func.count()).where(AskMessage.role == "user", AskMessage.created_at >= since)
                             .group_by(q_day)):
        questions_day[day.isoformat()] = int(n)

    # ---------------------------------------------------------------- feedback
    fb_day = cast(func.timezone("UTC", AskFeedback.created_at), Date)
    feedback_day = {d: {"up": 0, "down": 0} for d in _days(start, end)}
    for day, rating, n in db.execute(select(fb_day, AskFeedback.rating, func.count()).where(AskFeedback.created_at >= since)
                                     .group_by(fb_day, AskFeedback.rating)):
        feedback_day.setdefault(day.isoformat(), {"up": 0, "down": 0})[rating] = int(n)
    by_model = [{"model": m or "?", "up": int(u or 0), "down": int(d or 0)} for m, u, d in db.execute(
        select(AskFeedback.model, func.count().filter(AskFeedback.rating == "up"),
               func.count().filter(AskFeedback.rating == "down"))
        .where(AskFeedback.created_at >= since).group_by(AskFeedback.model))]
    recent = [{"at": f.created_at.isoformat() if f.created_at else None, "workspace": names.get(f.workspace_id, f.workspace_id),
               "question": (f.question or "")[:300], "comment": f.comment, "model": f.model, "client": f.client,
               "ticket_uid": f.ticket_uid}
              for f in db.scalars(select(AskFeedback).where(AskFeedback.rating == "down", AskFeedback.created_at >= since)
                                  .order_by(AskFeedback.created_at.desc()).limit(20))]
    from app.services import ask_feedback

    # ---------------------------------------------------------------- people, as numbers
    users = {"total": int(db.scalar(select(func.count()).select_from(User)) or 0),
             "signed_in_7d": int(db.scalar(select(func.count()).select_from(User).where(
                 User.last_login_at >= now - timedelta(days=7))) or 0),
             "signed_in_30d": int(db.scalar(select(func.count()).select_from(User).where(
                 User.last_login_at >= now - timedelta(days=30))) or 0),
             "new_in_period": int(db.scalar(select(func.count()).select_from(User).where(User.created_at >= since)) or 0)}

    from app.services import storage
    storage_report = storage.report(db, start, refresh=refresh_storage)

    return {
        "storage": storage_report,
        "from": start.isoformat(), "to": end.isoformat(), "days": days, "counting": usage.enabled(),
        "now": {"active_5m": distinct(now - timedelta(minutes=5)), "active_15m": distinct(now - timedelta(minutes=15)),
                "active_24h": distinct(now - timedelta(hours=24))},
        "users": users,
        "requests_per_day": [{"day": d, **v} for d, v in sorted(per_day.items())],
        "records_per_day": [{"day": d, **v} for d, v in sorted(records_day.items())],
        # The period before this one, of the same length: for "up / down" against it.
        "previous": previous,
        "current": {**current, "ask_questions": sum(questions_day.values()),
                    "tokens": sum(v["prompt_tokens"] + v["completion_tokens"] for v in llm_day.values())},
        "people_per_day": [{"day": d, **v, "peak_at_once": peak.get(d, 0), "peak_at": peak_at.get(d)}
                           for d, v in sorted(people_day.items())],
        "functions": {"top": top, "slowest": slowest, "failing": failing, "by_client": by_client_fn},
        "workspaces": sorted(workspaces.values(), key=lambda w: -(w["requests"] + w["writes"])),
        "llm": {"per_day": [{"day": d, **v} for d, v in sorted(llm_day.items())],
                "by_model": llm_by(UsageLLM.model, "model"), "by_purpose": llm_by(UsageLLM.purpose, "purpose"),
                "by_workspace": llm_by(UsageLLM.workspace_id, "workspace")},
        "ask": {"questions_per_day": [{"day": d, "questions": n} for d, n in sorted(questions_day.items())],
                "outcomes": ask_outcomes, "avg_seconds": round(float(ask_seconds), 1) if ask_seconds else None,
                "tools": tools},
        "feedback": {"per_day": [{"day": d, **v} for d, v in sorted(feedback_day.items())],
                     "by_model": by_model, "recent_negative": recent,
                     "workspace": ask_feedback.workspace_id(), "assignee": ask_feedback.assignee_email(db)},
    }
