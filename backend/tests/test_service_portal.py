"""The service portal of a site (docs/service-portal.md): catalogue and routing, one ticket per submission, the
requester's own view of it, and the staff's existing ticket pages with public replies and internal notes."""
import asyncio
import io
import secrets
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.datastructures import Headers, UploadFile

from app.auth import OidcIdentity
from app.db import SessionLocal
from app.models.attachment import Attachment
from app.models.group import Group, GroupMember
from app.models.issue import Issue, IssueComment
from app.models.role import RoleBinding
from app.models.schema import Schema
from app.models.service_portal import SupportRequest
from app.models.user import User
from app.models.workflow import Notification
from app.models.workspace import SiteAdministrator, Workspace
from app.routers import issues as issues_router
from app.routers import service_portal as r
from app.schemas.issue import IssueCommentCreate, IssueUpdate
from app.services import notify
from app.services.roles import ensure_system_roles


def _bind(db, ws, user_or_group, role, kind="user"):
    db.add(RoleBinding(workspace_id=ws, subject_type=kind, subject_id=user_or_group, role_id=role,
                       created_at=datetime.now(timezone.utc)))


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    from app.services import service_portal as portal_service
    monkeypatch.setattr(portal_service, "ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(issues_router, "ATTACHMENTS_DIR", str(tmp_path))
    t = secrets.token_hex(4)
    db = SessionLocal()
    ensure_system_roles(db)
    ids = {"site": f"lnf-{t}", "sparc": f"sparc-{t}", "it": f"lnfit-{t}", "other_site": f"lnl-{t}",
           "elsewhere": f"else-{t}"}
    db.add_all([Workspace(id=ids["site"], name="LNF", role="site"),
                Workspace(id=ids["other_site"], name="LNL", role="site")])
    db.flush()
    db.add_all([Workspace(id=ids["sparc"], name="SPARC", site_id=ids["site"]),
                Workspace(id=ids["it"], name="LNF IT", site_id=ids["site"]),
                Workspace(id=ids["elsewhere"], name="Elsewhere")])
    people = {n: User(id=f"{n}-{t}", email=f"{n}-{t}@infn.it", name=n.title(), active=True)
              for n in ("requester", "other_requester", "agent", "site_admin", "it_owner", "outsider", "lnl_user")}
    db.add_all(people.values())
    db.flush()
    db.add(SiteAdministrator(site_id=ids["site"], user_id=people["site_admin"].id))
    team = Group(uid=f"net-{t}", name=f"Network team {t}", source="local", active=True)
    desk = Group(uid=f"desk-{t}", name=f"Service desk {t}", source="local", active=True)
    db.add_all([team, desk])
    db.flush()
    db.add(GroupMember(group_uid=team.uid, user_id=people["agent"].id, source="local"))
    db.add(GroupMember(group_uid=desk.uid, user_id=people["agent"].id, source="local"))
    _bind(db, ids["sparc"], people["requester"].id, "viewer")
    _bind(db, ids["sparc"], people["other_requester"].id, "viewer")
    _bind(db, ids["other_site"], people["lnl_user"].id, "viewer")
    _bind(db, ids["it"], people["it_owner"].id, "owner")
    _bind(db, ids["it"], team.uid, "agent", "group")
    _bind(db, ids["it"], desk.uid, "agent", "group")
    schema = Schema(uid=f"net-incident-{t}", name="Network incident", applies_to="tickets", workspace_id=ids["it"],
                    attributes=[{"key": "building", "name": "Building", "type": "text"},
                                {"key": "impact", "name": "Impact", "type": "enumeration",
                                 "options": [{"value": "one", "label": "Just me"}, {"value": "many", "label": "Many"}]},
                                {"key": "internal_cost", "name": "Internal cost", "type": "text"}])
    db.add(schema)
    db.commit()
    lab = {"db": db, "ids": ids, "people": people, "team": team, "desk": desk, "schema": schema, "t": t}
    yield lab
    db.rollback()
    from app.ledger.audit import allow_purge
    for w in ("sparc", "it", "elsewhere", "site", "other_site"):
        ws = db.get(Workspace, ids[w])
        if ws is not None:
            allow_purge(db)
            db.delete(ws)
            db.commit()
    db.close()


def as_(lab, who):
    return OidcIdentity(user=lab["db"].get(User, lab["people"][who].id))


def build_portal(lab, open_=True):
    """A site with a helpdesk and a network service, both published by the IT workspace's owner."""
    db, ids, site = lab["db"], lab["ids"], lab["ids"]["site"]
    admin = as_(lab, "site_admin")
    desk = r.create_service(site, r.PortalServiceIn(name="Service desk", category="General", provider_workspace_id=ids["it"],
                                              team_group_uid=lab["desk"].uid), identity=admin, db=db)
    desk = r.create_request_type(site, desk["uid"], r.PortalRequestTypeIn(name="Ask the service desk"), identity=admin, db=db)
    net = r.create_service(site, r.PortalServiceIn(name="Network & connectivity", category="IT",
                                             description="Wi-Fi, VPN, network ports", provider_workspace_id=ids["it"],
                                             team_group_uid=lab["team"].uid), identity=admin, db=db)
    net = r.create_request_type(site, net["uid"], r.PortalRequestTypeIn(
        name="Wi-Fi or network problem", schema_uid=lab["schema"].uid, guidance="Check the cable first.",
        fields=[r.PortalFieldIn(key="building", label="Building", required=True), r.PortalFieldIn(key="impact")]),
        identity=admin, db=db)
    owner = as_(lab, "it_owner")
    for svc in (desk, net):
        r.authorize_service(site, svc["uid"], identity=owner, db=db)
        r.publish_service(site, svc["uid"], identity=admin, db=db)
    if open_:
        r.put_service_desk_settings(site, r.PortalSettingsIn(enabled=True, emergency="Call 112",
                                                       helpdesk_request_type_uid=desk["request_types"][0]["uid"]),
                                    identity=admin, db=db)
    return {"desk": desk, "net": net, "net_type": net["request_types"][0]["uid"],
            "desk_type": desk["request_types"][0]["uid"]}


def send(lab, who="requester", rt=None, submission=None, files=(), **extra):
    payload = {"submission_uid": submission or secrets.token_hex(6), "request_type_uid": rt,
               "origin_workspace_id": lab["ids"]["sparc"], "title": "No network in room 12",
               "description": "The port does not light up.", "fields": {}}
    payload.update(extra)
    import json
    uploads = [UploadFile(file=io.BytesIO(data), filename=name, headers=Headers({"content-type": "text/plain"}))
               for name, data in files]
    resp = asyncio.run(r.submit_request(lab["ids"]["site"], None, payload=json.dumps(payload), files=uploads,
                                        identity=as_(lab, who), db=lab["db"]))
    import json as j
    return resp.status_code, j.loads(resp.body)


def status_code(fn, *a, **k):
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code, (e.detail.get("code") if isinstance(e.detail, dict) else e.detail)
    return None


# --------------------------------------------------------------------------- catalogue and routing

def test_the_sites_facility_members_see_its_catalogue_and_others_do_not(lab):
    db, site = lab["db"], lab["ids"]["site"]
    build_portal(lab)
    mine = r.my_portal_sites(identity=as_(lab, "requester"), db=db)
    assert [s["id"] for s in mine] == [site] and mine[0]["origins"] == [{"id": lab["ids"]["sparc"], "name": "SPARC"}]
    cat = r.site_catalogue(site, identity=as_(lab, "requester"), db=db)
    names = [s["name"] for c in cat["categories"] for s in c["services"]]
    assert sorted(names) == ["Network & connectivity", "Service desk"] and cat["helpdesk"] and cat["emergency"] == "Call 112"
    assert r.my_portal_sites(identity=as_(lab, "lnl_user"), db=db) == []
    assert status_code(r.site_catalogue, site, identity=as_(lab, "lnl_user"), db=db) == (404, "not_found")
    assert status_code(r.site_catalogue, site, identity=as_(lab, "outsider"), db=db) == (404, "not_found")


def test_a_form_shows_only_the_fields_chosen_for_requesters(lab):
    p = build_portal(lab)
    form = r.request_type_form(lab["ids"]["site"], p["net_type"], identity=as_(lab, "requester"), db=lab["db"])
    assert [f["key"] for f in form["fields"]] == ["building", "impact"]
    assert form["fields"][1]["options"] == [{"value": "one", "label": "Just me"}, {"value": "many", "label": "Many"}]
    assert form["guidance"] == "Check the cable first." and form["service"]["name"] == "Network & connectivity"


def test_routing_is_the_request_types_service_and_im_not_sure_is_the_helpdesk(lab):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    chosen = r.route_preview(site, r.PortalPreviewIn(request_type_uid=p["net_type"]), identity=as_(lab, "requester"), db=db)
    assert chosen["service_name"] == "Network & connectivity" and chosen["team_name"] == lab["team"].name
    assert chosen["provider_name"] == "LNF IT" and not chosen["helpdesk"]
    unsure = r.route_preview(site, r.PortalPreviewIn(request_type_uid=None), identity=as_(lab, "requester"), db=db)
    assert unsure["helpdesk"] and unsure["team_name"] == lab["desk"].name
    assert "provider_workspace_id" not in chosen and "team_group_uid" not in chosen


def test_publishing_needs_the_destinations_owner_and_a_team_that_can_work_tickets_there(lab):
    db, site, ids = lab["db"], lab["ids"]["site"], lab["ids"]
    admin = as_(lab, "site_admin")
    svc = r.create_service(site, r.PortalServiceIn(name="Facilities", provider_workspace_id=ids["it"],
                                             team_group_uid=lab["team"].uid), identity=admin, db=db)
    r.create_request_type(site, svc["uid"], r.PortalRequestTypeIn(name="Heating"), identity=admin, db=db)
    # The site administrator manages access, but does not own the IT workspace.
    assert status_code(r.publish_service, site, svc["uid"], identity=admin, db=db) == (403, "destination_authority")
    lazy = Group(uid=f"lazy-{lab['t']}", name="Nobody's team", source="local", active=True)
    db.add(lazy)
    db.commit()
    r.update_service(site, svc["uid"], r.PortalServiceIn(name="Facilities", provider_workspace_id=ids["it"],
                                                   team_group_uid=lazy.uid), identity=admin, db=db)
    r.authorize_service(site, svc["uid"], identity=as_(lab, "it_owner"), db=db)
    assert status_code(r.authorize_service, site, svc["uid"], identity=admin, db=db) == (403, "destination_authority")
    with pytest.raises(HTTPException) as e:
        r.publish_service(site, svc["uid"], identity=admin, db=db)
    assert e.value.detail["code"] == "not_publishable" and "no role" in " ".join(e.value.detail["problems"])
    assert status_code(r.create_service, site, r.PortalServiceIn(name="Away", provider_workspace_id=ids["elsewhere"],
                                                           team_group_uid=lab["team"].uid),
                       identity=admin, db=db) == (422, "destination")
    assert status_code(r.get_service_desk, site, identity=as_(lab, "requester"), db=db) == (403, "forbidden")


def test_the_portal_does_not_open_without_a_helpdesk(lab):
    db, site = lab["db"], lab["ids"]["site"]
    build_portal(lab, open_=False)
    assert status_code(r.put_service_desk_settings, site, r.PortalSettingsIn(enabled=True), identity=as_(lab, "site_admin"),
                       db=db) == (422, "helpdesk_required")


def test_a_destination_that_stops_being_valid_is_refused_not_rerouted(lab):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    lab["team"].active = False
    db.commit()
    with pytest.raises(HTTPException) as e:
        r.route_preview(site, r.PortalPreviewIn(request_type_uid=p["net_type"]), identity=as_(lab, "requester"), db=db)
    assert e.value.status_code == 409 and e.value.detail["code"] == "service_unavailable"
    assert e.value.detail["fallback"]["helpdesk"], "the helpdesk is offered, not chosen silently"
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], fields={"building": "B1"})
    assert e.value.detail["code"] == "service_unavailable"
    assert db.scalar(select(SupportRequest).where(SupportRequest.requester_id == lab["people"]["requester"].id)) is None


# --------------------------------------------------------------------------- submitting

def test_one_submission_is_one_ticket_in_the_teams_queue_and_a_retry_returns_it(lab):
    db = lab["db"]
    p = build_portal(lab)
    sub = secrets.token_hex(6)
    code, first = send(lab, rt=p["net_type"], submission=sub, fields={"building": "B1", "impact": "many"},
                       files=[("trace.txt", b"ping: timeout")])
    assert code == 201 and first["created"] and first["key"]
    code, again = send(lab, rt=p["net_type"], submission=sub, fields={"building": "B1", "impact": "many"},
                       files=[("trace.txt", b"ping: timeout")])
    assert code == 200 and not again["created"] and again["uid"] == first["uid"]
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], submission=sub, title="Something else", fields={"building": "B1"})
    assert e.value.detail["code"] == "idempotency_mismatch"
    request = db.get(SupportRequest, first["uid"])
    issue = db.get(Issue, request.issue_uid)
    assert db.scalar(select(SupportRequest).where(SupportRequest.submission_uid == sub)) is request
    assert issue.workspace_id == lab["ids"]["it"] and issue.assigned_group_uid == lab["team"].uid
    assert issue.assignee is None and issue.state == "new" and issue.created_by == lab["people"]["requester"].id
    assert issue.attributes["building"] == "B1" and issue.schema_uid == lab["schema"].uid
    assert request.submitted == [{"key": "building", "label": "Building", "value": "B1"},
                                 {"key": "impact", "label": "Impact", "value": "Many"}]
    files = db.scalars(select(Attachment).where(Attachment.issue_uid == issue.uid)).all()
    assert [(f.filename, f.audience) for f in files] == [("trace.txt", "requester")]
    queued = db.scalars(select(Notification).where(Notification.issue_uid == issue.uid,
                                                   Notification.kind == "queued")).all()
    assert [n.recipient for n in queued] == [lab["people"]["agent"].id]
    assert notify.watchers(db, issue) == [], "the requester is not a watcher of the ticket"


def test_a_requester_cannot_set_internal_fields_or_send_from_a_workspace_not_theirs(lab):
    p = build_portal(lab)
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], fields={"building": "B1", "internal_cost": "1000"})
    assert e.value.detail["code"] == "field_not_allowed"
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], fields={})
    assert e.value.detail["code"] == "field_required"
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], fields={"building": "B1"}, origin_workspace_id=lab["ids"]["it"])
    assert e.value.detail["code"] == "origin"
    # Forged routing fields are not read at all: the server decides.
    code, body = send(lab, rt=p["net_type"], fields={"building": "B1"}, assignee="mallory",
                      provider_workspace_id=lab["ids"]["elsewhere"], team_group_uid="x")
    issue = lab["db"].get(Issue, lab["db"].get(SupportRequest, body["uid"]).issue_uid)
    assert issue.workspace_id == lab["ids"]["it"] and issue.assignee is None


def test_a_changed_route_after_the_review_asks_for_a_new_review(lab):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    seen = r.route_preview(site, r.PortalPreviewIn(request_type_uid=p["net_type"]), identity=as_(lab, "requester"), db=db)
    r.update_service(site, p["net"]["uid"], r.PortalServiceIn(name="Network", provider_workspace_id=lab["ids"]["it"],
                                                         team_group_uid=lab["desk"].uid),
                     identity=as_(lab, "site_admin"), db=db)
    with pytest.raises(HTTPException) as e:
        send(lab, rt=p["net_type"], fields={"building": "B1"}, route_version=seen["version"])
    assert e.value.status_code == 409 and e.value.detail["code"] == "route_changed"


# --------------------------------------------------------------------------- the requester's view

def _ticket(lab, p, who="requester"):
    _, body = send(lab, who=who, rt=p["net_type"], fields={"building": "B1"})
    return body["uid"], lab["db"].get(SupportRequest, body["uid"]).issue_uid


def test_requesters_see_only_their_own_requests_and_no_ticket_rights_come_with_them(lab):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    mine, issue_uid = _ticket(lab, p)
    theirs, _ = _ticket(lab, p, who="other_requester")
    assert [x["uid"] for x in r.list_my_requests(site, identity=as_(lab, "requester"), db=db)] == [mine]
    assert status_code(r.get_my_request, site, theirs, identity=as_(lab, "requester"), db=db) == (404, "not_found")
    assert status_code(r.reply_to_my_request, site, theirs, r.PortalReplyIn(body="hi"), identity=as_(lab, "requester"),
                       db=db) == (404, "not_found")
    assert status_code(r.get_my_request, lab["ids"]["other_site"], mine, identity=as_(lab, "requester"),
                       db=db) == (404, "not_found")
    from app.services.permissions import resolve_permission
    assert not resolve_permission(db, lab["people"]["requester"], lab["ids"]["it"], "read", "tickets")


def test_internal_notes_and_files_stay_internal_and_public_replies_reach_the_requester(lab, tmp_path):
    db, site, it = lab["db"], lab["ids"]["site"], lab["ids"]["it"]
    p = build_portal(lab)
    mine, issue_uid = _ticket(lab, p)
    agent = lab["people"]["agent"].id
    requester = lab["people"]["requester"]
    issues_router.create_issue_comment(issue_uid, IssueCommentCreate(
        uid=f"n-{lab['t']}", body=f"Internal: router is ours @{requester.email}"), workspace_id=it,
        current_user_id=agent, db=db)
    issues_router.create_issue_comment(issue_uid, IssueCommentCreate(
        uid=f"p-{lab['t']}", body="We are on our way.", audience="requester"), workspace_id=it,
        current_user_id=agent, db=db)
    asyncio.run(issues_router.upload_issue_attachment(issue_uid, UploadFile(file=io.BytesIO(b"secret"),
                                                                             filename="internal.log"),
                                                      audience="internal", workspace_id=it, current_user_id=agent,
                                                      db=db))
    public = asyncio.run(issues_router.upload_issue_attachment(issue_uid, UploadFile(file=io.BytesIO(b"steps"),
                                                                                      filename="howto.pdf"),
                                                               audience="requester", workspace_id=it,
                                                               current_user_id=agent, db=db))
    view = r.get_my_request(site, mine, identity=as_(lab, "requester"), db=db)
    assert [c["body"] for c in view["conversation"]] == ["We are on our way."]
    assert view["conversation"][0]["author_name"] == "Agent"
    assert sorted(a["filename"] for a in view["attachments"]) == ["howto.pdf"]
    hidden = db.scalar(select(Attachment).where(Attachment.issue_uid == issue_uid,
                                                Attachment.filename == "internal.log"))
    assert status_code(r.download_my_request_file, site, mine, hidden.uid, identity=as_(lab, "requester"),
                       db=db) == (404, "not_found")
    assert r.download_my_request_file(site, mine, public.uid, identity=as_(lab, "requester"), db=db).path
    told = db.scalars(select(Notification).where(Notification.issue_uid == issue_uid,
                                                 Notification.recipient.in_([requester.id, requester.email]))).all()
    assert {n.kind for n in told} == {"request_reply"}, "mentioned in an internal note, told nothing of it"
    assert all(n.detail.get("path") == f"/support/{site}/requests/{mine}" for n in told)
    assert all("router" not in (n.detail.get("excerpt") or "") for n in told)
    assert notify.notification_link(told[0]) is None or "ws=" not in notify.notification_link(told[0])
    with pytest.raises(Exception):
        IssueCommentCreate(uid=f"x-{lab['t']}", body="x", audience="everyone")


def test_a_ticket_not_from_the_portal_takes_no_public_reply(lab):
    db, it = lab["db"], lab["ids"]["it"]
    issue = Issue(uid=f"plain-{lab['t']}", workspace_id=it, title="Plain", state="new", attributes={}, labels=[])
    db.add(issue)
    db.commit()
    with pytest.raises(HTTPException) as e:
        issues_router.create_issue_comment(issue.uid, IssueCommentCreate(uid=f"d-{lab['t']}", body="hi",
                                                                         audience="requester"),
                                           workspace_id=it, current_user_id=None, db=db)
    assert e.value.detail["code"] == "no_requester"
    assert db.get(IssueComment, f"d-{lab['t']}") is None


def test_status_follows_the_workflow_and_a_resolved_request_can_be_reopened(lab):
    db, site, it = lab["db"], lab["ids"]["site"], lab["ids"]["it"]
    p = build_portal(lab)
    mine, issue_uid = _ticket(lab, p)
    agent = lab["people"]["agent"].id
    issues_router.update_issue(issue_uid, IssueUpdate(state="in_progress"), workspace_id=it, current_user_id=agent,
                               db=db, if_match=None, x_argus_client=None)
    assert r.get_my_request(site, mine, identity=as_(lab, "requester"), db=db)["status"]["label"] == "In progress"
    issues_router.transition_issue(issue_uid, issues_router.TransitionIn(to="resolved", resolution="Fixed"),
                                   workspace_id=it, identity=as_(lab, "agent"), current_user_id=agent, db=db,
                                   if_match=None, x_argus_client=None)
    view = r.get_my_request(site, mine, identity=as_(lab, "requester"), db=db)
    assert view["status"] == {"category": "done", "label": "Resolved"} and view["resolution"] == "Fixed"
    assert view["can_reopen"]
    kinds = [n.kind for n in db.scalars(select(Notification).where(
        Notification.issue_uid == issue_uid, Notification.recipient == lab["people"]["requester"].id))]
    assert kinds == ["request_status", "request_resolved"]
    after = r.reopen_my_request(site, mine, r.PortalReopenIn(body="Still broken"), identity=as_(lab, "requester"), db=db)
    assert after["status"]["category"] != "done"
    assert after["conversation"][-1]["body"] == "Still broken" and after["conversation"][-1]["mine"]


def test_staff_filter_by_service_and_team_and_reroute_within_the_workspace_only(lab):
    db, site, it = lab["db"], lab["ids"]["site"], lab["ids"]["it"]
    p = build_portal(lab)
    _, issue_uid = _ticket(lab, p)
    found = issues_router.list_issues(service_uid=p["net"]["uid"], assigned_group_uid=None, mine=False,
                                      workspace_id=it, current_user_id=None, db=db)
    assert [i.uid for i in found] == [issue_uid]
    assert issues_router.list_issues(service_uid=None, assigned_group_uid=lab["desk"].uid, mine=False,
                                     workspace_id=it, current_user_id=None, db=db) == []
    moved = issues_router.update_issue(issue_uid, IssueUpdate(service_uid=p["desk"]["uid"]), workspace_id=it,
                                       current_user_id=lab["people"]["agent"].id, db=db, if_match=None,
                                       x_argus_client=None)
    assert moved.service_uid == p["desk"]["uid"] and moved.assigned_group_uid == lab["desk"].uid
    info = issues_router.get_service_request(issue_uid, workspace_id=it, db=db)
    assert info["service"]["name"] == "Service desk" and info["requester"]["email"] == lab["people"]["requester"].email
    other = r.create_service(site, r.PortalServiceIn(name="SPARC ops", provider_workspace_id=lab["ids"]["sparc"],
                                               team_group_uid=lab["team"].uid), identity=as_(lab, "site_admin"), db=db)
    assert status_code(issues_router.update_issue, issue_uid, IssueUpdate(service_uid=other["uid"]), workspace_id=it,
                       current_user_id=None, db=db, if_match=None, x_argus_client=None) == (422, "reroute")


def test_a_retired_service_keeps_its_requests_visible(lab):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    mine, _ = _ticket(lab, p)
    r.unpublish_service(site, p["net"]["uid"], identity=as_(lab, "site_admin"), db=db)
    assert [x["uid"] for x in r.list_my_requests(site, identity=as_(lab, "requester"), db=db)] == [mine]
    assert r.get_my_request(site, mine, identity=as_(lab, "requester"), db=db)["service_name"] == \
        "Network & connectivity"


def test_assistance_makes_no_model_call_when_ai_is_off(lab, monkeypatch):
    db, site = lab["db"], lab["ids"]["site"]
    p = build_portal(lab)
    r.put_service_desk_settings(site, r.PortalSettingsIn(enabled=True, assistance=True,
                                                   helpdesk_request_type_uid=p["desk_type"]),
                                identity=as_(lab, "site_admin"), db=db)
    from app.models.llm_config import LLMConfig
    from app.services import llm
    # The requester's workspace switched AI off, whatever the installation's default (other tests may set one,
    # checked and enabled): an explicit disable stays a disable.
    db.add(LLMConfig(workspace_id=lab["ids"]["sparc"], base_url="http://model.invalid", model="m", enabled=False,
                     last_check_ok=True))
    db.commit()
    monkeypatch.setattr(llm, "complete_structured", lambda *a, **k: pytest.fail("no model call with AI off"))
    out = r.assist(site, r.PortalAssistIn(text="wifi network down in building B", origin_workspace_id=lab["ids"]["sparc"],
                                    use_ai=True), identity=as_(lab, "requester"), db=db)
    assert out["ai"] is None and out["ai_available"] is False and isinstance(out["articles"], list)


def test_knowledge_suggestions_come_from_the_requesters_own_readable_published_documents(lab):
    from app.models.document import Document, DocumentRevision
    db, site, t = lab["db"], lab["ids"]["site"], lab["t"]
    p = build_portal(lab)
    r.put_service_desk_settings(site, r.PortalSettingsIn(enabled=True, assistance=True,
                                                   helpdesk_request_type_uid=p["desk_type"]),
                                identity=as_(lab, "site_admin"), db=db)
    now = datetime.now(timezone.utc)
    for code, ws, conf in (("pub", "sparc", "interno"), ("secret", "sparc", "riservato"), ("it", "it", "interno")):
        doc = Document(uid=f"{code}-{t}", code=f"D-{code}-{t}", title=f"Wireless network troubleshooting {code}",
                       workspace_id=lab["ids"][ws], confidentiality=conf)
        db.add(doc)
        db.flush()
        rev = DocumentRevision(uid=f"{code}-r-{t}", document_uid=doc.uid, revision_number=1, state="published",
                               body_markdown="Restart the wireless adapter.", published_at=now)
        db.add(rev)
        db.flush()
        doc.current_revision_uid = rev.uid
    db.commit()
    out = r.assist(site, r.PortalAssistIn(text="wireless network is down", origin_workspace_id=lab["ids"]["sparc"]),
                   identity=as_(lab, "requester"), db=db)
    assert [a["uid"] for a in out["articles"]] == [f"pub-{t}"]


def test_first_help_comes_from_articles_the_requester_may_read_in_the_services_workspaces(lab, monkeypatch):
    from app.models.document import Document, DocumentRevision
    from app.models.llm_config import LLMConfig
    from app.services import llm
    db, site, t = lab["db"], lab["ids"]["site"], lab["t"]
    p = build_portal(lab)
    r.put_service_desk_settings(site, r.PortalSettingsIn(enabled=True, assistance=True,
                                                   helpdesk_request_type_uid=p["desk_type"]),
                                identity=as_(lab, "site_admin"), db=db)
    now = datetime.now(timezone.utc)
    doc = Document(uid=f"kb-{t}", code=f"D-kb-{t}", title="Network port not working", workspace_id=lab["ids"]["it"],
                   confidentiality="interno")
    db.add(doc)
    db.flush()
    rev = DocumentRevision(uid=f"kb-r-{t}", document_uid=doc.uid, revision_number=1, state="published",
                           published_at=now, body_markdown="# Intro\n\nWho to call.\n\nIf the network port light is "
                                                           "off, try the other wall socket.")
    db.add(rev)
    db.flush()
    doc.current_revision_uid = rev.uid
    db.add(LLMConfig(workspace_id=lab["ids"]["sparc"], base_url="http://model.invalid", model="m", enabled=True,
                     last_check_ok=True))
    db.commit()
    seen = []

    def model(endpoint, system, prompt, **kw):
        seen.append(prompt)
        return ('{"first_help": ["Try the other wall socket."], "sources": ["A"], "choice": 1, "why": "Network.", '
                '"title": "Network port down", "summary": "The port light is off."}')
    monkeypatch.setattr(llm, "complete_structured", model)
    ask = r.PortalAssistIn(text="the network port light is off", origin_workspace_id=lab["ids"]["sparc"], use_ai=True)

    # The IT workspace's articles are not the requester's to read: not searched, not shown to the model.
    out = r.assist(site, ask, identity=as_(lab, "requester"), db=db)
    assert out["articles"] == [] and out["ai"]["first_help"] == [] and "other wall socket" not in seen[-1]

    _bind(db, lab["ids"]["it"], lab["people"]["requester"].id, "viewer")
    db.commit()
    out = r.assist(site, ask, identity=as_(lab, "requester"), db=db)
    assert [a["uid"] for a in out["articles"]] == [doc.uid] and "_passages" not in out["articles"][0]
    assert "other wall socket" in seen[-1] and "Who to call" not in seen[-1]
    assert out["ai"]["first_help"] == ["Try the other wall socket."]
    assert out["ai"]["sources"] == [{"uid": doc.uid, "code": doc.code, "title": doc.title,
                                     "workspace_id": lab["ids"]["it"]}]


def test_robot_tokens_and_workspace_bound_personal_tokens_have_no_portal(lab):
    from app.auth import PatIdentity, TokenScope
    db, site = lab["db"], lab["ids"]["site"]
    build_portal(lab)
    robot = PatIdentity(workspace_id=lab["ids"]["sparc"])
    assert status_code(r.my_portal_sites, identity=robot, db=db) == (403, "sign_in_required")
    user = lab["people"]["requester"]
    bound = OidcIdentity(user=user, token=TokenScope(kind="personal", workspace_id=lab["ids"]["sparc"]))
    assert status_code(r.site_catalogue, site, identity=bound, db=db) == (403, "token_scope")
    read_only = OidcIdentity(user=user, token=TokenScope(kind="personal", scopes=frozenset({"read"})))
    assert r.site_catalogue(site, identity=read_only, db=db)["site"]["id"] == site
    with pytest.raises(HTTPException) as e:
        asyncio.run(r.submit_request(site, None, payload="{}", files=[], identity=read_only, db=db))
    assert e.value.detail["code"] == "token_scope"


def test_a_token_kept_to_one_workspace_cannot_administer_the_site_and_says_so(lab):
    from app.auth import TokenScope
    db, site = lab["db"], lab["ids"]["site"]
    admin = db.get(User, lab["people"]["site_admin"].id)
    bound = OidcIdentity(user=admin, token=TokenScope(kind="personal", workspace_id=lab["ids"]["sparc"]))
    with pytest.raises(HTTPException) as e:
        r.create_service(site, r.PortalServiceIn(name="X", provider_workspace_id=lab["ids"]["it"],
                                                 team_group_uid=lab["team"].uid), identity=bound, db=db)
    assert e.value.status_code == 403 and "kept to one workspace" in str(e.value.detail)


def test_ask_argus_proposes_a_help_centre_service_and_only_a_site_administrator_applies_it(lab):
    from app.models.ask_conversation import AskConversation
    from app.models.service_portal import ServiceOffering, ServiceRequestType
    from app.services import ask_actions
    db, ids, t = lab["db"], lab["ids"], lab["t"]
    convo = AskConversation(id=f"c-{t}", workspace_id=ids["sparc"], owner=lab["people"]["site_admin"].id, title="x")
    db.add(convo)
    db.commit()
    propose = ask_actions.Proposer(db, ids["sparc"], convo.id, 1)
    args = {"site": "LNF", "name": "Network & connectivity", "category": "IT", "destination": "LNF IT",
            "team": lab["team"].name, "request_types": [{"name": "Wi-Fi problem", "ticket_type": "Network incident",
                                                         "fields": [{"key": "building", "required": True}]}]}
    with pytest.raises(ask_actions.Refused) as e:
        propose("propose_help_centre_service", {**args, "team": "Nobody"})
    assert lab["team"].name in str(e.value), "a wrong name is refused with the valid choices"
    with pytest.raises(ask_actions.Refused) as e:
        propose("propose_help_centre_service", {**args, "request_types": [
            {"name": "x", "ticket_type": "Network incident", "fields": [{"key": "nope"}]}]})
    assert "building" in str(e.value)
    out = propose("propose_help_centre_service", {**args, "reason": "Network &amp; Wi-Fi in one place"})
    assert out["proposed"] and "draft" in out["summary"]
    from app.models.ask_conversation import AskAction
    assert db.get(AskAction, out["_action"]["id"]).payload["reason"] == "Network & Wi-Fi in one place", \
        "a model's HTML-escaped prose is shown as text"
    assert db.scalar(select(ServiceOffering).where(ServiceOffering.site_id == ids["site"])) is None, "nothing yet"
    action_id = out["_action"]["id"]

    refused = ask_actions.apply(db, as_(lab, "requester"), ids["sparc"], "requester", convo.id, [action_id])
    assert refused[0]["status"] == "failed" and "Site administrators" in refused[0]["error"]
    from app.models.ask_conversation import AskAction
    db.get(AskAction, action_id).status = "proposed"
    db.commit()
    done = ask_actions.apply(db, as_(lab, "site_admin"), ids["sparc"], "site_admin", convo.id, [action_id])
    assert done[0]["status"] == "applied", done[0]["error"]
    svc = db.scalar(select(ServiceOffering).where(ServiceOffering.site_id == ids["site"]))
    assert svc.name == "Network & connectivity" and not svc.active and svc.provider_workspace_id == ids["it"]
    rt = db.scalar(select(ServiceRequestType).where(ServiceRequestType.service_uid == svc.uid))
    assert rt.schema_uid == lab["schema"].uid and rt.fields[0]["key"] == "building" and rt.fields[0]["required"]
    with pytest.raises(ask_actions.Refused) as e:
        propose("propose_help_centre_service", {**args, "name": "Network and connectivity service"})
    assert "already has a service called 'Network & connectivity'" in str(e.value), "the same service, not a new one"
