"""INFN mail delivery authenticates as the confidential ARGUS client."""
from types import SimpleNamespace

import json

import pytest
import requests

from app.db import SessionLocal
from app.models.workflow import Notification
from app.services import infn_mail, notify
from tests.test_email_notifications import _note, fake_servers_reach_test_addresses, people  # noqa: F401


@pytest.fixture(autouse=True)
def mail_config(monkeypatch):
    monkeypatch.setenv("INFN_MAIL_URL", "https://api.app-pre.infn.it/mail/send/")
    monkeypatch.setenv("INFN_MAIL_TOKEN_URL", "https://idp-test.app.infn.it/auth/realms/aai/protocol/openid-connect/token")
    monkeypatch.setenv("BACK_END_CLIENT_OAUTH", json.dumps({"client_id": "argus-mail", "client_secret": "secret"}))
    monkeypatch.delenv("INFN_MAIL_FROM", raising=False)
    infn_mail._access_token = None
    infn_mail._token_expires_at = 0
    yield
    infn_mail._access_token = None
    infn_mail._token_expires_at = 0


def test_client_credentials_are_exchanged_once_and_cached(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"access_token": "service-token", "expires_in": 300})
    monkeypatch.setattr(infn_mail.requests, "post", post)
    assert infn_mail._client_token() == "service-token"
    assert infn_mail._client_token() == "service-token"
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url.endswith("/protocol/openid-connect/token")
    assert kwargs["data"] == {"grant_type": "client_credentials"}
    assert kwargs["auth"] == ("argus-mail", "secret")
    assert kwargs["allow_redirects"] is False


def test_mail_request_uses_service_token_and_openapi_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(infn_mail, "_client_token", lambda: "service-token")
    monkeypatch.setattr(infn_mail.requests, "post", lambda url, **kwargs: (
        calls.append((url, kwargs)) or SimpleNamespace(status_code=200,
            json=lambda: {"errorCode": 0, "payload": True})))
    infn_mail.send("person@infn.it", "Subject", "Body")
    url, kwargs = calls[0]
    assert url == "https://api.app-pre.infn.it/mail/send/"
    assert kwargs["headers"] == {"Authorization": "Bearer service-token"}
    assert kwargs["json"] == {"to": ["person@infn.it"], "subject": "Subject", "message": "Body"}


def test_token_exchange_failures_do_not_expose_client_secret(monkeypatch):
    def refused(*args, **kwargs):
        return SimpleNamespace(status_code=401)
    monkeypatch.setattr(infn_mail.requests, "post", refused)
    with pytest.raises(notify.MailError) as exc:
        infn_mail._client_token()
    assert "secret" not in str(exc.value)


def test_only_committed_request_notifications_are_sent(people, monkeypatch):
    sent = []
    monkeypatch.setattr(infn_mail, "send", lambda *args: sent.append(args))
    w = people
    with SessionLocal() as db:
        unrelated = _note(db, w["ws"], w["bob"], title="Unrelated")
        db.commit()
        infn_mail.track_request(db)
        note = _note(db, w["ws"], w["bob"], title="Assigned to you: pump")
        db.commit()
        _note(db, w["ws"], w["bob"], title="Rolled back")
        db.rollback()
        infn_mail.deliver_request(db)
        assert len(sent) == 1
        assert sent[0][:2] == (w["bob"].email, "[ARGUS] Assigned to you: pump")
        db.expire_all()
        assert db.get(Notification, note.id).delivered_at is not None
        assert db.get(Notification, unrelated.id).delivered_at is None


def test_infn_only_counts_as_configured_and_does_not_start_smtp_worker(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert notify.email_configured()
    assert notify.deliver_pending(None) == 0


def test_token_timeout_is_reported_without_credentials(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("secret")
    monkeypatch.setattr(infn_mail.requests, "post", timeout)
    with pytest.raises(notify.MailError) as exc:
        infn_mail._client_token()
    assert "secret" not in str(exc.value)
