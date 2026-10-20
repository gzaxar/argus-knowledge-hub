"""The hub as an MCP server.

Served from this application rather than as a separate process, because
everything it needs is already here: the same Bearer token, the same
permission check, the same workspace scoping. A second service would have
to reimplement all three and could get them subtly wrong.

The transport is streamable HTTP: one POST carrying a JSON-RPC request,
answered with JSON. There is no server-initiated stream — these tools
answer immediately — so GET is refused, which the specification allows.
"""
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, PatIdentity, get_identity, grants_of, require_permission
from app.db import get_db
from app.models.workspace import Workspace
from app.services.mcp_tools import call, catalogue
from app.services.permissions import resolve_permission
from app.services.visibility import set_current_grants

router = APIRouter(prefix="/mcp", tags=["mcp"])
log = logging.getLogger(__name__)

# The revision of the protocol this speaks. Clients send their own; the
# specification says to answer with one we support rather than theirs.
PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {"name": "argus-knowledge-hub", "version": "1.0.0"}

INSTRUCTIONS = (
    "The structured knowledge of an accelerator: equipment, the work done on it, and "
    "the documentation that covers it.\n\n"
    "Prefer graph_neighbours for anything that spans records — what has gone wrong "
    "with a piece of equipment before, which procedure covers it, what it depends on. "
    "Searching text alone will miss those, because the answer is not in one document.\n"
    "For EPICS IOCs built with ibek (drivers, ibek-templates, a beamline values.yaml entry) use the ioc_* "
    "tools: ioc_search first, and ioc_render to check an entry before proposing it; ioc_scaffold_module "
    "writes a new support module (asyn driver or StreamDevice, SNL sequences, simulator, ibek files) from a "
    "description of the device.\n"
    "Every tool works in one workspace: the request's own (its X-Workspace-Id, or the one the token is "
    "fixed to) unless you pass `workspace`. list_workspaces says which ones you may ask in; to answer "
    "across workspaces, call a tool once per workspace.\n"
    "Everything here is read-only."
)

# Offered to MCP clients only. Ask ARGUS uses the same tools inside one
# workspace, so neither of these belongs in the shared catalogue.
LIST_WORKSPACES = {
    "name": "list_workspaces",
    "description": "The workspaces this token may ask in (id, name, whether shared), and which one is "
                   "used when a tool is called without `workspace`.",
    "inputSchema": {"type": "object", "properties": {}},
}
WORKSPACE_ARGUMENT = {
    "type": "string",
    "description": "The workspace id to ask in (see list_workspaces); omit for the request's own",
}


def _tools() -> list[dict]:
    tools = [LIST_WORKSPACES]
    for tool in catalogue():
        schema = dict(tool["inputSchema"])
        schema["properties"] = {**schema.get("properties", {}), "workspace": WORKSPACE_ARGUMENT}
        tools.append({**tool, "inputSchema": schema})
    return tools


def _may_read(db: Session, identity: Identity, workspace_id: str) -> bool:
    """The check require_permission("read") makes for the header, for any workspace."""
    if isinstance(identity, PatIdentity):
        return workspace_id == identity.workspace_id      # a robot works for its own workspace only
    if identity.token is not None:
        if not identity.token.may("read", "objects"):
            return False
        if identity.token.workspace_id and identity.token.workspace_id != workspace_id:
            return False
    return resolve_permission(db, identity.user, workspace_id, "read", "objects")


def _workspaces(db: Session, identity: Identity, current: str) -> dict:
    # A staging import is nobody's yet; read-only evidence can be asked.
    rows = db.scalars(select(Workspace).where(Workspace.import_state.is_distinct_from("staging"))
                      .order_by(Workspace.name))
    return {
        "current": current,
        "workspaces": [{"id": w.id, "name": w.name, "shared": bool(w.is_global)}
                       for w in rows if _may_read(db, identity, w.id)],
    }


def _result(request_id: Any, payload: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": payload})


def _error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


@router.get("")
@router.get("/")
def no_server_stream() -> Response:
    """These tools answer on the spot; there is nothing to stream."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("")
@router.post("/")
async def rpc(
    request: Request,
    workspace_id: str = Depends(require_permission("read")),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> Response:
    try:
        body = await request.json()
    except Exception:
        return _error(None, -32700, "The request body was not JSON.")

    if isinstance(body, list):
        # Batches are legal but nothing sends them here; saying so beats
        # answering the first one and silently dropping the rest.
        return _error(None, -32600, "Batched requests are not supported.")

    method: Optional[str] = body.get("method")
    request_id = body.get("id")

    # Notifications carry no id and expect no body.
    if request_id is None and (method or "").startswith("notifications/"):
        return Response(status_code=202)

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": _tools()})

    if method == "tools/call":
        params = body.get("params") or {}
        name = params.get("name")
        arguments = dict(params.get("arguments") or {})
        if name == LIST_WORKSPACES["name"]:
            return _result(request_id, {
                "content": [{"type": "text", "text": json.dumps(_workspaces(db, identity, workspace_id))}],
                "isError": False,
            })
        target = arguments.pop("workspace", None) or workspace_id
        if target != workspace_id:
            # Another workspace for this one call: the same read check the
            # header gets, and that workspace's restricted-field grants.
            if db.get(Workspace, target) is None or not _may_read(db, identity, target):
                return _result(request_id, {
                    "content": [{"type": "text", "text": f"You may not ask in workspace {target!r}; "
                                                         "list_workspaces says where you may."}],
                    "isError": True,
                })
            set_current_grants(grants_of(db, identity, target))
        try:
            text = call(db, target, name, arguments)
        except KeyError:
            return _error(request_id, -32602, f"No such tool: {name}")
        except Exception as e:
            # A failing tool is a result the model should see and work
            # around, not a transport error that kills the conversation.
            log.exception("MCP tool %s failed", name)
            return _result(request_id, {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            })
        return _result(request_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        })

    return _error(request_id, -32601, f"Unsupported method: {method}")
