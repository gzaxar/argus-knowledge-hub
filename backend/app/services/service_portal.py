"""The service portal of a site (docs/service-portal.md): who may use it, where a request goes, the one ticket it
becomes, and what its requester may see of that ticket.

Rules this module keeps:

* A requester is a person signed in, who can read the site or one of its current facilities. Nothing here gives
  them a right on the provider workspace: they reach their own requests only through `SupportRequest`.
* Routing is deterministic: the request type chosen names its service, the service names its provider workspace
  and its team. "I'm not sure" is the site's helpdesk request type. A destination that is not valid any more is
  refused with a clear error — never sent somewhere else silently.
* One submission is one ticket: `(requester, submission_uid)` is unique, and a retry returns the first answer.
* A requester sees what they sent, public replies and files, a status mapped from the workflow's state category,
  and the resolution. Internal notes, internal files, history, watchers and other tickets stay with the staff.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.group import Group, GroupMember
from app.models.issue import Issue, IssueComment, IssueHistory
from app.models.role import Role, RoleBinding, SiteGroupRoleBinding
from app.models.schema import Schema
from app.models.service_portal import ServiceOffering, ServiceRequestType, SiteServiceSettings, SupportRequest
from app.models.user import User
from app.models.workspace import Workspace
from app.services import sites as site_service
from app.services import workflows
from app.services.permissions import administers_site, current_site, effective_permissions, resolve_permission

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")
MAX_FILES = 10
MAX_FILE_BYTES = int(os.environ.get("ARGUS_PORTAL_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
MAX_TITLE = 200
MAX_TEXT = 20000

# What a requester reads for a state, by the workflow category of the state (never by its translated name).
REQUESTER_STATUS = {"open": "Open", "active": "In progress", "waiting": "Waiting", "done": "Resolved"}
READ_RESOURCES = ("objects", "tickets", "documents")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def now() -> datetime:
    return datetime.now(timezone.utc)


def problem(status: int, code: str, error: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, "code": code, **extra})


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:60] or "service"


# --------------------------------------------------------------------------- who

def requester_of(identity, *, write: bool = False) -> User:
    """The person behind a portal call: signed in, or a personal token of theirs that is not bound to one
    workspace (a site's portal spans several) and has the scopes the call needs. Never a robot token."""
    from app.auth import OidcIdentity
    if not isinstance(identity, OidcIdentity):
        raise problem(403, "sign_in_required", "The service portal is for people, not robot tokens.")
    scope = identity.token
    if scope is not None and (scope.workspace_id is not None or not scope.may("read", "tickets")
                              or (write and not scope.may("create", "tickets"))):
        raise problem(403, "token_scope", "This token may not use the service portal: it needs no workspace limit, "
                      "and read (and create, to send) on tickets.")
    user = identity.user
    if not user.active or getattr(user, "removed_at", None) is not None:
        raise problem(403, "inactive", "This account is not active.")
    return user


def site_workspaces(db: Session, site_id: str) -> list[str]:
    return [site_id, *site_service.facilities(db, site_id)]


def reads(db: Session, user: User, workspace_id: str) -> bool:
    return any(resolve_permission(db, user, workspace_id, "read", r) for r in READ_RESOURCES)


def eligible_origins(db: Session, user: User, site_id: str) -> list[Workspace]:
    """The workspaces of the site a person can read now: where a request of theirs may come from."""
    out = []
    for ws_id in site_workspaces(db, site_id):
        ws = db.get(Workspace, ws_id)
        if ws is not None and ws.import_state is None and reads(db, user, ws_id):
            out.append(ws)
    return out


def settings_of(db: Session, site_id: str) -> Optional[SiteServiceSettings]:
    return db.get(SiteServiceSettings, site_id)


def portal_site(db: Session, user: User, site_id: str, *, open_only: bool = True) -> tuple:
    """The site, its portal settings and the requester's origins; 404 when the portal is not theirs to use.
    `open_only=False` keeps existing requests reachable while the portal is closed for new ones."""
    site = db.get(Workspace, site_id)
    if site is None or site.role != site_service.ROLE:
        raise problem(404, "not_found", "Service portal not found")
    settings = settings_of(db, site_id)
    origins = eligible_origins(db, user, site_id)
    if not origins:
        raise problem(404, "not_found", "Service portal not found")
    if open_only and (settings is None or not settings.enabled) and not may_manage_user(db, user, site_id):
        raise problem(404, "not_found", "Service portal not found")
    return site, settings, origins


def eligible_sites(db: Session, user: User) -> list[dict]:
    out = []
    for site in db.scalars(select(Workspace).where(Workspace.role == site_service.ROLE).order_by(Workspace.name)):
        settings = settings_of(db, site.id)
        open_ = bool(settings and settings.enabled)
        manager = may_manage_user(db, user, site.id)
        if not open_ and not manager:
            continue
        origins = eligible_origins(db, user, site.id)
        if not origins:
            continue
        out.append({"id": site.id, "name": site.name, "open": open_, "manager": manager,
                    "headline": settings.headline if settings else None,
                    "origins": [{"id": w.id, "name": w.name} for w in origins]})
    return out


# --------------------------------------------------------------------------- who manages

def may_manage_user(db: Session, user: User, site_id: str) -> bool:
    return bool(user.is_admin or administers_site(db, user.id, site_id))


def manager_of(db: Session, identity, site_id: str) -> tuple[Workspace, User]:
    """A site's service catalogue is managed by its site administrators and the installation's."""
    from app.auth import OidcIdentity
    site = db.get(Workspace, site_id)
    if site is None or site.role != site_service.ROLE:
        raise problem(404, "not_found", "Site not found")
    if not isinstance(identity, OidcIdentity) or (
            identity.token is not None and (not identity.token.may("admin")
                                            or identity.token.workspace_id not in (None, site_id))):
        raise problem(403, "forbidden", "Site administrators only")
    if not may_manage_user(db, identity.user, site_id):
        raise problem(403, "forbidden", "Site administrators only")
    return site, identity.user


def may_authorize_destination(db: Session, user: Optional[User], workspace_id: str) -> bool:
    """Who may let a service send tickets into a workspace: the installation's administrators, or someone who
    manages that workspace's access by a role of their own there — administering its site is not enough."""
    if user is None or not user.active:
        return False
    if user.is_admin:
        return True
    granted = effective_permissions(db, user, workspace_id, include_site_administration=False)
    return "manage_members" in granted.get("workspace", set())


def team_ticket_rights(db: Session, group_uid: str, workspace_id: str) -> set[str]:
    """The ticket actions a group's roles give it in a workspace, directly or site-wide."""
    roles = list(db.scalars(select(Role).join(RoleBinding, RoleBinding.role_id == Role.id).where(
        RoleBinding.workspace_id == workspace_id, RoleBinding.subject_type == "group",
        RoleBinding.subject_id == group_uid)))
    site_id = current_site(db, workspace_id)
    if site_id:
        roles += list(db.scalars(select(Role).join(SiteGroupRoleBinding, SiteGroupRoleBinding.role_id == Role.id)
                                 .where(SiteGroupRoleBinding.site_id == site_id,
                                        SiteGroupRoleBinding.group_uid == group_uid)))
    out: set[str] = set()
    for role in roles:
        out |= set((role.permissions or {}).get("tickets") or [])
    return out


# --------------------------------------------------------------------------- health of a destination

def service_problems(db: Session, svc: ServiceOffering) -> list[str]:
    """Why a service cannot take requests now (empty: it can). Checked on publishing and on every use."""
    out = []
    ws = db.get(Workspace, svc.provider_workspace_id)
    if ws is None:
        return [f"The destination workspace {svc.provider_workspace_id} no longer exists."]
    if ws.id != svc.site_id and current_site(db, ws.id) != svc.site_id:
        out.append(f"{ws.name} is no longer at this site.")
    if ws.import_state is not None:
        out.append(f"{ws.name} is being imported or holds read-only evidence.")
    group = db.get(Group, svc.team_group_uid)
    if group is None or not group.active:
        out.append("The responsible team is no longer an active group.")
    else:
        rights = team_ticket_rights(db, group.uid, ws.id)
        if not {"read", "modify"} <= rights:
            out.append(f"The team {group.name} has no role in {ws.name} that reads and changes tickets.")
    authorizer = db.get(User, svc.authorized_by) if svc.authorized_by else None
    if svc.authorized_by is None:
        out.append(f"Nobody who manages {ws.name} has authorised this service to send it tickets.")
    elif not may_authorize_destination(db, authorizer, ws.id):
        out.append(f"The person who authorised tickets into {ws.name} may no longer do so: authorise it again.")
    return out


def request_type_problems(db: Session, svc: ServiceOffering, rt: ServiceRequestType) -> list[str]:
    out = service_problems(db, svc)
    if rt.schema_uid:
        schema = db.get(Schema, rt.schema_uid)
        if schema is None or schema.applies_to != "tickets":
            out.append(f"{rt.name}: its ticket type no longer exists.")
        elif not (schema.is_global or schema.workspace_id == svc.provider_workspace_id):
            out.append(f"{rt.name}: its ticket type {schema.name} cannot be used in the destination workspace.")
        else:
            out += [f"{rt.name}: {p}" for p in field_problems(db, schema, rt.fields or [])]
    elif rt.fields:
        out.append(f"{rt.name}: requester fields need a ticket type to belong to.")
    return out


def field_problems(db: Session, schema: Schema, fields: list[dict]) -> list[str]:
    from app.services.attribute_validation import effective_attributes
    from app.services.visibility import restricted_fields
    defs = {a.get("key") or a.get("name"): a for a in effective_attributes(db, schema)}
    restricted = restricted_fields(db, schema.uid)
    out = []
    for f in fields:
        key = f.get("key")
        if key not in defs:
            out.append(f"the field {key!r} is not a field of {schema.name}.")
        elif key in restricted:
            out.append(f"the field {key!r} is restricted and cannot be asked of requesters.")
        elif str(key).startswith("argus_"):
            out.append(f"the field {key!r} is kept by ARGUS itself.")
    return out


def usable(db: Session, svc: Optional[ServiceOffering], rt: Optional[ServiceRequestType]) -> bool:
    return bool(svc and rt and svc.active and rt.active and rt.service_uid == svc.uid
                and not request_type_problems(db, svc, rt))


# --------------------------------------------------------------------------- the catalogue

def helpdesk_type(db: Session, settings: Optional[SiteServiceSettings]) -> Optional[ServiceRequestType]:
    if settings is None or not settings.helpdesk_request_type_uid:
        return None
    return db.get(ServiceRequestType, settings.helpdesk_request_type_uid)


def form_fields(db: Session, rt: ServiceRequestType) -> list[dict]:
    """The fields a requester fills in, described from the ticket type: no other field of the type is shown."""
    from app.services.attribute_validation import effective_attributes
    schema = db.get(Schema, rt.schema_uid) if rt.schema_uid else None
    defs = {a.get("key") or a.get("name"): a for a in effective_attributes(db, schema)} if schema else {}
    out = []
    for f in rt.fields or []:
        d = defs.get(f.get("key"))
        if d is None:
            continue
        options = [{"value": o.get("value") if o.get("value") is not None else o.get("id"),
                    "label": o.get("label") or o.get("name") or str(o.get("value") or o.get("id"))}
                   for o in (d.get("options") or [])] if d.get("type") == "enumeration" else []
        out.append({"key": f["key"], "label": f.get("label") or d.get("label") or d.get("name") or f["key"],
                    "help": f.get("help") or d.get("description"), "required": bool(f.get("required")),
                    "type": d.get("type") or "text", "options": options})
    return out


def request_type_out(db: Session, rt: ServiceRequestType, *, with_form: bool = False) -> dict:
    out = {"uid": rt.uid, "slug": rt.slug, "name": rt.name, "description": rt.description,
           "allow_attachments": rt.allow_attachments}
    if with_form:
        out["guidance"] = rt.guidance
        out["fields"] = form_fields(db, rt)
    return out


def catalogue(db: Session, site: Workspace, settings: Optional[SiteServiceSettings]) -> dict:
    """What a requester sees: services that can take requests now, by category, with their request types."""
    categories: dict[str, list] = {}
    helpdesk = helpdesk_type(db, settings)
    for svc in db.scalars(select(ServiceOffering).where(ServiceOffering.site_id == site.id,
                                                        ServiceOffering.active.is_(True))
                          .order_by(ServiceOffering.position, ServiceOffering.name)):
        types = [rt for rt in db.scalars(select(ServiceRequestType).where(
            ServiceRequestType.service_uid == svc.uid, ServiceRequestType.active.is_(True))
            .order_by(ServiceRequestType.position, ServiceRequestType.name)) if usable(db, svc, rt)]
        if not types:
            continue
        categories.setdefault(svc.category or "Services", []).append({
            "uid": svc.uid, "slug": svc.slug, "name": svc.name, "description": svc.description,
            "hours": svc.hours, "contact": svc.contact,
            "request_types": [request_type_out(db, rt) for rt in types]})
    helpdesk_ok = helpdesk is not None and usable(db, db.get(ServiceOffering, helpdesk.service_uid), helpdesk)
    return {
        "site": {"id": site.id, "name": site.name},
        "open": bool(settings and settings.enabled),
        "headline": (settings.headline if settings else None) or "How can we help?",
        "welcome": settings.welcome if settings else None,
        "emergency": settings.emergency if settings else None,
        "assistance": bool(settings and settings.assistance),
        "helpdesk": request_type_out(db, helpdesk) if helpdesk_ok else None,
        "categories": [{"name": name, "services": svcs} for name, svcs in categories.items()],
    }


def find_request_type(db: Session, site_id: str, uid: str) -> tuple[ServiceOffering, ServiceRequestType]:
    rt = db.get(ServiceRequestType, uid)
    svc = db.get(ServiceOffering, rt.service_uid) if rt else None
    if rt is None or svc is None or svc.site_id != site_id:
        raise problem(404, "not_found", "Request type not found")
    return svc, rt


# --------------------------------------------------------------------------- routing

def route(db: Session, site_id: str, request_type_uid: Optional[str]) -> dict:
    """Where a request goes: from its request type to the service, the provider workspace and the team. With no
    request type ("I'm not sure"), the site's helpdesk. An unusable destination is refused, with the helpdesk
    offered instead when it can take it."""
    settings = settings_of(db, site_id)
    helpdesk = helpdesk_type(db, settings)
    if request_type_uid is None:
        if helpdesk is None:
            raise problem(409, "no_helpdesk", "This site has no helpdesk to send a request to.")
        svc, rt = find_request_type(db, site_id, helpdesk.uid)
        reason = "You were not sure which service to ask: the site's helpdesk takes it and finds the right team."
    else:
        svc, rt = find_request_type(db, site_id, request_type_uid)
        reason = f"You chose {svc.name}: {rt.name}."
    if not usable(db, svc, rt):
        fallback = None
        if helpdesk is not None and helpdesk.uid != rt.uid:
            try:
                fallback = route(db, site_id, None)
            except HTTPException:
                fallback = None
        raise problem(409, "service_unavailable",
                      f"{svc.name} cannot take requests at the moment. Nothing was sent.", fallback=fallback)
    provider = db.get(Workspace, svc.provider_workspace_id)
    team = db.get(Group, svc.team_group_uid)
    version = hashlib.sha256(json.dumps([
        settings.version if settings else 0, svc.uid, svc.version, rt.uid, rt.version, svc.provider_workspace_id,
        svc.team_group_uid, rt.schema_uid, svc.authorized_by], default=str).encode()).hexdigest()[:16]
    return {"request_type_uid": rt.uid, "request_type_name": rt.name, "service_uid": svc.uid,
            "service_name": svc.name, "provider_workspace_id": provider.id, "provider_name": provider.name,
            "team_group_uid": team.uid, "team_name": team.name, "schema_uid": rt.schema_uid,
            "helpdesk": helpdesk is not None and rt.uid == helpdesk.uid, "reason": reason, "version": version}


def check_staff_routing(db: Session, issue: Issue, patch: dict) -> None:
    """A member of staff moves a request to another service, or another team: within the ticket's workspace only
    (a different provider workspace is a handoff the portal does not do), to a team that is an active group."""
    if patch.get("service_uid") not in (None, issue.service_uid):
        svc = db.get(ServiceOffering, patch["service_uid"])
        if svc is None or svc.provider_workspace_id != issue.workspace_id:
            raise problem(422, "reroute", "A request can only move to another service of this same workspace.")
        if "assigned_group_uid" not in patch:
            patch["assigned_group_uid"] = svc.team_group_uid
    if "service_uid" in patch and patch["service_uid"] is None and issue.service_uid is not None:
        raise problem(422, "reroute", "A portal request keeps a service: choose another one instead.")
    if patch.get("assigned_group_uid") not in (None, issue.assigned_group_uid):
        group = db.get(Group, patch["assigned_group_uid"])
        if group is None or not group.active:
            raise problem(422, "team", "Choose an active group as the team.")


# --------------------------------------------------------------------------- submitting

def submission_hash(payload: dict, files: Iterable[tuple[str, int]]) -> str:
    body = {k: payload.get(k) for k in ("request_type_uid", "origin_workspace_id", "title", "description", "fields")}
    body["files"] = sorted([list(f) for f in files])
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def existing_submission(db: Session, user: User, submission_uid: str) -> Optional[SupportRequest]:
    return db.scalar(select(SupportRequest).where(SupportRequest.requester_id == user.id,
                                                  SupportRequest.submission_uid == submission_uid))


def _clean_fields(db: Session, rt: ServiceRequestType, given: dict) -> tuple[dict, list[dict]]:
    allowed = {f["key"]: f for f in form_fields(db, rt)}
    extra = sorted(set(given or {}) - set(allowed))
    if extra:
        raise problem(422, "field_not_allowed", f"These fields cannot be set from the portal: {', '.join(extra)}.")
    attributes, shown = {}, []
    for key, f in allowed.items():
        value = (given or {}).get(key)
        if isinstance(value, str):
            value = value.strip()[:MAX_TEXT]
        if value in (None, "", []):
            if f["required"]:
                raise problem(422, "field_required", f"{f['label']} is required.", field=key)
            continue
        if not isinstance(value, (str, int, float, bool, list)):
            raise problem(422, "field_value", f"{f['label']}: give a plain value.", field=key)
        attributes[key] = value
        label = next((o["label"] for o in f["options"] if str(o["value"]) == str(value)), None)
        shown.append({"key": key, "label": f["label"], "value": label if label is not None else value})
    return attributes, shown


def store_file(issue: Issue, contents: bytes, filename: str, mime: Optional[str], author: str,
               audience: str) -> Attachment:
    uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    path = os.path.join(ATTACHMENTS_DIR, uid)
    with open(path, "wb") as f:
        f.write(contents)
    return Attachment(uid=uid, workspace_id=issue.workspace_id, issue_uid=issue.uid,
                      filename=os.path.basename(filename or "") or uid, mime_type=mime, file_size=len(contents),
                      storage_path=path, author=author, audience=audience)


def check_files(files: list[tuple[str, Optional[str], bytes]]) -> None:
    if len(files) > MAX_FILES:
        raise problem(422, "too_many_files", f"Attach at most {MAX_FILES} files.")
    for name, _, contents in files:
        if len(contents) > MAX_FILE_BYTES:
            raise problem(413, "file_too_large", f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")


def submit(db: Session, user: User, site_id: str, payload: dict,
           files: list[tuple[str, Optional[str], bytes]]) -> tuple[SupportRequest, bool]:
    """One request, one ticket. Returns the request and whether it was made now (False: a retry of one made)."""
    submission_uid = str(payload.get("submission_uid") or "").strip()
    if not submission_uid or len(submission_uid) > 100:
        raise problem(422, "submission_uid", "A submission needs its client-made submission_uid.")
    digest = submission_hash(payload, ((n, len(c)) for n, _, c in files))
    _, settings, origins = portal_site(db, user, site_id)
    previous = existing_submission(db, user, submission_uid)
    if previous is not None:
        if previous.request_hash != digest:
            raise problem(422, "idempotency_mismatch",
                          "This submission id was already used for a different request.")
        return previous, False
    if settings is None or not settings.enabled:
        raise problem(409, "portal_closed", "This site's portal is not taking requests yet.")
    origin = payload.get("origin_workspace_id")
    if origin not in {w.id for w in origins}:
        raise problem(422, "origin", "Choose where you are reporting from among your workspaces at this site.")
    title = (payload.get("title") or "").strip()
    if not title:
        raise problem(422, "title_required", "Give your request a short summary.", field="title")
    if len(title) > MAX_TITLE:
        raise problem(422, "title_too_long", f"Keep the summary under {MAX_TITLE} characters.", field="title")
    description = (payload.get("description") or "").strip()[:MAX_TEXT] or None
    target = route(db, site_id, payload.get("request_type_uid"))
    if payload.get("route_version") and payload["route_version"] != target["version"]:
        raise problem(409, "route_changed", "Where this request goes has changed since you reviewed it: "
                      "check it again before sending.", preview=target)
    svc, rt = find_request_type(db, site_id, target["request_type_uid"])
    if files and not rt.allow_attachments:
        raise problem(422, "no_attachments", f"{rt.name} does not take attachments.")
    check_files(files)
    attributes, shown = _clean_fields(db, rt, payload.get("fields") or {})

    from app.services import tickets
    issue = tickets.create_ticket(db, svc.provider_workspace_id, {
        "uid": str(uuid.uuid4()), "asset_uid": None, "schema_uid": rt.schema_uid, "attributes": attributes,
        "title": title, "description": description, "state": "new", "priority": None, "assignee": None,
        "labels": [], "due_date": None, "created_by": user.id, "service_uid": svc.uid,
        "assigned_group_uid": svc.team_group_uid}, user.id, watch_reporter=False)
    origin_ws = db.get(Workspace, origin)
    request = SupportRequest(
        uid=str(uuid.uuid4()), site_id=site_id, origin_workspace_id=origin, requester_id=user.id,
        issue_uid=issue.uid, service_uid=svc.uid, request_type_uid=rt.uid, service_name=svc.name,
        request_type_name=rt.name, submitted=shown,
        route={"reason": target["reason"], "version": target["version"], "helpdesk": target["helpdesk"],
               "team_group_uid": svc.team_group_uid, "origin_name": origin_ws.name if origin_ws else origin},
        submission_uid=submission_uid, request_hash=digest, created_at=now(), public_activity_at=now(),
        requester_seen_at=now())
    db.add(request)
    db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=issue.uid, type="updated", author=user.id,
                        field="Service request", to_value=f"{svc.name}: {rt.name}",
                        details=f"From {origin_ws.name if origin_ws else origin}. {target['reason']}",
                        timestamp=now()))
    for name, mime, contents in files:
        db.add(store_file(issue, contents, name, mime, user.id, "requester"))
    db.flush()
    queue_notify(db, issue, svc, user.id)
    return request, True


# --------------------------------------------------------------------------- notifications

def support_request_for(db: Session, issue_uid: str) -> Optional[SupportRequest]:
    return db.scalar(select(SupportRequest).where(SupportRequest.issue_uid == issue_uid))


def staff_may_read(db: Session, issue: Issue, who: str) -> bool:
    from app.services.notify import _user
    user = _user(db, who)
    return user is not None and user.active and resolve_permission(db, user, issue.workspace_id, "read", "tickets")


def team_members(db: Session, issue: Issue) -> list[str]:
    """The team's active members who may read tickets where it lives: who hears of a request in its queue."""
    if not issue.assigned_group_uid:
        return []
    group = db.get(Group, issue.assigned_group_uid)
    if group is None or not group.active:
        return []
    out = []
    for user in db.scalars(select(User).join(GroupMember, GroupMember.user_id == User.id).where(
            GroupMember.group_uid == group.uid, User.active.is_(True))):
        if resolve_permission(db, user, issue.workspace_id, "read", "tickets"):
            out.append(user.id)
    return out


def queue_notify(db: Session, issue: Issue, svc: ServiceOffering, actor: Optional[str]) -> None:
    from app.services import notify
    group = db.get(Group, issue.assigned_group_uid) if issue.assigned_group_uid else None
    notify.notify(db, issue, "queued", f"New request for {group.name if group else svc.name}: {issue.title}",
                  actor, team_members(db, issue), {"service": svc.name})


def requester_path(request: SupportRequest) -> str:
    return f"/support/{request.site_id}/requests/{request.uid}"


def tell_requester(db: Session, issue: Issue, kind: str, title: str, actor: Optional[str],
                   excerpt: Optional[str] = None) -> None:
    """A requester-safe notification: what changed, the public text only, a link to the portal page."""
    from app.services import notify
    request = support_request_for(db, issue.uid)
    if request is None or request.requester_id == actor:
        return
    request.public_activity_at = now()
    detail = {"path": requester_path(request), "portal": True}
    if excerpt:
        detail["excerpt"] = excerpt[:200]
    notify.notify(db, issue, kind, title, actor, [request.requester_id], detail, requester_safe=True)


def status_of(db: Session, issue: Issue) -> dict:
    wf = workflows.workflow_for(db, issue.workspace_id, issue.schema_uid)
    state = workflows.state_of(wf, issue.state) or {}
    category = state.get("category") or ("done" if issue.closed_at else "open")
    return {"category": category, "label": REQUESTER_STATUS.get(category, "Open")}


def on_transition(db: Session, issue: Issue, actor: Optional[str], before: str, after: str) -> None:
    if not issue.service_uid or before == after:
        return
    wf = workflows.workflow_for(db, issue.workspace_id, issue.schema_uid)
    was = (workflows.state_of(wf, before) or {}).get("category")
    now_ = (workflows.state_of(wf, after) or {}).get("category")
    if was == now_:
        return
    request = support_request_for(db, issue.uid)
    if request is None:
        return
    label = REQUESTER_STATUS.get(now_ or "open", "Open")
    tell_requester(db, issue, "request_resolved" if now_ == "done" else "request_status",
                   f"Your request {issue.key or ''} is {label.lower()}: {issue.title}".replace("  ", " "), actor)


def on_public_reply(db: Session, issue: Issue, body: str, actor: Optional[str]) -> None:
    tell_requester(db, issue, "request_reply", f"New reply on your request {issue.key or ''}: {issue.title}"
                   .replace("  ", " "), actor, excerpt=body)


def on_public_file(db: Session, issue: Issue, filename: str, actor: Optional[str]) -> None:
    tell_requester(db, issue, "request_reply", f"A file was shared on your request {issue.key or ''}: "
                   f"{filename}".replace("  ", " "), actor)


# --------------------------------------------------------------------------- what the requester sees

def owned(db: Session, user: User, site_id: str, uid: str) -> tuple[SupportRequest, Issue]:
    """The requester's own request, or 404 — for a guessed id as for one that is someone else's."""
    portal_site(db, user, site_id, open_only=False)
    request = db.get(SupportRequest, uid)
    if request is None or request.requester_id != user.id or request.site_id != site_id:
        raise problem(404, "not_found", "Request not found")
    issue = db.get(Issue, request.issue_uid)
    if issue is None or issue.deleted_at is not None:
        raise problem(404, "not_found", "Request not found")
    return request, issue


def _restricted_for(db: Session, user: User, issue: Issue) -> bool:
    from app.auth import OidcIdentity, grants_of
    from app.services.visibility import restricted_class
    cls = restricted_class(issue)
    return cls is not None and not grants_of(db, OidcIdentity(user=user), issue.workspace_id).allows(cls)


def _name(db: Session, who: Optional[str], requester_id: str) -> str:
    if who == requester_id:
        return "You"
    user = db.get(User, who) if who else None
    return (user.name or "Support team") if user else "Support team"


def reopen_target(db: Session, issue: Issue) -> Optional[dict]:
    """The move a requester may make on a resolved request: one the workflow allows from here, out of `done`,
    needing nothing (no approval, assignee, resolution or comment)."""
    wf = workflows.workflow_for(db, issue.workspace_id, issue.schema_uid)
    if (workflows.state_of(wf, issue.state) or {}).get("category") != "done":
        return None
    for t in workflows.transitions_from(wf, issue.state):
        if t["category"] != "done" and not t["requires"]:
            return t
    return None


def projection(db: Session, request: SupportRequest, issue: Issue, *, detail: bool = False,
               user: Optional[User] = None) -> dict:
    status = status_of(db, issue)
    out = {"uid": request.uid, "key": issue.key, "title": issue.title, "service_name": request.service_name,
           "request_type_name": request.request_type_name, "status": status, "created_at": request.created_at,
           "updated_at": request.public_activity_at, "site_id": request.site_id,
           "origin_name": (request.route or {}).get("origin_name"),
           "unread": bool(request.public_activity_at and (request.requester_seen_at is None
                                                          or request.public_activity_at > request.requester_seen_at))}
    if not detail:
        return out
    restricted = user is not None and _restricted_for(db, user, issue)
    resolution = (issue.attributes or {}).get("argus_resolution") if status["category"] == "done" else None
    out.update({"restricted": restricted, "resolution": resolution, "resolved_at": issue.closed_at,
                "can_reply": not restricted, "can_reopen": not restricted and reopen_target(db, issue) is not None,
                "allow_attachments": True})
    if restricted:
        out.update({"description": None, "submitted": [], "conversation": [], "attachments": [],
                    "notice": "This request is handled confidentially: its details are not shown here."})
        return out
    comments = db.scalars(select(IssueComment).where(IssueComment.issue_uid == issue.uid,
                                                     IssueComment.audience == "requester")
                          .order_by(IssueComment.created_at)).all()
    files = db.scalars(select(Attachment).where(Attachment.issue_uid == issue.uid,
                                                Attachment.audience == "requester")
                       .order_by(Attachment.created_at)).all()
    out.update({
        "description": issue.description, "submitted": request.submitted or [],
        "conversation": [{"uid": c.uid, "body": c.body, "created_at": c.created_at,
                          "mine": c.author == request.requester_id,
                          "author_name": _name(db, c.author, request.requester_id)} for c in comments],
        "attachments": [{"uid": a.uid, "filename": a.filename, "mime_type": a.mime_type, "file_size": a.file_size,
                         "created_at": a.created_at, "mine": a.author == request.requester_id} for a in files],
    })
    return out


def my_requests(db: Session, user: User, site_id: str, *, open_only: bool = False) -> list[dict]:
    portal_site(db, user, site_id, open_only=False)
    rows = db.execute(select(SupportRequest, Issue).join(Issue, Issue.uid == SupportRequest.issue_uid).where(
        SupportRequest.requester_id == user.id, SupportRequest.site_id == site_id, Issue.deleted_at.is_(None))
        .order_by(SupportRequest.public_activity_at.desc())).all()
    out = [projection(db, r, i) for r, i in rows]
    return [p for p in out if p["status"]["category"] != "done"] if open_only else out


def reply(db: Session, user: User, request: SupportRequest, issue: Issue, body: str,
          comment_uid: Optional[str] = None) -> IssueComment:
    from app.services import notify
    if _restricted_for(db, user, issue):
        raise problem(403, "restricted", "This request is handled confidentially.")
    text = (body or "").strip()
    if not text:
        raise problem(422, "empty", "Write a reply first.")
    if comment_uid:
        existing = db.get(IssueComment, comment_uid)
        if existing is not None:
            if existing.issue_uid != issue.uid or existing.author != user.id:
                raise problem(409, "conflict", "That reply id is taken.")
            return existing
    comment = IssueComment(uid=comment_uid or str(uuid.uuid4()), issue_uid=issue.uid, author=user.id,
                           body=text[:MAX_TEXT], audience="requester")
    db.add(comment)
    request.public_activity_at = request.requester_seen_at = now()
    db.flush()
    recipients = notify.audience(db, issue) + ([] if issue.assignee else team_members(db, issue))
    notify.notify(db, issue, "commented", f"The requester replied on {issue.title}", user.id, recipients,
                  {"excerpt": text[:200]})
    return comment


def reopen(db: Session, user: User, request: SupportRequest, issue: Issue, body: Optional[str]) -> None:
    from app.services import notify
    if _restricted_for(db, user, issue):
        raise problem(403, "restricted", "This request is handled confidentially.")
    target = reopen_target(db, issue)
    if target is None:
        raise problem(409, "reopen_not_allowed",
                      "This request cannot be reopened from the portal: add a reply and the team will see it.")
    before = issue.state
    try:
        workflows.transition(db, issue, target["to"], user.id)
    except workflows.WorkflowError as exc:
        raise problem(409, "reopen_not_allowed", str(exc))
    if body and body.strip():
        reply(db, user, request, issue, body)
    request.public_activity_at = request.requester_seen_at = now()
    notify.notify(db, issue, "transitioned", f"The requester reopened {issue.title}", user.id,
                  notify.audience(db, issue) + team_members(db, issue), {"from": before, "to": issue.state})


# --------------------------------------------------------------------------- administration

def settings_out(db: Session, site: Workspace) -> dict:
    s = settings_of(db, site.id)
    return {"site_id": site.id, "site_name": site.name, "enabled": bool(s and s.enabled),
            "headline": s.headline if s else None, "welcome": s.welcome if s else None,
            "emergency": s.emergency if s else None,
            "helpdesk_request_type_uid": s.helpdesk_request_type_uid if s else None,
            "assistance": bool(s and s.assistance), "version": s.version if s else 0}


def service_admin_out(db: Session, svc: ServiceOffering) -> dict:
    ws = db.get(Workspace, svc.provider_workspace_id)
    group = db.get(Group, svc.team_group_uid)
    authorizer = db.get(User, svc.authorized_by) if svc.authorized_by else None
    types = db.scalars(select(ServiceRequestType).where(ServiceRequestType.service_uid == svc.uid)
                       .order_by(ServiceRequestType.position, ServiceRequestType.name)).all()
    return {"uid": svc.uid, "slug": svc.slug, "name": svc.name, "category": svc.category,
            "description": svc.description, "hours": svc.hours, "contact": svc.contact,
            "provider_workspace_id": svc.provider_workspace_id, "provider_name": ws.name if ws else None,
            "team_group_uid": svc.team_group_uid, "team_name": group.name if group else None,
            "active": svc.active, "position": svc.position, "version": svc.version,
            "authorized_by": (authorizer.email or authorizer.id) if authorizer else None,
            "authorized_at": svc.authorized_at, "problems": service_problems(db, svc),
            "request_types": [{"uid": rt.uid, "slug": rt.slug, "name": rt.name, "description": rt.description,
                               "guidance": rt.guidance, "schema_uid": rt.schema_uid, "fields": rt.fields or [],
                               "allow_attachments": rt.allow_attachments, "active": rt.active,
                               "position": rt.position, "problems": request_type_problems(db, svc, rt)}
                              for rt in types]}


def validate_destination(db: Session, site_id: str, provider: str, team: str) -> None:
    ws = db.get(Workspace, provider)
    if ws is None or provider not in site_workspaces(db, site_id):
        raise problem(422, "destination", "Choose the site itself or one of its facilities as the destination.")
    group = db.get(Group, team)
    if group is None or not group.active:
        raise problem(422, "team", "Choose an active group as the responsible team.")


def bump(row) -> None:
    row.version = (row.version or 0) + 1
