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
from typing import Optional

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


def has_objects(p: Package) -> bool:
    return bool((p.section("object_types") or {}).get("types"))


def _apply_package(db: Session, workspace_id: str, p: Package, options: dict) -> dict:
    """Any package but the core: its object types (in the scope the workspace takes them: self-contained, as
    the shared catalogue, or hanging from one), its Other Equipment classes, enumerations, and ticket and
    document kinds. Types the workspace already has (from the package that held them before) are left as they
    are: they are its, edits included; only the missing ones are made."""
    from app.services import asset_types, equipment_classes
    out: dict = {}
    scope = options.get("scope") or asset_types.SCOPE_ALL
    if has_objects(p):
        from app.packages import compile as c
        sets = {**defaults.option_sets(), **(p.section("option_sets") or {})}
        specs = [asset_types._spec(t) for t in c.object_types(p, sets)]      # this package's own, as given
        mine = [t for t in specs if scope == asset_types.SCOPE_ALL or asset_types.scope_of(t.name) == scope]
        here = {t.name for t in mine if db.get(Schema, asset_types.type_uid(workspace_id, t.name)) is not None}
        only = None if not here else {t.name for t in mine if t.name not in here}
        if only != set():
            r = asset_types.ensure_asset_types(db, workspace_id, scope=scope,
                                               catalogue_workspace_id=options.get("catalogue_workspace_id"),
                                               specs=specs, only=only)
            out.update({"created": r.created, "extended": r.extended, "adopted": r.adopted, "renamed": r.renamed,
                        "reused": r.reused, "duplicates": r.duplicates})
        if here:
            out["already_in_place"] = sorted(here)
    if p.section("equipment_classes") and scope != asset_types.SCOPE_BEAMLINE:
        out["equipment_classes_added"] = equipment_classes.seed(db)
    if p.section("enumerations"):
        out["enumerations_added"] = _add_enumerations(db, workspace_id, p)
    for area in ("ticket_types", "document_types"):
        kinds = [k["name"] for k in (p.section(area) or {}).get("kinds") or []]
        if kinds:
            out[f"{area}_added"] = _add_kinds(db, workspace_id, area, kinds)
    db.flush()
    return out


def _add_enumerations(db: Session, workspace_id: str, p: Package) -> list[str]:
    import uuid
    from app.models.global_value import GlobalValue
    from app.packages import compile as c
    have = {(g.applies_to, g.key) for g in db.scalars(select(GlobalValue).where(GlobalValue.workspace_id == workspace_id))}
    added = []
    for e in c.enumerations(p, defaults.option_sets()):
        if (e["applies_to"], e["key"]) in have:
            continue
        db.add(GlobalValue(uid=str(uuid.uuid4()), workspace_id=workspace_id, key=e["key"], name=e["name"],
                           type=e["type"], applies_to=e["applies_to"], is_system_default=True,
                           default_value=e["default"], options=e["options"]))
        added.append(f"{e['applies_to']}.{e['key']}")
    return added


def _add_kinds(db: Session, workspace_id: str, area: str, kinds: list[str]) -> list[str]:
    if area == "ticket_types":
        from app.services.ticket_types import ensure_ticket_kinds as ensure
    else:
        from app.services.document_types import ensure_document_kinds as ensure
    before = {s.name for s in db.scalars(select(Schema).where(Schema.workspace_id == workspace_id))}
    ensure(db, workspace_id, set(kinds))
    return [k for k in kinds if k not in before]


def _apply(db: Session, workspace_id: str, p: Package, options: dict) -> dict:
    return _apply_core(db, workspace_id, options) if p.id == defaults.CORE else _apply_package(db, workspace_id, p, options)


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


def _object_options(db: Session, workspace_id: str, catalogue_workspace_id: Optional[str],
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
    if any(has_objects(p) for p, _ in steps):
        options = _object_options(db, workspace_id, catalogue_workspace_id, scope)
    from app.services import catalogue_icons
    token = catalogue_icons.PREVIEW.set(not keep)
    savepoint = db.begin_nested()
    try:
        for p, step in steps:
            if step.action == "unchanged":
                continue
            own = options if has_objects(p) else {}
            if step.action == "upgrade":
                from app.packages import upgrade
                own = installed(db, workspace_id)[p.id].options or {}
                step.result = upgrade.apply(db, workspace_id, p, decisions) if keep else \
                    upgrade.preview(db, workspace_id, p, decisions)
            else:
                step.result = _apply(db, workspace_id, p, own)
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
    """Record the packages one workspace evidently has but no record names, as `detected`, at the version this
    release ships: core facility when it has the base ticket type; a package of object types when one of its
    types is here (or in the catalogue the workspace hangs from). Installs nothing. Returns how many."""
    from app.services import asset_types
    from app.services.ticket_types import BASE_UID_SUFFIX
    have = installed(db, ws)
    n = 0
    if defaults.CORE not in have and db.get(Schema, f"{ws}:{BASE_UID_SUFFIX}") is not None:
        _record(db, ws, available()[defaults.CORE], "detected", None, {}, None, None)
        n += 1
    hangs_from = None
    usable = None
    for pid in defaults.ordered():
        p = available()[pid]
        if pid in have or not has_objects(p):
            continue
        names = [t["name"] for t in p.section("object_types")["types"]]
        if usable is None:
            hangs_from = asset_types.catalogue_of(db, ws)
            usable = asset_types.resolve_type_uids(db, ws, hangs_from)
        own = next((r for r in (db.get(Schema, asset_types.type_uid(ws, n)) for n in names) if r is not None), None)
        if own is None and not (hangs_from and any(n in usable for n in names)):
            continue
        if own is not None and own.is_global:
            options = {"scope": asset_types.SCOPE_GLOBAL}
        elif hangs_from:
            options = {"scope": asset_types.SCOPE_BEAMLINE, "catalogue_workspace_id": hangs_from}
        else:
            options = {"scope": asset_types.SCOPE_ALL}
        _record(db, ws, p, "detected", None, options, None, None)
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
