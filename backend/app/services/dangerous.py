"""The few actions that cannot be taken back and reach a whole workspace (docs/dangerous-actions.md): deleting
it, making it global, deleting a type with every record of it, deleting its orphaned objects in bulk.

Each one is done only by a person signed in to ARGUS — never with an API token, so never from an MCP client or a
script — and only when the request carries the workspace's name, typed by that person, in `X-Confirm-Workspace`
(percent-encoded, as a header is plain ASCII). The web asks twice: the question, then the name.
"""
from typing import Optional
from urllib.parse import unquote

from fastapi import Header, HTTPException

from app.auth import PatIdentity, token_scope
from app.models.workspace import Workspace

HEADER = "X-Confirm-Workspace"


def confirm_header(x_confirm_workspace: Optional[str] = Header(default=None)) -> Optional[str]:
    """The name typed to confirm, as sent."""
    return unquote(x_confirm_workspace) if x_confirm_workspace is not None else None


def by_a_person(identity) -> bool:
    return not isinstance(identity, PatIdentity) and token_scope(identity) is None


def require(identity, workspace: Workspace, typed: Optional[str], what: str) -> None:
    """Refuse `what` unless a person signed in asks for it and typed the workspace's name exactly."""
    if not by_a_person(identity):
        raise HTTPException(status_code=403, detail={
            "error": f"{what} cannot be done with an API token or from MCP: a person signed in to ARGUS does it, "
                     "typing the workspace's name to confirm.",
            "code": "person_only"})
    if (typed or "").strip() != (workspace.name or "").strip():
        raise HTTPException(status_code=428, detail={
            "error": f"{what} needs the workspace's name, “{workspace.name}”, typed to confirm "
                     f"(the {HEADER} header).",
            "code": "confirm_workspace_name", "workspace": workspace.name})
