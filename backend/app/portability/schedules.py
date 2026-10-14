"""Periodic Git exports: a published export, repeated at an interval.

An administrator sets a schedule on an export published to a Git repository. Each run makes a new export with
the same scope, destination, dependency outcomes and identity profile, and takes it through the usual steps —
analysis, approval, generation and verification, publication — audited as always:

- `incremental` (the default): an increment on the last export the schedule published, so the repository holds
  the base and a chain of increments, each a signed tag naming the one before;
- `complete`: a complete export each time, of the same mode as the one the schedule was set on.

Setting the schedule is the standing approval of its runs. It is given under the rules for approving the export
itself: an instance administrator; for a high-risk export (a full one, or one carrying people's identities) a
recent sign-in, and, where separation of duties is in force, someone other than the export's requester. Exports
carrying restricted classes are not scheduled: generating one needs a recent sign-in every time.

A run does nothing when nothing was recorded since the last publication (`skip_unchanged`), and stops when the
analysis needs a person — a new dependency without an outcome, an attachment to inspect, a secret found: the
export waits on the Portability page, and the schedule waits for it to be published or revoked before it makes
another. Three failures in a row switch the schedule off.

Runs are started by `python -m app.portability scheduled` (a CronJob in the Helm chart, every 15 minutes) or by
"Run now". A run claims its schedule in the database first, so two runners never run it at once.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.portability import PortabilityEvent, PortabilityExport, PortabilitySchedule
from app.portability import service
from app.portability.families import SEQUENCED_TABLES
from app.portability.service import ServiceError

CHAINS = ("incremental", "complete")
MIN_MINUTES, MAX_MINUTES = 60, 31 * 24 * 60
MAX_FAILURES = 3
STALE_RUN = timedelta(hours=6)           # a claim older than this was a runner that died
OPEN_STATES = {"requested", "analysing", "awaiting_approval", "approved", "generating", "verifying",
               "ready_to_publish", "publishing"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _event(db: Session, sched: PortabilitySchedule, kind: str, actor: str, detail: Optional[dict] = None) -> None:
    db.add(PortabilityEvent(subject_kind="schedule", subject_id=sched.id, kind=kind, actor=actor, detail=detail))
    db.flush()


def actor_of(sched: PortabilitySchedule) -> str:
    return f"schedule {sched.id} (set by {sched.created_by})"


def view(sched: PortabilitySchedule) -> dict:
    iso = lambda v: v.isoformat() if v else None  # noqa: E731
    return {"id": sched.id, "source_export_id": sched.source_export_id, "chain": sched.chain,
            "every_minutes": sched.every_minutes, "skip_unchanged": sched.skip_unchanged, "enabled": sched.enabled,
            "mode": sched.mode, "workspaces": sched.workspaces, "repository": (sched.destination or {}).get("repository"),
            "next_run_at": iso(sched.next_run_at), "running": sched.running_since is not None,
            "last_run_at": iso(sched.last_run_at), "last_outcome": sched.last_outcome,
            "last_message": sched.last_message, "last_export_id": sched.last_export_id,
            "last_published_export_id": sched.last_published_export_id, "failures": sched.failures,
            "runs": sched.runs, "created_by": sched.created_by, "updated_by": sched.updated_by,
            "created_at": iso(sched.created_at)}


def _check_interval(minutes: int) -> int:
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise ServiceError("the interval must be a number of minutes", "invalid", 422)
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise ServiceError("the interval must be between an hour and 31 days", "invalid", 422)
    return minutes


def create(db: Session, exp: PortabilityExport, actor: str, *, every_minutes: int, chain: str = "incremental",
           skip_unchanged: bool = True, admin: bool, fresh_auth: bool, step_up_how: str = "",
           cfg: Optional[service.Config] = None) -> PortabilitySchedule:
    """A schedule repeating `exp`, which must be published to a Git repository."""
    cfg = cfg or service.config()
    if not admin:
        raise ServiceError("scheduling an export needs an instance administrator", "forbidden", 403)
    if exp.state != "published" or not (exp.git or {}).get("tag"):
        raise ServiceError("only an export published to a Git repository can be repeated", "invalid", 409)
    repo = (exp.destination or {}).get("repository")
    if repo not in cfg.repositories:
        raise ServiceError(f"the repository {repo!r} is no longer registered", "invalid", 409)
    if exp.classifications:
        raise ServiceError("an export carrying restricted classes cannot be repeated automatically: generating one "
                           "needs a recent sign-in every time", "restricted_not_schedulable", 409)
    if chain not in CHAINS:
        raise ServiceError(f"chain must be one of {', '.join(CHAINS)}", "invalid", 422)
    minutes = _check_interval(every_minutes)
    pol = cfg.policy
    if exp.risk == "high":
        if actor == exp.requested_by and pol.separation_of_duties:
            raise ServiceError("repeating a high-risk export needs an administrator other than its requester",
                               "separation", 403)
        if not fresh_auth:
            raise ServiceError("repeating a high-risk export needs a recent sign-in"
                               + (" or, with a recent session, an explicit confirmation"
                                  if pol.step_up == "session_confirmation" else ""), "step_up_required", 401,
                               {"step_up": step_up_how or "missing"})
    if db.scalar(select(PortabilitySchedule.id).where(PortabilitySchedule.source_export_id == exp.id)):
        raise ServiceError("this export already has a schedule: change that one", "exists", 409)
    # What an incremental run repeats is the scope of the chain's first export.
    origin = exp
    while origin.mode == "incremental" and origin.base_export_id:
        origin = db.get(PortabilityExport, origin.base_export_id) or origin
        if origin.mode != "incremental":
            break
    sched = PortabilitySchedule(
        id=f"sch-{uuid.uuid4().hex[:10]}", source_export_id=exp.id, chain=chain, every_minutes=minutes,
        skip_unchanged=skip_unchanged, enabled=True, mode=origin.mode, workspaces=list(exp.workspaces or []),
        destination={k: v for k, v in (exp.destination or {}).items() if k in ("repository", "artifact_store")},
        decisions=dict(exp.decisions or {}), next_run_at=now() + timedelta(minutes=minutes),
        last_published_export_id=exp.id, created_by=actor)
    db.add(sched)
    db.flush()
    _event(db, sched, "schedule_set", actor, {"export": exp.id, "every_minutes": minutes, "chain": chain,
                                              "risk": exp.risk, "step_up": step_up_how or fresh_auth})
    service.audit(db, exp, "scheduled", actor, {"schedule": sched.id, "every_minutes": minutes, "chain": chain})
    return sched


def change(db: Session, sched: PortabilitySchedule, actor: str, *, enabled: Optional[bool] = None,
           every_minutes: Optional[int] = None, skip_unchanged: Optional[bool] = None,
           chain: Optional[str] = None) -> PortabilitySchedule:
    changes = {}
    if every_minutes is not None and every_minutes != sched.every_minutes:
        sched.every_minutes = changes["every_minutes"] = _check_interval(every_minutes)
        sched.next_run_at = now() + timedelta(minutes=sched.every_minutes)
    if chain is not None and chain != sched.chain:
        if chain not in CHAINS:
            raise ServiceError(f"chain must be one of {', '.join(CHAINS)}", "invalid", 422)
        sched.chain = changes["chain"] = chain
    if skip_unchanged is not None and skip_unchanged != sched.skip_unchanged:
        sched.skip_unchanged = changes["skip_unchanged"] = skip_unchanged
    if enabled is not None and enabled != sched.enabled:
        sched.enabled = changes["enabled"] = enabled
        if enabled:
            sched.failures = 0
            sched.next_run_at = now() + timedelta(minutes=sched.every_minutes)
    if changes:
        sched.updated_by = actor
        _event(db, sched, "schedule_changed", actor, changes)
    return sched


def remove(db: Session, sched: PortabilitySchedule, actor: str) -> None:
    _event(db, sched, "schedule_removed", actor, {"export": sched.source_export_id})
    db.delete(sched)
    db.flush()


# --------------------------------------------------------------------------- running

def current_vector(db: Session) -> dict:
    """The highest sequence of every table an export's watermark covers: equal to a published export's
    watermark vector means nothing was recorded since."""
    return {t: int(db.execute(text(f"SELECT coalesce(max(seq), 0) FROM {t}")).scalar()) for t in SEQUENCED_TABLES}


def claim(db: Session, schedule_id: str, *, force: bool = False) -> bool:
    """Take the schedule for one run (committed), unless another runner has it. `force` runs it now, due or not."""
    t = now()
    q = update(PortabilitySchedule).where(
        PortabilitySchedule.id == schedule_id,
        or_(PortabilitySchedule.running_since.is_(None), PortabilitySchedule.running_since < t - STALE_RUN))
    if not force:
        q = q.where(PortabilitySchedule.enabled.is_(True), PortabilitySchedule.next_run_at <= t)
    taken = db.execute(q.values(running_since=t)).rowcount == 1
    db.commit()
    return taken


def _finish(db: Session, sched: PortabilitySchedule, outcome: str, message: str,
            export_id: Optional[str] = None) -> dict:
    sched = db.get(PortabilitySchedule, sched.id)
    t = now()
    sched.last_run_at, sched.last_outcome, sched.last_message = t, outcome, message[:2000]
    sched.runs = (sched.runs or 0) + 1
    if export_id:
        sched.last_export_id = export_id
    if outcome == "published":
        sched.last_published_export_id = export_id
    sched.failures = (sched.failures or 0) + 1 if outcome == "failed" else 0
    if sched.failures >= MAX_FAILURES:
        sched.enabled = False
        sched.last_message = f"{sched.last_message} — switched off after {MAX_FAILURES} failures in a row"
    sched.next_run_at = t + timedelta(minutes=sched.every_minutes)
    sched.running_since = None
    _event(db, sched, "schedule_run", actor_of(sched), {"outcome": outcome, "message": message[:500],
                                                        "export": export_id})
    db.commit()
    return {"schedule": sched.id, "outcome": outcome, "message": message, "export": export_id}


def run(engine: Engine, db: Session, sched: PortabilitySchedule, cfg: Optional[service.Config] = None) -> dict:
    """One run of a claimed schedule. Always releases the claim and says what happened."""
    cfg = cfg or service.config()
    actor = actor_of(sched)
    pending = db.get(PortabilityExport, sched.last_export_id) if sched.last_export_id else None
    if pending is not None and pending.state in OPEN_STATES:
        if pending.state in ("approved", "ready_to_publish"):
            # The schedule's own export, approved but not yet generated or published (the signing key or the
            # repository was not there last time): carried on from where it stopped.
            try:
                if pending.state == "approved":
                    service.generate_export(engine, db, pending, actor, cfg)
                exp = service.publish_export(db, db.get(PortabilityExport, pending.id), actor, cfg)
                db.commit()
                return _finish(db, sched, "published", f"published {exp.id} as {exp.git.get('tag')}", exp.id)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                return _finish(db, sched, "failed", f"{pending.id}: {e}", pending.id)
        if pending.state in ("generating", "verifying", "publishing"):
            return _finish(db, sched, "waiting", f"{pending.id} is still {pending.state}", pending.id)
        return _finish(db, sched, "waiting", f"{pending.id} is {pending.state.replace('_', ' ')}: it needs a person "
                                             "on the Portability page before the next run", pending.id)
    base = db.get(PortabilityExport, sched.last_published_export_id or sched.source_export_id)
    if base is None or base.state != "published":
        base = db.scalar(select(PortabilityExport).where(
            PortabilityExport.id.in_([sched.source_export_id, sched.last_published_export_id or ""]),
            PortabilityExport.state == "published").order_by(PortabilityExport.created_at.desc()))
    if base is None:
        return _finish(db, sched, "failed", "the export this schedule continues is no longer published (revoked or "
                                            "expired): set a new schedule on a published export")
    if sched.skip_unchanged and (base.watermark or {}).get("vector") == current_vector(db):
        return _finish(db, sched, "unchanged", f"nothing recorded since {base.id}")
    exp_id = None
    try:
        incremental = sched.chain == "incremental"
        exp = service.create_export(
            db, actor, mode="incremental" if incremental else sched.mode,
            workspaces=list(sched.workspaces or []), classifications=[], destination=dict(sched.destination or {}),
            decisions={k: v for k, v in (sched.decisions or {}).items() if k not in ("identity_profile", "purpose")},
            base_export_id=base.id if incremental else None,
            identity_profile=(sched.decisions or {}).get("identity_profile"),
            purpose=(sched.decisions or {}).get("purpose"), cfg=cfg)
        exp_id = exp.id
        service.analyse_export(db, exp, actor, cfg)
        db.commit()
        if not exp.analysis.get("ready"):
            return _finish(db, sched, "waiting", f"{exp.id} needs a person: " + "; ".join(
                exp.analysis.get("warnings") or ["its analysis is not complete"]), exp.id)
        # The standing approval given by the administrator who set the schedule (with a recent sign-in, and not
        # as the export's requester, for a high-risk export): theirs, recorded as given through the schedule.
        service.approve_export(db, exp, f"{sched.created_by} (standing approval, schedule {sched.id})", admin=True,
                               fresh_auth=True, cfg=cfg, step_up_how="schedule")
        db.commit()
        service.generate_export(engine, db, exp, actor, cfg)
        exp = service.publish_export(db, db.get(PortabilityExport, exp.id), actor, cfg)
        db.commit()
        return _finish(db, sched, "published", f"published {exp.id} as {exp.git.get('tag')}", exp.id)
    except Exception as e:  # noqa: BLE001 — every failure is recorded on the schedule
        db.rollback()
        return _finish(db, sched, "failed", str(e) or e.__class__.__name__, exp_id)


def run_due(engine: Engine, cfg: Optional[service.Config] = None, at: Optional[datetime] = None) -> list[dict]:
    """Every enabled schedule whose time has come, one after the other."""
    out = []
    with Session(engine) as db:
        due = list(db.scalars(select(PortabilitySchedule.id).where(
            PortabilitySchedule.enabled.is_(True), PortabilitySchedule.next_run_at <= (at or now()))
            .order_by(PortabilitySchedule.next_run_at)))
    for sid in due:
        with Session(engine) as db:
            if not claim(db, sid):
                continue
            out.append(run(engine, db, db.get(PortabilitySchedule, sid), cfg))
    return out


def run_now(engine: Engine, db: Session, sched: PortabilitySchedule, cfg: Optional[service.Config] = None) -> dict:
    if not claim(db, sched.id, force=True):
        raise ServiceError("this schedule is running already", "busy", 409)
    return run(engine, db, db.get(PortabilitySchedule, sched.id), cfg)
