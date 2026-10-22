"""Anonymous usage counts, for the Statistics page (models/usage.py).

Every request is counted, in memory, by day, client, workspace and function (the route it matched); who made
it only as a keyed hash, per five-minute slot, which is enough to count people at once and per day. The
language model's calls are counted the same way, with the tokens the provider reports (or an estimate when it
reports none). A thread writes the counts out every half minute, adding to what is there, so several API
replicas count into the same rows; a count still in memory when a process dies is lost, which a statistic
can afford.

ARGUS_USAGE_STATS=0 switches it off.
"""
from __future__ import annotations

import atexit
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

FLUSH_SECONDS = 30
BUCKET_MINUTES = 5
PRESENCE_DAYS = 400          # presence slots older than this are dropped; daily counts are kept
KEY_SETTING = "usage_key"
STORAGE_SECONDS = 3600       # storage is measured hourly (the day keeps its last measurement)

# What the current request is: its client and workspace, and (set by authentication) who it is.
_request: ContextVar[Optional[dict]] = ContextVar("argus_usage_request", default=None)

_lock = threading.Lock()
_requests: dict[tuple, list[int]] = {}          # (day, client, workspace, function) -> [count, errors, ms]
_presence: set[tuple] = set()                   # (bucket, client, user id)
_llm: dict[tuple, list[int]] = {}               # (day, workspace, model, purpose) -> [calls, failures, in, out, est, ms]
_thread: Optional[threading.Thread] = None
_key: Optional[bytes] = None


def enabled() -> bool:
    return os.environ.get("ARGUS_USAGE_STATS", "1").strip().lower() not in ("0", "false", "no", "off")


def client_of(headers, path: str) -> str:
    """web, app (the Android app), mcp (an assistant through MCP) or api (scripts, robots)."""
    if (headers.get("x-argus-client") or "").lower().startswith("flutter"):
        return "app"
    if path.startswith("/mcp"):
        return "mcp"
    if "mozilla" in (headers.get("user-agent") or "").lower():
        return "web"
    return "api"


def counted(method: str, path: str) -> bool:
    return enabled() and method != "OPTIONS" and not (
        path in ("/health", "/v1/meta/version", "/v1/meta/api") or path.startswith(("/docs", "/openapi", "/redoc")))


def begin(headers, path: str) -> dict:
    holder = {"client": client_of(headers, path), "workspace": (headers.get("x-workspace-id") or "")[:100],
              "user": None, "started": time.monotonic()}
    _request.set(holder)
    return holder


def note_user(user_id: Optional[str], workspace_id: Optional[str] = None) -> None:
    """Who the request is (from authentication): kept only as a keyed hash, and only per five minutes."""
    holder = _request.get()
    if holder is not None:
        if user_id:
            holder["user"] = user_id
        if workspace_id and not holder["workspace"]:
            holder["workspace"] = workspace_id


def end(holder: dict, function: str, status: int) -> None:
    now = datetime.now(timezone.utc)
    ms = int((time.monotonic() - holder["started"]) * 1000)
    with _lock:
        row = _requests.setdefault((now.date(), holder["client"], holder["workspace"], function[:200]), [0, 0, 0])
        row[0] += 1
        row[1] += 1 if status >= 500 else 0
        row[2] += ms
        if holder.get("user"):
            bucket = now.replace(minute=now.minute - now.minute % BUCKET_MINUTES, second=0, microsecond=0)
            _presence.add((bucket, holder["client"], holder["user"]))
    _start()


def note_llm(model: Optional[str], purpose: str, *, prompt_tokens: Optional[int] = None,
             completion_tokens: Optional[int] = None, prompt_text: str = "", completion_text: str = "",
             seconds: float = 0.0, failed: bool = False) -> None:
    """One call to the language model. Tokens the provider did not report are estimated from the text."""
    if not enabled():
        return
    estimated = prompt_tokens is None and completion_tokens is None and not failed
    if prompt_tokens is None:
        prompt_tokens = len(prompt_text) // 4
    if completion_tokens is None:
        completion_tokens = len(completion_text) // 4
    holder = _request.get()
    workspace = (holder or {}).get("workspace") or ""
    with _lock:
        row = _llm.setdefault((datetime.now(timezone.utc).date(), workspace, (model or "?")[:200], purpose),
                              [0, 0, 0, 0, 0, 0])
        row[0] += 1
        row[1] += 1 if failed else 0
        row[2] += int(prompt_tokens or 0)
        row[3] += int(completion_tokens or 0)
        row[4] += 1 if estimated else 0
        row[5] += int(seconds * 1000)
    _start()


def _person_key(db) -> bytes:
    """The installation's own key for the presence hash, made the first time and kept in the settings."""
    global _key
    if _key is None:
        from app.models.app_setting import AppSetting
        row = db.get(AppSetting, KEY_SETTING)
        if row is None:
            row = AppSetting(key=KEY_SETTING, value={"key": secrets.token_hex(32)})
            db.add(row)
            db.flush()
        _key = bytes.fromhex(row.value["key"])
    return _key


def person(db, user_id: str) -> str:
    return hmac.new(_person_key(db), user_id.encode(), hashlib.sha256).hexdigest()[:20]


def flush() -> None:
    """Add what was counted in memory to the tables."""
    global _requests, _presence, _llm
    with _lock:
        requests_, presence, llm = _requests, _presence, _llm
        _requests, _presence, _llm = {}, set(), {}
    if not (requests_ or presence or llm):
        return
    from sqlalchemy.dialects.postgresql import insert

    from app.db import SessionLocal
    from app.models.usage import UsageLLM, UsagePresence, UsageRequest
    db = SessionLocal()
    try:
        if requests_:
            stmt = insert(UsageRequest).values([
                {"day": k[0], "client": k[1], "workspace_id": k[2], "function": k[3], "count": v[0], "errors": v[1],
                 "ms_total": v[2]} for k, v in requests_.items()])
            db.execute(stmt.on_conflict_do_update(
                index_elements=["day", "client", "workspace_id", "function"],
                set_={"count": UsageRequest.count + stmt.excluded.count,
                      "errors": UsageRequest.errors + stmt.excluded.errors,
                      "ms_total": UsageRequest.ms_total + stmt.excluded.ms_total}))
        if presence:
            rows = {(b, c, person(db, u)) for b, c, u in presence}
            db.execute(insert(UsagePresence).values([{"bucket": b, "client": c, "person": p} for b, c, p in rows])
                       .on_conflict_do_nothing())
        if llm:
            stmt = insert(UsageLLM).values([
                {"day": k[0], "workspace_id": k[1], "model": k[2], "purpose": k[3], "calls": v[0], "failures": v[1],
                 "prompt_tokens": v[2], "completion_tokens": v[3], "estimated_calls": v[4], "ms_total": v[5]}
                for k, v in llm.items()])
            db.execute(stmt.on_conflict_do_update(
                index_elements=["day", "workspace_id", "model", "purpose"],
                set_={c: getattr(UsageLLM, c) + getattr(stmt.excluded, c)
                      for c in ("calls", "failures", "prompt_tokens", "completion_tokens", "estimated_calls",
                                "ms_total")}))
        db.commit()
    except Exception:  # noqa: BLE001 — a statistic never fails anything else
        db.rollback()
        log.warning("usage counts not written", exc_info=True)
    finally:
        db.close()


def prune(db, now: Optional[datetime] = None) -> int:
    from sqlalchemy import delete

    from app.models.usage import UsagePresence
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=PRESENCE_DAYS)
    return db.execute(delete(UsagePresence).where(UsagePresence.bucket < cutoff)).rowcount or 0


def _measure_storage() -> None:
    """Today's storage measurement (services/storage.py), kept for the trend."""
    from app.db import SessionLocal
    from app.services import storage
    db = SessionLocal()
    try:
        storage.snapshot(db)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.warning("storage not measured", exc_info=True)
    finally:
        db.close()


def _loop() -> None:
    last_prune = 0.0
    last_storage = 0.0
    while True:
        time.sleep(FLUSH_SECONDS)
        flush()
        if time.monotonic() - last_storage > STORAGE_SECONDS:
            last_storage = time.monotonic()
            _measure_storage()
        if time.monotonic() - last_prune > 86400:
            last_prune = time.monotonic()
            from app.db import SessionLocal
            db = SessionLocal()
            try:
                prune(db)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            finally:
                db.close()


def _start() -> None:
    global _thread
    if _thread is None:
        with _lock:
            if _thread is None:
                _thread = threading.Thread(target=_loop, name="usage-counts", daemon=True)
                _thread.start()
                atexit.register(flush)
