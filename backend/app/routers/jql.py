"""Advanced query (services/jql.py), over tickets, equipment and documents."""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, PatIdentity, get_identity, grants_of
from app.db import get_db
from app.services import jql
from app.services import knowledge_hub as hub
from app.services.permissions import resolve_permission

router = APIRouter(prefix="/v1/search", tags=["search"])

RESOURCE = {"tickets": "tickets", "assets": "objects", "documents": "documents"}


@router.get("/jql/fields")
def jql_fields(identity=Depends(get_identity)):
    """For each kind of record, the fields a query can name, what they mean and whether results can be
    ordered by them. Any other name is one of the record's attributes."""
    return jql.field_reference()


@router.get("/jql")
def search_jql(
    entity: str = Query(..., pattern="^(tickets|assets|documents)$"),
    q: str = Query("", alias="jql", max_length=4000, description='e.g. status = Open AND assignee = currentUser()'),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
):
    """Tickets, equipment or documents selected by an advanced query. Without `project = …` the query searches the
    current workspace (and what is shared with every workspace); `project in (a, b)` searches those the person
    may read. A query that cannot be read answers 422 with where it went wrong."""
    from app.models.workspace import Workspace
    from app.services.notify import may_see
    from app.services.visibility import can_see
    resource = RESOURCE[entity]
    if isinstance(identity, PatIdentity):
        if not identity.may("read", resource):
            raise HTTPException(status_code=403, detail="Not permitted")
        workspaces, current, user_ids = [identity.workspace_id], identity.workspace_id, []
        user = None
    else:
        user = identity.user
        user_ids = [x for x in (user.id, user.email) if x]
        from sqlalchemy import select
        workspaces = [w for w in db.scalars(select(Workspace.id))
                      if resolve_permission(db, user, w, "read", resource)]
        current = x_workspace_id if x_workspace_id in workspaces else None
        if x_workspace_id and current is None:
            raise HTTPException(status_code=403, detail="Not permitted")
    cache: dict[str, object] = {}

    def grants(ws: str):
        if ws not in cache:
            cache[ws] = identity.grants if isinstance(identity, PatIdentity) and hasattr(identity, "grants") \
                else grants_of(db, identity, ws)
        return cache[ws]

    def visible(record) -> bool:
        if entity == "tickets":
            return user is None or may_see(db, record, user.id)
        if entity == "assets":
            return can_see(record, grants(record.workspace_id if record.workspace_id in workspaces else (current or record.workspace_id)))
        if record.confidentiality == "riservato" and user is not None and not user.is_admin \
                and user.id != record.owner_user_id \
                and not resolve_permission(db, user, record.workspace_id, "approve", "documents"):
            return False
        return True

    try:
        found = jql.run(db, entity, q, user_ids=user_ids, workspaces=workspaces, current_workspace=current,
                        visible=visible, grants=grants(current) if current else None, limit=limit, offset=offset)
    except jql.JqlError as e:
        raise HTTPException(status_code=422, detail={"error": e.message, "position": e.position, "code": "jql"})
    names = {w.id: w.name for w in db.query(Workspace).filter(Workspace.id.in_({r.workspace_id for r in found["rows"]}))}
    if entity == "tickets":
        items = [{**hub.ticket_summary(r), "workspace_id": r.workspace_id} for r in found["rows"]]
    elif entity == "assets":
        items = [hub.asset_summary(r) for r in found["rows"]]
    else:
        items = [hub.document_summary(db, r) for r in found["rows"]]
    for item in items:
        item["workspace_name"] = names.get(item.get("workspace_id"), item.get("workspace_id"))
    return {"entity": entity, "jql": q, "total": found["total"], "capped": found["capped"],
            "offset": offset, "items": items}
