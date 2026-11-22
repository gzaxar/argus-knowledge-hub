"""The unified knowledge layer's API: context, search and the operations cockpit.

Every endpoint here answers across assets, tickets and documents, so none of
them can use a single `require_permission`: the caller needs read access to
*some* section to be in the workspace, and each section is filled only if they
may read it (services/knowledge_hub.Access).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, PatIdentity, get_identity
from app.db import get_db
from app.models.asset import Asset
from app.models.document import Document
from app.models.issue import Issue
from app.services import knowledge_hub as hub
from app.services.permissions import resolve_permission
from app.services.visibility import asset_visible_in, can_see

router = APIRouter(prefix="/v1/hub", tags=["hub"])


class _Scope:
    def __init__(self, workspace_id: str, access: hub.Access, user_id: Optional[str]):
        self.workspace_id = workspace_id
        self.access = access
        self.user_id = user_id


def scope(
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
) -> _Scope:
    if isinstance(identity, PatIdentity):
        return _Scope(identity.workspace_id, hub.Access(identity.may("read", "objects"), identity.may("read", "tickets"),
                                                        identity.may("read", "documents")), None)
    if not x_workspace_id:
        raise HTTPException(status_code=400, detail="Missing X-Workspace-Id header")
    user = identity.user

    def can(resource: str) -> bool:
        return resolve_permission(db, user, x_workspace_id, "read", resource)

    access = hub.Access(assets=can("objects"), tickets=can("tickets"), documents=can("documents"))
    if not (access.assets or access.tickets or access.documents):
        raise HTTPException(status_code=403, detail="Not permitted")
    user_id = user.id if isinstance(identity, OidcIdentity) else None
    return _Scope(x_workspace_id, access, user_id)


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(8, ge=1, le=50),
    s: _Scope = Depends(scope),
    db: Session = Depends(get_db),
):
    return hub.unified_search(db, s.workspace_id, s.access, q, limit)


@router.get("/overview")
def overview(s: _Scope = Depends(scope), identity=Depends(get_identity), db: Session = Depends(get_db)):
    from app.routers.workspaces import _require_owner_or_admin
    try:   # Start here is the set-up of the workspace: for those who may set it up, not for everyone in it
        _require_owner_or_admin(s.workspace_id, identity, db)
        setup = True
    except HTTPException:
        setup = False
    return hub.overview(db, s.workspace_id, s.access, s.user_id, setup=setup)


@router.get("/assets/{uid}/context")
def asset_context(uid: str, s: _Scope = Depends(scope), db: Session = Depends(get_db)):
    if not s.access.assets:
        raise HTTPException(status_code=403, detail="Not permitted")
    asset = db.get(Asset, uid)
    if asset is None or asset.deleted_at is not None or not asset_visible_in(asset, s.workspace_id):
        raise HTTPException(status_code=404, detail="Asset not found")
    return hub.asset_context(db, s.workspace_id, asset, s.access)


@router.get("/tickets/{uid}/context")
def ticket_context(uid: str, s: _Scope = Depends(scope), db: Session = Depends(get_db)):
    if not s.access.tickets:
        raise HTTPException(status_code=403, detail="Not permitted")
    issue = db.get(Issue, uid)
    if issue is None or issue.deleted_at is not None or issue.workspace_id != s.workspace_id or not can_see(issue):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return hub.ticket_context(db, s.workspace_id, issue, s.access)


@router.get("/documents/{uid}/context")
def document_context(uid: str, s: _Scope = Depends(scope), db: Session = Depends(get_db)):
    if not s.access.documents:
        raise HTTPException(status_code=403, detail="Not permitted")
    doc = db.get(Document, uid)
    readable = doc is not None and (
        doc.workspace_id == s.workspace_id
        or (doc.is_global and doc.confidentiality != "riservato")
    )
    if not readable:
        raise HTTPException(status_code=404, detail="Document not found")
    return hub.document_context(db, s.workspace_id, doc, s.access)


@router.get("/my-work")
def my_work(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """This person's open tickets in every workspace they can open — assigned to them, reported by them or
    watched — whichever workspace the app is in: what the phone's home shows under "Your tickets"."""
    from sqlalchemy import or_, select
    from app.models.workflow import TicketWatcher
    from app.models.workspace import Workspace
    from app.services.notify import may_see
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=422, detail="Your work belongs to a person, not an API token.")
    me = [x for x in (identity.user.id, identity.user.email) if x]
    watched = select(TicketWatcher.issue_uid).where(TicketWatcher.user.in_(me))
    rows = db.scalars(select(Issue).where(
        Issue.deleted_at.is_(None), Issue.closed_at.is_(None),
        or_(Issue.assignee.in_(me), Issue.created_by.in_(me), Issue.uid.in_(watched)))
        .order_by(Issue.updated_at.desc().nulls_last()).limit(300))
    allowed: dict[str, bool] = {}
    names: dict[str, str] = {}
    out = []
    for i in rows:
        if not hub.is_open(i):
            continue
        if i.workspace_id not in allowed:
            allowed[i.workspace_id] = resolve_permission(db, identity.user, i.workspace_id, "read", "tickets")
            ws = db.get(Workspace, i.workspace_id)
            names[i.workspace_id] = ws.name if ws else i.workspace_id
        if not allowed[i.workspace_id] or not may_see(db, i, identity.user.id):
            continue
        why = "assigned" if i.assignee in me else ("reported" if i.created_by in me else "watching")
        out.append({**hub.ticket_summary(i), "workspace_id": i.workspace_id,
                    "workspace_name": names[i.workspace_id], "why": why})
        if len(out) >= 100:
            break
    order = {"assigned": 0, "reported": 1, "watching": 2}
    return sorted(out, key=lambda t: order[t["why"]])
