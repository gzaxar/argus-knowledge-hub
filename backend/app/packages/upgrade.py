"""Moving a workspace to a newer version of a package: previewed, applied with a migration plan, recorded.

`preview` lists every change (app/packages/diff.py) against the workspace: additive and definition changes
go in by themselves; each breaking one needs a decision in the plan — `apply` it, or `keep` the workspace's
definition — and some cannot be applied while records would be left invalid (the preview says how many).
`apply` carries the plan out in the installer's transaction and the history keeps every decision.
A workspace's own edits are kept: what it removed is not added back, what it relabelled is not relabelled.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.package import PackageSnapshot, WorkspacePackage
from app.models.schema import Schema
from app.packages import diff as d
from app.packages.loader import available
from app.packages.model import Package

KEEP, APPLY = "keep", "apply"


class PlanProblem(ValueError):
    pass


def snapshot(db: Session, p: Package) -> None:
    """Keep this version's definitions, once."""
    if db.scalar(select(PackageSnapshot).where(PackageSnapshot.package_id == p.id,
                                               PackageSnapshot.checksum == p.checksum)) is None:
        db.add(PackageSnapshot(package_id=p.id, version=p.version, checksum=p.checksum,
                               manifest=p.describe(), sections=p.sections))
        db.flush()


def _old(db: Session, row: WorkspacePackage) -> dict:
    snap = db.scalar(select(PackageSnapshot).where(PackageSnapshot.package_id == row.package_id,
                                                   PackageSnapshot.checksum == row.checksum))
    if snap is None:
        raise PlanProblem(f"there is no record of what {row.package_id} {row.version} held, so the upgrade cannot "
                          f"be compared; reinstalling it is not possible either — ask the ARGUS maintainers")
    return snap.sections


def _shared_sets() -> dict:
    out: dict = {}
    for p in available().values():
        out.update(p.section("option_sets") or {})
    return out


def _scope_names(row: WorkspacePackage, old_sections: dict, new: Package) -> Optional[set]:
    """The object types this workspace holds itself under its scope: a beamline its machine's own, the
    catalogue the shared ones; None when it holds them all."""
    from app.services import asset_types
    scope = (row.options or {}).get("scope") or asset_types.SCOPE_ALL
    if scope == asset_types.SCOPE_ALL:
        return None
    out: set = set()
    for sections in (old_sections, new.sections):
        section = sections.get("object_types") or {}
        parents = {t["name"]: t.get("parent") for t in section.get("types") or []}
        roots = set(section.get("beamline_roots") or [])
        for name in parents:
            cur, own = name, False
            while cur is not None:
                if cur in roots:
                    own = True
                    break
                cur = parents.get(cur)
            if (own and scope == asset_types.SCOPE_BEAMLINE) or (not own and scope == asset_types.SCOPE_GLOBAL):
                out.add(name)
    return out


def changes(db: Session, workspace_id: str, new: Package) -> list[d.Change]:
    row = db.scalar(select(WorkspacePackage).where(WorkspacePackage.workspace_id == workspace_id,
                                                   WorkspacePackage.package_id == new.id))
    if row is None:
        raise PlanProblem(f"workspace {workspace_id} does not have {new.id}")
    sets = _shared_sets()
    old_sections = _old(db, row)
    old = d.definitions(old_sections, new.id, sets)
    newer = d.definitions(new.sections, new.id, sets)
    found = _kept_by_extensions(db, workspace_id, new, _moved(new, d.compare(old, newer)))
    return d.assess(db, workspace_id, found, old, _scope_names(row, old_sections, new)), old


def _kept_by_extensions(db: Session, workspace_id: str, new: Package, found: list) -> list:
    """An attribute or option a package no longer defines itself, because a package the workspace also has now
    adds it as an extension (core-facility 2.0 left the beam vocabulary to the accelerator package), is not
    removed: it stays, held by that package. Without such a package it is removed like any other (a decision)."""
    from app.packages import compile as c
    from app.packages.install import installed
    held: dict = {}
    for pid in installed(db, workspace_id):
        p = available().get(pid)
        if p is None or pid == new.id:
            continue
        for e in c.extensions(p, _shared_sets()):
            for a in e.attributes:
                held[(e.area, e.type, a["key"])] = pid
            for key, opts in e.options.items():
                for o in opts:
                    held[(e.area, e.type, f"{key}:{o['id']}")] = pid
    out = []
    for ch in found:
        owner = held.get((ch.area, ch.subject, ch.element)) if ch.element else None
        if ch.what == "removed" and owner:
            out.append(d.Change(ch.id.rsplit("/", 1)[0] + "/moved", d.DEFINITION, ch.area, ch.subject, ch.element,
                                "moved", f"{ch.element.split(':')[-1]!r} on {ch.subject} is now added by {owner} "
                                         f"(unchanged)"))
            continue
        out.append(ch)
    return out


def _moved(new: Package, found: list) -> list:
    """A type (or an Other Equipment class) the package no longer holds because it moved to a package it now
    stands on (accelerator 2.0: the backbone to core-objects, IT to it) is not removed: it is the same type,
    in the workspace as it was, held by that package — which the same installation installs first."""
    from app.packages import defaults
    types: dict = {}
    classes: dict = {}
    for pid in defaults.closure(new.id):
        if pid == new.id:
            continue
        p = available()[pid]
        for t in (p.section("object_types") or {}).get("types") or []:
            types[t["name"]] = pid
        for cls in (p.section("equipment_classes") or {}).get("classes") or []:
            classes[cls] = pid
    out = []
    for ch in found:
        if ch.area == "object_types" and ch.subject in types:
            if ch.element is None and ch.what == "removed":
                out.append(d.Change(f"object_types/{ch.subject}/moved", d.DEFINITION, "object_types", ch.subject, None,
                                    "moved", f"type {ch.subject!r} is now in the package {types[ch.subject]} "
                                             f"(the same type, unchanged)"))
            continue                 # its attributes went with it: nothing to compare here
        if ch.area == "equipment_classes" and ch.what == "removed" and ch.subject in classes:
            out.append(d.Change(f"equipment_classes/{ch.subject}/moved", d.DEFINITION, "equipment_classes",
                                ch.subject, None, "moved", f"class {ch.subject!r} is now in {classes[ch.subject]}"))
            continue
        out.append(ch)
    return out


def preview(db: Session, workspace_id: str, new: Package, decisions: Optional[dict] = None) -> dict:
    found, _old_defs = changes(db, workspace_id, new)
    decisions = decisions or {}
    breaking = [c for c in found if c.category == d.BREAKING]
    undecided = [c.id for c in breaking if c.id not in decisions]
    blocked = [c.id for c in breaking if decisions.get(c.id) == APPLY and c.violations]
    return {"package_id": new.id, "to_version": new.version,
            "changes": [c.as_dict() for c in found],
            "automatic": [c.id for c in found if c.category != d.BREAKING],
            "needs_decision": [c.id for c in breaking], "undecided": undecided, "blocked": blocked,
            "conflicts": [c.id for c in found if c.conflict]}


# --------------------------------------------------------------------------- applying

def _schema_for(db: Session, workspace_id: str, ch: d.Change) -> Optional[Schema]:
    schemas = d.workspace_schemas(db, workspace_id, ch.area) if ch.area in (
        "object_types", "ticket_types", "document_types") else {}
    if ch.area in ("ticket_types", "document_types"):
        return schemas.get({"ticket_types": "Ticket", "document_types": "Document"}[ch.area]
                           if ch.subject == "base" else ch.subject)
    return schemas.get(ch.subject) or schemas.get((ch.before or {}).get("name") or "")


def _set_attrs(schema: Schema, attrs: list) -> None:
    schema.attributes = attrs
    flag_modified(schema, "attributes")


def _move_values(db: Session, workspace_id: str, area: str, schema: Schema, old_key: str, new_key: str) -> int:
    model, column, where = d._records(db, area, d._subtree(db, workspace_id, area, schema))
    n = 0
    for record in db.scalars(select(model).where(where, column.has_key(old_key))):
        attrs = dict(record.attributes or {})
        attrs.setdefault(new_key, attrs.pop(old_key))
        record.attributes = attrs
        flag_modified(record, "attributes")
        n += 1
    return n


def _apply_breaking(db: Session, workspace_id: str, ch: d.Change) -> str:
    """Carry out one breaking change the plan applies. Returns what was done."""
    from app.models.global_value import GlobalValue
    if ch.violations:
        raise PlanProblem(f"{ch.id}: {ch.violations} record(s) hold values the new definition would not accept — "
                          f"change them first, or keep the workspace's definition")
    if ch.area == "equipment_classes":
        from app.models.equipment_class import EquipmentClass
        cls = db.get(EquipmentClass, ch.subject)
        if cls is not None and cls.status == "active":
            cls.status = "retired"
        return "class no longer offered"
    if ch.area == "enumerations":
        applies_to, key = ch.subject.split(".", 1)
        gv = db.scalar(select(GlobalValue).where(GlobalValue.workspace_id == workspace_id,
                                                 GlobalValue.applies_to == applies_to, GlobalValue.key == key))
        if gv is None:
            return "not in the workspace"
        if ch.element:            # an option removed
            gv.options = [o for o in gv.options or [] if o.get("id") != ch.element]
            flag_modified(gv, "options")
            return "option removed"
        db.delete(gv)
        return "enumeration removed"
    schema = _schema_for(db, workspace_id, ch)
    if schema is None:
        return "not in the workspace"
    if ch.element is None:        # the type or kind itself
        if ch.what == "removed" or ch.what == "tightened":
            schema.is_concrete = False
            schema.metadata_json = {**(schema.metadata_json or {}), "withdrawn": ch.what == "removed"}
            return "no longer a type records can have; its records stay"
        if ch.what == "moved":
            parent_name = (ch.after or {}).get("parent")
            parent = None
            if parent_name:
                from app.services.asset_types import resolve_type_uids
                parent = resolve_type_uids(db, workspace_id).get(parent_name)
                if parent is None:
                    raise PlanProblem(f"{ch.id}: the new parent {parent_name!r} is not usable here")
            schema.parent_schema_uid = parent
            return f"moved under {parent_name}"
        if ch.what == "renamed":
            schema.name = ch.subject
            return "renamed in place (same uid)"
        return "nothing to do"
    attrs = [dict(a) for a in schema.attributes or []]
    if ":" in ch.element:         # an option of an attribute removed
        key, oid = ch.element.split(":", 1)
        for a in attrs:
            if a.get("key") == key:
                a["options"] = [o for o in a.get("options") or [] if o.get("id") != oid]
        _set_attrs(schema, attrs)
        return "option removed"
    if ch.what == "removed":
        _set_attrs(schema, [a for a in attrs if a.get("key") != ch.element])
        return "definition removed; the values records hold under it are kept"
    if ch.what == "renamed":
        old_key = (ch.before or {}).get("key")
        _set_attrs(schema, [dict(ch.after) if a.get("key") == old_key else a for a in attrs])
        moved = _move_values(db, workspace_id, ch.area, schema, old_key, ch.element)
        return f"renamed; values moved on {moved} record(s)"
    if ch.what in ("retyped", "tightened"):
        _set_attrs(schema, [dict(ch.after) if a.get("key") == ch.element else a for a in attrs])
        return "new definition applied"
    return "nothing to do"


def _add_types(db: Session, workspace_id: str, row: WorkspacePackage, new: Package, names: set) -> None:
    """Create the types the newer version adds, from its own definitions, parents first, as seeding makes them
    (same uid scheme, shared when this workspace is the catalogue)."""
    from app.packages import compile as c
    from app.services import asset_types, catalogue_icons
    shared = (row.options or {}).get("scope") == asset_types.SCOPE_GLOBAL
    specs = [t for t in c.object_types(new, _shared_sets()) if t.name in names]
    usable = asset_types.resolve_type_uids(db, workspace_id, (row.options or {}).get("catalogue_workspace_id"))
    for t in specs:
        usable.setdefault(t.name, asset_types.type_uid(workspace_id, t.name))
    made = {}
    for t in specs:                                  # the package lists parents before children
        uid = asset_types.type_uid(workspace_id, t.name)
        if db.get(Schema, uid) is not None:
            continue
        attrs = []
        for a in t.attributes:
            a = dict(a)
            if a.get("type") == "reference" and a.get("referenceType") in usable:
                a["referenceSchemaUid"] = usable[a["referenceType"]]
            attrs.append(a)
        db.add(Schema(uid=uid, workspace_id=workspace_id, name=t.name, description=t.description,
                      applies_to="objects", is_concrete=not t.abstract,
                      parent_schema_uid=usable.get(t.parent) if t.parent else None, attributes=attrs,
                      is_global=shared, metadata_json={"source": "argus", **({"aliases": t.aliases} if t.aliases else {}),
                                                       **({"locatable": True} if t.locatable else {}),
                                                       **({"map_layer": t.map_layer} if t.map_layer else {})}))
        db.flush()
        made[t.name] = uid
    every = {t.name: t for t in c.object_types(new, _shared_sets())}

    def icon_of(name):                               # its own, or its nearest ancestor's, in the newer version
        while name is not None and name in every:
            if every[name].icon:
                return every[name].icon
            name = every[name].parent
        return None
    if made:
        catalogue_icons.apply(db, workspace_id, made, shared, icon_of=icon_of)


def _apply_automatic(db: Session, workspace_id: str, row: WorkspacePackage, new: Package,
                     found: list[d.Change]) -> list[str]:
    """Additive and definition changes, keeping the workspace's own edits."""
    from app.models.global_value import GlobalValue
    done = []
    added_types = {c.subject for c in found if c.area == "object_types" and c.element is None and c.what == "added"}
    if added_types:
        _add_types(db, workspace_id, row, new, added_types)
        done.append(f"types added: {', '.join(sorted(added_types))}")
    for ch in found:
        if ch.category == d.BREAKING or (ch.area == "object_types" and ch.element is None and ch.what == "added"):
            continue
        if ch.what == "moved":
            continue                    # the same definition, held by another package
        if ch.area == "workflows":
            done += _apply_workflow(db, workspace_id, new, ch)
            continue
        if ch.conflict and ch.category == d.DEFINITION:
            continue                    # the workspace's own edit wins
        if ch.area == "equipment_classes":
            from app.services import equipment_classes
            equipment_classes.seed(db)
            continue
        if ch.area == "enumerations":
            applies_to, key = ch.subject.split(".", 1)
            gv = db.scalar(select(GlobalValue).where(GlobalValue.workspace_id == workspace_id,
                                                     GlobalValue.applies_to == applies_to, GlobalValue.key == key))
            if ch.element is None and ch.what == "added":
                from app.routers.workspaces import seed_default_global_values
                seed_default_global_values(db, workspace_id)
            elif gv is not None and ch.element and ch.what == "added":
                if not any(o.get("id") == ch.element for o in gv.options or []):
                    gv.options = [*(gv.options or []), dict(ch.after)]
                    flag_modified(gv, "options")
            elif gv is not None and ch.element and ch.what == "relabelled":
                gv.options = [dict(ch.after) if o.get("id") == ch.element else o for o in gv.options or []]
                flag_modified(gv, "options")
            elif gv is not None and ch.what == "changed":
                gv.name, gv.default_value = ch.after["name"], ch.after["default"]
            done.append(ch.id)
            continue
        if ch.area in ("ticket_types", "document_types") and ch.subject != "base" and ch.element is None:
            if ch.what == "added":
                from app.services.document_types import type_uid as doc_uid
                from app.services.ticket_types import BASE_UID_SUFFIX as TICKET
                base = f"{workspace_id}:{TICKET}" if ch.area == "ticket_types" else \
                    f"{workspace_id}:argus-document"
                uid = f"{base}:{ch.subject.lower().replace(' ', '-')}" if ch.area == "ticket_types" else \
                    doc_uid(workspace_id, ch.subject)
                if db.get(Schema, uid) is None and db.get(Schema, base) is not None:
                    db.add(Schema(uid=uid, workspace_id=workspace_id, name=ch.subject,
                                  description=(ch.after or {}).get("description"),
                                  applies_to="tickets" if ch.area == "ticket_types" else "documents",
                                  parent_schema_uid=base, attributes=[], metadata_json={"source": "argus"}))
            else:
                schema = _schema_for(db, workspace_id, ch)
                if schema is not None and (ch.after or {}).get("description"):
                    schema.description = ch.after["description"]
            done.append(ch.id)
            continue
        schema = _schema_for(db, workspace_id, ch)
        if schema is None:
            continue
        if ch.element is None:          # a type's own properties
            prop = ch.id.rsplit("/", 1)[-1]
            if prop == "description":
                schema.description = ch.after["description"]
            elif prop in ("aliases", "locatable", "map_layer"):
                meta = {**(schema.metadata_json or {}), prop: ch.after[prop]}
                schema.metadata_json = {k: v for k, v in meta.items() if v not in (None, False)}
            elif prop == "concrete":
                schema.is_concrete = True
            done.append(ch.id)
            continue
        attrs = [dict(a) for a in schema.attributes or []]
        keys = {a.get("key") for a in attrs}
        if ":" in ch.element:
            key, oid = ch.element.split(":", 1)
            for a in attrs:
                if a.get("key") == key:
                    opts = list(a.get("options") or [])
                    if ch.what == "added" and not any(o.get("id") == oid for o in opts):
                        opts.append(dict(ch.after))
                    elif ch.what == "relabelled":
                        opts = [dict(ch.after) if o.get("id") == oid else o for o in opts]
                    a["options"] = opts
        elif ch.what == "added":
            if ch.element not in keys:
                attrs.append(dict(ch.after))
        elif ch.what in ("relabelled", "changed", "widened"):
            attrs = [({**a, "name": ch.after["name"], "indexed": ch.after.get("indexed"),
                       "readOnly": ch.after.get("readOnly"), "multiValue": ch.after.get("multiValue")}
                      if a.get("key") == ch.element else a) for a in attrs]
        _set_attrs(schema, attrs)
        done.append(ch.id)
    return done


def _apply_workflow(db: Session, workspace_id: str, new: Package, ch: d.Change) -> list[str]:
    """A package's workflow added, or changed where the workspace has not edited its copy."""
    from app.models.workflow import Workflow
    from app.packages.install import add_workflows, workflow_uid
    from app.services import workflows
    uid = workflow_uid(workspace_id, new.id, ch.subject)
    wf = db.get(Workflow, uid)
    if wf is None:
        add_workflows(db, workspace_id, new)
        return [ch.id]
    if wf.version == 1 and ch.what == "changed":
        n = ch.after
        workflows.save(db, workspace_id, {"name": n["name"], "initial": n["initial"], "states": n["states"],
                                          "transitions": n["transitions"],
                                          "source": {"package": new.id, "id": ch.subject, "version": new.version}},
                       uid=uid)
        wf.version = 1                  # still the package's: a later version may change it again
        add_workflows(db, workspace_id, new)
        return [ch.id]
    ch.conflict = "the workspace edited this workflow itself"
    return []


def _fill_detected(db: Session, workspace_id: str, row: WorkspacePackage, new: Package) -> list[str]:
    """A package recorded as `detected` (found in place, never installed by the installer) may lack types its
    version defines — before 1.35.26 one type was enough to be detected. Nobody removed them: they were never
    made. An upgrade makes them, in the scope the workspace holds."""
    from app.models.package import PackageInstallation
    from app.services import asset_types
    installed_by_installer = db.scalar(select(PackageInstallation.id).where(
        PackageInstallation.workspace_id == workspace_id, PackageInstallation.package_id == new.id,
        PackageInstallation.action.in_(("install", "upgrade"))).limit(1))
    if installed_by_installer is not None:
        return []
    old_sections = _old(db, row)
    scope = _scope_names(row, old_sections, new)
    names = [t["name"] for t in (new.section("object_types") or {}).get("types") or []]
    missing = {n for n in names if (scope is None or n in scope)
               and db.get(Schema, asset_types.type_uid(workspace_id, n)) is None}
    if missing:
        _add_types(db, workspace_id, row, new, missing)
    return sorted(missing)


def apply(db: Session, workspace_id: str, new: Package, decisions: Optional[dict]) -> dict:
    """The upgrade, with its plan. Every breaking change must be decided; the history keeps the decisions."""
    decisions = dict(decisions or {})
    for k, v in decisions.items():
        if v not in (KEEP, APPLY):
            raise PlanProblem(f"decision for {k}: {v!r} — use apply or keep")
    found, _old_defs = changes(db, workspace_id, new)
    breaking = [c for c in found if c.category == d.BREAKING]
    undecided = [c.id for c in breaking if c.id not in decisions]
    if undecided:
        raise PlanProblem(f"this upgrade needs a migration plan: decide {len(undecided)} change(s) "
                          f"(apply or keep): {', '.join(undecided[:6])}" + ("…" if len(undecided) > 6 else ""))
    for c in breaking:
        if decisions[c.id] not in c.actions:
            raise PlanProblem(f"{c.id} can only be {' or '.join(c.actions)}")
    row = db.scalar(select(WorkspacePackage).where(WorkspacePackage.workspace_id == workspace_id,
                                                   WorkspacePackage.package_id == new.id))
    outcome = {}
    for c in breaking:          # renames and removals first, so additions land on the new names
        outcome[c.id] = _apply_breaking(db, workspace_id, c) if decisions[c.id] == APPLY else "kept as the workspace has it"
    automatic = _apply_automatic(db, workspace_id, row, new, found)
    filled = _fill_detected(db, workspace_id, row, new)
    if filled:
        automatic.append(f"types a detected package lacked: {', '.join(filled)}")
    db.flush()
    return {"decisions": decisions, "outcome": outcome, "automatic": automatic,
            "conflicts": {c.id: c.conflict for c in found if c.conflict},
            "changes": len(found)}
