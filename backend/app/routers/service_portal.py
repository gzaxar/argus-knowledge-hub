"""The service portal (docs/service-portal.md).

`/v1/support/...` is the requester's side: the sites whose portal they may use, a site's catalogue, a request
type's form, the routing preview, submitting, and their own requests. None of it reads `X-Workspace-Id`: a request
names its site and its origin explicitly, and every call checks again who the caller is and what they may reach.

`/v1/admin/sites/{site}/service-desk/...` is the site administrators' catalogue: settings, services, request types,
and authorising a destination workspace.
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.models.attachment import Attachment
from app.models.group import Group
from app.models.issue import Issue
from app.models.schema import Schema
from app.models.service_portal import ServiceOffering, ServiceRequestType, SiteServiceSettings, SupportRequest
from app.models.user import User
from app.models.workspace import Workspace
from app.services import service_portal as portal

router = APIRouter(prefix="/v1/support", tags=["service portal"])
admin_router = APIRouter(prefix="/v1/admin/sites", tags=["service portal"])


# --------------------------------------------------------------------------- requester

@router.get("/sites")
def my_portal_sites(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The sites whose portal this person may use: those they can read, or one of whose facilities they can."""
    return portal.eligible_sites(db, portal.requester_of(identity))


@router.get("/sites/{site_id}")
def site_catalogue(site_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    user = portal.requester_of(identity)
    site, settings, origins = portal.portal_site(db, user, site_id)
    out = portal.catalogue(db, site, settings)
    out["origins"] = [{"id": w.id, "name": w.name} for w in origins]
    out["open_requests"] = len(portal.my_requests(db, user, site_id, open_only=True))
    return out


@router.get("/sites/{site_id}/request-types/{uid}")
def request_type_form(site_id: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    user = portal.requester_of(identity)
    portal.portal_site(db, user, site_id)
    svc, rt = portal.find_request_type(db, site_id, uid)
    if not portal.usable(db, svc, rt):
        raise portal.problem(404, "not_found", "Request type not found")
    out = portal.request_type_out(db, rt, with_form=True)
    out["service"] = {"uid": svc.uid, "name": svc.name, "description": svc.description, "hours": svc.hours,
                      "contact": svc.contact, "category": svc.category}
    return out


class PortalPreviewIn(BaseModel):
    request_type_uid: Optional[str] = Field(None, description="null: \"I'm not sure\", the site's helpdesk")
    origin_workspace_id: Optional[str] = None


@router.post("/sites/{site_id}/route-preview")
def route_preview(site_id: str, body: PortalPreviewIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Where a request would go, and why — shown on the review step, and checked again on submitting."""
    user = portal.requester_of(identity)
    _, _, origins = portal.portal_site(db, user, site_id)
    if body.origin_workspace_id and body.origin_workspace_id not in {w.id for w in origins}:
        raise portal.problem(422, "origin", "Choose where you are reporting from among your workspaces at this site.")
    preview = portal.route(db, site_id, body.request_type_uid)
    # What a requester needs to review: the service and team by name, not the destination's internals.
    return {k: preview[k] for k in ("request_type_uid", "request_type_name", "service_name", "team_name",
                                    "provider_name", "helpdesk", "reason", "version")}


@router.post("/sites/{site_id}/requests", status_code=201)
async def submit_request(site_id: str, request: Request, payload: str = Form(..., description="The request, JSON"),
                         files: list[UploadFile] = File(default_factory=list), identity=Depends(get_identity),
                         db: Session = Depends(get_db)):
    """Send a request: one ticket in the service's workspace, in its team's queue. `payload` carries
    `submission_uid` (made by the client once per request and kept for every retry), `request_type_uid` (null for
    the helpdesk), `origin_workspace_id`, `title`, `description`, `fields` and the reviewed `route_version`.
    A retry of the same submission answers with the request already made (200), never a second ticket."""
    user = portal.requester_of(identity, write=True)
    try:
        data = json.loads(payload)
        assert isinstance(data, dict)
    except (ValueError, AssertionError):
        raise portal.problem(422, "payload", "payload must be a JSON object")
    loaded = [(f.filename or "file", f.content_type, await f.read()) for f in files or []]
    try:
        created_request, created = portal.submit(db, user, site_id, data, loaded)
        db.commit()
    except IntegrityError:
        # The same submission sent twice at once: the other one made it.
        db.rollback()
        existing = portal.existing_submission(db, user, str(data.get("submission_uid")))
        if existing is None:
            raise
        created_request, created = existing, False
    except HTTPException:
        db.rollback()
        raise
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    issue = db.get(Issue, created_request.issue_uid)
    body = {"uid": created_request.uid, "key": issue.key if issue else None, "created": created,
            "site_id": site_id}
    return JSONResponse(status_code=201 if created else 200, content=jsonable_encoder(body))


@router.get("/sites/{site_id}/requests")
def list_my_requests(site_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The caller's own requests at this site. There is no way to list anyone else's."""
    return portal.my_requests(db, portal.requester_of(identity), site_id)


@router.get("/sites/{site_id}/requests/{uid}")
def get_my_request(site_id: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    user = portal.requester_of(identity)
    request, issue = portal.owned(db, user, site_id, uid)
    out = portal.projection(db, request, issue, detail=True, user=user)
    request.requester_seen_at = portal.now()
    db.commit()
    return out


class PortalReplyIn(BaseModel):
    body: str
    uid: Optional[str] = Field(None, description="Client-made, so a retry does not post the reply twice")


@router.post("/sites/{site_id}/requests/{uid}/messages", status_code=201)
def reply_to_my_request(site_id: str, uid: str, body: PortalReplyIn, identity=Depends(get_identity),
                        db: Session = Depends(get_db)):
    user = portal.requester_of(identity, write=True)
    request, issue = portal.owned(db, user, site_id, uid)
    portal.reply(db, user, request, issue, body.body, body.uid)
    db.commit()
    return portal.projection(db, request, issue, detail=True, user=user)


@router.post("/sites/{site_id}/requests/{uid}/attachments", status_code=201)
async def add_file_to_my_request(site_id: str, uid: str, file: UploadFile, identity=Depends(get_identity),
                                 db: Session = Depends(get_db)):
    user = portal.requester_of(identity, write=True)
    request, issue = portal.owned(db, user, site_id, uid)
    if portal._restricted_for(db, user, issue):
        raise portal.problem(403, "restricted", "This request is handled confidentially.")
    contents = await file.read()
    portal.check_files([(file.filename or "file", file.content_type, contents)])
    existing = db.scalars(select(Attachment).where(Attachment.issue_uid == issue.uid)).all()
    if len([a for a in existing if a.author == user.id]) >= portal.MAX_FILES * 3:
        raise portal.problem(422, "too_many_files", "This request has as many of your files as it can take.")
    attachment = portal.store_file(issue, contents, file.filename or "file", file.content_type, user.id, "requester")
    db.add(attachment)
    request.public_activity_at = request.requester_seen_at = portal.now()
    from app.services import notify
    notify.notify(db, issue, "commented", f"The requester added a file to {issue.title}", user.id,
                  notify.audience(db, issue) + ([] if issue.assignee else portal.team_members(db, issue)),
                  {"excerpt": attachment.filename})
    db.commit()
    return portal.projection(db, request, issue, detail=True, user=user)


@router.get("/sites/{site_id}/requests/{uid}/attachments/{attachment_uid}")
def download_my_request_file(site_id: str, uid: str, attachment_uid: str, identity=Depends(get_identity),
                             db: Session = Depends(get_db)):
    """A file of the requester's own request that is shared with them; 404 for any other."""
    user = portal.requester_of(identity)
    request, issue = portal.owned(db, user, site_id, uid)
    attachment = db.get(Attachment, attachment_uid)
    if attachment is None or attachment.issue_uid != issue.uid or attachment.audience != "requester" \
            or portal._restricted_for(db, user, issue):
        raise portal.problem(404, "not_found", "File not found")
    import os
    if not os.path.exists(attachment.storage_path):
        raise portal.problem(404, "not_found", "File not found")
    return FileResponse(attachment.storage_path, filename=attachment.filename,
                        media_type=attachment.mime_type or "application/octet-stream")


class PortalReopenIn(BaseModel):
    body: Optional[str] = None


@router.post("/sites/{site_id}/requests/{uid}/reopen")
def reopen_my_request(site_id: str, uid: str, body: PortalReopenIn, identity=Depends(get_identity),
                      db: Session = Depends(get_db)):
    user = portal.requester_of(identity, write=True)
    request, issue = portal.owned(db, user, site_id, uid)
    portal.reopen(db, user, request, issue, body.body)
    db.commit()
    return portal.projection(db, request, issue, detail=True, user=user)


# --------------------------------------------------------------------------- staff

@router.get("/queues")
def workspace_queues(workspace_id: str = Depends(require_permission("read", resource="tickets")),
                     db: Session = Depends(get_db)):
    """For the ticket list and board of a workspace: the portal services whose tickets it holds, and their teams,
    to filter by. Staff only: it needs ticket read in the workspace."""
    services = db.scalars(select(ServiceOffering).where(ServiceOffering.provider_workspace_id == workspace_id)
                          .order_by(ServiceOffering.name)).all()
    team_uids = {s.team_group_uid for s in services} | set(db.scalars(
        select(Issue.assigned_group_uid).where(Issue.workspace_id == workspace_id,
                                               Issue.assigned_group_uid.is_not(None)).distinct()))
    teams = db.scalars(select(Group).where(Group.uid.in_(team_uids)).order_by(Group.name)).all() if team_uids else []
    return {"services": [{"uid": s.uid, "name": s.name, "team_group_uid": s.team_group_uid} for s in services],
            "teams": [{"uid": g.uid, "name": g.name, "active": g.active} for g in teams]}


# --------------------------------------------------------------------------- assistance (optional)

class PortalAssistIn(BaseModel):
    text: str
    origin_workspace_id: str
    use_ai: bool = False


@router.post("/sites/{site_id}/assist")
def assist(site_id: str, body: PortalAssistIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Help while choosing: knowledge articles the requester may read in their own workspace, and — only when
    asked, and only where that workspace's AI is on — a suggested request type and a summary to edit. Nothing is
    sent: the requester reviews and submits."""
    from app.services import portal_assist
    user = portal.requester_of(identity)
    site, settings, origins = portal.portal_site(db, user, site_id)
    if not settings or not settings.assistance:
        raise portal.problem(404, "not_found", "Assistance is not offered on this portal.")
    if body.origin_workspace_id not in {w.id for w in origins}:
        raise portal.problem(422, "origin", "Choose where you are reporting from among your workspaces at this site.")
    return portal_assist.assist(db, user, site, settings, body.origin_workspace_id, body.text, body.use_ai)


# --------------------------------------------------------------------------- administration

class PortalSettingsIn(BaseModel):
    enabled: bool = False
    headline: Optional[str] = None
    welcome: Optional[str] = None
    emergency: Optional[str] = None
    helpdesk_request_type_uid: Optional[str] = None
    assistance: bool = False


class PortalServiceIn(BaseModel):
    name: str
    slug: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    hours: Optional[str] = None
    contact: Optional[str] = None
    provider_workspace_id: str
    team_group_uid: str
    position: int = 0


class PortalFieldIn(BaseModel):
    key: str
    label: Optional[str] = None
    help: Optional[str] = None
    required: bool = False


class PortalRequestTypeIn(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    guidance: Optional[str] = None
    schema_uid: Optional[str] = None
    fields: list[PortalFieldIn] = []
    allow_attachments: bool = True
    active: bool = True
    position: int = 0


def _desk(db: Session, site_id: str) -> dict:
    site = db.get(Workspace, site_id)
    services = db.scalars(select(ServiceOffering).where(ServiceOffering.site_id == site_id)
                          .order_by(ServiceOffering.position, ServiceOffering.name)).all()
    return {"settings": portal.settings_out(db, site),
            "services": [portal.service_admin_out(db, s) for s in services]}


def _service(db: Session, site_id: str, uid: str) -> ServiceOffering:
    svc = db.get(ServiceOffering, uid)
    if svc is None or svc.site_id != site_id:
        raise portal.problem(404, "not_found", "Service not found")
    return svc


def _unique_slug(db: Session, model, scope_col, scope: str, wanted: str, own_uid: Optional[str] = None) -> str:
    if not portal.SLUG.match(wanted):
        raise portal.problem(422, "slug", "A short name uses lower-case letters, digits and dashes.")
    clash = db.scalar(select(model).where(scope_col == scope, model.slug == wanted))
    if clash is not None and clash.uid != own_uid:
        raise portal.problem(409, "slug_taken", f"{wanted} is already used here.")
    return wanted


@admin_router.get("/{site_id}/service-desk")
def get_service_desk(site_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    portal.manager_of(db, identity, site_id)
    return _desk(db, site_id)


@admin_router.get("/{site_id}/service-desk/options")
def service_desk_options(site_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """What a service may point at: the site and its facilities (with their ticket types), and active groups."""
    _, user = portal.manager_of(db, identity, site_id)
    workspaces = []
    for ws_id in portal.site_workspaces(db, site_id):
        ws = db.get(Workspace, ws_id)
        if ws is None:
            continue
        types = db.scalars(select(Schema).where(Schema.applies_to == "tickets", Schema.is_concrete.is_(True),
                                                (Schema.workspace_id == ws_id) | Schema.is_global.is_(True))
                           .order_by(Schema.name)).all()
        from app.services.attribute_validation import effective_attributes
        workspaces.append({"id": ws.id, "name": ws.name, "may_authorize": portal.may_authorize_destination(db, user, ws.id),
                           "ticket_types": [{"uid": t.uid, "name": t.name, "fields": [
                               {"key": a.get("key") or a.get("name"), "label": a.get("label") or a.get("name"),
                                "type": a.get("type")} for a in effective_attributes(db, t)
                               if not str(a.get("key") or a.get("name") or "").startswith("argus_")]}
                               for t in types]})
    groups = db.scalars(select(Group).where(Group.active.is_(True)).order_by(Group.name)).all()
    return {"workspaces": workspaces, "groups": [{"uid": g.uid, "name": g.name} for g in groups]}


@admin_router.put("/{site_id}/service-desk/settings")
def put_service_desk_settings(site_id: str, body: PortalSettingsIn, identity=Depends(get_identity),
                              db: Session = Depends(get_db)):
    """Opening the portal needs a helpdesk request type that can take requests: "I'm not sure" must lead
    somewhere."""
    _, user = portal.manager_of(db, identity, site_id)
    settings = db.get(SiteServiceSettings, site_id)
    if settings is None:
        settings = SiteServiceSettings(site_id=site_id, version=0)
        db.add(settings)
    if body.helpdesk_request_type_uid:
        portal.find_request_type(db, site_id, body.helpdesk_request_type_uid)
    if body.enabled:
        rt = db.get(ServiceRequestType, body.helpdesk_request_type_uid) if body.helpdesk_request_type_uid else None
        svc = db.get(ServiceOffering, rt.service_uid) if rt else None
        if not portal.usable(db, svc, rt):
            db.rollback()
            problems = portal.request_type_problems(db, svc, rt) if svc and rt else []
            raise portal.problem(422, "helpdesk_required", "Before opening the portal, choose a published helpdesk "
                                 "request type for \"I'm not sure\".", problems=problems)
    for k, v in body.model_dump().items():
        setattr(settings, k, (v.strip() or None) if isinstance(v, str) else v)
    settings.updated_by = user.id
    portal.bump(settings)
    db.commit()
    return _desk(db, site_id)


@admin_router.post("/{site_id}/service-desk/services", status_code=201)
def create_service(site_id: str, body: PortalServiceIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """A new service, unpublished: it takes requests once published."""
    portal.manager_of(db, identity, site_id)
    portal.validate_destination(db, site_id, body.provider_workspace_id, body.team_group_uid)
    slug = _unique_slug(db, ServiceOffering, ServiceOffering.site_id, site_id, body.slug or portal.slugify(body.name))
    svc = ServiceOffering(uid=str(uuid.uuid4()), site_id=site_id, slug=slug, name=body.name.strip(),
                          category=(body.category or "").strip() or None, description=body.description,
                          hours=body.hours, contact=body.contact, provider_workspace_id=body.provider_workspace_id,
                          team_group_uid=body.team_group_uid, position=body.position, active=False, version=1)
    db.add(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.put("/{site_id}/service-desk/services/{uid}")
def update_service(site_id: str, uid: str, body: PortalServiceIn, identity=Depends(get_identity),
                   db: Session = Depends(get_db)):
    """Changing a published service's destination needs authority over the new one: without it, the service is
    unpublished until someone who manages that workspace publishes it."""
    _, user = portal.manager_of(db, identity, site_id)
    svc = _service(db, site_id, uid)
    portal.validate_destination(db, site_id, body.provider_workspace_id, body.team_group_uid)
    moved = body.provider_workspace_id != svc.provider_workspace_id
    svc.slug = _unique_slug(db, ServiceOffering, ServiceOffering.site_id, site_id,
                            body.slug or svc.slug, own_uid=svc.uid)
    for k in ("name", "category", "description", "hours", "contact", "provider_workspace_id", "team_group_uid",
              "position"):
        setattr(svc, k, getattr(body, k))
    if moved:
        if portal.may_authorize_destination(db, user, svc.provider_workspace_id):
            svc.authorized_by, svc.authorized_at = user.id, portal.now()
        else:
            svc.authorized_by, svc.authorized_at, svc.active = None, None, False
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.post("/{site_id}/service-desk/services/{uid}/authorize")
def authorize_service(site_id: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The destination's side: someone who manages the provider workspace's access by a role there (or an
    installation administrator) lets this service create tickets in it. They need not administer the site."""
    from app.auth import OidcIdentity
    svc = _service(db, site_id, uid)
    if not isinstance(identity, OidcIdentity) or identity.token is not None:
        raise portal.problem(403, "forbidden", "Authorise a destination while signed in.")
    if not portal.may_authorize_destination(db, identity.user, svc.provider_workspace_id):
        raise portal.problem(403, "destination_authority", "Only someone who manages the destination workspace's "
                             "access, or an installation administrator, can authorise tickets into it.")
    svc.authorized_by, svc.authorized_at = identity.user.id, portal.now()
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.post("/{site_id}/service-desk/services/{uid}/revoke")
def revoke_service_authorization(site_id: str, uid: str, identity=Depends(get_identity),
                                 db: Session = Depends(get_db)):
    """Withdraw the destination's authorisation: the service stops taking requests at once."""
    from app.auth import OidcIdentity
    svc = _service(db, site_id, uid)
    if not isinstance(identity, OidcIdentity) or not (
            portal.may_authorize_destination(db, identity.user, svc.provider_workspace_id)
            or portal.may_manage_user(db, identity.user, site_id)):
        raise portal.problem(403, "forbidden", "Not permitted")
    svc.authorized_by, svc.authorized_at, svc.active = None, None, False
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.get("/service-desk/authorizations")
def my_destination_authorizations(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The services, at any site, that send or want to send tickets into a workspace the caller manages."""
    from app.auth import OidcIdentity
    if not isinstance(identity, OidcIdentity):
        return []
    out = []
    for svc in db.scalars(select(ServiceOffering).order_by(ServiceOffering.site_id, ServiceOffering.name)):
        if portal.may_authorize_destination(db, identity.user, svc.provider_workspace_id):
            site = db.get(Workspace, svc.site_id)
            out.append({**portal.service_admin_out(db, svc), "site_id": svc.site_id,
                        "site_name": site.name if site else svc.site_id})
    return out


@admin_router.post("/{site_id}/service-desk/services/{uid}/publish")
def publish_service(site_id: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Publish a service (a site administrator): it must be able to take requests now, its destination authorised
    by someone who manages that workspace — the caller themselves when they do."""
    _, user = portal.manager_of(db, identity, site_id)
    svc = _service(db, site_id, uid)
    if svc.authorized_by is None or not portal.may_authorize_destination(
            db, db.get(User, svc.authorized_by),
            svc.provider_workspace_id):
        if not portal.may_authorize_destination(db, user, svc.provider_workspace_id):
            ws = db.get(Workspace, svc.provider_workspace_id)
            raise portal.problem(403, "destination_authority",
                                 f"Tickets into {ws.name if ws else svc.provider_workspace_id} need the authorisation "
                                 "of someone who manages that workspace's access (or an installation administrator): "
                                 "ask them to authorise this service, then publish it.")
        svc.authorized_by, svc.authorized_at = user.id, portal.now()
        db.flush()
    problems = portal.service_problems(db, svc)
    types = db.scalars(select(ServiceRequestType).where(ServiceRequestType.service_uid == svc.uid,
                                                        ServiceRequestType.active.is_(True))).all()
    if not types:
        problems.append("Add at least one request type first.")
    for rt in types:
        problems += [p for p in portal.request_type_problems(db, svc, rt) if p not in problems]
    if problems:
        db.rollback()
        raise portal.problem(422, "not_publishable", "This service cannot take requests yet.", problems=problems)
    svc.active = True
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.post("/{site_id}/service-desk/services/{uid}/unpublish")
def unpublish_service(site_id: str, uid: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Stop taking requests. Its existing requests stay with their requesters and on the team's tickets."""
    portal.manager_of(db, identity, site_id)
    svc = _service(db, site_id, uid)
    settings = db.get(SiteServiceSettings, site_id)
    helpdesk = portal.helpdesk_type(db, settings)
    if settings and settings.enabled and helpdesk and helpdesk.service_uid == svc.uid:
        raise portal.problem(409, "helpdesk_in_use", "This is the open portal's helpdesk: choose another helpdesk, "
                             "or close the portal, first.")
    svc.active = False
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


def _apply_request_type(db: Session, svc: ServiceOffering, rt: ServiceRequestType, body: PortalRequestTypeIn) -> None:
    rt.slug = _unique_slug(db, ServiceRequestType, ServiceRequestType.service_uid, svc.uid,
                           body.slug or rt.slug or portal.slugify(body.name), own_uid=rt.uid)
    for k in ("name", "description", "guidance", "schema_uid", "allow_attachments", "active", "position"):
        setattr(rt, k, getattr(body, k))
    rt.fields = [f.model_dump() for f in body.fields]
    if rt.schema_uid:
        schema = db.get(Schema, rt.schema_uid)
        if schema is None or schema.applies_to != "tickets":
            raise portal.problem(422, "ticket_type", "Choose a ticket type.")
        problems = portal.field_problems(db, schema, rt.fields)
        if problems:
            raise portal.problem(422, "fields", problems[0], problems=problems)
    elif rt.fields:
        raise portal.problem(422, "fields", "Requester fields come from a ticket type: choose one first.")


@admin_router.post("/{site_id}/service-desk/services/{uid}/request-types", status_code=201)
def create_request_type(site_id: str, uid: str, body: PortalRequestTypeIn, identity=Depends(get_identity),
                        db: Session = Depends(get_db)):
    portal.manager_of(db, identity, site_id)
    svc = _service(db, site_id, uid)
    rt = ServiceRequestType(uid=str(uuid.uuid4()), service_uid=svc.uid, version=1)
    _apply_request_type(db, svc, rt, body)
    db.add(rt)
    portal.bump(svc)
    db.commit()
    return portal.service_admin_out(db, svc)


@admin_router.put("/{site_id}/service-desk/request-types/{uid}")
def update_request_type(site_id: str, uid: str, body: PortalRequestTypeIn, identity=Depends(get_identity),
                        db: Session = Depends(get_db)):
    portal.manager_of(db, identity, site_id)
    svc, rt = portal.find_request_type(db, site_id, uid)
    settings = db.get(SiteServiceSettings, site_id)
    if not body.active and settings and settings.enabled and settings.helpdesk_request_type_uid == rt.uid:
        raise portal.problem(409, "helpdesk_in_use", "This is the open portal's helpdesk: choose another helpdesk, "
                             "or close the portal, first.")
    _apply_request_type(db, svc, rt, body)
    portal.bump(rt)
    db.commit()
    return portal.service_admin_out(db, svc)
