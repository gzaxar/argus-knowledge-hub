"""Saved imports that run by themselves: every few hours, daily at a time, or weekly on a day at a time, in a
time zone — the same run as the Run button's (`start_job`), so an import of a wiki or a Confluence space checked
every night adds a revision only where a page changed.

- A run acts as the person who set the schedule, with their permissions as they are at the time: someone no
  longer allowed to import there does not import there by a schedule either.
- A run does not start while the import's previous one (by schedule or by hand) is still going; it is tried
  again on the next tick.
- A failed run is recorded on the import and told to the person who set the schedule; after MAX_FAILURES in a
  row the schedule switches itself off and says so, rather than failing every night unseen.
- One scheduled run at a time per server (the timer runs them one after the other), and a run is claimed in
  the database first, so two servers never run the same import at once.

ARGUS_IMPORT_SCHEDULER=off turns the timer off for a process (the tests, a one-off command).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models.import_config import ImportConfig
from app.models.import_job import ImportJob

log = logging.getLogger(__name__)

TICK_SECONDS = 60
STALE_RUN = timedelta(hours=12)          # a run "running" this long died with its process
MAX_FAILURES = 3
KINDS = ("off", "hours", "daily", "weekly")
_scheduler: Optional[threading.Thread] = None


class ScheduleError(ValueError):
    pass


def enabled() -> bool:
    return os.environ.get("ARGUS_IMPORT_SCHEDULER", "on").lower() not in ("off", "0", "false", "no")


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- when

def _zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError(f"unknown time zone {name!r}")


def next_run(config: ImportConfig, after: datetime) -> Optional[datetime]:
    """The first time after `after` the schedule says, or None when it is off."""
    kind = config.schedule_kind or "off"
    if kind == "off":
        return None
    if kind == "hours":
        return after + timedelta(hours=config.schedule_every_hours or 24)
    tz = _zone(config.schedule_timezone)
    hour, minute = (int(x) for x in (config.schedule_time or "02:00").split(":"))
    local = after.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if kind == "daily":
        if candidate <= local:
            candidate = (candidate.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=tz)
    else:
        days = ((config.schedule_weekday or 0) - candidate.weekday()) % 7
        candidate = (candidate.replace(tzinfo=None) + timedelta(days=days)).replace(tzinfo=tz)
        if candidate <= local:
            candidate = (candidate.replace(tzinfo=None) + timedelta(days=7)).replace(tzinfo=tz)
    # Read on the local wall clock: 02:00 stays 02:00 across the changes of daylight saving.
    return candidate.astimezone(timezone.utc)


def apply(config: ImportConfig, schedule, user_id: Optional[str], at: Optional[datetime] = None) -> None:
    """Set a saved import's schedule (a ScheduleIn), as `user_id`: it runs as them from now on."""
    kind = schedule.kind
    if kind not in KINDS:
        raise ScheduleError("a schedule is off, hours, daily or weekly")
    if kind != "off" and not user_id:
        raise ScheduleError("a scheduled import runs as a person: set it signed in, not with an API token")
    if kind == "hours" and not schedule.every_hours:
        raise ScheduleError("say every how many hours")
    if kind in ("daily", "weekly") and not schedule.time:
        raise ScheduleError("say at what time")
    if kind == "weekly" and schedule.weekday is None:
        raise ScheduleError("say on which day")
    if kind in ("daily", "weekly"):
        _zone(schedule.timezone)
    config.schedule_kind = kind
    config.schedule_every_hours = schedule.every_hours if kind == "hours" else None
    config.schedule_time = schedule.time if kind in ("daily", "weekly") else None
    config.schedule_weekday = schedule.weekday if kind == "weekly" else None
    config.schedule_timezone = (schedule.timezone or "UTC") if kind in ("daily", "weekly") else None
    config.scheduled_by = user_id if kind != "off" else None
    config.schedule_failures = 0
    config.next_run_at = next_run(config, at or now())


# --------------------------------------------------------------------------- one run, by hand or by schedule

def start_job(db: Session, config: ImportConfig, identity, add_task: Callable) -> ImportJob:
    """A run of the saved import `config`, as `identity`: its job, and its work handed to `add_task` (the
    request's background tasks, or a direct call from the timer)."""
    from app.routers.imports import actor_name, check_it_workspace
    from app.services.confluence_import import run_confluence_import
    from app.services.crypto import decrypt_secret
    from app.services.dokuwiki_import import run_dokuwiki_import
    from app.services.epik8s_import import run_epik8s_import
    from app.services.git_import import run_git_import
    from app.services.jira_import import run_jira_import
    from app.services.jira_issue_import import run_jira_issue_import
    import uuid
    pat = decrypt_secret(config.encrypted_secret) if config.encrypted_secret else None
    p = config.params or {}
    if config.source == "epik8s" and p.get("it_workspace"):
        check_it_workspace(db, identity, p["it_workspace"])
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=config.workspace_id, source=config.source)
    db.add(job)
    config.last_run_at = now()
    config.last_import_job_uid = job.uid
    db.commit()
    ws, merge = config.workspace_id, config.merge_strategy
    if config.source == "jira":
        add_task(run_jira_import, job.uid, ws, p["base_url"], pat, p["jira_schema_id"], merge)
    elif config.source == "jira-issues":
        add_task(run_jira_issue_import, job.uid, ws, p["base_url"], pat, p["jql"], merge, p.get("schema_uid"),
                 p.get("link_assets", True))
    elif config.source == "confluence":
        add_task(run_confluence_import, job.uid, ws, p.get("base_url"), pat, p.get("space_key"), p.get("cql"), merge,
                 p.get("link_assets", True), p.get("page_url"), p.get("include_children", True))
    elif config.source == "dokuwiki":
        add_task(run_dokuwiki_import, job.uid, ws, p["page_url"], p.get("include_children", True), merge,
                 p.get("link_assets", True))
    elif config.source == "epik8s":
        add_task(run_epik8s_import, job.uid, ws, p["provider"], p["repo_url"], pat, p.get("branch", "main"),
                 p.get("path", "deploy/values.yaml"), merge, p.get("create_missing_nodes", True),
                 p.get("infer_elements", False), p.get("it_workspace"), p.get("infer_controllers", False),
                 p.get("link_inventory", False), p.get("ai_unrecognised", False), actor_name(identity))
    else:
        add_task(run_git_import, job.uid, ws, p["provider"], p["repo_url"], pat, p.get("branch", "main"), merge)
    return job


def _busy(db: Session, config: ImportConfig, at: datetime) -> bool:
    """Whether the import's previous run is still going (and not a run that died with its process)."""
    if not config.last_import_job_uid:
        return False
    job = db.get(ImportJob, config.last_import_job_uid)
    if job is None or job.status not in ("pending", "running"):
        return False
    since = job.started_at or job.created_at
    return since is not None and at - since < STALE_RUN


def claim(db: Session, uid: str, at: Optional[datetime] = None) -> bool:
    """Take a due import for one run (committed), unless another server has it."""
    at = at or now()
    taken = db.execute(update(ImportConfig).where(
        ImportConfig.uid == uid, ImportConfig.schedule_kind != "off", ImportConfig.next_run_at <= at,
        or_(ImportConfig.running_since.is_(None), ImportConfig.running_since < at - STALE_RUN),
    ).values(running_since=at)).rowcount == 1
    db.commit()
    return taken


def _tell(db: Session, config: ImportConfig, title: str, job_uid: Optional[str]) -> None:
    from app.models.workflow import Notification
    if not config.scheduled_by:
        return
    path = f"/workspaces/{config.workspace_id}/imports/{job_uid}" if job_uid else \
        f"/workspaces/{config.workspace_id}/imports"
    db.add(Notification(workspace_id=config.workspace_id, recipient=config.scheduled_by, kind="import_failed",
                        title=title, detail={"subject": "import", "uid": config.uid, "path": path}, actor=None,
                        created_at=now()))


def _finish(db: Session, config: ImportConfig, outcome: str, message: str, job_uid: Optional[str] = None) -> dict:
    at = now()
    config.last_outcome, config.last_message = outcome, message[:2000]
    config.running_since = None
    if outcome == "failed":
        config.schedule_failures = (config.schedule_failures or 0) + 1
        title = f"The scheduled import “{config.name}” failed: {message[:200]}"
        if config.schedule_failures >= MAX_FAILURES:
            config.schedule_kind = "off"
            config.last_message = f"{config.last_message} — schedule switched off after {MAX_FAILURES} failures in a row"
            title = f"The scheduled import “{config.name}” failed {MAX_FAILURES} times in a row: its schedule is off"
        _tell(db, config, title, job_uid)
    elif outcome == "succeeded":
        config.schedule_failures = 0
    config.next_run_at = next_run(config, at)
    db.commit()
    return {"config": config.uid, "outcome": outcome, "message": message, "job": job_uid}


def run_one(db: Session, uid: str) -> dict:
    """One scheduled run of a claimed import, start to end (the timer's thread waits for it)."""
    from app.auth import OidcIdentity
    from app.models.user import User
    from app.services.permissions import resolve_permission
    config = db.get(ImportConfig, uid)
    at = now()
    if _busy(db, config, at):
        config.running_since = None
        config.next_run_at = at + timedelta(minutes=15)            # its previous run is still going: later
        config.last_outcome, config.last_message = "skipped", "the previous run was still going"
        db.commit()
        return {"config": uid, "outcome": "skipped"}
    user = db.get(User, config.scheduled_by) if config.scheduled_by else None
    if user is None or not resolve_permission(db, user, config.workspace_id, "create", "objects"):
        return _finish(db, config, "failed", "the person who set the schedule may no longer import here")
    try:
        job = start_job(db, config, OidcIdentity(user=user), lambda fn, *args: fn(*args))
    except Exception as e:  # noqa: BLE001 — a run that could not start is a failed run, told as such
        db.rollback()
        config = db.get(ImportConfig, uid)
        return _finish(db, config, "failed", getattr(e, "detail", None) or str(e))
    db.expire_all()
    job = db.get(ImportJob, job.uid)
    config = db.get(ImportConfig, uid)
    if job.status == "succeeded":
        return _finish(db, config, "succeeded", job.progress or "Import complete", job.uid)
    return _finish(db, config, "failed", job.error or f"the import ended {job.status}", job.uid)


# --------------------------------------------------------------------------- the timer

def due(db: Session, at: Optional[datetime] = None) -> list[str]:
    return list(db.scalars(select(ImportConfig.uid).where(
        ImportConfig.schedule_kind != "off", ImportConfig.next_run_at <= (at or now()))
        .order_by(ImportConfig.next_run_at)))


def tick(factory: Callable[[], Session], at: Optional[datetime] = None) -> list[dict]:
    db = factory()
    try:
        uids = due(db, at)
    finally:
        db.close()
    out = []
    for uid in uids:
        db = factory()
        try:
            if claim(db, uid, at):
                out.append(run_one(db, uid))
        finally:
            db.close()
    return out


def _loop(factory: Callable[[], Session]) -> None:
    while True:
        time.sleep(TICK_SECONDS)
        try:
            for result in tick(factory):
                log.info("scheduled import %s: %s", result["config"], result["outcome"])
        except Exception:  # noqa: BLE001 — a database briefly away must not stop the timer for good
            log.warning("scheduled imports skipped", exc_info=True)


def start_scheduler() -> None:
    global _scheduler
    if not enabled() or _scheduler is not None:
        return
    from app.db import SessionLocal
    _scheduler = threading.Thread(target=_loop, args=(SessionLocal,), daemon=True, name="import-schedule")
    _scheduler.start()
