"""What a newer version of a package changes, said change by change, against what a workspace has.

Three versions are compared: the definitions the workspace was given (its snapshot), the newer version, and
the workspace's own definitions today (which show its local edits). Each change is one of:

    additive     new types, attributes, options, kinds, enumerations, classes — applied automatically
    definition   a label, a description, an icon, aliases — applied automatically where the workspace has
                 not edited it itself
    breaking     a removal, a rename, an attribute's type changed, a type moved in the tree or no longer
                 concrete, tighter validation (a pattern, unique, required, single-valued, fewer options) —
                 needs a decision: keep the workspace's definition, or apply the change

and says whether it touches something the workspace edited (a conflict), and how many records it affects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.schema import Schema
from app.packages import compile as c
from app.packages.model import Package

ADDITIVE, DEFINITION, BREAKING = "additive", "definition", "breaking"
# The attribute properties whose change only relabels; any other change of a definition is checked below.
LABELS = ("name",)


@dataclass
class Change:
    id: str                       # stable: what a migration plan's decision names
    category: str                 # additive | definition | breaking
    area: str                     # object_types | ticket_types | document_types | enumerations | equipment_classes
    subject: str                  # the type, kind, base or enumeration
    element: Optional[str]        # the attribute key or option id, when it is about one
    what: str                     # added | removed | renamed | relabelled | retyped | moved | tightened | …
    detail: str
    before: Optional[dict] = None
    after: Optional[dict] = None
    conflict: Optional[str] = None      # what the workspace changed here itself
    records: int = 0                    # how many records it bears on
    violations: int = 0                 # values the newer definition would not accept
    actions: list = field(default_factory=lambda: ["apply", "keep"])

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "category", "area", "subject", "element", "what", "detail",
                                              "before", "after", "conflict", "records", "violations", "actions")}


# --------------------------------------------------------------------------- normalising definitions

def _sets(sections: dict, extra_sets: dict) -> dict:
    return {**extra_sets, **(sections.get("option_sets") or {})}


def _pkg(sections: dict, package_id: str) -> Package:
    from pathlib import Path
    return Package(id=package_id, version="", name="", description="", owner="", depends={}, provides=[],
                   path=Path("."), checksum="", sections=sections)


def definitions(sections: dict, package_id: str, extra_sets: Optional[dict] = None) -> dict:
    """A package's definitions keyed for comparison."""
    sets = _sets(sections, extra_sets or {})
    p = _pkg(sections, package_id)
    raw_types = {t["name"]: t for t in (sections.get("object_types") or {}).get("types") or []}
    types = {}
    for t in c.object_types(p, sets):
        types[t.name] = {"parent": t.parent, "abstract": t.abstract, "description": t.description, "icon": t.icon,
                         "aliases": t.aliases, "locatable": t.locatable, "map_layer": t.map_layer,
                         "attributes": {a["key"]: a for a in t.attributes},
                         "attr_renamed_from": {a["key"]: a.get("renamed_from")
                                               for a in raw_types[t.name].get("attributes") or []
                                               if a.get("renamed_from")}}
    kinds = {}
    for area in ("ticket_types", "document_types"):
        k = c.kind_set(p, area, sets)
        if k:
            kinds[area] = {"base": {a["key"]: a for a in k.base_attributes},
                           "kinds": {name: {"description": d, "icon": i} for name, d, i in k.kinds},
                           "fields": {name: {a["key"]: a for a in attrs} for name, attrs in k.kind_attributes.items()}}
    enums = {}
    for e in c.enumerations(p, sets):
        enums[f"{e['applies_to']}.{e['key']}"] = {"name": e["name"], "default": e["default"],
                                                  "options": {o["id"]: o for o in e["options"]}}
    classes = set((sections.get("equipment_classes") or {}).get("classes") or [])
    former = dict((sections.get("object_types") or {}).get("former_names") or {})
    extensions = {}
    for e in c.extensions(p, sets):
        extensions[(e.area, e.type)] = {"attributes": {a["key"]: a for a in e.attributes},
                                        "options": {k: {o["id"]: o for o in v} for k, v in e.options.items()}}
    flows = {w["id"]: {"name": w.get("name"), "initial": w.get("initial"), "states": w.get("states"),
                       "transitions": w.get("transitions"), "applies_to": list(w.get("applies_to") or [])}
             for w in sections.get("workflows") or [] if package_id != "core-facility"}
    return {"types": types, "kinds": kinds, "enumerations": enums, "classes": classes, "former_names": former,
            "extensions": extensions, "workflows": flows}


# --------------------------------------------------------------------------- comparing attributes

def _tighter(old: dict, new: dict) -> list[str]:
    out = []
    if new.get("regex") and new.get("regex") != old.get("regex"):
        out.append(f"must match {new['regex']}")
    if new.get("unique") and not old.get("unique"):
        out.append("must be unique")
    if new.get("required") and not old.get("required"):
        out.append("is required")
    if old.get("multiValue") and not new.get("multiValue"):
        out.append("takes one value only")
    return out


def _attribute_changes(area: str, subject: str, old: dict, new: dict, renamed: dict) -> list[Change]:
    out: list[Change] = []
    base = f"{area}/{subject}/attributes"
    renamed_old = {v: k for k, v in renamed.items()}          # old key -> new key
    for key, n in new.items():
        if key in renamed and renamed[key] in old and key not in old:
            out.append(Change(f"{base}/{key}/renamed", BREAKING, area, subject, key, "renamed",
                              f"attribute {renamed[key]!r} becomes {key!r}: values move with it",
                              old[renamed[key]], n))
            continue
        o = old.get(key)
        if o is None:
            out.append(Change(f"{base}/{key}/added", ADDITIVE, area, subject, key, "added",
                              f"new attribute {n['name']!r}", None, n))
            continue
        if o.get("type") != n.get("type") or o.get("referenceType") != n.get("referenceType"):
            out.append(Change(f"{base}/{key}/retyped", BREAKING, area, subject, key, "retyped",
                              f"{key!r} changes from {o.get('type')} to {n.get('type')}", o, n))
            continue
        tighter = _tighter(o, n)
        if tighter:
            out.append(Change(f"{base}/{key}/tightened", BREAKING, area, subject, key, "tightened",
                              f"{key!r} " + ", ".join(tighter), o, n))
        oo = {x["id"]: x for x in o.get("options") or []}
        no = {x["id"]: x for x in n.get("options") or []}
        for oid in no:
            if oid not in oo:
                out.append(Change(f"{base}/{key}/options/{oid}/added", ADDITIVE, area, subject, f"{key}:{oid}",
                                  "added", f"{key!r} gains the option {no[oid]['value']!r}", None, no[oid]))
            elif oo[oid].get("value") != no[oid].get("value"):
                out.append(Change(f"{base}/{key}/options/{oid}/relabelled", DEFINITION, area, subject,
                                  f"{key}:{oid}", "relabelled",
                                  f"option {oid!r} reads {no[oid]['value']!r} instead of {oo[oid]['value']!r}",
                                  oo[oid], no[oid]))
        for oid in oo:
            if oid not in no:
                out.append(Change(f"{base}/{key}/options/{oid}/removed", BREAKING, area, subject, f"{key}:{oid}",
                                  "removed", f"{key!r} loses the option {oo[oid]['value']!r}", oo[oid], None))
        if o.get("name") != n.get("name"):
            out.append(Change(f"{base}/{key}/relabelled", DEFINITION, area, subject, key, "relabelled",
                              f"{key!r} is called {n['name']!r} instead of {o['name']!r}", o, n))
        if not o.get("multiValue") and n.get("multiValue"):
            out.append(Change(f"{base}/{key}/multi", ADDITIVE, area, subject, key, "widened",
                              f"{key!r} takes several values", o, n))
        if o.get("indexed") != n.get("indexed") or o.get("readOnly") != n.get("readOnly"):
            out.append(Change(f"{base}/{key}/flags", DEFINITION, area, subject, key, "changed",
                              f"{key!r}: indexed {n.get('indexed')}, read-only {n.get('readOnly')}", o, n))
    for key, o in old.items():
        if key not in new and key not in renamed_old:
            out.append(Change(f"{base}/{key}/removed", BREAKING, area, subject, key, "removed",
                              f"attribute {o['name']!r} ({key}) is no longer defined", o, None,
                              actions=["apply", "keep"]))
    return out


def compare(old: dict, new: dict) -> list[Change]:
    """Every difference between two versions' definitions."""
    out: list[Change] = []
    ot, nt = old["types"], new["types"]
    # A type renamed is listed under former_names (new: old): seeding renames it in place, keeping its uid.
    renamed_types = {n: o for n, o in new.get("former_names", {}).items() if n in nt and o in ot and n not in ot}
    renamed_old = {v: k for k, v in renamed_types.items()}
    for name, n in nt.items():
        source = renamed_types.get(name) if name not in ot and renamed_types.get(name) in ot else None
        o = ot.get(name) or (ot.get(source) if source else None)
        if o is None:
            out.append(Change(f"object_types/{name}/added", ADDITIVE, "object_types", name, None, "added",
                              f"new type {name!r}" + (f" under {n['parent']!r}" if n["parent"] else ""), None,
                              {"parent": n["parent"]}))
            continue
        if source:
            out.append(Change(f"object_types/{name}/renamed", BREAKING, "object_types", name, None, "renamed",
                              f"type {source!r} is called {name!r} (same records, same uid)",
                              {"name": source}, {"name": name}, actions=["apply"]))
        if o["parent"] != n["parent"]:
            out.append(Change(f"object_types/{name}/moved", BREAKING, "object_types", name, None, "moved",
                              f"{name!r} moves from under {o['parent']!r} to under {n['parent']!r}",
                              {"parent": o["parent"]}, {"parent": n["parent"]}, actions=["apply", "keep"]))
        if not o["abstract"] and n["abstract"]:
            out.append(Change(f"object_types/{name}/abstract", BREAKING, "object_types", name, None, "tightened",
                              f"{name!r} is no longer a type records can have", {"abstract": False},
                              {"abstract": True}, actions=["apply", "keep"]))
        elif o["abstract"] and not n["abstract"]:
            out.append(Change(f"object_types/{name}/concrete", ADDITIVE, "object_types", name, None, "widened",
                              f"records can be of type {name!r}", {"abstract": True}, {"abstract": False}))
        for prop in ("description", "icon", "aliases", "locatable", "map_layer"):
            if o[prop] != n[prop]:
                out.append(Change(f"object_types/{name}/{prop}", DEFINITION, "object_types", name, None, "changed",
                                  f"{name!r}: new {prop}", {prop: o[prop]}, {prop: n[prop]}))
        out.extend(_attribute_changes("object_types", name, o["attributes"], n["attributes"], n["attr_renamed_from"]))
    for name, o in ot.items():
        if name not in nt and name not in renamed_old:
            out.append(Change(f"object_types/{name}/removed", BREAKING, "object_types", name, None, "removed",
                              f"type {name!r} is no longer defined", {"parent": o["parent"]}, None,
                              actions=["apply", "keep"]))

    for area in ("ticket_types", "document_types"):
        ok, nk = old["kinds"].get(area), new["kinds"].get(area)
        if not ok and not nk:
            continue
        ok = ok or {"base": {}, "kinds": {}}
        nk = nk or {"base": {}, "kinds": {}}
        out.extend(_attribute_changes(area, "base", ok["base"], nk["base"], {}))
        for name, n in nk["kinds"].items():
            if name not in ok["kinds"]:
                out.append(Change(f"{area}/{name}/added", ADDITIVE, area, name, None, "added", f"new kind {name!r}",
                                  None, n))
            elif ok["kinds"][name] != n:
                out.append(Change(f"{area}/{name}/changed", DEFINITION, area, name, None, "changed",
                                  f"kind {name!r}: new description or icon", ok["kinds"][name], n))
        for name in nk["kinds"]:
            if name in ok["kinds"] or (nk.get("fields") or {}).get(name):
                out.extend(_attribute_changes(area, name, (ok.get("fields") or {}).get(name, {}),
                                              (nk.get("fields") or {}).get(name, {}), {}))
        for name in ok["kinds"]:
            if name not in nk["kinds"]:
                out.append(Change(f"{area}/{name}/removed", BREAKING, area, name, None, "removed",
                                  f"kind {name!r} is no longer defined", ok["kinds"][name], None,
                                  actions=["apply", "keep"]))

    oe, ne = old["enumerations"], new["enumerations"]
    for key, n in ne.items():
        o = oe.get(key)
        if o is None:
            out.append(Change(f"enumerations/{key}/added", ADDITIVE, "enumerations", key, None, "added",
                              f"new enumeration {n['name']!r} ({key})", None, {"options": list(n["options"])}))
            continue
        for oid, opt in n["options"].items():
            if oid not in o["options"]:
                out.append(Change(f"enumerations/{key}/options/{oid}/added", ADDITIVE, "enumerations", key, oid,
                                  "added", f"{key} gains {opt['value']!r}", None, opt))
            elif o["options"][oid] != opt:
                out.append(Change(f"enumerations/{key}/options/{oid}/relabelled", DEFINITION, "enumerations", key,
                                  oid, "relabelled", f"{key}: option {oid!r} changes", o["options"][oid], opt))
        for oid, opt in o["options"].items():
            if oid not in n["options"]:
                out.append(Change(f"enumerations/{key}/options/{oid}/removed", BREAKING, "enumerations", key, oid,
                                  "removed", f"{key} loses {opt['value']!r}", opt, None))
        if o["name"] != n["name"] or o["default"] != n["default"]:
            out.append(Change(f"enumerations/{key}/changed", DEFINITION, "enumerations", key, None, "changed",
                              f"{key}: new name or default", {"name": o["name"], "default": o["default"]},
                              {"name": n["name"], "default": n["default"]}))
    for key, o in oe.items():
        if key not in ne:
            out.append(Change(f"enumerations/{key}/removed", BREAKING, "enumerations", key, None, "removed",
                              f"enumeration {key} is no longer defined", {"name": o["name"]}, None,
                              actions=["apply", "keep"]))

    for (area, subject), n in new.get("extensions", {}).items():
        o = old.get("extensions", {}).get((area, subject), {"attributes": {}, "options": {}})
        out.extend(_extension_changes(area, subject, o, n))
    for (area, subject), o in old.get("extensions", {}).items():
        if (area, subject) not in new.get("extensions", {}):
            out.extend(_extension_changes(area, subject, o, {"attributes": {}, "options": {}}))

    ow, nw = old.get("workflows", {}), new.get("workflows", {})
    for wid, n in nw.items():
        if wid not in ow:
            out.append(Change(f"workflows/{wid}/added", ADDITIVE, "workflows", wid, None, "added",
                              f"new workflow {n['name']!r}" + (f" for {', '.join(n['applies_to'])}" if n["applies_to"] else ""),
                              None, n))
        elif ow[wid] != n:
            out.append(Change(f"workflows/{wid}/changed", DEFINITION, "workflows", wid, None, "changed",
                              f"workflow {n['name']!r}: new states, transitions or kinds", ow[wid], n))
    for wid, o in ow.items():
        if wid not in nw:
            out.append(Change(f"workflows/{wid}/removed", BREAKING, "workflows", wid, None, "removed",
                              f"workflow {o['name']!r} is no longer in the package; the workspace keeps its copy",
                              o, None, actions=["keep"]))

    for cls in sorted(new["classes"] - old["classes"]):
        out.append(Change(f"equipment_classes/{cls}/added", ADDITIVE, "equipment_classes", cls, None, "added",
                          f"new equipment class {cls!r}"))
    for cls in sorted(old["classes"] - new["classes"]):
        out.append(Change(f"equipment_classes/{cls}/removed", BREAKING, "equipment_classes", cls, None, "removed",
                          f"equipment class {cls!r} is no longer offered", actions=["apply", "keep"]))
    return out


def _extension_changes(area: str, subject: str, old: dict, new: dict) -> list[Change]:
    """What a package adds to another package's type, between two versions: attributes, and options."""
    out = _attribute_changes(area, subject, old["attributes"], new["attributes"], {})
    for key in sorted(set(old["options"]) | set(new["options"])):
        oo, no = old["options"].get(key, {}), new["options"].get(key, {})
        base = f"{area}/{subject}/attributes/{key}/options"
        for oid, opt in no.items():
            if oid not in oo:
                out.append(Change(f"{base}/{oid}/added", ADDITIVE, area, subject, f"{key}:{oid}", "added",
                                  f"{key!r} gains the option {opt['value']!r}", None, opt))
            elif oo[oid].get("value") != opt.get("value"):
                out.append(Change(f"{base}/{oid}/relabelled", DEFINITION, area, subject, f"{key}:{oid}",
                                  "relabelled", f"option {oid!r} reads {opt['value']!r}", oo[oid], opt))
        for oid, opt in oo.items():
            if oid not in no:
                out.append(Change(f"{base}/{oid}/removed", BREAKING, area, subject, f"{key}:{oid}", "removed",
                                  f"{key!r} loses the option {opt['value']!r}", opt, None))
    return out


# --------------------------------------------------------------------------- the workspace side

def workspace_schemas(db: Session, workspace_id: str, area: str) -> dict[str, Schema]:
    applies = {"object_types": "objects", "ticket_types": "tickets", "document_types": "documents"}[area]
    return {s.name: s for s in db.scalars(select(Schema).where(Schema.workspace_id == workspace_id,
                                                               Schema.applies_to == applies))}


def _records(db: Session, area: str, schema_uids: list[str]):
    """(model, attributes column, filter) for the records of these types."""
    from app.models.asset import Asset
    from app.models.document import Document, DocumentRevision
    from app.models.issue import Issue
    if area == "object_types":
        return Asset, Asset.attributes, Asset.schema_uid.in_(schema_uids)
    if area == "ticket_types":
        return Issue, Issue.attributes, Issue.schema_uid.in_(schema_uids)
    docs = select(Document.uid).where(Document.document_type_uid.in_(schema_uids))
    return DocumentRevision, DocumentRevision.attributes, DocumentRevision.document_uid.in_(docs)


def _values(db: Session, area: str, schema_uids: list[str], key: str) -> list:
    model, column, where = _records(db, area, schema_uids)
    return [v for v in db.scalars(select(column[key]).where(where, column.has_key(key))) if v not in (None, "", [])]


def _subtree(db: Session, workspace_id: str, area: str, schema: Schema) -> list[str]:
    """The type and every type under it, in this workspace: their records carry its attributes."""
    applies = {"object_types": "objects", "ticket_types": "tickets", "document_types": "documents"}[area]
    rows = list(db.scalars(select(Schema).where(Schema.applies_to == applies,
                                                (Schema.workspace_id == workspace_id) | Schema.is_global.is_(True))))
    children: dict = {}
    for r in rows:
        children.setdefault(r.parent_schema_uid, []).append(r.uid)
    out, todo = [], [schema.uid]
    while todo:
        uid = todo.pop()
        out.append(uid)
        todo.extend(children.get(uid, []))
    return out


def _violations(values: list, after: dict) -> int:
    n = 0
    pattern = re.compile(after["regex"]) if after.get("regex") else None
    options = {o["id"] for o in after.get("options") or []} | {o["value"] for o in after.get("options") or []}
    for v in values:
        items = v if isinstance(v, list) else [v]
        if pattern and any(not pattern.fullmatch(str(x)) for x in items):
            n += 1
        elif not after.get("multiValue") and isinstance(v, list) and len(v) > 1:
            n += 1
        elif after.get("options") and any(str(x) not in options for x in items):
            n += 1
    return n


def assess(db: Session, workspace_id: str, changes: list[Change], old: dict, scope_names: Optional[set] = None) -> list[Change]:
    """Each change against the workspace: whether it touches the workspace's own edits, and the records it
    bears on. `scope_names` limits object types to those this workspace holds itself (a beamline holds only
    its machine's own; the shared ones are the catalogue workspace's)."""
    by_area = {a: workspace_schemas(db, workspace_id, a) for a in ("object_types", "ticket_types", "document_types")}
    out = []
    for ch in changes:
        if ch.area == "object_types" and scope_names is not None and ch.subject not in scope_names and \
                (ch.before or {}).get("name") not in scope_names:
            continue
        schemas = by_area.get(ch.area, {})
        if ch.area in ("ticket_types", "document_types"):
            base_name = {"ticket_types": "Ticket", "document_types": "Document"}[ch.area]
            subject_schema = schemas.get(base_name if ch.subject == "base" else ch.subject)
        else:
            subject_schema = schemas.get(ch.subject) or schemas.get((ch.before or {}).get("name") or "")
        if subject_schema is not None and ch.element and ch.what != "added" and ":" not in ch.element:
            here = {a.get("key"): a for a in subject_schema.attributes or []}
            source_key = (ch.before or {}).get("key", ch.element)
            if ch.area == "object_types":
                given = old["types"].get(ch.subject, {}).get("attributes", {})
            elif ch.subject == "base":
                given = old["kinds"].get(ch.area, {}).get("base", {})
            else:
                given = (old["kinds"].get(ch.area, {}).get("fields") or {}).get(ch.subject, {})
            mine = here.get(source_key)
            if mine is None and source_key in given:
                ch.conflict = "the workspace removed this attribute itself"
            elif mine is not None and source_key in given and _comparable(mine) != _comparable(given[source_key]):
                ch.conflict = "the workspace changed this attribute itself"
            uids = _subtree(db, workspace_id, ch.area, subject_schema)
            values = _values(db, ch.area, uids, source_key)
            ch.records = len(values)
            if ch.what in ("tightened", "retyped") and ch.after:
                ch.violations = _violations(values, ch.after) if ch.what == "tightened" else len(values)
        elif subject_schema is not None and ch.element and ":" in ch.element and ch.what == "removed":
            key, oid = ch.element.split(":", 1)
            uids = _subtree(db, workspace_id, ch.area, subject_schema)
            values = _values(db, ch.area, uids, key)
            label = (ch.before or {}).get("value")
            ch.records = sum(1 for v in values if any(str(x) in (oid, label) for x in (v if isinstance(v, list) else [v])))
            ch.violations = ch.records
        elif subject_schema is not None and ch.what in ("removed", "moved", "tightened", "renamed") and not ch.element:
            model, _col, where = _records(db, ch.area, [subject_schema.uid])
            ch.records = db.scalar(select(func.count()).select_from(model).where(where)) or 0
        elif subject_schema is None and ch.what not in ("added",) and ch.area not in (
                "enumerations", "equipment_classes", "workflows"):
            ch.conflict = "the workspace no longer has this"
        out.append(ch)
    return out


def _comparable(attr: dict) -> dict:
    return {k: attr.get(k) for k in ("type", "name", "options", "regex", "unique", "required", "multiValue",
                                     "referenceType")}
