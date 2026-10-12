"""Importing Jira issues as tickets.

The mapping that needs care is status: Jira lets every project define its
own workflow, so the names can't be trusted, but each status carries one
of three statusCategory values — too coarse on its own, because "Closed"
and "Resolved" both land in "done", and "Pending" and "In Progress" both
land in "indeterminate". Names decide where they're unambiguous, the
category catches everything else.
"""
import json
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.packages.install import install
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset
from app.models.asset_subresources import AssetTicket
from app.models.import_job import ImportJob
from app.models.issue import Issue, IssueComment
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services.jira_issue_import import map_priority, map_state, run_jira_issue_import


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


def _status(name, category):
    return {"name": name, "statusCategory": {"key": category}}


def test_status_name_wins_where_it_is_unambiguous():
    # Both are "done" to Jira; they are different states to us.
    assert map_state(_status("Closed", "done")) == "closed"
    assert map_state(_status("Resolved", "done")) == "resolved"
    # Both are "indeterminate"; likewise.
    assert map_state(_status("In Progress", "indeterminate")) == "in_progress"
    assert map_state(_status("Waiting for customer", "indeterminate")) == "pending"
    # Italian workflows are in use on this tracker.
    assert map_state(_status("Chiuso", "done")) == "closed"
    assert map_state(_status("In corso", "indeterminate")) == "in_progress"


def test_unknown_status_falls_back_to_its_category():
    """A project with a bespoke workflow still has to land somewhere
    sensible rather than defaulting everything to "new"."""
    assert map_state(_status("Awaiting triage by SOC", "new")) == "new"
    assert map_state(_status("Escalated to vendor", "indeterminate")) == "in_progress"
    assert map_state(_status("Shipped", "done")) == "resolved"
    assert map_state({}) == "new"


def test_priority_covers_both_jira_schemes():
    assert map_priority({"name": "Blocker"}) == "blocker"
    assert map_priority({"name": "Highest"}) == "critical"
    assert map_priority({"name": "Major"}) == "high"
    assert map_priority({"name": "Trivial"}) == "low"
    assert map_priority({"name": "Media"}) == "medium"
    assert map_priority(None) is None
    assert map_priority({"name": "Wibble"}) is None


class _JiraStub(BaseHTTPRequestHandler):
    issues: list = []
    comments: dict = {}

    def log_message(self, *args):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/rest/api/2/serverInfo":
            self._json({"baseUrl": "http://stub", "deploymentType": "Server"})
        elif parsed.path == "/rest/api/2/search":
            query = parse_qs(parsed.query)
            start = int(query.get("startAt", ["0"])[0])
            size = int(query.get("maxResults", ["100"])[0])
            page = self.issues[start:start + size]
            self._json({"total": len(self.issues), "startAt": start, "issues": page})
        elif parsed.path.endswith("/comment"):
            key = parsed.path.split("/")[-2]
            self._json({"comments": self.comments.get(key, [])})
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def jira_stub():
    server = HTTPServer(("127.0.0.1", 0), _JiraStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _issue(key, summary, status, category, **fields):
    base = {
        "key": key,
        "fields": {
            "summary": summary,
            "description": fields.get("description"),
            "status": _status(status, category),
            "priority": fields.get("priority"),
            "assignee": fields.get("assignee"),
            "reporter": fields.get("reporter"),
            "labels": fields.get("labels", []),
            "duedate": fields.get("duedate"),
            "resolutiondate": fields.get("resolutiondate"),
            "updated": fields.get("updated", "2026-09-01T10:00:00.000+0000"),
            "issuetype": {"name": fields.get("issuetype", "Task")},
            "project": {"key": fields.get("project", "LNF")},
            "components": [{"name": c} for c in fields.get("components", [])],
        },
    }
    return base


def _run(workspace_id, base_url, **kwargs):
    db = SessionLocal()
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=workspace_id, source="jira-issues")
    db.add(job)
    db.commit()
    job_uid = job.uid
    db.close()
    run_jira_issue_import(job_uid, workspace_id, base_url, "pat", "project = LNF", **kwargs)
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    result = (job.status, job.error, dict(job.counts or {}))
    db.close()
    return result


def test_imports_issues_with_comments_and_is_idempotent(jira_stub):
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"

    _JiraStub.issues = [
        _issue(f"LNF-{suffix}-1", "Camera offline", "In Progress", "indeterminate",
               priority={"name": "Major"}, assignee={"displayName": "Giulia Bianchi"},
               reporter={"displayName": "Marco Rossi"}, labels=["vacuum"],
               components=["Controls"]),
        _issue(f"LNF-{suffix}-2", "Replace pump", "Closed", "done",
               priority={"name": "Low"}, resolutiondate="2026-08-20T09:00:00.000+0000"),
    ]
    _JiraStub.comments = {
        f"LNF-{suffix}-1": [
            {"id": "1", "author": {"displayName": "Marco Rossi"}, "body": "Looking into it"},
            {"id": "2", "author": "mrossi", "body": "Rebooted"},
        ]
    }

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, counts = _run(ws, base_url)
    assert status == "succeeded", error
    assert counts["tickets"] == 2
    assert counts["comments"] == 2

    db = SessionLocal()
    first = db.get(Issue, f"{ws}:LNF-{suffix}-1")
    assert first.title == "Camera offline"
    assert first.state == "in_progress"
    assert first.priority == "high"
    assert first.assignee == "Giulia Bianchi"
    assert first.created_by == "Marco Rossi"
    assert first.labels == ["vacuum"]
    assert first.attributes["argus_source_key"] == f"LNF-{suffix}-1"
    assert first.attributes["argus_source_url"].endswith(f"/browse/LNF-{suffix}-1")
    assert first.attributes["argus_components"] == ["Controls"]
    # The plain-string author shape, which crashed the asset importer once.
    authors = {c.author for c in db.scalars(
        select(IssueComment).where(IssueComment.issue_uid == first.uid)
    )}
    assert authors == {"Marco Rossi", "mrossi"}

    second = db.get(Issue, f"{ws}:LNF-{suffix}-2")
    assert second.state == "closed"
    assert second.closed_at is not None
    db.close()

    # Re-running must not duplicate comments or tickets.
    status, error, counts = _run(ws, base_url)
    assert status == "succeeded", error
    assert counts["comments"] == 0, "second run should add no new comments"
    db = SessionLocal()
    assert db.scalar(select(Issue).where(Issue.uid == f"{ws}:LNF-{suffix}-1")) is not None
    assert len(db.scalars(select(IssueComment).where(
        IssueComment.issue_uid == f"{ws}:LNF-{suffix}-1")).all()) == 2
    db.close()


def test_pagination_fetches_every_page(jira_stub):
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    # More than one page at the importer's page size.
    _JiraStub.issues = [
        _issue(f"LNF-{suffix}-{n}", f"Issue {n}", "Open", "new") for n in range(250)
    ]
    _JiraStub.comments = {}

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, counts = _run(ws, base_url)
    assert status == "succeeded", error
    assert counts["tickets"] == 250

    db = SessionLocal()
    assert len(db.scalars(select(Issue).where(Issue.workspace_id == ws)).all()) == 250
    db.close()


def test_a_ticket_naming_an_asset_key_is_linked_to_it(jira_stub):
    """What makes having tickets and equipment in one place worth anything:
    "LNFT2-145356 is offline" becomes a real link to that camera."""
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    asset_key = f"LNFT2-{secrets.randbelow(900000) + 100000}"

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.flush()
    db.add(Schema(uid=f"sc-{suffix}", workspace_id=ws, name="Cameras"))
    db.flush()
    db.add(Asset(uid=f"as-{suffix}", workspace_id=ws, schema_uid=f"sc-{suffix}",
                 key=asset_key, name="FI4-B-CAM-VIS-001", type="Cameras"))
    db.commit()
    db.close()

    _JiraStub.issues = [
        _issue(f"LNF-{suffix}-1", f"{asset_key} is offline", "Open", "new",
               description="Seen during the run."),
        # A key-shaped string that matches no asset must not link anything.
        _issue(f"LNF-{suffix}-2", "Unrelated ABC-999 mention", "Open", "new"),
    ]
    _JiraStub.comments = {}

    status, error, counts = _run(ws, base_url)
    assert status == "succeeded", error
    assert counts["asset_links"] == 1

    db = SessionLocal()
    linked = db.get(Issue, f"{ws}:LNF-{suffix}-1")
    assert linked.asset_uid == f"as-{suffix}"
    tickets = db.scalars(select(AssetTicket).where(AssetTicket.asset_uid == f"as-{suffix}")).all()
    assert [t.ticket_key for t in tickets] == [f"LNF-{suffix}-1"]
    assert db.get(Issue, f"{ws}:LNF-{suffix}-2").asset_uid is None
    db.close()


def test_link_assets_can_be_turned_off(jira_stub):
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    asset_key = f"LNFT3-{secrets.randbelow(900000) + 100000}"

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.flush()
    db.add(Schema(uid=f"sc-{suffix}", workspace_id=ws, name="Cameras"))
    db.flush()
    db.add(Asset(uid=f"as-{suffix}", workspace_id=ws, schema_uid=f"sc-{suffix}",
                 key=asset_key, name="Cam", type="Cameras"))
    db.commit()
    db.close()

    _JiraStub.issues = [_issue(f"LNF-{suffix}-1", f"{asset_key} broken", "Open", "new")]
    _JiraStub.comments = {}

    status, error, counts = _run(ws, base_url, link_assets=False)
    assert status == "succeeded", error
    assert counts.get("asset_links", 0) == 0
    db = SessionLocal()
    assert db.get(Issue, f"{ws}:LNF-{suffix}-1").asset_uid is None
    db.close()


def test_a_failing_search_marks_the_job_failed(jira_stub):
    """A broken JQL or a rejected token has to surface, not look like an
    import that found nothing."""
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, _counts = _run(ws, base_url + "/wrong-prefix")
    assert status == "failed"
    # Resolution happens before any search, so the address is blamed by name
    # rather than surfacing a bare 404 from the first query.
    assert "No Jira REST API found" in (error or "")
    assert "context path" in (error or "")


class _ContextPathStub(_JiraStub):
    """Jira Server published under /jira, like issues.infn.it: the site root
    answers, but its REST API is only under the context path."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/jira/"):
            self.send_response(404)
            self.end_headers()
            return
        self.path = self.path[len("/jira"):]
        super().do_GET()


@pytest.fixture()
def context_path_stub():
    server = HTTPServer(("127.0.0.1", 0), _ContextPathStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_context_path_is_found_rather_than_404ing(context_path_stub):
    """The first real import failed exactly this way: the server URL was the
    site root, the REST API lives under /jira, and Jira answered 404 without
    saying why."""
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    _ContextPathStub.issues = [_issue(f"LNF-{suffix}-1", "Works anyway", "Open", "new")]
    _ContextPathStub.comments = {}

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, counts = _run(ws, context_path_stub)
    assert status == "succeeded", error
    assert counts["tickets"] == 1

    db = SessionLocal()
    issue = db.get(Issue, f"{ws}:LNF-{suffix}-1")
    # The stored link has to use the resolved base, or it points nowhere.
    assert "/jira/browse/" in issue.attributes["argus_source_url"]
    db.close()


def test_an_unreachable_api_says_what_was_tried():
    """Better than "404 Not Found for url ..." — name the addresses tried and
    the usual cause."""
    from app.services.jira_issue_import import resolve_api_base
    from app.services.jira_import import _TimeoutSession

    with pytest.raises(RuntimeError, match="context path"):
        resolve_api_base(_TimeoutSession(), "http://127.0.0.1:1/nothing-here")


def _rich_issue(key, suffix):
    """An issue carrying everything the standard Jira view shows."""
    base = _issue(key, "BTF template per olog nuova infrastruttura", "To Do", "new",
                  priority={"name": "Major"}, issuetype="Task",
                  reporter={"displayName": "Andrea Michelotti"},
                  assignee={"displayName": "Giovanni Lorenzo Napoleoni"},
                  labels=["BTF"], components=["Olog"],
                  description="https://btf-olog.k8sda.lnf.infn.it/Olog")
    base["fields"].update({
        "resolution": None,
        "fixVersions": [],
        "versions": [{"name": "2026.1"}],
        "votes": {"votes": 0},
        "watches": {"watchCount": 1},
        "environment": "BTF hall",
        "parent": {"key": f"LNFDCS-{suffix}-epic"},
        "timespent": 3600,
        "timeoriginalestimate": 7200,
        "created": "2026-01-08T11:41:00.000+0100",
    })
    return base


def test_standard_jira_fields_are_captured(jira_stub):
    """The mockup's issue view, field by field — anything not captured here
    simply cannot be rendered later."""
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    key = f"LNFDCS-{suffix}"
    _JiraStub.issues = [_rich_issue(key, suffix)]
    _JiraStub.comments = {}

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, _counts = _run(ws, base_url)
    assert status == "succeeded", error

    db = SessionLocal()
    a = db.get(Issue, f"{ws}:{key}").attributes
    assert a["argus_source_key"] == key
    assert a["argus_source_url"].endswith(f"/browse/{key}")
    assert a["argus_project"] == "LNF"
    assert a["argus_source_status"] == "To Do"
    assert a["argus_source_type"] == "Task"
    # Jira reports no resolution as null; a list cell saying "Unresolved" is
    # more use than an empty one.
    assert a["argus_resolution"] == "Unresolved"
    assert a["argus_components"] == ["Olog"]
    assert a["argus_affects_versions"] == ["2026.1"]
    assert a["argus_fix_versions"] == []
    assert a["argus_reporter"] == "Andrea Michelotti"
    assert a["argus_votes"] == 0
    assert a["argus_watchers"] == 1
    assert a["argus_environment"] == "BTF hall"
    assert a["argus_parent"] == f"LNFDCS-{suffix}-epic"
    assert a["argus_time_spent"] == 3600
    assert a["argus_time_estimate"] == 7200
    assert a["argus_source_created"].startswith("2026-01-08")
    db.close()


def test_a_ticket_type_is_created_per_jira_issue_type(jira_stub):
    """Imported issues get a real ticket type, so their fields render and
    sort through the machinery every other type uses."""
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    _JiraStub.issues = [
        _issue(f"LNF-{suffix}-1", "A task", "Open", "new", issuetype="Task"),
        _issue(f"LNF-{suffix}-2", "An incident", "Open", "new", issuetype="Incident"),
        _issue(f"LNF-{suffix}-3", "Another task", "Open", "new", issuetype="Task"),
    ]
    _JiraStub.comments = {}

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, _counts = _run(ws, base_url)
    assert status == "succeeded", error

    db = SessionLocal()
    base = db.get(Schema, f"{ws}:argus-ticket")
    assert base is not None and base.applies_to == "tickets"
    assert base.is_concrete is False
    assert {a["key"] for a in base.attributes} >= {
        "argus_source_key", "argus_resolution", "argus_components", "argus_watchers",
    }

    children = db.scalars(
        select(Schema).where(Schema.parent_schema_uid == base.uid)
    ).all()
    from app.services.ticket_types import DEFAULT_ISSUE_TYPES
    # The workspace's own kinds (core-facility), and the one the data named that it lacked: nothing else.
    assert {c.name for c in children} == set(DEFAULT_ISSUE_TYPES) | {"Incident"}, "only types actually present"
    # Fields come from the parent, so a child adds none of its own.
    assert all(c.attributes == [] for c in children)

    task_uid = next(c.uid for c in children if c.name == "Task")
    assert db.get(Issue, f"{ws}:LNF-{suffix}-1").schema_uid == task_uid
    assert db.get(Issue, f"{ws}:LNF-{suffix}-3").schema_uid == task_uid
    incident_uid = next(c.uid for c in children if c.name == "Incident")
    assert db.get(Issue, f"{ws}:LNF-{suffix}-2").schema_uid == incident_uid
    db.close()


def test_a_reimport_moves_legacy_keys_onto_the_argus_ones(jira_stub):
    """Tickets imported before the model became ARGUS's own hold their
    values under Jira-era keys. A re-run has to move them, not leave two
    spellings of the same field side by side."""
    _server, base_url = jira_stub
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    key = f"LNFDCS-{suffix}"
    _JiraStub.issues = [_issue(key, "Camera offline", "Open", "new", issuetype="Task")]
    _JiraStub.comments = {}

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.flush()
    db.add(Issue(
        uid=f"{ws}:{key}", workspace_id=ws, title="Camera offline", state="new",
        attributes={
            "jiraKey": key, "jiraUrl": "http://old/browse/" + key,
            "jiraProject": "LNFDCS", "jiraStatus": "Open",
            "jiraIssueType": "Task", "jiraComponents": ["Olog"],
            # Something a person added by hand must survive.
            "local_note": "keep me",
        },
    ))
    db.commit()
    db.close()

    status, error, _counts = _run(ws, base_url)
    assert status == "succeeded", error

    db = SessionLocal()
    a = db.get(Issue, f"{ws}:{key}").attributes
    assert not any(k.startswith("jira") for k in a)
    assert a["argus_source_key"] == key
    assert a["argus_source"] == "jira"
    assert a["local_note"] == "keep me"
    db.close()
