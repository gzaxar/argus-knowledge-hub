"""Quotas: how much a workspace may hold and use, set in Administration → Quotas (docs/quotas.md).

Per workspace, each with an installation-wide default an instance administrator sets, and an override per
workspace (a number, or "unlimited"):

  storage_bytes     its attachment files                                      default 50 GiB
  file_bytes        the largest single file it takes                          default 2 GiB
  ai_tokens_5h      language-model tokens in the last 5 hours                 default unlimited
  ai_tokens_week    language-model tokens in the last 7 days                  default unlimited
  assets            records not deleted                                       default unlimited
  documents         documents not deleted                                     default unlimited
  members           people given access directly (a group counts as none)     default unlimited
  api_ops_day       requests made with a token (scripts, robots, MCP) today   default unlimited
  api_ops_minute    the same, in the current minute                          default unlimited

and one for the installation: `imports_at_once`, portability imports not over (each holds its archive, about 2 GB
for a large one), default 1.

What a quota stops is what would add to it — a new record, a file, a member, a model call; reading, editing and
deleting always work, so a workspace over a quota can get back under it. The check is where the thing is written
(a flush guard on the session, as services/sites.py's), so every path is held to it: forms, the API, the Jira,
GLPI and Confluence imports, bundles. An instance administrator signed in is never stopped (auth notes it on the
request); a portability import loading an archive is not either — its dry run lists what it would bring over a
quota instead. At 80% a quota warns (its workspace's administration, the argus_quota_ratio metric).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

SETTING = "quotas"
GiB = 2 ** 30
WARN_AT = 0.8


@dataclass(frozen=True)
class Quota:
    key: str
    label: str
    unit: str               # bytes | tokens | count
    default: Optional[int]  # None: unlimited
    what: str


QUOTAS = [
    Quota("storage_bytes", "Storage", "bytes", 50 * GiB, "the workspace's attachment files"),
    Quota("file_bytes", "Largest file", "bytes", 2 * GiB, "one file uploaded or attached"),
    Quota("ai_tokens_5h", "AI tokens, 5 hours", "tokens", None, "language-model tokens in the last 5 hours"),
    Quota("ai_tokens_week", "AI tokens, week", "tokens", None, "language-model tokens in the last 7 days"),
    Quota("assets", "Records", "count", None, "records not deleted"),
    Quota("documents", "Documents", "count", None, "documents not deleted"),
    Quota("members", "Members", "count", None, "people given access directly (groups are not counted)"),
    Quota("api_ops_day", "API operations, day", "count", None, "requests made with a token today (UTC)"),
    Quota("api_ops_minute", "API operations, minute", "count", None, "requests made with a token this minute"),
]
def _imports_default() -> Optional[int]:
    """1, or what the deployment says (ARGUS_QUOTA_IMPORTS_AT_ONCE; empty or "unlimited": no limit)."""
    import os
    v = os.environ.get("ARGUS_QUOTA_IMPORTS_AT_ONCE")
    if v is None:
        return 1
    return None if v.strip().lower() in ("", "unlimited", "none") else int(v)


INSTALLATION = [Quota("imports_at_once", "Imports at once", "count", _imports_default(),
                      "portability imports not over: each holds its archive until finalized or discarded")]
BY_KEY = {q.key: q for q in QUOTAS + INSTALLATION}


class QuotaExceeded(Exception):
    """What a person is told: which quota, its limit, what is used, and when it frees up (a window)."""

    def __init__(self, key: str, limit: int, used: int, adding: int = 1, workspace_id: Optional[str] = None,
                 frees_at: Optional[datetime] = None, message: Optional[str] = None):
        q = BY_KEY[key]
        self.key, self.limit, self.used, self.adding, self.workspace_id, self.frees_at = \
            key, limit, used, adding, workspace_id, frees_at
        where = f" of {workspace_id}" if workspace_id else ""
        super().__init__(message or (
            f"The {q.label.lower()} quota{where} is {fmt(q, limit)}: {fmt(q, used)} is used"
            + (f", and this would add {fmt(q, adding)}" if adding and q.key != "file_bytes" else "")
            + (f". It frees up from {frees_at.strftime('%Y-%m-%d %H:%M UTC')}" if frees_at else "")
            + ". An instance administrator can raise it (Administration → Quotas)."))

    def detail(self) -> dict:
        return {"error": str(self), "code": "quota_exceeded", "quota": self.key, "limit": self.limit,
                "used": self.used, "adding": self.adding, "workspace_id": self.workspace_id,
                "frees_at": self.frees_at.isoformat() if self.frees_at else None}


def fmt(q: Quota, v: Optional[int]) -> str:
    if v is None:
        return "unlimited"
    if q.unit == "bytes":
        x, units = float(v), ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while x >= 1024 and i < len(units) - 1:
            x, i = x / 1024, i + 1
        return f"{x:.1f} {units[i]}" if i else f"{int(x)} B"
    return f"{v:,} tokens" if q.unit == "tokens" else f"{v:,}"


# --------------------------------------------------------------------------- settings

def _setting(db: Session) -> dict:
    from app.models.app_setting import AppSetting
    row = db.get(AppSetting, SETTING)
    v = row.value if row is not None and isinstance(row.value, dict) else {}
    return {"defaults": dict(v.get("defaults") or {}), "workspaces": {k: dict(x) for k, x in
                                                                       (v.get("workspaces") or {}).items()}}


def defaults(db: Session) -> dict:
    """Each quota's installation-wide default: the administrator's (a number or None for unlimited), else built in."""
    set_ = _setting(db)["defaults"]
    return {q.key: (set_[q.key] if q.key in set_ else q.default) for q in QUOTAS + INSTALLATION}


def limits(db: Session, workspace_id: str) -> dict:
    """The quotas in effect for a workspace: its override where it has one, else the default."""
    s = _setting(db)
    base = defaults(db)
    own = s["workspaces"].get(workspace_id, {})
    return {q.key: (own[q.key] if q.key in own else base[q.key]) for q in QUOTAS}


def _valid(key: str, v) -> Optional[int]:
    if key not in BY_KEY:
        raise ValueError(f"no quota {key}")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError(f"{key}: a quota is a whole number from 0, or null for unlimited")
    return v


def set_defaults(db: Session, values: dict, reset: tuple = ()) -> dict:
    """Set defaults (None: unlimited); keys in `reset` go back to the built-in default. The caller commits."""
    s = _setting(db)
    for k, v in values.items():
        s["defaults"][k] = _valid(k, v)
    for k in reset:
        _valid(k, None)
        s["defaults"].pop(k, None)
    _save(db, s)
    return defaults(db)


def set_workspace(db: Session, workspace_id: str, values: dict, reset: tuple = ()) -> dict:
    """A workspace's overrides (None: unlimited); keys in `reset` follow the default again."""
    s = _setting(db)
    own = s["workspaces"].setdefault(workspace_id, {})
    for k, v in values.items():
        if k not in {q.key for q in QUOTAS}:
            raise ValueError(f"{k} is not a workspace quota")
        own[k] = _valid(k, v)
    for k in reset:
        own.pop(k, None)
    if not own:
        s["workspaces"].pop(workspace_id, None)
    _save(db, s)
    return limits(db, workspace_id)


def overrides(db: Session, workspace_id: str) -> dict:
    return _setting(db)["workspaces"].get(workspace_id, {})


def _save(db: Session, s: dict) -> None:
    from app.models.app_setting import AppSetting
    row = db.get(AppSetting, SETTING)
    if row is None:
        db.add(AppSetting(key=SETTING, value=s))
    else:
        row.value = s
    db.flush()


# --------------------------------------------------------------------------- what is used

def _count_assets(db, ws):
    from app.models.asset import Asset
    return int(db.scalar(select(func.count()).select_from(Asset).where(
        Asset.workspace_id == ws, Asset.deleted_at.is_(None))) or 0)


def _count_documents(db, ws):
    from app.models.document import Document
    q = select(func.count()).select_from(Document).where(Document.workspace_id == ws)
    if hasattr(Document, "deleted_at"):
        q = q.where(Document.deleted_at.is_(None))
    return int(db.scalar(q) or 0)


def _storage_bytes(db, ws):
    from app.models.attachment import Attachment
    return int(db.scalar(select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
        Attachment.workspace_id == ws)) or 0)


def _members(db, ws) -> set:
    from app.models.membership import Membership
    from app.models.role import RoleBinding
    people = set(db.scalars(select(RoleBinding.subject_id).where(RoleBinding.workspace_id == ws,
                                                                 RoleBinding.subject_type == "user")))
    people |= set(db.scalars(select(Membership.user_id).where(Membership.workspace_id == ws)))
    return people


def ai_tokens(db: Session, ws: str, hours: int) -> tuple[int, Optional[datetime]]:
    """Tokens used in the last `hours`, and when the oldest hour counted leaves the window."""
    from app.models.usage import QuotaAIUsage
    now = datetime.now(timezone.utc)
    since = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    rows = list(db.execute(select(QuotaAIUsage.hour, QuotaAIUsage.tokens).where(
        QuotaAIUsage.workspace_id == ws, QuotaAIUsage.hour >= since).order_by(QuotaAIUsage.hour)))
    used = sum(int(t) for _h, t in rows)
    oldest = rows[0][0] if rows else None
    return used, (oldest + timedelta(hours=hours)) if oldest else None


def usage(db: Session, ws: str) -> dict:
    return {"storage_bytes": _storage_bytes(db, ws), "file_bytes": None,
            "ai_tokens_5h": ai_tokens(db, ws, 5)[0], "ai_tokens_week": ai_tokens(db, ws, 24 * 7)[0],
            "assets": _count_assets(db, ws), "documents": _count_documents(db, ws), "members": len(_members(db, ws)),
            "api_ops_day": _api.today(ws), "api_ops_minute": _api.this_minute(ws)}


def status(db: Session, ws: str) -> list[dict]:
    """Each quota of a workspace: its limit and where it comes from, what is used, and whether it warns."""
    lim, use, own = limits(db, ws), usage(db, ws), overrides(db, ws)
    out = []
    for q in QUOTAS:
        limit, used = lim[q.key], use[q.key]
        ratio = (used / limit) if (limit and used is not None) else (1.0 if limit == 0 and used else None)
        out.append({"key": q.key, "label": q.label, "unit": q.unit, "what": q.what, "limit": limit, "used": used,
                    "ratio": ratio, "source": "workspace" if q.key in own else "default",
                    "level": None if ratio is None else "over" if ratio >= 1 else "warn" if ratio >= WARN_AT else "ok"})
    _publish(ws, out)
    return out


def _publish(ws: str, rows: list[dict]) -> None:
    try:
        from app.services import metrics
        metrics.record_quota(ws, {r["key"]: r["ratio"] for r in rows})
    except Exception:  # noqa: BLE001 — a metric never stands in the way
        pass


# --------------------------------------------------------------------------- who is never stopped

def bypassed() -> bool:
    """An instance administrator signed in (auth notes it on the request, services/usage.py's holder)."""
    from app.services import usage as usage_mod
    holder = usage_mod._request.get()
    return bool(holder and holder.get("admin"))


def note_admin(is_admin: bool) -> None:
    from app.services import usage as usage_mod
    holder = usage_mod._request.get()
    if holder is not None and is_admin:
        holder["admin"] = True


def current_workspace() -> Optional[str]:
    from app.services import usage as usage_mod
    holder = usage_mod._request.get()
    ws = (holder or {}).get("workspace")
    return ws if ws and ws != usage_mod.UNKNOWN_WORKSPACE else None


# --------------------------------------------------------------------------- the checks

def check_file(db: Session, ws: str, size: int) -> None:
    """Before an upload starts: the file's own size, and the room left in the workspace."""
    if bypassed() or not ws:
        return
    lim = limits(db, ws)
    if lim["file_bytes"] is not None and size > lim["file_bytes"]:
        raise QuotaExceeded("file_bytes", lim["file_bytes"], size, 0, ws,
                            message=f"The file is {fmt(BY_KEY['file_bytes'], size)}; the largest file {ws} takes is "
                                    f"{fmt(BY_KEY['file_bytes'], lim['file_bytes'])}. An instance administrator can "
                                    f"raise it (Administration → Quotas).")
    if lim["storage_bytes"] is not None:
        used = _storage_bytes(db, ws)
        if used + size > lim["storage_bytes"]:
            raise QuotaExceeded("storage_bytes", lim["storage_bytes"], used, size, ws)


def check_ai(db: Session, ws: Optional[str]) -> None:
    """Before a call to the language model on a workspace's behalf."""
    if not ws or bypassed():
        return
    lim = limits(db, ws)
    for key, hours in (("ai_tokens_5h", 5), ("ai_tokens_week", 24 * 7)):
        if lim[key] is None:
            continue
        used, frees = ai_tokens(db, ws, hours)
        if used >= lim[key]:
            raise QuotaExceeded(key, lim[key], used, 0, ws, frees_at=frees)


def note_tokens(ws: Optional[str], tokens: int) -> None:
    """A model call's tokens, into its workspace's hour (its own short transaction: the call is already made)."""
    if not ws or tokens <= 0:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert
        from app.db import SessionLocal
        from app.models.usage import QuotaAIUsage
        hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        with SessionLocal() as db:
            stmt = insert(QuotaAIUsage).values(hour=hour, workspace_id=ws[:100], tokens=tokens)
            db.execute(stmt.on_conflict_do_update(index_elements=["hour", "workspace_id"],
                                                  set_={"tokens": QuotaAIUsage.tokens + stmt.excluded.tokens}))
            db.commit()
    except Exception:  # noqa: BLE001 — counting must never fail the call that was made
        import logging
        logging.getLogger(__name__).warning("AI tokens not counted for the quota", exc_info=True)


def check_import_slot(db: Session) -> None:
    """Before a portability import is registered: how many are not over yet. Everyone is held to it."""
    from app.models.portability import PortabilityImport
    limit = defaults(db)["imports_at_once"]
    if limit is None:
        return
    open_ = list(db.scalars(select(PortabilityImport.id).where(
        PortabilityImport.state.notin_(("finalized", "discarded", "invalid")),
        PortabilityImport.purged_at.is_(None))))
    if len(open_) >= limit:
        raise QuotaExceeded("imports_at_once", limit, len(open_), 1, None, message=(
            f"{len(open_)} import(s) not over yet ({', '.join(open_[:3])}): finalize or discard "
            f"{'it' if len(open_) == 1 else 'one'} first. At most {limit} at once (Administration → Quotas)."))


# --------------------------------------------------------------------------- API operations (in memory)

class _ApiCounter:
    """Requests made with a token, per workspace: today (seeded from the usage counts already written, so a
    restart does not reset the day) and this minute. Per API process: several replicas each count their own."""

    def __init__(self):
        self.lock = threading.Lock()
        self.day: dict[tuple, int] = {}
        self.minute: dict[str, deque] = {}

    def _seed(self, ws: str, day) -> int:
        try:
            from app.db import SessionLocal
            from app.models.usage import UsageRequest
            with SessionLocal() as db:
                return int(db.scalar(select(func.coalesce(func.sum(UsageRequest.count), 0)).where(
                    UsageRequest.day == day, UsageRequest.workspace_id == ws,
                    UsageRequest.client.in_(("api", "mcp")))) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def today(self, ws: str) -> int:
        day = datetime.now(timezone.utc).date()
        with self.lock:
            v = self.day.get((day, ws))
        return v if v is not None else self._seed(ws, day)

    def this_minute(self, ws: str) -> int:
        now = time.time()
        with self.lock:
            q = self.minute.get(ws)
            while q and q[0] < now - 60:
                q.popleft()
            return len(q) if q else 0

    def hit(self, ws: str) -> tuple[int, int]:
        day, now = datetime.now(timezone.utc).date(), time.time()
        seed = None
        with self.lock:
            if (day, ws) not in self.day:
                seed = True
        if seed:
            base = self._seed(ws, day)
            with self.lock:
                self.day.setdefault((day, ws), base)
        with self.lock:
            self.day[(day, ws)] += 1
            for k in [k for k in self.day if k[0] != day]:
                del self.day[k]
            q = self.minute.setdefault(ws, deque())
            while q and q[0] < now - 60:
                q.popleft()
            q.append(now)
            return self.day[(day, ws)], len(q)


_api = _ApiCounter()
_limits_cache: dict[str, tuple[float, dict]] = {}


def _cached_limits(ws: str) -> dict:
    hit = _limits_cache.get(ws)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from app.db import SessionLocal
    with SessionLocal() as db:
        v = limits(db, ws)
    _limits_cache[ws] = (time.monotonic() + 30, v)
    return v


def check_api(ws: str) -> Optional[QuotaExceeded]:
    """A request made with a token naming a workspace: counted, and refused past its quota (429)."""
    try:
        lim = _cached_limits(ws)
    except Exception:  # noqa: BLE001 — no database, no quota: the request goes on and fails on its own
        return None
    if lim["api_ops_day"] is None and lim["api_ops_minute"] is None:
        return None
    day, minute = _api.hit(ws)
    if lim["api_ops_minute"] is not None and minute > lim["api_ops_minute"]:
        return QuotaExceeded("api_ops_minute", lim["api_ops_minute"], minute - 1, 1, ws,
                             frees_at=datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1))
    if lim["api_ops_day"] is not None and day > lim["api_ops_day"]:
        tomorrow = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return QuotaExceeded("api_ops_day", lim["api_ops_day"], day - 1, 1, ws, frees_at=tomorrow)
    return None


def forget_cache() -> None:
    _limits_cache.clear()


# --------------------------------------------------------------------------- the flush guard

def _on_flush(session, flush_context, instances) -> None:
    """New records, documents, files and members, counted against their workspace's quotas before they are
    written. Nothing is counted when no quota applies to them."""
    from app.models.asset import Asset
    from app.models.attachment import Attachment
    from app.models.document import Document
    from app.models.membership import Membership
    from app.models.role import RoleBinding
    from app.services.sites import LOADING_ARCHIVE
    if not session.new or session.info.get(LOADING_ARCHIVE) or bypassed():
        return
    adds: dict[str, dict] = {}
    for o in session.new:
        if isinstance(o, Asset) and o.workspace_id and o.deleted_at is None:
            adds.setdefault(o.workspace_id, {}).setdefault("assets", []).append(o)
        elif isinstance(o, Document) and getattr(o, "workspace_id", None):
            adds.setdefault(o.workspace_id, {}).setdefault("documents", []).append(o)
        elif isinstance(o, Attachment) and o.workspace_id:
            adds.setdefault(o.workspace_id, {}).setdefault("files", []).append(o)
        elif isinstance(o, RoleBinding) and o.subject_type == "user" and o.workspace_id:
            adds.setdefault(o.workspace_id, {}).setdefault("members", []).append(o.subject_id)
        elif isinstance(o, Membership) and o.workspace_id:
            adds.setdefault(o.workspace_id, {}).setdefault("members", []).append(o.user_id)
    if not adds:
        return
    with session.no_autoflush:
        for ws, new in adds.items():
            lim = limits(session, ws)
            if new.get("assets") and lim["assets"] is not None:
                used = _count_assets(session, ws)
                if used + len(new["assets"]) > lim["assets"]:
                    raise QuotaExceeded("assets", lim["assets"], used, len(new["assets"]), ws)
            if new.get("documents") and lim["documents"] is not None:
                used = _count_documents(session, ws)
                if used + len(new["documents"]) > lim["documents"]:
                    raise QuotaExceeded("documents", lim["documents"], used, len(new["documents"]), ws)
            if new.get("files"):
                sizes = [int(a.file_size or 0) for a in new["files"]]
                if lim["file_bytes"] is not None and max(sizes) > lim["file_bytes"]:
                    check_file(session, ws, max(sizes))
                if lim["storage_bytes"] is not None:
                    used = _storage_bytes(session, ws)
                    if used + sum(sizes) > lim["storage_bytes"]:
                        raise QuotaExceeded("storage_bytes", lim["storage_bytes"], used, sum(sizes), ws)
            if new.get("members") and lim["members"] is not None:
                have = _members(session, ws)
                newcomers = set(new["members"]) - have
                if newcomers and len(have) + len(newcomers) > lim["members"]:
                    raise QuotaExceeded("members", lim["members"], len(have), len(newcomers), ws)


def install_guard() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session
    if not event.contains(_Session, "before_flush", _on_flush):
        event.listen(_Session, "before_flush", _on_flush)


install_guard()
