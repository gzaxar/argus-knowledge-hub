"""The header a person sends with a dangerous action: the workspace's name, typed (services/dangerous.py)."""
from urllib.parse import quote

from app.db import SessionLocal
from app.models.workspace import Workspace


def typed(workspace_id: str) -> dict:
    db = SessionLocal()
    try:
        ws = db.get(Workspace, workspace_id)
        return {"X-Confirm-Workspace": quote(ws.name)} if ws is not None else {}
    finally:
        db.close()
