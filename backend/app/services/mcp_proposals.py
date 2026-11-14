"""Proposals an assistant sends through the MCP server — Claude, ChatGPT or any MCP client (docs/mcp-proposals.md).

The MCP server stays read-only: these tools change nothing. Each call is checked as Ask ARGUS checks its own
proposals (services/ask_actions.py: the type exists, the records are there, the relation is one the rules allow)
and kept for a person, who applies or discards it in the Review queue ("Proposed by assistants"). Applying goes through the same code as
the forms, with that person's permissions, in their name in the ledger.

A day's proposals of one token (or one person) in one workspace are one conversation (`source = "mcp"`), so a
record proposed earlier that day is referred to as `new:N` by the next proposals: "create the six screens and
relate each to its camera" works across calls. Pull requests are not offered here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ask_conversation import AskAction, AskConversation
from app.services import ask_actions

OFFERED = ("propose_create_record", "propose_update_record", "propose_relation", "propose_ticket", "propose_document")

GUIDE = (
    "You may propose changes: propose_create_record, propose_update_record, propose_relation, propose_ticket and "
    "propose_document. A proposal changes nothing: it waits in the workspace's Review queue for a person, who "
    "applies or discards it — never say a change was made. Look records up first and use their keys. A record you "
    "propose to create is new:N (N is in the reply) for your next proposals of the same day. A refused proposal "
    "says why: correct it rather than repeat it.\n"
)


def tools() -> list[dict]:
    """The proposal tools as MCP describes tools: not read-only, but neither destructive nor reaching outside."""
    out = []
    for spec in ask_actions.tool_specs():
        f = spec["function"]
        if f["name"] not in OFFERED:
            continue
        out.append({"name": f["name"], "description": f["description"] + " It waits for a person in the "
                    "workspace's Review queue.", "inputSchema": f["parameters"],
                    "annotations": {"title": f["name"].replace("_", " ").capitalize(), "readOnlyHint": False,
                                    "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}})
    return out


def owner_of(identity) -> str:
    """Who the proposals are from: the person (also through their personal token), or the workspace token."""
    from app.routers.ledger import actor_of
    return actor_of(identity)


def _label(identity) -> str:
    from app.auth import PatIdentity
    if isinstance(identity, PatIdentity):
        return f"token {identity.name}" if identity.name else "a workspace token"
    user = identity.user
    return f"{user.name or user.email or 'a person'}'s assistant"


def kind_of(name: str, arguments: dict) -> str:
    return {"propose_create_record": "create", "propose_update_record": "update", "propose_ticket": "ticket",
            "propose_document": "document"}.get(name) or ("unrelate" if arguments.get("remove") else "relate")


def may_propose(db: Session, identity, workspace_id: str, kind: str) -> bool:
    """What the caller could do by hand: a proposal to create needs the right to create, and so on. The person who
    applies it needs it too."""
    from app.auth import PatIdentity
    from app.services.permissions import resolve_permission
    action, resource = ask_actions.PERMISSION[kind], ask_actions.RESOURCE.get(kind, "objects")
    if isinstance(identity, PatIdentity):
        return identity.workspace_id == workspace_id and identity.may(action, resource)
    if identity.token is not None and not identity.token.may(action, resource):
        return False
    return resolve_permission(db, identity.user, workspace_id, action, resource)


def conversation_for(db: Session, workspace_id: str, identity) -> AskConversation:
    owner = owner_of(identity)
    today = datetime.now(timezone.utc).date().isoformat()
    title = f"Proposals from {_label(identity)} — {today}"
    found = db.scalar(select(AskConversation).where(
        AskConversation.workspace_id == workspace_id, AskConversation.owner == owner,
        AskConversation.source == "mcp", AskConversation.title == title))
    if found is None:
        found = AskConversation(id=str(uuid.uuid4()), workspace_id=workspace_id, owner=owner, title=title,
                                source="mcp", client=_label(identity))
        db.add(found)
        db.flush()
    return found


def propose(db: Session, workspace_id: str, identity, name: str, arguments: dict, link_base: str = "") -> dict:
    """One proposal, checked and kept; or the reason it is refused."""
    if name not in OFFERED:
        raise KeyError(name)
    kind = kind_of(name, arguments or {})
    if not may_propose(db, identity, workspace_id, kind):
        raise ask_actions.Refused(f"you may not {ask_actions.PERMISSION[kind]} "
                                  f"{ask_actions.RESOURCE.get(kind, 'objects')} in this workspace, so you may not "
                                  "propose it either")
    conversation = conversation_for(db, workspace_id, identity)
    out = ask_actions.Proposer(db, workspace_id, conversation.id, turn_seq=0)(name, arguments or {})
    out.pop("_action", None)
    out["review"] = f"{link_base}/review" if link_base else "/review"
    out["status"] = "waiting in the Review queue for a person to apply or discard it: nothing has changed yet"
    return out


# --------------------------------------------------------------------------- the Review queue's section

def listed(db: Session, workspace_id: str, status: Optional[str] = "proposed", limit: int = 500) -> list[dict]:
    q = (select(AskAction, AskConversation).join(AskConversation, AskConversation.id == AskAction.conversation_id)
         .where(AskConversation.workspace_id == workspace_id, AskConversation.source == "mcp"))
    if status:
        q = q.where(AskAction.status == status)
    rows = db.execute(q.order_by(AskConversation.created_at.desc(), AskAction.number).limit(limit))
    return [{**ask_actions.view(a), "conversation": {"id": c.id, "title": c.title, "from": c.client},
             "created_at": a.created_at} for a, c in rows]


def _by_conversation(db: Session, workspace_id: str, ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a, c in db.execute(select(AskAction, AskConversation).join(
            AskConversation, AskConversation.id == AskAction.conversation_id).where(
            AskAction.id.in_(ids), AskConversation.workspace_id == workspace_id, AskConversation.source == "mcp")):
        out.setdefault(c.id, []).append(a.id)
    return out


def apply(db: Session, identity, workspace_id: str, actor: str, ids: list[str]) -> list[dict]:
    """Apply the chosen proposals, each conversation's in the order they were made, as the person applying."""
    for conversation_id, chosen in _by_conversation(db, workspace_id, ids).items():
        ask_actions.apply(db, identity, workspace_id, actor, conversation_id, chosen)
    return [x for x in listed(db, workspace_id, status=None) if x["id"] in set(ids)]


def discard(db: Session, workspace_id: str, actor: str, ids: list[str]) -> list[dict]:
    for conversation_id, chosen in _by_conversation(db, workspace_id, ids).items():
        ask_actions.discard(db, actor, conversation_id, chosen)
    return [x for x in listed(db, workspace_id, status=None) if x["id"] in set(ids)]
