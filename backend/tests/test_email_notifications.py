"""Notifications by e-mail: each one as it happens or in a daily digest, as each person chose, none of what they
muted, linked to its page in its workspace; never a backlog; a refused recipient does not stop the others. A
revision sent for review asks the people who can approve it."""
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

from app.db import SessionLocal
from app.models.workflow import Notification, NotificationPreference
from app.services import notify
from tests.test_find_follow_jql import as_, client, people  # noqa: F401 — fixture


class FakeSMTP:
    def __init__(self, refuse=(), code=550):
        self.sent: list[EmailMessage] = []
        self.refuse = set(refuse)
        self.code = code

    def send_message(self, msg):
        import smtplib
        if msg["To"] in self.refuse or "*" in self.refuse:
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (self.code, b"refused")})
        self.sent.append(msg)

    def quit(self):
        pass

    def to(self, address):
        return [m for m in self.sent if m["To"] == address]


REAL_DELIVERABLE = notify.deliverable


@pytest.fixture(autouse=True)
def fake_servers_reach_test_addresses(monkeypatch):
    """The people here have test addresses (@argus.test), which a real server could never reach: the fake
    servers of these tests can."""
    monkeypatch.setattr(notify, "deliverable", lambda address: "@" in (address or ""))


@pytest.fixture()
def mail(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ARGUS_WEB_URL", "https://argus.example.org")
    smtp = FakeSMTP()
    monkeypatch.setattr(notify, "_connect", lambda: smtp)
    return smtp


def _note(db, ws, user, kind="assigned", title="Assigned to you: a pump", age_hours=0.0, **detail):
    n = Notification(workspace_id=ws, recipient=user.id, kind=kind, title=title, detail=detail, actor=None,
                     created_at=datetime.now(timezone.utc) - timedelta(hours=age_hours))
    db.add(n)
    db.flush()
    return n


def _prefer(db, user, email, muted=(), last=None):
    db.merge(NotificationPreference(user_id=user.id, email=email, muted=list(muted), last_digest_at=last))
    db.flush()


def test_each_notification_is_emailed_with_its_page_in_its_workspace(people, mail):
    w = people
    db = SessionLocal()
    doc = _note(db, w["ws"], w["bob"], kind="document_changed", title="DOC-1 Bake-out: revision 2 published",
                subject="document", uid="d-1")
    old = _note(db, w["ws"], w["bob"], title="Assigned to you: last year's", age_hours=72)
    notify.deliver_pending(db)
    db.commit()
    [msg] = [m for m in mail.to(w["bob"].email) if "Bake-out" in m["Subject"]]
    body = msg.get_content()
    assert msg["Subject"] == "[ARGUS] DOC-1 Bake-out: revision 2 published"
    assert f"https://argus.example.org/documents/d-1?ws={w['ws']}" in body and "Linac" in body
    assert msg["Auto-Submitted"] == "auto-generated"
    assert not any("last year" in m["Subject"] for m in mail.sent), "a backlog is not e-mailed"
    db.refresh(doc)
    db.refresh(old)
    assert doc.delivered_at is not None and old.delivered_at is not None
    notify.deliver_pending(db)
    assert len([m for m in mail.to(w["bob"].email) if "Bake-out" in m["Subject"]]) == 1, "sent once"
    db.close()


def test_what_a_person_muted_or_switched_off_stays_in_the_app(people, mail):
    w = people
    db = SessionLocal()
    _prefer(db, w["ann"], "instant", muted=["following"])
    _prefer(db, w["cid"], "off")
    _note(db, w["ws"], w["ann"], kind="asset_changed", title="Pump 7: label added", subject="asset", uid="a")
    _note(db, w["ws"], w["ann"], kind="mentioned", title="You were mentioned on a pump")
    _note(db, w["ws"], w["cid"], title="Assigned to you: cid's pump")
    notify.deliver_pending(db)
    db.commit()
    assert [m["Subject"] for m in mail.to(w["ann"].email)] == ["[ARGUS] You were mentioned on a pump"]
    assert mail.to(w["cid"].email) == []
    db.close()


def test_a_digest_gathers_a_day_and_goes_once_after_its_hour(people, mail, monkeypatch):
    w = people
    monkeypatch.setenv("NOTIFY_DIGEST_HOUR", "7")
    db = SessionLocal()
    rome = timezone(timedelta(hours=2))
    morning = datetime(2026, 10, 15, 7, 5, tzinfo=rome)
    _prefer(db, w["bob"], "digest", last=morning - timedelta(days=1))
    for title in ("Assigned to you: one", "New comment on two"):
        n = _note(db, w["ws"], w["bob"], title=title)
        n.created_at = morning - timedelta(hours=3)
    db.flush()
    notify.deliver_pending(db, at=morning - timedelta(hours=1))          # before the hour: nothing yet
    assert mail.to(w["bob"].email) == []
    notify.deliver_pending(db, at=morning)
    [digest] = mail.to(w["bob"].email)
    assert digest["Subject"] == "[ARGUS] Your daily digest: 2 notification(s)"
    assert "* Assigned to you: one" in digest.get_content() and "* New comment on two" in digest.get_content()
    _note(db, w["ws"], w["bob"], title="Assigned to you: three").created_at = morning
    notify.deliver_pending(db, at=morning + timedelta(hours=2))          # the same day: tomorrow's digest
    assert len(mail.to(w["bob"].email)) == 1
    db.rollback()
    db.close()


def test_a_refused_recipient_does_not_stop_the_others(people, monkeypatch):
    w = people
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    smtp = FakeSMTP(refuse={w["ann"].email})
    monkeypatch.setattr(notify, "_connect", lambda: smtp)
    db = SessionLocal()
    refused = _note(db, w["ws"], w["ann"], title="Assigned to you: refused")
    _note(db, w["ws"], w["bob"], title="Assigned to you: delivered")
    notify.deliver_pending(db)
    assert [m["Subject"] for m in smtp.to(w["bob"].email)] == ["[ARGUS] Assigned to you: delivered"]
    db.refresh(refused)
    assert refused.delivered_at is not None, "not retried for ever"
    db.rollback()
    db.close()


def test_an_unreachable_server_leaves_them_for_the_next_run(people, monkeypatch):
    w = people
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")

    def down():
        raise notify.MailError("connection refused")
    monkeypatch.setattr(notify, "_connect", down)
    db = SessionLocal()
    n = _note(db, w["ws"], w["bob"], title="Assigned to you: later")
    assert notify.deliver_pending(db) == 0
    db.refresh(n)
    assert n.delivered_at is None
    db.rollback()
    db.close()


def test_the_relay_is_reached_over_starttls_with_its_account(monkeypatch):
    calls = []

    class Server:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

    monkeypatch.setattr(notify.smtplib, "SMTP", Server)
    monkeypatch.setenv("SMTP_HOST", "smtp.lnf.infn.it")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "argus")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("SMTP_SECURITY", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    notify._connect()
    assert calls == [("connect", "smtp.lnf.infn.it", 587), ("ehlo",), ("starttls",), ("ehlo",), ("login", "argus")]
    assert notify._sender() == "ARGUS <argus@lnf.infn.it>"


def test_preferences_and_a_test_message(people, monkeypatch):
    w = people
    monkeypatch.delenv("SMTP_HOST", raising=False)
    as_(w["ann"])
    got = client.get("/v1/notifications/preferences").json()
    assert got["email"] == "instant" and got["muted"] == [] and got["email_configured"] is False
    assert {c["key"] for c in got["categories"]} == set(notify.EMAIL_CATEGORIES)
    assert client.post("/v1/notifications/preferences/test").status_code == 409
    r = client.put("/v1/notifications/preferences", json={"email": "digest", "muted": ["workspace"]})
    assert r.status_code == 200 and r.json()["email"] == "digest" and r.json()["muted"] == ["workspace"]
    assert client.put("/v1/notifications/preferences", json={"muted": ["nonsense"]}).status_code == 422
    smtp = FakeSMTP()
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(notify, "_connect", lambda: smtp)
    assert client.post("/v1/notifications/preferences/test").json() == {"sent_to": w["ann"].email}
    assert smtp.to(w["ann"].email)[0]["Subject"] == "[ARGUS] Test message"


def test_a_revision_sent_for_review_asks_those_who_can_approve_it(people):
    w = people
    h = {"X-Workspace-Id": w["ws"]}
    as_(w["ann"])
    doc = str(uuid.uuid4())
    assert client.post("/v1/documents", headers=h, json={"uid": doc, "title": "Interlock test",
                                                         "body_markdown": "Steps"}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/revisions/{doc}-r1/submit", headers=h).status_code == 200
    as_(w["bob"])
    asked = [n for n in client.get("/v1/notifications/everywhere", params={"include_read": True}).json()
             if n["detail"].get("uid") == doc]
    assert [n["kind"] for n in asked] == ["review_requested"]
    assert asked[0]["title"].startswith("Review requested:") and asked[0]["title"].endswith("Interlock test, revision 1")
    as_(w["cid"])                                       # may approve, may not read documents
    assert not [n for n in client.get("/v1/notifications/everywhere", params={"include_read": True}).json()
                if n["detail"].get("uid") == doc]


def test_a_relay_that_defers_keeps_them_for_the_next_run(people, monkeypatch):
    """Not signed in, the LNF relay answers each recipient "454 Relay access denied": temporary. Nothing is
    given up; once the account is set, the next run sends them."""
    w = people
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    smtp = FakeSMTP(refuse={"*"}, code=454)
    monkeypatch.setattr(notify, "_connect", lambda: smtp)
    db = SessionLocal()
    n = _note(db, w["ws"], w["bob"], title="Assigned to you: deferred")
    assert notify.deliver_pending(db) == 0
    db.refresh(n)
    assert n.delivered_at is None
    smtp.refuse.clear()
    notify.deliver_pending(db)
    assert [m["Subject"] for m in smtp.to(w["bob"].email)] == ["[ARGUS] Assigned to you: deferred"]
    db.rollback()
    db.close()


def test_addresses_at_domains_that_cannot_receive_mail_are_not_emailed():
    deliverable = REAL_DELIVERABLE
    for address in ("owner.test@argus.test", "play-review@argus-review.invalid", "a@example.com", "b@x.example",
                    "c@host.localhost", "nobody", ""):
        assert not deliverable(address), address
    for address in ("andrea.michelotti@lnf.infn.it", "someone@gmail.com", "Name <x@lnf.infn.it>"):
        assert deliverable(address), address


def test_a_test_account_keeps_its_notifications_in_the_app(people, monkeypatch):
    monkeypatch.setattr(notify, "deliverable", REAL_DELIVERABLE)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    smtp = FakeSMTP()
    monkeypatch.setattr(notify, "_connect", lambda: smtp)
    db = SessionLocal()
    try:
        n = _note(db, people["ws"], people["ann"])               # ann-…@argus.test
        db.commit()
        notify.deliver_pending(db)
        db.commit()
        assert smtp.sent == []
        assert db.get(Notification, n.id).delivered_at is not None   # settled: not retried at every run
    finally:
        db.rollback()
        db.close()
