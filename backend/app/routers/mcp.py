"""The hub as an MCP server.

Served from this application rather than as a separate process, because
everything it needs is already here: the same Bearer token, the same
permission check, the same workspace scoping. A second service would have
to reimplement all three and could get them subtly wrong.

The transport is streamable HTTP: one POST carrying a JSON-RPC request,
answered with JSON. There is no server-initiated stream — these tools
answer immediately — so GET is refused, which the specification allows.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.db import get_db
from app.services.mcp_tools import call, catalogue

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
    "Everything here is read-only."
)


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
        return _result(request_id, {"tools": catalogue()})

    if method == "tools/call":
        params = body.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            text = call(db, workspace_id, name, arguments)
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
