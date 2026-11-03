"""Idempotency keys on mutating requests (flutter-app-design §3.2, revision §24.3 item 2, I-MOB-2).

A client that may retry, the field client above all, sends `Idempotency-Key: <uuid>` with a
mutating request, and keeps the key for every retry of that command.

- **First time:** the key is reserved, the request runs, and its answer is stored against
  (workspace, principal, key) with a hash of the request.
- **Same key, same request:** the stored answer is returned with `Idempotent-Replayed: true`, and
  nothing runs again.
- **Same key, another request:** 422 `idempotency_mismatch`.
- **Still running:** 409 `in_progress` with `Retry-After`.

The following are not stored, so a retry runs the request again:
- server errors (5xx);
- 401, 426 and 429 answers, which are about the caller or the moment, not the command.

Limits:
- The answer is stored after the endpoint has committed. A process that dies between the two
  leaves the key reserved; after `STALE_AFTER` the reservation is released and a retry runs again.
- Endpoints that must never apply twice, even then, also carry their own guard (a client-supplied
  uid, an Installation's current-state check).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from app import problems

HEADER = "idempotency-key"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
NOT_STORED = {401, 426, 429}
STALE_AFTER = timedelta(minutes=10)
KEPT_HEADERS = ("content-type", "etag", "location")


def retention() -> timedelta:
    """The offline retention (U22, proposed 7 days) plus seven days."""
    days = int(os.environ.get("ARGUS_OFFLINE_RETENTION_DAYS", "7"))
    return timedelta(days=days + 7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def principal_of(db, authorization: Optional[str]) -> Optional[str]:
    """Who is asking, stable across token refreshes; None when the credentials are not valid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    raw = authorization.split(" ", 1)[1].strip()
    from app.auth import find_token
    token = find_token(db, raw)
    if token is not None:
        return f"pat:{token.id}"
    from app.auth_oidc import oidc_configured, verify_oidc_token
    if oidc_configured():
        try:
            claims = verify_oidc_token(raw)
        except Exception:
            return None
        return f"oidc:{claims.get('iss')}|{claims.get('sub')}"
    return None


def request_hash(method: str, path: str, query: str, body: bytes) -> str:
    h = hashlib.sha256()
    for part in (method.encode(), b"\0", path.encode(), b"\0", query.encode(), b"\0"):
        h.update(part)
    h.update(body)
    return h.hexdigest()


def _replay(row) -> Response:
    headers = dict(row.response_headers or {})
    headers["Idempotent-Replayed"] = "true"
    return Response(content=row.response_body or b"", status_code=row.status_code, headers=headers)


CAPTURED = "x-argus-captured-at"


def offline_retention() -> timedelta:
    """How long a command captured offline may wait before it is sent (U22, proposed 7 days)."""
    return timedelta(days=int(os.environ.get("ARGUS_OFFLINE_RETENTION_DAYS", "7")))


def expired(request: Request) -> Optional[Response]:
    """A command captured offline longer ago than the retention is not applied (revision §24.4, A65).
    The client says when the person captured it (`X-ARGUS-Captured-At`, with the device's offset
    from server time already applied); a request without the header is live."""
    raw = request.headers.get(CAPTURED)
    if request.method not in MUTATING or not raw:
        return None
    try:
        at = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return problems.response(422, {"error": "X-ARGUS-Captured-At must be an ISO 8601 time.", "code": "invalid",
                                       "field": "X-ARGUS-Captured-At"})
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if _now() - at > offline_retention():
        return problems.response(422, {
            "error": f"This was captured on {at.date().isoformat()}, longer ago than the "
                     f"{offline_retention().days}-day offline retention. It was not applied; do it again if it still "
                     "holds.", "code": "expired"})
    return None


async def run(request: Request, call_next):
    # Token responses must never be persisted or replayed by the API.
    if request.url.path == "/v1/auth/oidc/token":
        return await call_next(request)
    key = request.headers.get(HEADER)
    if request.method not in MUTATING or key is None:
        refused = expired(request)
        return refused if refused is not None else await call_next(request)
    key = key.strip()
    if not key or len(key) > 200 or not key.isprintable():
        return problems.response(422, {"error": "The Idempotency-Key must be 1 to 200 printable characters.",
                                       "code": "invalid", "field": "Idempotency-Key"})
    from app.db import SessionLocal
    from app.models.device import IdempotencyRecord
    body = await request.body()
    digest = request_hash(request.method, request.url.path, request.url.query, body)
    workspace = request.headers.get("x-workspace-id") or ""
    db = SessionLocal()
    try:
        principal = principal_of(db, request.headers.get("authorization"))
        if principal is None:
            # Not signed in: the endpoint answers 401 and there is nothing to remember.
            return await call_next(request)
        where = (IdempotencyRecord.workspace_id == workspace, IdempotencyRecord.principal == principal,
                 IdempotencyRecord.key == key)
        row = db.scalar(select(IdempotencyRecord).where(*where))
        if row is not None and (row.expires_at < _now() or (
                row.state == "in_progress" and row.created_at < _now() - STALE_AFTER)):
            db.delete(row)
            db.commit()
            row = None
        if row is None:
            # A stored answer is replayed whatever its age; only a new application of an old command
            # is refused.
            refused = expired(request)
            if refused is not None:
                return refused
            row = IdempotencyRecord(workspace_id=workspace, principal=principal, key=key, request_hash=digest,
                                    method=request.method, path=request.url.path, state="in_progress",
                                    expires_at=_now() + retention())
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(select(IdempotencyRecord).where(*where))
                if row is None:
                    return problems.response(409, {"error": "This request is being processed. Try again shortly.",
                                                   "code": "in_progress"}, {"Retry-After": "2"})
            else:
                return await _execute(db, row, request, call_next)
        if row.request_hash != digest:
            return problems.response(422, {
                "error": "This Idempotency-Key was used for a different request. Use a new key for a new command.",
                "code": "idempotency_mismatch"})
        if row.state != "done":
            return problems.response(409, {"error": "This request is being processed. Try again shortly.",
                                           "code": "in_progress"}, {"Retry-After": "2"})
        return _replay(row)
    finally:
        db.close()


async def _execute(db, row, request: Request, call_next) -> Response:
    try:
        response = await call_next(request)
    except Exception:
        db.delete(row)
        db.commit()
        raise
    chunks = [chunk async for chunk in response.body_iterator]
    content = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    if response.status_code >= 500 or response.status_code in NOT_STORED:
        db.delete(row)
    else:
        row.state = "done"
        row.status_code = response.status_code
        row.response_body = content
        row.response_headers = {k: v for k, v in headers.items() if k.lower() in KEPT_HEADERS}
    db.commit()
    return Response(content=content, status_code=response.status_code, headers=headers,
                    background=response.background)


def purge(db) -> int:
    """Delete expired records (run by `python -m app.ledger escalate`, the periodic job)."""
    from app.models.device import IdempotencyRecord
    result = db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < _now()))
    return result.rowcount or 0
