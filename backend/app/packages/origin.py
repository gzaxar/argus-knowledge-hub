"""Where a type comes from, for the type tree and a type's page: a package (which, at which version the
workspace holding the type has it), an import (Jira, Insight…), or made in that workspace.

A type is from a package when a package installed in the workspace that holds it defines it by name: an object
type, a ticket or document kind, the base Ticket and Document (core-facility), or a type brought home by a type
migration (its own record of the package). Where it is stored — the workspace itself, or the shared catalogue a
workspace hangs from — does not change where it comes from.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.package import WorkspacePackage
from app.models.schema import Schema
from app.packages.loader import available

BASE = {("tickets", "Ticket"): "core-facility", ("documents", "Document"): "core-facility"}


def _defined() -> dict[tuple[str, str], list[str]]:
    """(applies_to, type name) -> the shipped packages that define it, in installation order."""
    from app.packages import defaults
    out: dict[tuple[str, str], list[str]] = {}
    for pid in defaults.ordered() + tuple(sorted(set(available()) - set(defaults.ordered()))):
        p = available().get(pid)
        if p is None:
            continue
        for t in (p.section("object_types") or {}).get("types") or []:
            out.setdefault(("objects", t["name"]), []).append(pid)
        for area, applies in (("ticket_types", "tickets"), ("document_types", "documents")):
            for k in (p.section(area) or {}).get("kinds") or []:
                out.setdefault((applies, k["name"]), []).append(pid)
    for key, pid in BASE.items():
        out.setdefault(key, []).append(pid)
    return out


def origins(db: Session, schemas: Iterable[Schema]) -> dict[str, dict]:
    """uid -> origin, for the types given: {"kind": "package", "package", "version", "package_name"} |
    {"kind": "import", "source"} | {"kind": "local"}."""
    schemas = list(schemas)
    owners = {s.workspace_id for s in schemas}
    installed: dict[str, dict[str, str]] = {}
    for r in db.scalars(select(WorkspacePackage).where(WorkspacePackage.workspace_id.in_(owners))):
        installed.setdefault(r.workspace_id, {})[r.package_id] = r.version
    defined = _defined()
    names = {pid: p.name for pid, p in available().items()}
    out = {}
    for s in schemas:
        meta = s.metadata_json or {}
        have = installed.get(s.workspace_id, {})
        home = (meta.get("brought_home") or {}).get("package")
        pid: Optional[str] = home if home in have else next(
            (p for p in defined.get((s.applies_to or "objects", s.name), []) if p in have), None)
        if pid:
            out[s.uid] = {"kind": "package", "package": pid, "version": have[pid], "package_name": names.get(pid, pid)}
        elif meta.get("source") and meta.get("source") != "argus":
            out[s.uid] = {"kind": "import", "source": str(meta["source"])}
        else:
            out[s.uid] = {"kind": "local"}
    return out
