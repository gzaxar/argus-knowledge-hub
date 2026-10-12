"""What an importer needs a workspace to have, said up front instead of installed behind its back.

An importer declares the capabilities it needs (a package's `provides`: `object-catalogue`,
`accelerator-catalogue`, `tickets`, `documents`). `require` checks the workspace's package record and, when
a capability is missing, stops with what to install and where — it never installs anything itself, so
importing IT or plant data cannot bring accelerator types in, and a workspace's definitions change only
through the installer (previewed, recorded).

What an import may still create are the types its data names (a Jira issue type, an Insight object type,
a source's own record type): those are the data's, not a package's.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.packages.loader import available


class MissingPrerequisite(ValueError):
    """The workspace lacks a package an import needs. A ValueError, so every import's error path already
    reports it; `code` lets an API say which."""
    code = "missing_package"

    def __init__(self, workspace_id: str, capability: str, offered_by: list[str]):
        self.workspace_id, self.capability, self.offered_by = workspace_id, capability, offered_by
        names = ", ".join(offered_by) or "a package that provides it"
        super().__init__(
            f"Workspace “{workspace_id}” has no {capability.replace('-', ' ')}: this import needs it. Install "
            f"{names} first, on the workspace's Packages page (or POST /v1/workspaces/{workspace_id}/packages/"
            f"install) — nothing was imported.")


def providers(capability: str) -> list[str]:
    """The shipped packages that provide a capability."""
    return sorted(p.id for p in available().values() if capability in p.provides)


def capabilities(db: Session, workspace_id: str) -> set[str]:
    """What the packages a workspace has provide."""
    from app.packages.install import installed
    shipped = available()
    out: set[str] = set()
    for package_id in installed(db, workspace_id):
        p = shipped.get(package_id)
        if p is not None:
            out.update(p.provides)
    return out


def require(db: Session, workspace_id: str, *needed: str) -> None:
    """Stop the import, before it writes anything, unless the workspace has every capability needed."""
    have = capabilities(db, workspace_id)
    if any(c not in have for c in needed):
        # A workspace given its definitions before the record began (or by a script around the installer)
        # has them all the same: what it evidently has is recorded first — nothing is installed.
        from app.packages.install import detect_workspace
        if detect_workspace(db, workspace_id):
            have = capabilities(db, workspace_id)
    for capability in needed:
        if capability not in have:
            raise MissingPrerequisite(workspace_id, capability, providers(capability))


def missing(db: Session, workspace_id: str, needed: Iterable[str]) -> list[str]:
    have = capabilities(db, workspace_id)
    return [c for c in needed if c not in have]
