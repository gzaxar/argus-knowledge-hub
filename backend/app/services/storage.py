"""How full ARGUS's storage is, how fast it grows and how much room is left: the Statistics page's storage section.

Three areas: the attachment files (ATTACHMENTS_DIR), the portability archives (ARGUS_PORTABILITY_ROOT) and the
database. Each is measured against the room planned for it (ARGUS_STORAGE_*_SIZE, the Helm chart's volume
sizes) and, for the two directories, against what the disk under them still has free: a local-path volume does
not enforce its size, so either can run out first. The database lives on another node; only its planned size is
known here.

A measurement is kept per day (the last of the day, models/usage.py UsageStorage), taken every hour by the usage
thread, so the trend builds up; the attachments' own dates give their growth from the start.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

AREAS = {
    "attachments": ("ATTACHMENTS_DIR", "/data/attachments", "ARGUS_STORAGE_ATTACHMENTS_SIZE"),
    "portability": ("ARGUS_PORTABILITY_ROOT", "/data/portability", "ARGUS_STORAGE_PORTABILITY_SIZE"),
}
DATABASE_SIZE = "ARGUS_STORAGE_DATABASE_SIZE"
WALK_SECONDS = 120            # a directory too big to walk in this long is reported as measured so far
_UNITS = {"": 1, "k": 10 ** 3, "m": 10 ** 6, "g": 10 ** 9, "t": 10 ** 12,
          "ki": 2 ** 10, "mi": 2 ** 20, "gi": 2 ** 30, "ti": 2 ** 40}


def parse_size(value: Optional[str]) -> Optional[int]:
    """Bytes in a Kubernetes quantity ("15Gi", "500M", "1073741824"); None when not given or not one."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmMgGtT]i?)?\s*[bB]?\s*", value or "")
    if not m:
        return None
    return int(float(m.group(1)) * _UNITS[(m.group(2) or "").lower()])


def dir_usage(path: str, budget: float = WALK_SECONDS) -> tuple[int, int, bool]:
    """(bytes, files, complete) under a directory, symbolic links not followed."""
    total = files = 0
    deadline = time.monotonic() + budget
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            return total, files, False
        try:
            with os.scandir(stack.pop()) as entries:
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files, True


def available(used: int, planned: Optional[int], disk_free: Optional[int]) -> Optional[int]:
    """What can still be written: the planned room left or the disk's free space, whichever runs out first."""
    room = [x for x in ((planned - used) if planned else None, disk_free) if x is not None]
    return max(0, min(room)) if room else None


def measure(db: Session) -> list[dict]:
    """Each area as it is now."""
    out = []
    for area, (env, default, size_env) in AREAS.items():
        path = os.environ.get(env, default)
        planned = parse_size(os.environ.get(size_env))
        if os.path.isdir(path):
            used, files, complete = dir_usage(path)
            try:
                disk = shutil.disk_usage(path)
                disk_free, disk_total = disk.free, disk.total
            except OSError:
                disk_free = disk_total = None
        else:
            used, files, complete, disk_free, disk_total = 0, 0, True, None, None
        out.append({"area": area, "used_bytes": used, "files": files, "complete": complete,
                    "planned_bytes": planned, "disk_free_bytes": disk_free, "disk_total_bytes": disk_total})
    used = int(db.scalar(text("SELECT pg_database_size(current_database())")) or 0)
    out.append({"area": "database", "used_bytes": used, "files": None, "complete": True,
                "planned_bytes": parse_size(os.environ.get(DATABASE_SIZE)), "disk_free_bytes": None,
                "disk_total_bytes": None})
    for a in out:
        a["available_bytes"] = available(a["used_bytes"], a["planned_bytes"], a["disk_free_bytes"])
    return out


def snapshot(db: Session) -> list[dict]:
    """Measure, and keep it as today's measurement (replacing an earlier one of the day). The caller commits."""
    areas = measure(db)
    today = datetime.now(timezone.utc).date()
    from app.models.usage import UsageStorage
    for a in areas:
        row = {"day": today, "area": a["area"], "used_bytes": a["used_bytes"], "planned_bytes": a["planned_bytes"],
               "disk_free_bytes": a["disk_free_bytes"], "files": a["files"], "measured_at": datetime.now(timezone.utc)}
        stmt = insert(UsageStorage).values(row)
        db.execute(stmt.on_conflict_do_update(index_elements=["day", "area"],
                                              set_={k: stmt.excluded[k] for k in row if k not in ("day", "area")}))
    return areas


def _days_left(available_bytes: Optional[int], per_day: float) -> Optional[int]:
    if available_bytes is None or per_day <= 0:
        return None
    return int(available_bytes / per_day)


def report(db: Session, start: date, refresh: bool = False) -> dict:
    """The storage section: each area now (today's measurement, or a new one), its daily trend since `start`,
    the attachments' growth and where their bytes are, the largest tables, and at the recent rate of growth
    how many days are left."""
    from app.models.attachment import Attachment
    from app.models.usage import UsageStorage
    from app.models.workspace import Workspace
    today = datetime.now(timezone.utc).date()
    latest = {r.area: r for r in db.scalars(select(UsageStorage).where(UsageStorage.day == today))}
    if refresh or set(latest) != {*AREAS, "database"}:
        now = snapshot(db)
        db.commit()
        measured_at = datetime.now(timezone.utc).isoformat()
    else:
        now = [{"area": r.area, "used_bytes": int(r.used_bytes), "files": r.files, "complete": True,
                "planned_bytes": r.planned_bytes, "disk_free_bytes": r.disk_free_bytes, "disk_total_bytes": None,
                "available_bytes": available(int(r.used_bytes), r.planned_bytes, r.disk_free_bytes)}
               for r in latest.values()]
        measured_at = max((r.measured_at for r in latest.values() if r.measured_at), default=None)
        measured_at = measured_at.isoformat() if measured_at else None

    trend: dict[str, dict[str, int]] = {}
    for r in db.scalars(select(UsageStorage).where(UsageStorage.day >= start).order_by(UsageStorage.day)):
        trend.setdefault(r.day.isoformat(), {})[r.area] = int(r.used_bytes)

    # The attachments' growth from their own dates: what was added each day, and the total it made.
    day = cast(func.timezone("UTC", Attachment.created_at), Date)
    before = int(db.scalar(select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
        Attachment.created_at < datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))) or 0)
    added = {d.isoformat(): (int(b or 0), int(n)) for d, b, n in db.execute(
        select(day, func.sum(Attachment.file_size), func.count()).where(
            Attachment.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by(day))}
    growth, running = [], before
    for i in range((today - start).days + 1):
        d = (start + timedelta(days=i)).isoformat()
        b, n = added.get(d, (0, 0))
        running += b
        growth.append({"day": d, "added_bytes": b, "added_files": n, "total_bytes": running})

    names = dict(db.execute(select(Workspace.id, Workspace.name)).all())
    by_workspace = [{"workspace": names.get(w, w), "files": int(n), "bytes": int(b or 0)} for w, n, b in db.execute(
        select(Attachment.workspace_id, func.count(), func.sum(Attachment.file_size))
        .group_by(Attachment.workspace_id).order_by(func.sum(Attachment.file_size).desc().nulls_last()).limit(15))]
    tables = [{"table": t, "bytes": int(b)} for t, b in db.execute(text(
        "SELECT c.relname, pg_total_relation_size(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY 2 DESC LIMIT 12"))]

    # The rate of growth: over the last 30 days of measurements where there are some, else the attachments' own.
    since30 = today - timedelta(days=30)
    rates: dict[str, float] = {}
    for area in (*AREAS, "database"):
        rows = list(db.execute(select(UsageStorage.day, UsageStorage.used_bytes).where(
            UsageStorage.area == area, UsageStorage.day >= since30).order_by(UsageStorage.day)))
        if len(rows) >= 2 and rows[-1][0] > rows[0][0]:
            rates[area] = (rows[-1][1] - rows[0][1]) / (rows[-1][0] - rows[0][0]).days
    if "attachments" not in rates:
        recent = int(db.scalar(select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
            Attachment.created_at >= datetime.combine(since30, datetime.min.time(), tzinfo=timezone.utc))) or 0)
        rates["attachments"] = recent / 30
    for a in now:
        per_day = rates.get(a["area"])
        a["growth_per_day_bytes"] = round(per_day) if per_day is not None else None
        a["days_left"] = _days_left(a.get("available_bytes"), per_day or 0)
    order = {"attachments": 0, "database": 1, "portability": 2}
    return {"measured_at": measured_at, "areas": sorted(now, key=lambda a: order.get(a["area"], 9)),
            "trend": [{"day": d, **v} for d, v in sorted(trend.items())], "attachment_growth": growth,
            "attachments_by_workspace": by_workspace, "largest_tables": tables}
