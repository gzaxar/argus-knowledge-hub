"""Migrate records to a package type: governed, previewed, batched, verified and reversible (docs/type-migration.md).

Records of a custom type, or of a type a shared catalogue workspace defines, move to a standard type that a
versioned ARGUS package defines. They stay where they are — each in its owning workspace — and keep their uid,
key, history, comments, files, relations, activities, map positions and indoor placements.

The target is never found by name. It is a package's type — (package, area, type as the package declares it) —
and in each owning workspace it is the type the installer made for it: the package must be installed there
(or, for a shared object type, in the catalogue the workspace hangs from), the installed version's recorded
definition must declare the type, and the type row must be the one the installer derives for it. Anything
else is reported, with the workspace or catalogue that needs the package.

The mapping is a plan of explicit decisions: each source field is copied (with a value map for choices),
transformed (a value map, a default, a cast), kept in provenance (removed from the record, kept with the
migration), or held for review (a record with a value there is not migrated until decided). Ticket states map
to the target workflow's states. Every record is checked against the target before anything is written:
required fields, choices, reference types and visibility, uniqueness, the relation rules of the packages,
references other records make to it, and — for tickets — that its state is one of the target workflow's.

Preview writes nothing. Apply needs the token of the preview it follows (the data must not have changed), then
works in batches, one savepoint per record, so a record that fails is reported and the rest go on; applying
again only does what is left. Assets move through the ledger (a confirmed type statement naming the type's uid,
and field statements), so a rebuild keeps them. Revert puts applied records back. Verify compares each record
with the inventory taken before the first batch, and deprecates the old type only when nothing depends on it.
A type is never deleted here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from packaging.version import Version
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.asset import Asset, Relation
from app.models.document import Document, DocumentRevision
from app.models.issue import Issue, IssueHistory
from app.models.package import PackageSnapshot, WorkspacePackage
from app.models.schema import Schema
from app.models.type_migration import TypeMigration, TypeMigrationItem
from app.models.workspace import Workspace

KINDS = ("objects", "tickets", "documents")
AREA = {"objects": "object_types", "tickets": "ticket_types", "documents": "document_types"}
ACTIONS = ("copy", "transform", "provenance", "review")
# Never moved, mapped or dropped by a migration: a record's classification decides who may see it.
PRESERVED = ("classification",)
RECORD_LIMIT = 500          # records listed in a preview (all are counted)
BATCH = 100


class MigrationError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _log(m: TypeMigration, actor: Optional[str], event: str, **detail) -> None:
    m.log = [*(m.log or []), {"at": now().isoformat(), "actor": actor, "event": event, **detail}]
    flag_modified(m, "log")
    m.updated_at = now()


# =========================================================================== records of a kind

def _model(kind: str):
    return {"objects": Asset, "tickets": Issue, "documents": Document}[kind]


def _type_col(kind: str):
    return {"objects": Asset.schema_uid, "tickets": Issue.schema_uid, "documents": Document.document_type_uid}[kind]


def _records(db: Session, kind: str, type_uids: Iterable[str], workspaces: Optional[Iterable[str]] = None) -> list:
    model, col = _model(kind), _type_col(kind)
    q = select(model).where(col.in_(list(type_uids)))
    if workspaces is not None:
        q = q.where(model.workspace_id.in_(list(workspaces)))
    if kind == "objects":
        q = q.where(Asset.deleted_at.is_(None), Asset.merged_into_uid.is_(None))
    return list(db.scalars(q.order_by(model.workspace_id, model.uid)))


def _attrs_of(db: Session, kind: str, rec) -> dict:
    if kind == "documents":
        rev = db.get(DocumentRevision, rec.current_revision_uid) if rec.current_revision_uid else None
        return dict((rev.attributes if rev else None) or {})
    return dict(rec.attributes or {})


def _label(kind: str, rec) -> dict:
    if kind == "objects":
        return {"uid": rec.uid, "key": rec.key, "name": rec.name, "workspace_id": rec.workspace_id}
    if kind == "tickets":
        return {"uid": rec.uid, "key": None, "name": rec.title, "workspace_id": rec.workspace_id}
    return {"uid": rec.uid, "key": rec.code, "name": rec.title, "workspace_id": rec.workspace_id}


# =========================================================================== source

def family(db: Session, schema_uid: str, with_descendants: bool) -> list[Schema]:
    root = db.get(Schema, schema_uid)
    if root is None:
        raise MigrationError("no such type")
    if not with_descendants:
        return [root]
    out, frontier = [root], [root.uid]
    while frontier:
        kids = list(db.scalars(select(Schema).where(Schema.parent_schema_uid.in_(frontier))))
        out += kids
        frontier = [k.uid for k in kids]
    return out


def descendants(db: Session, schema_uid: str) -> list[Schema]:
    return family(db, schema_uid, True)[1:]


def owning_workspaces(db: Session, kind: str, type_uids: list[str]) -> dict[str, int]:
    model, col = _model(kind), _type_col(kind)
    q = select(model.workspace_id, func.count()).where(col.in_(type_uids))
    if kind == "objects":
        q = q.where(Asset.deleted_at.is_(None), Asset.merged_into_uid.is_(None))
    return {ws: n for ws, n in db.execute(q.group_by(model.workspace_id))}


def sources(db: Session, kind: str) -> list[dict]:
    """The types records can be migrated from: every type of this kind that is not a package type where it
    lives, with its records by owning workspace (its own, and those of the types below it)."""
    if kind not in KINDS:
        raise MigrationError("kind is objects, tickets or documents")
    rows = list(db.scalars(select(Schema).where(Schema.applies_to == kind).order_by(Schema.workspace_id, Schema.name)))
    pkg = package_type_uids(db, kind)
    out = []
    for s in rows:
        if s.uid in pkg or ":ledger:" in s.uid:   # package types, and the ledger's own system types
            continue
        own = owning_workspaces(db, kind, [s.uid])
        below = owning_workspaces(db, kind, [d.uid for d in descendants(db, s.uid)])
        if not own and not below:
            continue
        out.append({"uid": s.uid, "name": s.name, "workspace_id": s.workspace_id, "is_global": s.is_global,
                    "parent_schema_uid": s.parent_schema_uid, "custom": not (s.metadata_json or {}).get("source") == "argus",
                    "deprecated": bool((s.metadata_json or {}).get("deprecated")),
                    "records": own, "records_below": below})
    return out


# =========================================================================== package types and provenance

def _declared(sections: dict, kind: str) -> dict[str, dict]:
    """The types a package version declares for this kind: name -> its definition."""
    sec = (sections or {}).get(AREA[kind]) or {}
    if kind == "objects":
        return {str(t["name"]): t for t in sec.get("types") or []}
    out = {str(k["name"]): k for k in sec.get("kinds") or []}
    if sec.get("base"):
        out[str(sec["base"].get("name") or "base")] = {**sec["base"], "_base": True}
    return out


def shipped_types(kind: str) -> list[dict]:
    """Every type the packages this installation ships declare for a kind (the targets one can choose)."""
    from app.packages.loader import available
    out = []
    for p in available().values():
        for name, t in _declared(p.sections, kind).items():
            out.append({"package_id": p.id, "package_name": p.name, "version": p.version, "type": name,
                        "abstract": bool(t.get("abstract")), "base": bool(t.get("_base")),
                        "description": str(t.get("description") or "")})
    return sorted(out, key=lambda x: (x["package_id"], x["type"]))


def _installed_sections(db: Session, row: WorkspacePackage) -> Optional[dict]:
    from app.packages.loader import available
    snap = db.scalar(select(PackageSnapshot).where(PackageSnapshot.package_id == row.package_id,
                                                   PackageSnapshot.checksum == row.checksum))
    if snap is not None:
        return snap.sections
    shipped = available().get(row.package_id)
    if shipped is not None and shipped.checksum == row.checksum:
        return shipped.sections
    return None


def _home(db: Session, ws: str, kind: str, type_name: str) -> str:
    """Where a package's type lives for records of `ws`: the workspace itself, or — for a shared object
    type — the catalogue workspace it hangs from (as the installer put it there)."""
    if kind != "objects":
        return ws
    from app.services import asset_types
    from app.packages.install import installed
    recorded = [r.options or {} for r in installed(db, ws).values()]
    catalogue = next((o.get("catalogue_workspace_id") for o in recorded if o.get("scope") == "beamline"
                      and o.get("catalogue_workspace_id")), None) or asset_types.catalogue_of(db, ws)
    if catalogue and type_name in asset_types.BY_NAME and asset_types.scope_of(type_name) == asset_types.SCOPE_GLOBAL:
        return catalogue
    return ws


def _derived_uid(db: Session, home: str, kind: str, type_name: str) -> Optional[str]:
    """The uid the installer gives a package's type in a workspace: derived from the package's own
    declaration, never looked up by name among the workspace's types."""
    from app.packages.install import kind_uid
    from app.services import asset_types
    if kind == "objects":
        own = asset_types.type_uid(home, type_name)
        if db.get(Schema, own) is not None:
            return own
        former = asset_types.FORMER_NAMES.get(type_name)
        if former and db.get(Schema, asset_types.type_uid(home, former)) is not None:
            return asset_types.type_uid(home, former)
        return own
    area = AREA[kind]
    kind_row = db.get(Schema, kind_uid(home, area, type_name))
    if kind_row is not None and kind_row.name == type_name:
        return kind_row.uid
    base = db.get(Schema, kind_uid(home, area, "base"))
    if base is not None and base.name == type_name:
        return base.uid                     # the package's base type (Ticket, Document) has the base uid
    return kind_uid(home, area, type_name)


def resolve_target(db: Session, ws: str, kind: str, target: dict) -> dict:
    """The package type, in one owning workspace: its row and provenance, or why it is not there."""
    from app.packages.install import installed
    pid, name, need = target["package_id"], target["type"], target.get("version")
    home = _home(db, ws, kind, name)
    out = {"workspace_id": ws, "home": home, "package_id": pid, "type": name, "schema_uid": None,
           "installed_version": None, "checksum": None}
    row = installed(db, home).get(pid)
    if row is None:
        return {**out, "status": "package_missing",
                "detail": f"{pid} is not installed in {home!r}" + (" (the shared catalogue)" if home != ws else "")}
    out.update(installed_version=row.version, checksum=row.checksum)
    if need and Version(row.version) < Version(need):
        return {**out, "status": "package_older",
                "detail": f"{home!r} has {pid} {row.version}; the target is {pid} {need}: upgrade it first"}
    sections = _installed_sections(db, row)
    if sections is None:
        return {**out, "status": "definition_unknown",
                "detail": f"there is no record of what {pid} {row.version} holds in {home!r}: upgrade the package"}
    if name not in _declared(sections, kind):
        return {**out, "status": "type_not_in_package",
                "detail": f"{pid} {row.version} in {home!r} does not declare {name!r}"}
    uid = _derived_uid(db, home, kind, name)
    schema = db.get(Schema, uid) if uid else None
    if schema is None or schema.workspace_id != home or schema.applies_to != kind:
        return {**out, "status": "type_missing",
                "detail": f"{home!r} has {pid} {row.version}, but not the type the installer makes for {name!r}"}
    if (_declared(sections, kind).get(name) or {}).get("abstract"):
        return {**out, "status": "abstract", "schema_uid": uid, "detail": f"{name!r} is abstract: choose a type below it"}
    return {**out, "status": "ok", "schema_uid": uid, "detail": None}


def package_type_uids(db: Session, kind: str) -> set[str]:
    """Every type row that is a package's type where it lives (by the provenance above), for every workspace."""
    from app.packages.install import installed
    out: set[str] = set()
    for (ws,) in db.execute(select(Workspace.id)):
        for row in installed(db, ws).values():
            sections = _installed_sections(db, row)
            for name in _declared(sections or {}, kind):
                uid = _derived_uid(db, ws, kind, name)
                if uid:
                    out.add(uid)
    return out


def install_preview(db: Session, home: str, package_id: str) -> dict:
    """What installing (or upgrading to) the package would do where it is needed — applied and rolled back."""
    from app.packages import install as installer
    try:
        plan = installer.plan(db, home, [package_id])
        return {"workspace_id": home, "ok": True, "plan": plan.as_dict()}
    except installer.CatalogueBehind as e:
        return {"workspace_id": home, "ok": False, "catalogue_workspace_id": e.catalogue, "needs": e.needs,
                "error": str(e)}
    except installer.PackageProblem as e:
        return {"workspace_id": home, "ok": False, "error": str(e)}
    finally:
        db.rollback()


# =========================================================================== mapping

def _effective(db: Session, schema: Optional[Schema]) -> list[dict]:
    from app.services.attribute_validation import effective_attributes
    return effective_attributes(db, schema) if schema is not None else []


def _key(a: dict) -> str:
    return str(a.get("key") or a.get("name"))


def _workflow_states(db: Session, ws: str, schema_uid: Optional[str]) -> list[dict]:
    from app.services import workflows
    return list((workflows.workflow_for(db, ws, schema_uid) or {}).get("states") or [])


def _option_values(attr: dict) -> list[str]:
    return [str(o.get("value") if o.get("value") is not None else o.get("id")) for o in attr.get("options") or []]


def _match_option(attr: dict, value) -> Optional[str]:
    """A source value's counterpart among a target choice list: the same option id, or the same label."""
    v = str(value).strip().lower()
    for o in attr.get("options") or []:
        if str(o.get("id", "")).lower() == v or str(o.get("value", "")).lower() == v:
            return str(o.get("value") if o.get("value") is not None else o.get("id"))
    return None


def _source_values(db: Session, kind: str, recs: list) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in recs:
        for k, v in _attrs_of(db, kind, r).items():
            for x in (v if isinstance(v, list) else [v]):
                if x not in (None, "", []):
                    out[k][json.dumps(x, sort_keys=True) if not isinstance(x, str) else x] += 1
    return out


def propose(db: Session, m: TypeMigration, target_schema: Optional[Schema]) -> dict:
    """A first mapping: a field the target has under the same key is copied (its choices matched by option
    id or label), any other is kept in provenance; ticket states the target workflow has are kept. A proposal
    only — every line is the administrator's to confirm or change."""
    fam = family(db, m.source_schema_uid, m.include_descendants)
    recs = _records(db, m.kind, [s.uid for s in fam], m.workspaces)
    src_defs = {}
    for s in fam:
        for a in _effective(db, s):
            src_defs.setdefault(_key(a), a)
    values = _source_values(db, m.kind, recs)
    tgt = {_key(a): a for a in _effective(db, target_schema)}
    attributes = {}
    for key in sorted(set(src_defs) | set(values)):
        if key in PRESERVED:
            continue
        a = src_defs.get(key) or {"key": key, "name": key, "type": "string"}
        t = tgt.get(key)
        entry: dict = {"name": a.get("name") or key, "type": a.get("type") or "string",
                       "records_with_value": sum(values.get(key, Counter()).values())}
        if t is not None:
            entry.update(action="copy", to=key)
            if t.get("type") == "enumeration":
                vm = {}
                for v in values.get(key, {}):
                    hit = _match_option(t, v)
                    if hit is not None:
                        vm[v] = hit
                entry["values"] = vm
        else:
            entry.update(action="provenance", to=None)
        attributes[key] = entry
    defaults = {_key(a): None for a in tgt.values() if a.get("required") and _key(a) not in
                {e.get("to") for e in attributes.values()}}
    states = {}
    if m.kind == "tickets" and target_schema is not None:
        target_states = {s["key"] for s in _workflow_states(db, (m.workspaces or [target_schema.workspace_id])[0], target_schema.uid)}
        for st in sorted({r.state for r in recs}):
            states[st] = st if st in target_states else None
    return {"attributes": attributes, "defaults": defaults, "states": states, "records": {}}


def _cast(value, to_type: str):
    if value in (None, ""):
        return value
    try:
        if to_type == "integer":
            return int(float(value))
        if to_type == "float":
            return float(value)
        if to_type == "boolean":
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "y", "on")
        if to_type in ("string", "text"):
            return value if isinstance(value, str) else json.dumps(value)
    except (TypeError, ValueError):
        raise MigrationError(f"{value!r} is not a {to_type}")
    return value


def map_record(m: TypeMigration, attrs: dict, tgt_defs: dict[str, dict]) -> tuple[dict, dict, list[str], list[str]]:
    """A record's fields under the mapping: (new attributes, provenance, review reasons, problems)."""
    mapping = m.mapping or {}
    rules = mapping.get("attributes") or {}
    new: dict = {k: v for k, v in attrs.items() if k in PRESERVED}
    prov: dict = {}
    review: list[str] = []
    problems: list[str] = []
    for key, value in attrs.items():
        if key in PRESERVED:
            continue
        rule = rules.get(key) or {"action": "provenance"}
        action = rule.get("action")
        empty = value in (None, "", [])
        if action == "review" and not empty:
            review.append(f"{key}: held for review")
            continue
        if action in ("copy", "transform") and rule.get("to"):
            to = rule["to"]
            t = tgt_defs.get(to) or {}
            out = value
            vm = rule.get("values") or {}
            if vm or t.get("type") == "enumeration":
                items = value if isinstance(value, list) else [value]
                mapped = []
                for x in items:
                    k = x if isinstance(x, str) else json.dumps(x, sort_keys=True)
                    if k in vm and vm[k] is not None:
                        mapped.append(vm[k])
                    elif t.get("type") == "enumeration" and x not in (None, "") and _match_option(t, x) is None:
                        problems.append(f"{key}: the value {x!r} has no choice in {to}: map it, keep it in provenance "
                                        f"or hold the record for review")
                        mapped.append(x)
                    else:
                        mapped.append(x)
                out = mapped if isinstance(value, list) else (mapped[0] if mapped else None)
            if action == "transform" and rule.get("cast"):
                try:
                    out = [_cast(x, rule["cast"]) for x in out] if isinstance(out, list) else _cast(out, rule["cast"])
                except MigrationError as e:
                    problems.append(f"{key}: {e}")
            if to in new and new[to] not in (None, "", []) and not empty:
                prov[key] = value
                problems.append(f"{key} and another field both go to {to}")
                continue
            if not empty or to not in new:
                new[to] = out
            continue
        if not empty:
            prov[key] = value
    for key, default in (mapping.get("defaults") or {}).items():
        if default not in (None, "") and new.get(key) in (None, "", []):
            new[key] = default
    return new, prov, review, problems


# =========================================================================== evaluation (preview and apply)

@dataclass
class Evaluation:
    record: object
    label: dict
    status: str                                       # ready | review | blocked | already | hidden | applied
    target_uid: Optional[str] = None
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    revisions: dict = field(default_factory=dict)     # documents: revision uid -> (before, after, provenance)


def _incoming(db: Session, uids: list[str], target_lineage: Callable[[str], set]) -> dict[str, list[str]]:
    """References other records make to these records through a typed reference field, that the target type
    would no longer satisfy: uid -> problems. A referrer's field is judged by its own type's definition
    (inherited fields included)."""
    from sqlalchemy.dialects.postgresql import array
    from app.services.attribute_validation import _descendant_schema_uids
    out: dict[str, list[str]] = defaultdict(list)
    if not uids:
        return out
    wanted = list(set(uids))
    keys = set()
    for schema in db.scalars(select(Schema).where(Schema.applies_to == "objects")):
        for a in schema.attributes or []:
            if a.get("type") == "reference" and a.get("referenceSchemaUid"):
                keys.add(_key(a))
    defs_of: dict[str, dict] = {}
    for key in sorted(keys):
        col = Asset.attributes[key]
        q = select(Asset).where(Asset.deleted_at.is_(None),
                                or_(col.astext.in_(wanted), col.op("?|")(array(wanted))))
        for referrer in db.scalars(q):
            if referrer.schema_uid not in defs_of:
                defs_of[referrer.schema_uid] = {_key(x): x for x in _effective(db, db.get(Schema, referrer.schema_uid))}
            a = defs_of[referrer.schema_uid].get(key)
            ref = (a or {}).get("referenceSchemaUid")
            if not a or a.get("type") != "reference" or not ref:
                continue
            allowed = {ref} | (_descendant_schema_uids(db, ref) if a.get("includeChildren") else set())
            v = referrer.attributes.get(key)
            for target in (v if isinstance(v, list) else [v]):
                if target in wanted and not (target_lineage(target) & allowed):
                    ref_name = db.get(Schema, ref).name if db.get(Schema, ref) else ref
                    out[target].append(f"{referrer.key or referrer.uid} refers to it as {a.get('name') or key}, "
                                       f"which must be a {ref_name}")
    return out


def evaluate(db: Session, m: TypeMigration, grants_for: Callable[[str], object]) -> tuple[list[Evaluation], dict]:
    """Every record the migration covers, judged against the target where it lives. Reads only."""
    from app.services import visibility, workflows
    from app.services.attribute_validation import check_attributes
    from app.packages import relations as relation_rules
    fam = family(db, m.source_schema_uid, m.include_descendants)
    fam_uids = [s.uid for s in fam]
    recs = _records(db, m.kind, fam_uids, m.workspaces)
    targets = {ws: resolve_target(db, ws, m.kind, m.target) for ws in m.workspaces}
    done = {i.record_uid: i for i in db.scalars(select(TypeMigrationItem).where(
        TypeMigrationItem.migration_id == m.id))}
    target_of = {r.uid: targets.get(r.workspace_id, {}).get("schema_uid") for r in recs}

    def lineage(uid: str) -> set:
        out, s = set(), db.get(Schema, target_of.get(uid) or "")
        while s is not None and s.uid not in out:
            out.add(s.uid)
            s = db.get(Schema, s.parent_schema_uid) if s.parent_schema_uid else None
        return out

    incoming = _incoming(db, [r.uid for r in recs], lineage) if m.kind == "objects" else {}
    tgt_defs_cache: dict[str, dict] = {}
    mapping_states = (m.mapping or {}).get("states") or {}
    held = (m.mapping or {}).get("records") or {}
    out: list[Evaluation] = []
    for r in recs:
        label = _label(m.kind, r)
        t = targets.get(r.workspace_id) or {}
        current_type = r.schema_uid if m.kind != "documents" else r.document_type_uid
        item = done.get(r.uid)
        if item is not None and item.status == "applied":
            out.append(Evaluation(r, label, "applied", t.get("schema_uid")))
            continue
        if t.get("status") != "ok":
            out.append(Evaluation(r, label, "blocked", None, reasons=[t.get("detail") or "no target"]))
            continue
        if current_type == t["schema_uid"]:
            out.append(Evaluation(r, label, "already", t["schema_uid"]))
            continue
        grants = grants_for(r.workspace_id)
        if not visibility.can_see(r, grants):
            out.append(Evaluation(r, label, "hidden", t["schema_uid"],
                                  reasons=["restricted: you may not see this record, so it is not migrated"]))
            continue
        target = db.get(Schema, t["schema_uid"])
        if t["schema_uid"] not in tgt_defs_cache:
            tgt_defs_cache[t["schema_uid"]] = {_key(a): a for a in _effective(db, target)}
        tgt_defs = tgt_defs_cache[t["schema_uid"]]
        ev = Evaluation(r, label, "ready", t["schema_uid"])
        decision = held.get(r.uid)
        if decision == "skip":
            ev.status, ev.reasons = "review", ["left out by an individual decision"]
            out.append(ev)
            continue
        before_attrs = _attrs_of(db, m.kind, r)
        new_attrs, prov, review, problems = map_record(m, before_attrs, tgt_defs)
        ev.before = {"type_uid": current_type, "attributes": before_attrs}
        ev.after = {"type_uid": t["schema_uid"], "attributes": new_attrs}
        ev.provenance = prov
        if m.kind == "tickets":
            ev.before["state"] = r.state
            wf = workflows.workflow_for(db, r.workspace_id, t["schema_uid"])
            keys = {s["key"] for s in (wf or {}).get("states") or []}
            new_state = r.state if r.state in keys else mapping_states.get(r.state)
            if new_state is None or new_state not in keys:
                problems.append(f"state {r.state!r} is not a state of the target workflow "
                                f"({(wf or {}).get('name')}): map it")
            else:
                ev.after["state"] = new_state
        if m.kind == "documents":
            for rev in db.scalars(select(DocumentRevision).where(DocumentRevision.document_uid == r.uid)):
                a2, p2, rv2, pb2 = map_record(m, dict(rev.attributes or {}), tgt_defs)
                ev.revisions[rev.uid] = {"before": dict(rev.attributes or {}), "after": a2, "provenance": p2}
                if rev.uid != r.current_revision_uid:
                    problems += [f"revision {rev.revision_number}: {x}" for x in pb2]
        # Checked against the target where the record lives.
        owner = {"objects": Asset, "tickets": Issue, "documents": Document}[m.kind]
        probe = copy.deepcopy(new_attrs)
        problems += check_attributes(db, target, probe, r.workspace_id, owner, exclude_uid=r.uid,
                                     skip_unique=m.kind == "documents")
        ev.after["attributes"] = probe          # choices written as stored (choice_value)
        if m.kind == "objects":
            for rel in db.scalars(select(Relation).where(or_(Relation.from_asset_uid == r.uid,
                                                             Relation.to_asset_uid == r.uid))):
                frm = t["schema_uid"] if rel.from_asset_uid == r.uid else getattr(db.get(Asset, rel.from_asset_uid), "schema_uid", None)
                to = t["schema_uid"] if rel.to_asset_uid == r.uid else getattr(db.get(Asset, rel.to_asset_uid), "schema_uid", None)
                if rel.from_asset_uid == r.uid and rel.to_asset_uid in target_of:
                    to = target_of[rel.to_asset_uid] or to
                if rel.to_asset_uid == r.uid and rel.from_asset_uid in target_of:
                    frm = target_of[rel.from_asset_uid] or frm
                msg = relation_rules.check(db, rel.relation_type, frm, to)
                if msg:
                    problems.append(f"relation: {msg}")
            problems += incoming.get(r.uid, [])
        for k in sorted(set(before_attrs) | set(ev.after["attributes"])):
            b, a = before_attrs.get(k), ev.after["attributes"].get(k)
            if b != a:
                ev.changes.append({"field": k, "before": b, "after": a,
                                   "provenance": k in prov})
        if problems:
            ev.status, ev.reasons = "blocked", sorted(set(problems))
        elif review:
            ev.status, ev.reasons = "review", review
        out.append(ev)
    return out, targets


def preview(db: Session, m: TypeMigration, grants_for: Callable[[str], object]) -> dict:
    """What applying would do, record by record and by owning workspace. Writes nothing."""
    evs, targets = evaluate(db, m, grants_for)
    by_ws: dict[str, Counter] = defaultdict(Counter)
    for e in evs:
        by_ws[e.label["workspace_id"]][e.status] += 1
    unmapped_values: dict[str, list] = defaultdict(list)
    rules = (m.mapping or {}).get("attributes") or {}
    for e in evs:
        for k, v in (e.before.get("attributes") or {}).items():
            r = rules.get(k) or {}
            if r.get("action") in ("copy", "transform") and v not in (None, "", []):
                for x in (v if isinstance(v, list) else [v]):
                    sx = x if isinstance(x, str) else json.dumps(x, sort_keys=True)
                    if sx not in (r.get("values") or {}) and sx not in unmapped_values[k]:
                        unmapped_values[k].append(sx)
    fingerprint = [(e.label["uid"], e.status, e.target_uid, e.after, sorted(e.provenance)) for e in evs]
    token = hashlib.sha256(json.dumps([m.target, m.mapping, m.workspaces, m.include_descendants, fingerprint],
                                      sort_keys=True, default=str).encode()).hexdigest()[:20]
    records = [{**e.label, "status": e.status, "reasons": e.reasons, "changes": e.changes[:20],
                "state": {"before": e.before.get("state"), "after": e.after.get("state")} if m.kind == "tickets" else None,
                "provenance": e.provenance}
               for e in sorted(evs, key=lambda x: ({"blocked": 0, "review": 1, "hidden": 2, "ready": 3}.get(x.status, 4),
                                                   x.label["workspace_id"], x.label["name"] or ""))]
    return {"token": token, "targets": list(targets.values()),
            "counts": {ws: dict(c) for ws, c in sorted(by_ws.items())},
            "total": dict(sum((c for c in by_ws.values()), Counter())),
            "records": records[:RECORD_LIMIT], "records_listed": min(len(records), RECORD_LIMIT),
            "records_total": len(records), "unmapped_values": dict(unmapped_values),
            "deprecation": deprecation_check(db, m)}


# =========================================================================== inventory and verification

def _inventory_of(db: Session, kind: str, rec) -> dict:
    from app.models.asset_subresources import AssetComment, AssetLabel
    from app.models.attachment import Attachment
    from app.models.spatial import SpatialFeature
    from app.models.indoor import IndoorPlacement
    from app.models.activity import Activity
    from app.models.issue import IssueComment, IssueLink
    out = {"uid": rec.uid}

    def n(q):
        return db.scalar(select(func.count()).select_from(q.subquery()))
    if kind == "objects":
        out.update(key=rec.key, comments=n(select(AssetComment.uid).where(AssetComment.asset_uid == rec.uid)),
                   labels=n(select(AssetLabel.uid).where(AssetLabel.asset_uid == rec.uid)),
                   attachments=n(select(Attachment.uid).where(Attachment.asset_uid == rec.uid)),
                   relations=n(select(Relation.id).where(or_(Relation.from_asset_uid == rec.uid,
                                                            Relation.to_asset_uid == rec.uid),
                                                        Relation.derivation.is_distinct_from("ledger"))),
                   spatial=n(select(SpatialFeature.uid).where(SpatialFeature.subject_uid == rec.uid,
                                                              SpatialFeature.state == "confirmed")),
                   placements=n(select(IndoorPlacement.uid).where(IndoorPlacement.asset_uid == rec.uid)),
                   activities=n(select(Activity.uid).where(Activity.asset_uid == rec.uid)))
    elif kind == "tickets":
        out.update(comments=n(select(IssueComment.uid).where(IssueComment.issue_uid == rec.uid)),
                   links=n(select(IssueLink.from_issue_uid).where(or_(IssueLink.from_issue_uid == rec.uid,
                                                                     IssueLink.to_issue_uid == rec.uid))),
                   attachments=n(select(Attachment.uid).where(Attachment.issue_uid == rec.uid)),
                   activities=n(select(Activity.uid).where(Activity.ticket_uid == rec.uid)),
                   asset=rec.asset_uid)
    else:
        revs = list(db.scalars(select(DocumentRevision.uid).where(DocumentRevision.document_uid == rec.uid)))
        out.update(key=rec.code, revisions=len(revs), current=rec.current_revision_uid,
                   attachments=n(select(Attachment.uid).where(Attachment.document_revision_uid.in_(revs))) if revs else 0,
                   activities=n(select(Activity.uid).where(Activity.document_uid == rec.uid)))
    return out


def deprecation_check(db: Session, m: TypeMigration) -> dict:
    """What still depends on the source type: records (anywhere), types below it, reference fields that
    name it. Deprecated only when nothing does; never deleted."""
    src = db.get(Schema, m.source_schema_uid)
    blocking = []
    left = owning_workspaces(db, m.kind, [m.source_schema_uid])
    if left:
        blocking.append({"what": "records", "detail": ", ".join(f"{n} in {ws}" for ws, n in sorted(left.items()))})
    kids = list(db.scalars(select(Schema).where(Schema.parent_schema_uid == m.source_schema_uid)))
    if kids:
        blocking.append({"what": "types below it", "detail": ", ".join(f"{k.name} ({k.workspace_id})" for k in kids)})
    refs = []
    for s in db.scalars(select(Schema)):
        for a in s.attributes or []:
            if a.get("referenceSchemaUid") == m.source_schema_uid:
                refs.append(f"{s.name}.{_key(a)} ({s.workspace_id})")
    if refs:
        blocking.append({"what": "reference fields", "detail": ", ".join(sorted(refs)[:20])})
    return {"type": src.name if src else m.source_schema_uid, "possible": not blocking, "blocking": blocking,
            "deprecated": bool(src and (src.metadata_json or {}).get("deprecated"))}


# =========================================================================== apply, revert, verify

def _apply_one(db: Session, m: TypeMigration, e: Evaluation, actor: str) -> None:
    from app.ledger import service as ledger
    from app.models.asset_subresources import AssetHistory
    from app.services import workflows
    r = e.record
    target = db.get(Schema, e.target_uid)
    reason = f"type migration {m.id}: {m.reason or ''}".strip()
    if m.kind == "objects":
        before = e.before["attributes"]
        after = e.after["attributes"]
        changes = {f"attr:{k}": after.get(k) for k in set(before) | set(after) if before.get(k) != after.get(k)}
        ledger.retype_to(db, r.workspace_id, actor, [r.uid], target, reason=reason, changes={r.uid: changes})
        db.refresh(r)
        if r.schema_uid != target.uid:
            raise MigrationError("the ledger did not put the record on the target type")
        db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=r.uid, type="type_migrated", author=actor,
                            details=f"type {getattr(db.get(Schema, e.before.get('type_uid') or ''), 'name', None) or e.before.get('type_uid')} → {target.name} "
                                    f"({m.target['package_id']} {m.target.get('version') or ''}) by migration {m.id}",
                            timestamp=now()))
    elif m.kind == "tickets":
        old_schema = db.get(Schema, r.schema_uid) if r.schema_uid else None
        r.schema_uid = target.uid
        r.attributes = e.after["attributes"]
        flag_modified(r, "attributes")
        db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=r.uid, type="type_migrated", author=actor, field="type",
                            from_value=old_schema.name if old_schema else None, to_value=target.name,
                            details=f"migration {m.id}", timestamp=now()))
        new_state = e.after.get("state")
        if new_state and new_state != r.state:
            wf = workflows.workflow_for(db, r.workspace_id, target.uid)
            old = r.state
            workflows.apply_state(r, wf, new_state)
            db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=r.uid, type="transition", author=actor, field="state",
                                from_value=old, to_value=new_state, details=f"state mapped by migration {m.id}",
                                timestamp=now()))
        r.version = (r.version or 1) + 1
        r.updated_at = now()
    else:
        r.document_type_uid = target.uid
        for rev_uid, rv in e.revisions.items():
            rev = db.get(DocumentRevision, rev_uid)
            rev.attributes = rv["after"] if rev_uid != r.current_revision_uid else e.after["attributes"]
            flag_modified(rev, "attributes")
        r.updated_at = now()
    db.flush()


def apply(db: Session, m: TypeMigration, token: str, actor: str, grants_for: Callable[[str], object],
          batch_size: int = BATCH) -> dict:
    """The records the preview showed as ready, in batches, each record in its own savepoint: one that fails
    is recorded and the others go on. Needs the preview's token; applying again only does what is left."""
    if m.status == "reverted":
        raise MigrationError("this migration was reverted: make a new one")
    current = preview(db, m, grants_for)
    if current["token"] != token:
        raise MigrationError("the records or the plan changed since the preview: preview again")
    bad = [t for t in current["targets"] if t["status"] != "ok"]
    if bad:
        raise MigrationError("the target is not available everywhere: " + "; ".join(t["detail"] for t in bad))
    evs, _targets = evaluate(db, m, grants_for)
    ready = [e for e in evs if e.status == "ready"]
    if not m.inventory:
        m.inventory = {e.label["uid"]: _inventory_of(db, m.kind, e.record) for e in ready}
        flag_modified(m, "inventory")
    m.status = "applying"
    batch_no = 1 + max([0, *[i.batch or 0 for i in db.scalars(select(TypeMigrationItem).where(
        TypeMigrationItem.migration_id == m.id))]])
    _log(m, actor, "apply_started", ready=len(ready))
    db.commit()
    applied = failed = 0
    for start in range(0, len(ready), batch_size):
        chunk = ready[start:start + batch_size]
        for e in chunk:
            item = db.scalar(select(TypeMigrationItem).where(TypeMigrationItem.migration_id == m.id,
                                                             TypeMigrationItem.record_uid == e.label["uid"]))
            if item is not None and item.status == "applied":
                continue
            if item is None:
                item = TypeMigrationItem(migration_id=m.id, record_uid=e.label["uid"], workspace_id=e.label["workspace_id"])
                db.add(item)
            sp = db.begin_nested()
            try:
                _apply_one(db, m, e, actor)
                sp.commit()
                item.status, item.error = "applied", None
                applied += 1
            except Exception as exc:  # noqa: BLE001 — a record that cannot move is reported, the rest go on
                sp.rollback()
                item.status, item.error = "failed", f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
                failed += 1
            item.batch, item.actor, item.at = batch_no, actor, now()
            item.before = {**e.before, "revisions": {k: v["before"] for k, v in e.revisions.items()}}
            item.after = {**e.after, "revisions": {k: v["after"] for k, v in e.revisions.items()}}
            item.provenance = {**e.provenance, **{f"revision:{k}": v["provenance"] for k, v in e.revisions.items()
                                                  if v["provenance"]}}
        _log(m, actor, "batch", batch=batch_no, records=len(chunk))
        db.commit()
        batch_no += 1
    left = [e for e in evaluate(db, m, grants_for)[0] if e.status in ("ready", "review", "blocked")]
    failures = db.scalar(select(func.count()).where(TypeMigrationItem.migration_id == m.id,
                                                    TypeMigrationItem.status == "failed"))
    m.status = "applied" if not left and not failures else "partially_applied"
    _log(m, actor, "apply_finished", applied=applied, failed=failed, left=len(left))
    db.commit()
    return {"applied": applied, "failed": failed, "left": len(left), "status": m.status}


def revert(db: Session, m: TypeMigration, actor: str, uids: Optional[list[str]] = None) -> dict:
    """Put applied records back as they were (through the ledger for assets), and say so in their history."""
    from app.ledger import service as ledger
    from app.services import workflows
    items = list(db.scalars(select(TypeMigrationItem).where(TypeMigrationItem.migration_id == m.id,
                                                            TypeMigrationItem.status == "applied")))
    if uids is not None:
        items = [i for i in items if i.record_uid in set(uids)]
    done = failed = 0
    for i in items:
        sp = db.begin_nested()
        try:
            old = db.get(Schema, i.before.get("type_uid"))
            if m.kind == "objects":
                a = db.get(Asset, i.record_uid)
                b = i.before.get("attributes") or {}
                cur = a.attributes or {}
                changes = {f"attr:{k}": b.get(k) for k in set(b) | set(cur) if b.get(k) != cur.get(k)}
                ledger.retype_to(db, i.workspace_id, actor, [a.uid], old, reason=f"revert of migration {m.id}",
                                 changes={a.uid: changes})
            elif m.kind == "tickets":
                t = db.get(Issue, i.record_uid)
                t.schema_uid, t.attributes = old.uid, i.before.get("attributes") or {}
                flag_modified(t, "attributes")
                if i.before.get("state") and i.before["state"] != t.state:
                    workflows.apply_state(t, workflows.workflow_for(db, t.workspace_id, old.uid), i.before["state"])
                db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=t.uid, type="type_migrated", author=actor,
                                    field="type", to_value=old.name, details=f"revert of migration {m.id}",
                                    timestamp=now()))
            else:
                d = db.get(Document, i.record_uid)
                d.document_type_uid = old.uid
                for rev_uid, attrs in (i.before.get("revisions") or {}).items():
                    rev = db.get(DocumentRevision, rev_uid)
                    if rev is not None:
                        rev.attributes = attrs
                        flag_modified(rev, "attributes")
            db.flush()
            sp.commit()
            i.status, i.at, i.actor = "reverted", now(), actor
            done += 1
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            i.error = f"revert failed: {exc}"
            failed += 1
    still = db.scalar(select(func.count()).where(TypeMigrationItem.migration_id == m.id,
                                                 TypeMigrationItem.status == "applied"))
    if not still:
        m.status = "reverted"
    _log(m, actor, "reverted", records=done, failed=failed)
    db.commit()
    return {"reverted": done, "failed": failed, "status": m.status}


def verify(db: Session, m: TypeMigration, actor: str, deprecate: bool = False) -> dict:
    """Each applied record against the inventory taken before: same uid and key, on the target type, its
    comments, files, relations, map positions, placements, activities, revisions and links all still there.
    Every difference is an exception. Deprecates the source type only when asked and nothing depends on it."""
    model = _model(m.kind)
    exceptions = []
    counts = Counter()
    for i in db.scalars(select(TypeMigrationItem).where(TypeMigrationItem.migration_id == m.id)):
        counts[i.status] += 1
        if i.status == "failed":
            exceptions.append({"uid": i.record_uid, "workspace_id": i.workspace_id, "problem": i.error})
            continue
        if i.status != "applied":
            continue
        rec = db.get(model, i.record_uid)
        if rec is None:
            exceptions.append({"uid": i.record_uid, "workspace_id": i.workspace_id, "problem": "the record is gone"})
            continue
        type_now = rec.schema_uid if m.kind != "documents" else rec.document_type_uid
        if type_now != i.after.get("type_uid"):
            exceptions.append({"uid": rec.uid, "workspace_id": i.workspace_id,
                               "problem": f"its type is now {type_now}, not {i.after.get('type_uid')}"})
        was = (m.inventory or {}).get(rec.uid)
        if was:
            now_ = _inventory_of(db, m.kind, rec)
            for k, v in was.items():
                if now_.get(k) != v:
                    exceptions.append({"uid": rec.uid, "workspace_id": i.workspace_id,
                                       "problem": f"{k}: {v} before, {now_.get(k)} now"})
        if m.kind == "objects" and rec.workspace_id != i.workspace_id:
            exceptions.append({"uid": rec.uid, "workspace_id": i.workspace_id, "problem": "it changed workspace"})
    dep = deprecation_check(db, m)
    if deprecate:
        if not dep["possible"]:
            raise MigrationError("the old type cannot be deprecated: " +
                                 "; ".join(f"{b['what']}: {b['detail']}" for b in dep["blocking"]))
        src = db.get(Schema, m.source_schema_uid)
        meta = dict(src.metadata_json or {})
        meta["deprecated"] = {"at": now().isoformat(), "by": actor, "migration": m.id,
                              "replaced_by": {"package_id": m.target["package_id"], "type": m.target["type"],
                                              "version": m.target.get("version")}}
        src.metadata_json = meta
        flag_modified(src, "metadata_json")
        dep = {**dep, "deprecated": True}
    report = {"at": now().isoformat(), "by": actor, "records": dict(counts), "exceptions": exceptions,
              "deprecation": dep}
    m.verification = report
    if not exceptions and m.status == "applied":
        m.status = "verified"
    _log(m, actor, "verified", exceptions=len(exceptions), deprecated=dep.get("deprecated"))
    db.commit()
    return report


# =========================================================================== plans

def create(db: Session, actor: str, kind: str, source_schema_uid: str, target: dict, workspaces: Optional[list[str]],
           include_descendants: bool, reason: Optional[str]) -> TypeMigration:
    if kind not in KINDS:
        raise MigrationError("kind is objects, tickets or documents")
    src = db.get(Schema, source_schema_uid)
    if src is None or src.applies_to != kind:
        raise MigrationError("the source is not a type of that kind")
    if not (reason or "").strip():
        raise MigrationError("give a reason: it is kept with every record moved")
    declared = {(t["package_id"], t["type"]): t for t in shipped_types(kind)}
    t = declared.get((target.get("package_id"), target.get("type")))
    if t is None:
        raise MigrationError("the target is not a type of a package this installation ships")
    if t["abstract"]:
        raise MigrationError(f"{t['type']} is abstract: choose a type below it")
    fam = family(db, source_schema_uid, include_descendants)
    found = owning_workspaces(db, kind, [s.uid for s in fam])
    chosen = sorted(set(workspaces or found) & set(found)) if workspaces else sorted(found)
    if not chosen:
        raise MigrationError("no records of that type in the workspaces chosen")
    m = TypeMigration(id=str(uuid.uuid4()), kind=kind, source_schema_uid=src.uid,
                      source={"name": src.name, "workspace_id": src.workspace_id, "is_global": src.is_global,
                              "family": [{"uid": s.uid, "name": s.name, "workspace_id": s.workspace_id} for s in fam],
                              "attributes": _effective(db, src)},
                      include_descendants=include_descendants, workspaces=chosen,
                      target={"package_id": t["package_id"], "type": t["type"], "area": AREA[kind],
                              "version": t["version"]},
                      reason=reason.strip(), status="draft", created_by=actor, log=[])
    db.add(m)
    db.flush()
    first_ok = next((r for r in (resolve_target(db, ws, kind, m.target) for ws in chosen) if r["status"] == "ok"), None)
    m.mapping = propose(db, m, db.get(Schema, first_ok["schema_uid"]) if first_ok else None)
    _log(m, actor, "created", source=src.uid, target=m.target, workspaces=chosen)
    db.commit()
    return m


def change(db: Session, m: TypeMigration, actor: str, body: dict) -> TypeMigration:
    """The administrator's decisions: the mapping, the workspaces, individual records, the reason."""
    if m.status in ("verified", "reverted"):
        raise MigrationError(f"a {m.status} migration is closed")
    mapping = copy.deepcopy(m.mapping or {})
    for key, rule in (body.get("attributes") or {}).items():
        if key in PRESERVED:
            raise MigrationError(f"{key} is never changed by a migration")
        if rule.get("action") not in ACTIONS:
            raise MigrationError(f"{key}: the action is one of {', '.join(ACTIONS)}")
        mapping.setdefault("attributes", {})[key] = {**(mapping.get("attributes", {}).get(key) or {}), **rule}
    for key, value in (body.get("defaults") or {}).items():
        mapping.setdefault("defaults", {})[key] = value
    for st, to in (body.get("states") or {}).items():
        mapping.setdefault("states", {})[st] = to
    for uid, decision in (body.get("records") or {}).items():
        if decision not in ("migrate", "skip"):
            raise MigrationError("a record's decision is migrate or skip")
        recs = mapping.setdefault("records", {})
        if decision == "migrate":
            recs.pop(uid, None)
        else:
            recs[uid] = "skip"
    if "workspaces" in body:
        fam = family(db, m.source_schema_uid, m.include_descendants)
        found = owning_workspaces(db, m.kind, [s.uid for s in fam])
        m.workspaces = sorted(set(body["workspaces"]) & set(found))
    if body.get("reason"):
        m.reason = str(body["reason"]).strip()
    m.mapping = mapping
    flag_modified(m, "mapping")
    _log(m, actor, "mapping_changed", changes={k: body[k] for k in body if k != "reason"})
    db.commit()
    return m


def view(m: TypeMigration, with_log: bool = True) -> dict:
    return {"id": m.id, "kind": m.kind, "source_schema_uid": m.source_schema_uid, "source": m.source,
            "include_descendants": m.include_descendants, "workspaces": m.workspaces, "target": m.target,
            "mapping": m.mapping, "reason": m.reason, "status": m.status, "verification": m.verification,
            "created_by": m.created_by, "created_at": m.created_at, "updated_at": m.updated_at,
            **({"log": m.log} if with_log else {})}


def fields(db: Session, m: TypeMigration) -> dict:
    """What the mapping step offers: the source's fields (with values seen), the target's fields (with their
    choices), and — for tickets — the target workflow's states, from the first workspace where the target is."""
    from app.services import workflows
    fam = family(db, m.source_schema_uid, m.include_descendants)
    recs = _records(db, m.kind, [s.uid for s in fam], m.workspaces)
    values = _source_values(db, m.kind, recs)
    src = {}
    for s in fam:
        for a in _effective(db, s):
            src.setdefault(_key(a), {"key": _key(a), "name": a.get("name") or _key(a), "type": a.get("type") or "string",
                                     "options": _option_values(a)})
    for k in values:
        src.setdefault(k, {"key": k, "name": k, "type": "string", "options": []})
    for k in src:
        src[k]["values"] = [v for v, _n in values.get(k, Counter()).most_common(50)]
    ok = next((r for r in (resolve_target(db, ws, m.kind, m.target) for ws in m.workspaces) if r["status"] == "ok"), None)
    target = db.get(Schema, ok["schema_uid"]) if ok else None
    tgt = [{"key": _key(a), "name": a.get("name") or _key(a), "type": a.get("type") or "string",
            "required": bool(a.get("required")), "options": _option_values(a)} for a in _effective(db, target)]
    states = []
    if m.kind == "tickets" and ok:
        states = [{"key": s["key"], "name": s.get("name") or s["key"]}
                  for s in (workflows.workflow_for(db, ok["workspace_id"], ok["schema_uid"]) or {}).get("states") or []]
    return {"source": [src[k] for k in sorted(src) if k not in PRESERVED], "target": tgt, "target_states": states,
            "source_states": sorted({r.state for r in recs}) if m.kind == "tickets" else [],
            "target_schema_uid": ok["schema_uid"] if ok else None}
