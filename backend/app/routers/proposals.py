"""Proposals sent by assistants through MCP, for a person to apply or discard (services/mcp_proposals.py).

- `GET /v1/proposals?status=proposed|applied|failed|discarded|all` — this workspace's proposals, newest first.
- `POST /v1/proposals/apply` and `/discard` with `{"ids": [...]}` — only a person signed in: a token may propose,
  never decide. Applying needs the right each change needs (create, modify, delete; tickets; documents) and runs
  through the same code as the forms, in the applying person's name.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.routers.ledger import actor_of
from app.services import mcp_proposals

router = APIRouter(prefix="/v1/proposals", tags=["proposals"])


class Chosen(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


def _person(identity) -> OidcIdentity:
    if not isinstance(identity, OidcIdentity) or identity.token is not None:
        raise HTTPException(status_code=403, detail="Only a person signed in applies or discards a proposal")
    return identity


@router.get("")
def list_proposals(status: Optional[str] = Query("proposed"), workspace_id: str = Depends(require_permission("read")),
                   db: Session = Depends(get_db)):
    return mcp_proposals.listed(db, workspace_id, status=None if status == "all" else status)


@router.post("/apply")
def apply_proposals(body: Chosen, workspace_id: str = Depends(require_permission("read")),
                    identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    return mcp_proposals.apply(db, person, workspace_id, actor_of(person), body.ids)


@router.post("/discard")
def discard_proposals(body: Chosen, workspace_id: str = Depends(require_permission("read")),
                      identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    return mcp_proposals.discard(db, workspace_id, actor_of(person), body.ids)
