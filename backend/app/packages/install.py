"""Putting packages in a workspace, in one transaction, and keeping the record of exactly what it uses.

* `plan` says what installing would do (each package with its dependencies first: install, upgrade, or
  unchanged), and what it would create and extend, by running the real installation and rolling it back.
* `install` does it. Everything happens in one savepoint: if any package fails, none is applied.
* Reapplying the version a workspace already has, with the same checksum, changes nothing at all.
* A workspace's record (`WorkspacePackage`) says which version of each package it has and the checksum of
  what was applied; its history (`PackageInstallation`) every install, upgrade, seeding by an import, and
  the packages found already in place when the record began (`detected`).

Installing a package is today's seeding, fed from the package (Phase 2 kept it byte-for-byte). Moving to a
newer version goes through app/packages/upgrade.py: additive and definition changes by themselves, each
breaking one by a decision in the migration plan, all recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from packaging.version import Version
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.package import PackageInstallation, WorkspacePackage
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.packages import defaults
from app.packages.loader import available
from app.packages.model import Package
from app.packages.validate import validate


class PackageProblem(ValueError):
    """Packages that cannot be installed as asked: unknown, invalid, or not installable here."""


@dataclass
class Step:
    package_id: str
    version: str
    checksum: str
    action: str                       # install | upgrade | unchanged
    from_version: Optional[str] = None
    requested: bool = True            # asked for, or there as a dependency
    result: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"package_id": self.package_id, "version": self.version, "checksum": self.checksum,
                "action": self.action, "from_version": self.from_version, "requested": self.requested,
                "result": self.result}


@dataclass
class Plan:
    workspace_id: str
    steps: list[Step]
    options: dict

    @property
    def changes(self) -> bool:
        return any(s.action != "unchanged" for s in self.steps)

    def as_dict(self) -> dict:
        return {"workspace_id": self.workspace_id, "options": self.options, "changes": self.changes,
                "steps": [s.as_dict() for s in self.steps]}


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- what each package does

def _apply_core(db: Session, workspace_id: str, options: dict) -> dict:
    from app.routers.workspaces import seed_default_global_values, seed_default_ticket_types
    from app.services.document_types import ensure_document_types
    before = _count(db, workspace_id)
    seed_default_global_values(db, workspace_id)
    seed_default_ticket_types(db, workspace_id)
    ensure_document_types(db, workspace_id)
    db.flush()
    return _added(db, workspace_id, before)


def _apply_accelerator(db: Session, workspace_id: str, options: dict) -> dict:
    from app.services import asset_types, equipment_classes
    scope = options.get("scope") or asset_types.SCOPE_ALL
    result = asset_types.ensure_asset_types(db, workspace_id, scope=scope,
                                            catalogue_workspace_id=options.get("catalogue_workspace_id"))
    classes = equipment_classes.seed(db) if scope != asset_types.SCOPE_BEAMLINE else []
    return {"created": result.created, "extended": result.extended, "adopted": result.adopted,
            "renamed": result.renamed, "reused": result.reused, "duplicates": result.duplicates,
            "equipment_classes_added": classes}


# Each installable package and how it is applied. A package is installable once ARGUS knows how to apply
# what it holds; the domain packages (IT, plant…) come with the release that applies them.
APPLIERS: dict[str, Callable[[Session, str, dict], dict]] = {
    defaults.CORE: _apply_core,
    defaults.ACCELERATOR: _apply_accelerator,
}


def _count(db: Session, workspace_id: str) -> dict:
    from app.models.global_value import GlobalValue
    return {"schemas": set(db.scalars(select(Schema.uid).where(Schema.workspace_id == workspace_id))),
            "values": set(db.scalars(select(GlobalValue.uid).where(GlobalValue.workspace_id == workspace_id)))}


def _added(db: Session, workspace_id: str, before: dict) -> dict:
    after = _count(db, workspace_id)
    names = {s.uid: s.name for s in db.scalars(select(Schema).where(
        Schema.uid.in_(after["schemas"] - before["schemas"])))}
    return {"created": sorted(names.values()), "enumerations_added": len(after["values"] - before["values"])}


# --------------------------------------------------------------------------- resolving

def resolve(package_ids: list[str], catalog: Optional[dict[str, Package]] = None) -> list[tuple[Package, bool]]:
    """The packages to apply, each after what it depends on: (package, requested)."""
    catalog = catalog if catalog is not None else available()
    order: list[tuple[Package, bool]] = []
    placed: set[str] = set()

    def visit(pid: str, requested: bool, trail: tuple) -> None:
        if pid in trail:
            raise PackageProblem(f"circular dependency: {' → '.join(trail + (pid,))}")
        p = catalog.get(pid)
        if p is None:
            raise PackageProblem(f"no package {pid!r}")
        problems = validate(p, catalog)
        if problems:
            raise PackageProblem(f"package {pid} is not valid: " + "; ".join(str(x) for x in problems[:5]))
        if pid not in APPLIERS:
            raise PackageProblem(f"package {pid} cannot be installed by this release of ARGUS")
        for dep in p.depends:
            visit(dep, False, trail + (pid,))
        if pid not in placed:
            placed.add(pid)
            order.append((p, requested))
        elif requested:
            order[:] = [(q, r or q.id == pid) for q, r in order]

    for pid in package_ids:
        visit(pid, True, ())
    return order


def installed(db: Session, workspace_id: str) -> dict[str, WorkspacePackage]:
    return {r.package_id: r for r in db.scalars(select(WorkspacePackage).where(
        WorkspacePackage.workspace_id == workspace_id))}


def _accelerator_options(db: Session, workspace_id: str, catalogue_workspace_id: Optional[str],
                         scope: Optional[str]) -> dict:
    """How the object catalogue goes in: hanging from a catalogue workspace (beamline), as the catalogue
    others hang from (global), or self-contained (all)."""
    from app.services import asset_types
    if catalogue_workspace_id:
        if catalogue_workspace_id == workspace_id:
            raise PackageProblem("a workspace cannot be its own catalogue")
        return {"scope": asset_types.SCOPE_BEAMLINE, "catalogue_workspace_id": catalogue_workspace_id}
    if scope == asset_types.SCOPE_GLOBAL:
        return {"scope": asset_types.SCOPE_GLOBAL}
    hangs_from = asset_types.catalogue_of(db, workspace_id)
    if hangs_from:
        return {"scope": asset_types.SCOPE_BEAMLINE, "catalogue_workspace_id": hangs_from}
    return {"scope": asset_types.SCOPE_ALL}


def _steps(db: Session, workspace_id: str, package_ids: list[str]) -> list[tuple[Package, Step]]:
    have = installed(db, workspace_id)
    out = []
    for p, requested in resolve(package_ids):
        row = have.get(p.id)
        if row is None:
            action = "install"
        elif row.version == p.version and row.checksum == p.checksum:
            action = "unchanged"
        elif row.version == p.version:
            raise PackageProblem(f"package {p.id} {p.version} differs from what this workspace was given at the same "
                                 f"version: a package that changes must raise its version")
        elif Version(p.version) < Version(row.version):
            raise PackageProblem(f"workspace has {p.id} {row.version}; this installation ships the older {p.version}")
        else:
            action = "upgrade"
        out.append((p, Step(p.id, p.version, p.checksum, action, row.version if row else None, requested)))
    return out


# --------------------------------------------------------------------------- planning and installing

def _run(db: Session, workspace_id: str, package_ids: list[str], *, catalogue_workspace_id: Optional[str],
         scope: Optional[str], actor: Optional[str], keep: bool, decisions: Optional[dict] = None) -> Plan:
    if db.get(Workspace, workspace_id) is None:
        raise PackageProblem(f"no workspace {workspace_id!r}")
    steps = _steps(db, workspace_id, package_ids)
    options = {}
    if any(p.id == defaults.ACCELERATOR for p, _ in steps):
        options = _accelerator_options(db, workspace_id, catalogue_workspace_id, scope)
    from app.services import catalogue_icons
    token = catalogue_icons.PREVIEW.set(not keep)
    savepoint = db.begin_nested()
    try:
        for p, step in steps:
            if step.action == "unchanged":
                continue
            own = options if p.id == defaults.ACCELERATOR else {}
            if step.action == "upgrade":
                from app.packages import upgrade
                own = installed(db, workspace_id)[p.id].options or {}
                step.result = upgrade.apply(db, workspace_id, p, decisions) if keep else \
                    upgrade.preview(db, workspace_id, p, decisions)
            else:
                step.result = APPLIERS[p.id](db, workspace_id, own)
            if keep:
                _record(db, workspace_id, p, step.action, step.from_version, own, step.result, actor)
        db.flush()
    except Exception:
        savepoint.rollback()
        raise
    finally:
        catalogue_icons.PREVIEW.reset(token)
    if keep:
        savepoint.commit()
    else:
        savepoint.rollback()
    return Plan(workspace_id, [s for _, s in steps], options)


def plan(db: Session, workspace_id: str, package_ids: list[str], *, catalogue_workspace_id: Optional[str] = None,
         scope: Optional[str] = None, decisions: Optional[dict] = None) -> Plan:
    """What installing these packages would do, applied and rolled back: nothing is kept."""
    from app.services.asset_types import CatalogueMissing
    try:
        return _run(db, workspace_id, package_ids, catalogue_workspace_id=catalogue_workspace_id, scope=scope,
                    actor=None, keep=False, decisions=decisions)
    except (CatalogueMissing, ValueError) as e:
        raise PackageProblem(str(e)) from None


def install(db: Session, workspace_id: str, package_ids: list[str], *, actor: Optional[str] = None,
            catalogue_workspace_id: Optional[str] = None, scope: Optional[str] = None,
            decisions: Optional[dict] = None) -> Plan:
    """Install (or upgrade to) these packages and what they depend on, all or nothing. The caller commits."""
    from app.services.asset_types import CatalogueMissing
    try:
        return _run(db, workspace_id, package_ids, catalogue_workspace_id=catalogue_workspace_id, scope=scope,
                    actor=actor, keep=True, decisions=decisions)
    except (CatalogueMissing, ValueError) as e:
        raise PackageProblem(str(e)) from None


def _record(db: Session, workspace_id: str, p: Package, action: str, from_version: Optional[str], options: dict,
            result: Optional[dict], actor: Optional[str]) -> None:
    row = db.scalar(select(WorkspacePackage).where(WorkspacePackage.workspace_id == workspace_id,
                                                   WorkspacePackage.package_id == p.id))
    if row is None:
        row = WorkspacePackage(workspace_id=workspace_id, package_id=p.id)
        db.add(row)
    row.version, row.checksum, row.installed_at, row.installed_by = p.version, p.checksum, now(), actor
    row.options = options or None
    from app.packages.upgrade import snapshot
    snapshot(db, p)
    db.add(PackageInstallation(workspace_id=workspace_id, package_id=p.id, action=action, from_version=from_version,
                               to_version=p.version, checksum=p.checksum, result=result, actor=actor, at=now()))


def detect_workspace(db: Session, ws: str) -> int:
    """Record the packages one workspace evidently has but no record names (core facility when it has the
    base ticket type; the accelerator catalogue when it has the catalogue's root type, or hangs from a
    catalogue that has), as `detected`, at the version this release ships. Installs nothing. Returns how
    many it recorded."""
    from app.services import asset_types
    from app.services.ticket_types import BASE_UID_SUFFIX
    have = installed(db, ws)
    n = 0
    if defaults.CORE not in have and db.get(Schema, f"{ws}:{BASE_UID_SUFFIX}") is not None:
        _record(db, ws, available()[defaults.CORE], "detected", None, {}, None, None)
        n += 1
    if defaults.ACCELERATOR not in have:
        own_root = db.get(Schema, asset_types.type_uid(ws, asset_types.ROOT_NAME))
        hangs_from = asset_types.catalogue_of(db, ws)
        if own_root is not None or hangs_from:
            if hangs_from:
                options = {"scope": asset_types.SCOPE_BEAMLINE, "catalogue_workspace_id": hangs_from}
            elif own_root.is_global:
                options = {"scope": asset_types.SCOPE_GLOBAL}
            else:
                options = {"scope": asset_types.SCOPE_ALL}
            _record(db, ws, available()[defaults.ACCELERATOR], "detected", None, options, None, None)
            n += 1
    if n:
        db.flush()
    return n


def detect(db: Session) -> int:
    """Begin the record for every workspace made before it (detect_workspace), and keep the definitions of
    each version in use that this release ships (what a later upgrade compares against). Idempotent."""
    n = sum(detect_workspace(db, ws) for ws in list(db.scalars(select(Workspace.id))))
    from app.packages.upgrade import snapshot
    shipped = available()
    for row in db.scalars(select(WorkspacePackage)):
        p = shipped.get(row.package_id)
        if p is not None and p.checksum == row.checksum:
            snapshot(db, p)
    return n


def history(db: Session, workspace_id: str) -> list[PackageInstallation]:
    return list(db.scalars(select(PackageInstallation).where(PackageInstallation.workspace_id == workspace_id)
                           .order_by(PackageInstallation.id)))
