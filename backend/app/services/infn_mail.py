"""INFN mail delivery through a confidential Keycloak client (client credentials)."""
import logging
import json
import os
import threading
import time
from urllib.parse import urlsplit

import requests
from sqlalchemy import event, select

from app.models.workflow import Notification
from app.models.workspace import Workspace
from app.services import notify

log = logging.getLogger("argus.notify")
_token_lock = threading.Lock()
_access_token: str | None = None
_token_expires_at = 0.0


def configured() -> bool:
    return all(os.environ.get(key) for key in (
        "INFN_MAIL_URL", "INFN_MAIL_TOKEN_URL", "BACK_END_CLIENT_OAUTH",
    ))


def track_request(db) -> None:
    """Remember notification rows committed by this request; never retain OAuth tokens here."""
    if db.info.get("infn_mail_tracking"):
        return
    db.info["infn_mail_tracking"] = True

    def flushed(session, context):
        session.info.setdefault("infn_mail_pending", set()).update(
            n.id for n in session.new if isinstance(n, Notification))

    def committed(session):
        if not session.in_nested_transaction():
            session.info.setdefault("infn_mail_committed", set()).update(
                session.info.pop("infn_mail_pending", set()))

    def rolled_back(session):
        session.info.pop("infn_mail_pending", None)

    event.listen(db, "after_flush", flushed)
    event.listen(db, "after_commit", committed)
    event.listen(db, "after_rollback", rolled_back)


def _https_endpoint(name: str) -> str:
    url = os.environ.get(name, "")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise notify.MailError(f"{name} must be an HTTPS URL without credentials, query or fragment.")
    return url


def _client_token() -> str:
    """Fetch and briefly cache a service-account token; never log or persist it."""
    global _access_token, _token_expires_at
    with _token_lock:
        if _access_token and time.monotonic() < _token_expires_at - 30:
            return _access_token
        endpoint = _https_endpoint("INFN_MAIL_TOKEN_URL")
        try:
            client = json.loads(os.environ["BACK_END_CLIENT_OAUTH"])
        except (ValueError, TypeError):
            raise notify.MailError("BACK_END_CLIENT_OAUTH must be JSON with client_id and client_secret.") from None
        if not isinstance(client, dict) or not isinstance(client.get("client_id"), str) or not client["client_id"] \
                or not isinstance(client.get("client_secret"), str) or not client["client_secret"]:
            raise notify.MailError("BACK_END_CLIENT_OAUTH must include non-empty client_id and client_secret.")
        client_id = client["client_id"]
        secret = client["client_secret"]
        data = {"grant_type": "client_credentials"}
        if client.get("scope"):
            if not isinstance(client["scope"], str):
                raise notify.MailError("BACK_END_CLIENT_OAUTH scope must be a string.")
            data["scope"] = client["scope"]
        try:
            response = requests.post(endpoint, data=data, auth=(client_id, secret),
                                     timeout=(5, 15), allow_redirects=False)
        except requests.RequestException as exc:
            kind = "timeout" if isinstance(exc, requests.Timeout) else "connection error"
            raise notify.MailError(f"INFN Keycloak token {kind}; check INFN_MAIL_TOKEN_URL.") from None
        if response.status_code != 200:
            raise notify.MailError(f"INFN Keycloak refused client credentials (HTTP {response.status_code}).")
        try:
            body = response.json()
            token = body.get("access_token") if isinstance(body, dict) else None
            expires = float(body.get("expires_in", 300)) if isinstance(body, dict) else 0
        except (ValueError, TypeError):
            raise notify.MailError("INFN Keycloak returned an invalid token response.") from None
        if not isinstance(token, str) or not token or expires <= 0:
            raise notify.MailError("INFN Keycloak did not return a usable access token.")
        _access_token = token
        _token_expires_at = time.monotonic() + expires
        return token


def send(to: str, subject: str, message: str) -> None:
    url = _https_endpoint("INFN_MAIL_URL")
    token = _client_token()
    body = {"to": [to], "subject": subject, "message": message}
    if os.environ.get("INFN_MAIL_FROM"):
        body["from"] = os.environ["INFN_MAIL_FROM"]
    try:
        response = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"},
                                 timeout=(3, 10), allow_redirects=False)
    except requests.RequestException as exc:
        kind = "timeout" if isinstance(exc, requests.Timeout) else "connection error"
        raise notify.MailError(f"INFN mail {kind}; check INFN_MAIL_URL and the network route.") from None
    if response.status_code != 200:
        raise notify.MailError(f"INFN mail refused the message (HTTP {response.status_code}).")
    try:
        result = response.json()
    except ValueError:
        raise notify.MailError("INFN mail returned HTTP 200 with a non-JSON response.") from None
    if not isinstance(result, dict):
        raise notify.MailError("INFN mail returned an invalid response.")
    if result.get("errorCode") != 0 or result.get("payload") is not True:
        code = result.get("errorCode", "unknown")
        domain = result.get("errorDomain")
        suffix = f" ({domain})" if isinstance(domain, str) and domain.isascii() else ""
        raise notify.MailError(f"INFN mail rejected the message (errorCode={code}{suffix}).")


def deliver_request(db) -> None:
    """Send committed instant notifications using the application's mail-service identity."""
    ids = db.info.pop("infn_mail_committed", set())
    if not ids or not configured():
        return
    from app.db import SessionLocal
    with SessionLocal() as delivery:
        rows = delivery.scalars(select(Notification).where(
            Notification.id.in_(ids), Notification.delivered_at.is_(None)
        ).order_by(Notification.id).with_for_update(skip_locked=True)).all()
        for n in rows:
            user = notify._user(delivery, n.recipient)
            address = (user.email if user else None) or (n.recipient if "@" in n.recipient else "")
            pref = notify.preference(delivery, user)
            mode = pref.email if pref else "instant"
            if mode == "off" or not notify.deliverable(address) or notify.category_of(n.kind) in (
                pref.muted or [] if pref else []
            ):
                n.delivered_at = notify.now()
            elif mode == "instant":
                workspace = delivery.get(Workspace, n.workspace_id)
                try:
                    send(address, f"[ARGUS] {n.title}"[:250],
                         notify._instant_body(delivery, n, workspace.name if workspace else n.workspace_id))
                except notify.MailError as exc:
                    log.warning("INFN notification %s remains pending: %s", n.id, exc)
                    break
                n.delivered_at = notify.now()
        delivery.commit()
