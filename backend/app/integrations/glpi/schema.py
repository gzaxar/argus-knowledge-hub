"""GLPI's own schema — GLPI 11's custom asset definitions and their fields, GLPI 10's genericobject types and
fields-plugin containers — proposed as ARGUS workspace types and fields, applied only once a person approves.

A proposal reuses what the workspace already has (a type of the same name, a field of the same key or label
and a compatible type) and proposes the rest as workspace types under IT Equipment and workspace fields
(`glpi_<name>`); a GLPI field type ARGUS has no equivalent for is reported and its values kept unmapped.
The proposal carries a digest of GLPI's schema: when GLPI's schema changes, the new proposal awaits review
and until then the import keeps to the approved mapping — a source change never alters an ARGUS schema by
itself. The package types (IT, core-objects…) are never changed: fields GLPI adds to its standard items go on
the workspace's copy of the mapped type, as any local field would.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.integrations.glpi import source
from app.integrations.glpi.mapping import STANDARD_MAP, custom_field_kind
from app.models.schema import Schema

PARENT = "IT Equipment"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "field"


def _options(snapshot: dict, dropdown_itemtype: Optional[str]) -> list[dict]:
    values = ((snapshot.get("dropdowns") or {}).get(dropdown_itemtype or "") or {})
    seen, out = set(), []
    for gid, name in sorted(values.items(), key=lambda kv: str(kv[1])):
        oid = _slug(name)
        if oid in seen:
            oid = f"{oid}_{gid}"
        seen.add(oid)
        out.append({"id": oid, "value": str(name), "glpi_id": str(gid)})
    return out


def source_schema(snapshot: dict) -> dict:
    """GLPI's own schema, as the digest sees it: what changes only when GLPI's schema changes."""
    custom = snapshot.get("custom") or {}
    return {
        "definitions": sorted(({"system_name": d.get("system_name"), "label": d.get("label"),
                                "itemtype": source.custom_itemtype(d)} for d in custom.get("asset_definitions") or []),
                              key=lambda x: str(x["system_name"])),
        "fields": sorted(({"definition": f.get("assetdefinitions_id"), "system_name": f.get("system_name"),
                           "type": f.get("type"), "itemtype": f.get("itemtype"),
                           "multiple": bool((f.get("field_options") or {}).get("multiple")) if isinstance(
                               f.get("field_options"), dict) else False}
                          for f in custom.get("custom_fields") or []), key=lambda x: (str(x["definition"]),
                                                                                     str(x["system_name"]))),
        "containers": sorted(({"name": c.get("name"), "itemtypes": source._json_list(c.get("itemtypes"))}
                              for c in custom.get("plugin_containers") or []), key=lambda x: str(x["name"])),
        "plugin_fields": sorted(({"container": f.get("plugin_fields_containers_id"), "name": f.get("name"),
                                  "type": f.get("type"), "multiple": bool(f.get("multiple"))}
                                 for f in custom.get("plugin_fields") or [] if f.get("type") != "header"),
                                key=lambda x: (str(x["container"]), str(x["name"]))),
        "generic_types": sorted(({"itemtype": g.get("itemtype"), "name": g.get("name")}
                                 for g in custom.get("generic_types") or []), key=lambda x: str(x["itemtype"])),
    }


def digest(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(source_schema(snapshot), sort_keys=True, default=str).encode()).hexdigest()


def _workspace_types(db: Session, workspace_id: str) -> dict[str, Schema]:
    from app.services.asset_types import resolve_type_uids
    out = {}
    for name, uid in resolve_type_uids(db, workspace_id).items():
        s = db.get(Schema, uid)
        if s is not None:
            out[name.lower()] = s
            for alias in (s.metadata_json or {}).get("aliases") or []:
                out.setdefault(str(alias).lower(), s)
    return out


def _all_attributes(db: Session, schema: Schema) -> dict[str, dict]:
    from app.services.attribute_validation import effective_attributes
    return {a.get("key"): a for a in effective_attributes(db, schema)}


def _field(db, snapshot, schema: Optional[Schema], source_key: str, label: str, glpi_type, kind, note,
           argus_key: str, multiple: bool, dropdown: Optional[str]) -> dict:
    out = {"source": source_key, "label": label, "glpi_type": glpi_type, "kind": kind, "argus_key": argus_key,
           "multiple": multiple, "note": note}
    if kind is None:
        return {**out, "action": "unsupported"}
    if kind == "enumeration":
        opts = _options(snapshot, dropdown)
        if opts:
            out["options"] = opts
        else:
            out.update(kind="string", note=(note or "") + " no values could be read: kept as text")
    if schema is not None:
        have = _all_attributes(db, schema)
        same = have.get(argus_key) or next((a for a in have.values() if str(a.get("name", "")).lower() == label.lower()
                                            and a.get("type") == out["kind"]), None)
        if same is not None:
            if same.get("type") != out["kind"]:
                return {**out, "action": "conflict", "argus_key": same["key"],
                        "note": f"{same['key']} is a {same.get('type')} here, GLPI's is {out['kind']}: kept unmapped"}
            return {**out, "action": "reuse", "argus_key": same["key"]}
    return {**out, "action": "create"}


def propose(db: Session, workspace_id: str, snapshot: dict) -> dict:
    """What GLPI's schema would become in this workspace: reused, created, or not supported."""
    custom = snapshot.get("custom") or {}
    types = _workspace_types(db, workspace_id)
    out_types, extensions, unsupported = [], [], []
    by_definition: dict = {}
    for f in custom.get("custom_fields") or []:
        by_definition.setdefault(f.get("assetdefinitions_id"), []).append(f)
    defs = [(d.get("id"), source.custom_itemtype(d), d.get("system_name"), d.get("label") or d.get("system_name"))
            for d in custom.get("asset_definitions") or []]
    defs += [(None, g.get("itemtype"), g.get("itemtype"), g.get("name") or g.get("itemtype"))
             for g in custom.get("generic_types") or [] if g.get("itemtype")]
    for def_id, itemtype, system_name, label in defs:
        existing = types.get(str(label).lower()) or types.get(str(system_name).lower())
        entry = {"source": itemtype, "system_name": system_name, "label": label,
                 "action": "reuse" if existing else "create",
                 "argus_type": existing.name if existing else str(label), "parent": None if existing else PARENT,
                 "fields": []}
        for f in by_definition.get(def_id, []) if def_id is not None else []:
            kind, note = custom_field_kind(f, glpi11=True)
            opts = f.get("field_options") if isinstance(f.get("field_options"), dict) else {}
            fe = _field(db, snapshot, existing, f"custom_{f.get('system_name')}", str(f.get("label") or f.get("system_name")),
                        f.get("type"), kind, note, f"glpi_{_slug(f.get('system_name'))}", bool(opts.get("multiple")),
                        f.get("itemtype"))
            entry["fields"].append(fe)
            if fe["action"] in ("unsupported", "conflict"):
                unsupported.append({"on": itemtype, **fe})
        out_types.append(entry)
    containers = {c.get("id"): c for c in custom.get("plugin_containers") or []}
    for f in custom.get("plugin_fields") or []:
        if f.get("type") == "header":
            continue
        c = containers.get(f.get("plugin_fields_containers_id")) or {}
        for itemtype in source._json_list(c.get("itemtypes")):
            target = (STANDARD_MAP.get(itemtype) or {}).get("argus")
            if not target or target in ("ticket", "attachment"):
                unsupported.append({"on": itemtype, "source": f"{c.get('name')}.{f.get('name')}", "action": "unsupported",
                                    "note": f"fields on {itemtype} are not imported in this release"})
                continue
            schema = types.get(target.lower())
            kind, note = custom_field_kind(f, glpi11=False)
            dropdown = f"PluginFields{str(f.get('name')).capitalize()}Dropdown" if f.get("type") == "dropdown" else None
            fe = _field(db, snapshot, schema, f"{c.get('name')}.{f.get('name')}", str(f.get("label") or f.get("name")),
                        f.get("type"), kind, note, f"glpi_{_slug(c.get('name'))}_{_slug(f.get('name'))}",
                        bool(f.get("multiple")), dropdown)
            extensions.append({"on_itemtype": itemtype, "argus_type": target, "container": c.get("name"), **fe})
            if fe["action"] in ("unsupported", "conflict"):
                unsupported.append({"on": itemtype, **fe})
    return {"digest": digest(snapshot), "workspace_id": workspace_id, "types": out_types, "extensions": extensions,
            "unsupported": unsupported,
            "changes": sum(1 for t in out_types if t["action"] == "create")
            + sum(1 for t in out_types for f in t["fields"] if f["action"] == "create")
            + sum(1 for e in extensions if e["action"] == "create")}


def status(state: Optional[dict], snapshot: dict) -> str:
    """none: GLPI defines nothing custom; approved; awaiting review (first time, or GLPI's schema changed)."""
    src = source_schema(snapshot)
    if not any(src.values()):
        return "none"
    if state and state.get("approved") and state["approved"].get("digest") == digest(snapshot):
        return "approved"
    return "awaiting review"


def _attr(field: dict) -> dict:
    a = {"id": field["argus_key"], "key": field["argus_key"], "name": field["label"], "type": field["kind"],
         "required": False, "multiValue": bool(field.get("multiple")), "unique": False, "readOnly": False,
         "indexed": False, "description": f"From GLPI ({field['source']})."}
    if field.get("options"):
        a["options"] = [{"id": o["id"], "value": o["value"]} for o in field["options"]]
    return a


def approve(db: Session, workspace_id: str, proposal: dict, actor: Optional[str]) -> dict:
    """Apply a reviewed proposal: create the types and fields it proposes (reused ones are left as they are)
    and return the mapping the import keeps to until the next approval."""
    from app.services import asset_types, catalogue_icons
    usable = asset_types.resolve_type_uids(db, workspace_id)
    parent_uid = usable.get(PARENT) or usable.get("Asset")
    mapping = {"types": {}, "fields": {}, "options": {}, "extensions": {}}
    made = {}
    for t in proposal.get("types") or []:
        if t["action"] == "create":
            uid = f"{workspace_id}:glpi-type:{_slug(t['system_name'])}"
            schema = db.get(Schema, uid)
            if schema is None:
                schema = Schema(uid=uid, workspace_id=workspace_id, name=t["argus_type"],
                                description=f"Items of GLPI's custom asset type {t['system_name']}.",
                                applies_to="objects", is_concrete=True, parent_schema_uid=parent_uid, attributes=[],
                                metadata_json={"source": "glpi", "glpi_itemtype": t["source"]})
                db.add(schema)
                db.flush()
                made[t["argus_type"]] = uid
        else:
            schema = db.get(Schema, usable.get(t["argus_type"]))
        mapping["types"][t["source"]] = t["argus_type"]
        _add_fields(schema, [f for f in t["fields"] if f["action"] == "create"], workspace_id)
        mapping["fields"][t["source"]] = {f["source"]: f["argus_key"] for f in t["fields"]
                                          if f["action"] in ("create", "reuse")}
        mapping["options"][t["source"]] = {f["source"]: {o["glpi_id"]: o["value"] for o in f.get("options") or []}
                                           for f in t["fields"] if f.get("options")}
    for e in proposal.get("extensions") or []:
        if e["action"] not in ("create", "reuse"):
            continue
        uid = usable.get(e["argus_type"])
        schema = db.get(Schema, uid) if uid else None
        if schema is None:
            continue
        if e["action"] == "create":
            if schema.workspace_id != workspace_id:
                continue                       # a shared catalogue's type: its own workspace decides
            _add_fields(schema, [e], workspace_id)
        mapping["extensions"].setdefault(e["on_itemtype"], {}).setdefault(e["container"], {})[e["source"].split(".", 1)[1]] = \
            {"key": e["argus_key"], "options": {o["glpi_id"]: o["value"] for o in e.get("options") or []}}
    if made:
        catalogue_icons.apply(db, workspace_id, made, False)
    db.flush()
    return {"digest": proposal["digest"], "at": datetime.now(timezone.utc).isoformat(), "by": actor,
            "mapping": mapping, "proposal": proposal}


def _add_fields(schema: Optional[Schema], fields: list[dict], workspace_id: str) -> None:
    if schema is None or not fields or schema.workspace_id != workspace_id:
        return
    have = [dict(a) for a in schema.attributes or []]
    keys = {a.get("key") for a in have}
    for f in fields:
        if f["argus_key"] not in keys:
            have.append(_attr(f))
            keys.add(f["argus_key"])
    schema.attributes = have
    flag_modified(schema, "attributes")


def local_types(db: Session, workspace_id: str) -> list[str]:
    return list(db.scalars(select(Schema.name).where(Schema.workspace_id == workspace_id,
                                                     Schema.metadata_json["source"].astext == "glpi")))
