"""A proposal to make a custom type a standard one: the package YAML it would be, checked, for review.

When the standard type a migration needs does not exist yet, a custom definition can be promoted — through the
normal route: a new version of a package, reviewed, released and installed like any other. This writes the
proposal (the YAML entry, the package's next version, a checklist) and checks it: field keys, option ids, the
parent's package and the dependencies it would need, and that no shipped package already has the type. It never
changes a package this installation ships: those are files in the code, and change only by a release.
Once the new version is installed, the records are migrated to it with a type migration.
"""
from __future__ import annotations

import re
from typing import Optional

import yaml
from packaging.version import Version
from sqlalchemy.orm import Session

from app.models.schema import Schema

KEY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
OPTION = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
AREA = {"objects": "object_types", "tickets": "ticket_types", "documents": "document_types"}
TYPE_MAP = {"string": "string", "text": "text", "integer": "integer", "float": "float", "boolean": "boolean",
            "date": "date", "datetime": "datetime", "enumeration": "enumeration", "reference": "reference",
            "user": "user", "group": "group", "url": "url"}


def _closure(pid: str, catalog: dict) -> list[str]:
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        if p in out or p not in catalog:
            continue
        out.append(p)
        todo += list(catalog[p].depends)
    return out


def _declares(p, kind: str) -> dict:
    sec = p.section(AREA[kind]) or {}
    if kind == "objects":
        return {str(t["name"]): t for t in sec.get("types") or []}
    return {str(k["name"]): k for k in sec.get("kinds") or []}


def _bump(version: str) -> str:
    v = Version(version)
    return f"{v.major}.{v.minor + 1}.0"


def propose(db: Session, schema_uid: str, package_id: str, name: Optional[str] = None) -> dict:
    from app.packages.loader import available
    catalog = available()
    schema = db.get(Schema, schema_uid)
    if schema is None:
        raise ValueError("no such type")
    pkg = catalog.get(package_id)
    if pkg is None:
        raise ValueError(f"no package {package_id!r} in this installation")
    kind = schema.applies_to or "objects"
    type_name = (name or schema.name).strip()
    problems: list[str] = []
    notes: list[str] = []

    # The name must be new in every shipped package: a type that exists is migrated to, not proposed again.
    for pid, p in catalog.items():
        if type_name in _declares(p, kind):
            problems.append(f"{pid} already declares {type_name!r}: migrate the records to it instead")

    # The parent: a type of this package or of one it depends on (or that it would have to depend on).
    parent_name = None
    depends_needed: list[str] = []
    if schema.parent_schema_uid:
        parent = db.get(Schema, schema.parent_schema_uid)
        parent_name = parent.name if parent else None
        if kind == "objects" and parent_name:
            owners = [pid for pid, p in catalog.items() if parent_name in _declares(p, kind)]
            reach = _closure(package_id, catalog)
            if not owners:
                problems.append(f"the parent {parent_name!r} is not a package type: promote it first, or choose a "
                                f"package type as the parent")
            elif not set(owners) & set(reach):
                depends_needed = owners[:1]
                notes.append(f"{package_id} must depend on {owners[0]} (which declares {parent_name!r})")

    # Fields: keys, types, option ids; and no clash with what the parent chain already has.
    inherited: set[str] = set()
    if parent_name:
        for pid in _closure(package_id, catalog) + depends_needed:
            p = catalog.get(pid)
            cur = parent_name
            seen = set()
            while p is not None and cur and cur not in seen:
                seen.add(cur)
                t = _declares(p, kind).get(cur)
                if t is None:
                    break
                inherited |= {str(a.get("key")) for a in t.get("attributes") or []}
                cur = t.get("parent")
    attributes = []
    keys = set()
    for a in schema.attributes or []:
        key = str(a.get("key") or a.get("name") or "")
        if not KEY.match(key):
            problems.append(f"field key {key!r}: lower case letters, digits and _, starting with a letter")
        if key in keys:
            problems.append(f"field key {key!r} appears twice")
        if key in inherited:
            problems.append(f"field key {key!r} is already defined by {parent_name!r} or above it")
        keys.add(key)
        t = TYPE_MAP.get(str(a.get("type") or "string"))
        if t is None:
            problems.append(f"{key}: type {a.get('type')!r} cannot be written in a package")
            t = "string"
        out = {"key": key, "name": str(a.get("name") or key), "type": t}
        if a.get("required"):
            out["required"] = True
        if a.get("multiValue"):
            out["multi"] = True
        if a.get("unique"):
            out["unique"] = True
        if a.get("unit"):
            out["unit"] = a["unit"]
        if a.get("regex"):
            out["regex"] = a["regex"]
        if t == "enumeration":
            opts, ids = [], set()
            for o in a.get("options") or []:
                oid = str(o.get("id") or "")
                if not OPTION.match(oid):
                    problems.append(f"{key}: option id {oid!r} is not a stable id (lower case, digits, _ . -)")
                if oid in ids:
                    problems.append(f"{key}: option id {oid!r} appears twice")
                ids.add(oid)
                opts.append({"id": oid, "value": str(o.get("value") if o.get("value") is not None else oid)})
            if not opts:
                problems.append(f"{key}: a choice list without choices")
            out["options"] = opts
        if t == "reference":
            ref = db.get(Schema, a.get("referenceSchemaUid")) if a.get("referenceSchemaUid") else None
            if ref is None:
                problems.append(f"{key}: the type it refers to is unknown")
            else:
                out["reference"] = ref.name
                if not any(ref.name in _declares(catalog[pid], "objects") for pid in _closure(package_id, catalog)):
                    notes.append(f"{key} refers to {ref.name!r}, which {package_id} does not reach: check it is a "
                                 f"package type it depends on")
            if a.get("includeChildren"):
                out["include_children"] = True
        attributes.append(out)

    entry: dict = {"name": type_name}
    if parent_name and kind == "objects":
        entry["parent"] = parent_name
    entry["description"] = schema.description or f"{type_name} (promoted from {schema.workspace_id})."
    if attributes:
        entry["attributes"] = attributes
    section = AREA[kind]
    body = ({section: {"types": [entry]}} if kind == "objects" else {section: {"kinds": [entry]}})
    snippet = yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=110)
    next_version = _bump(pkg.version)
    manifest = {"id": pkg.id, "version": next_version}
    if depends_needed:
        current = dict(pkg.depends) if isinstance(pkg.depends, dict) else {d: ">=0" for d in pkg.depends}
        manifest["depends"] = {**current, depends_needed[0]: ">=0"}
    checklist = [
        f"Add the entry below to backend/packages/{pkg.id}/ ({'object_types.yaml' if kind == 'objects' else section + ' file'}).",
        f"Raise {pkg.id}'s version from {pkg.version} to {next_version} in its package.yaml"
        + (f", and add the dependency on {depends_needed[0]}" if depends_needed else "") + ".",
        "Run the package checks (python -m app.packages validate) and the tests; open a merge request for review.",
        "Release; install or upgrade the package where the records live (or in their shared catalogue).",
        "Migrate the records with a type migration to the new standard type.",
    ]
    return {"ok": not problems, "problems": problems, "notes": notes, "package_id": pkg.id,
            "current_version": pkg.version, "next_version": next_version, "kind": kind, "type": type_name,
            "source": {"uid": schema.uid, "workspace_id": schema.workspace_id}, "yaml": snippet,
            "manifest": manifest, "checklist": checklist}
