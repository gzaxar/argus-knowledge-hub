"""What a GLPI installation is, worked out from its snapshot and recorded with the import configuration:
its version and APIs, its entities (and how many records each holds), which item types it exposes and
which ARGUS maps, its custom asset types and fields (GLPI 11's asset definitions, GLPI 10's fields and
genericobject plugins), and its plugins. Nothing here assumes one installation is like another."""
from __future__ import annotations

from collections import Counter

from app.integrations.glpi import source
from app.integrations.glpi.mapping import STANDARD_MAP, custom_field_kind


def discover(snapshot: dict) -> dict:
    items = snapshot.get("items") or {}
    custom = snapshot.get("custom") or {}
    per_entity: Counter = Counter()
    for rows in items.values():
        for row in rows:
            if "entities_id" in row:
                per_entity[str(row.get("entities_id"))] += 1
    itemtypes = {}
    for itemtype, rows in sorted(items.items()):
        target = STANDARD_MAP.get(itemtype)
        itemtypes[itemtype] = {"count": len(rows), "status": "mapped" if target else "custom" if itemtype.startswith(
            ("Glpi\\CustomAsset\\", "PluginGenericobject")) else "link" if "_" in itemtype or itemtype == "IPAddress"
            else "not mapped", "maps_to": target["argus"] if target else None}
    for itemtype, why in sorted((snapshot.get("unavailable") or {}).items()):
        itemtypes.setdefault(itemtype, {"count": 0, "maps_to": None})
        itemtypes[itemtype].update({"status": "unavailable", "why": why})
    plugins = snapshot.get("plugins") or []
    active = {p.get("directory") for p in plugins if p.get("state") in (1, "1", None)}
    fields = []
    for f in custom.get("custom_fields") or []:
        kind, note = custom_field_kind(f, glpi11=True)
        fields.append({"definition": f.get("assetdefinitions_id"), "system_name": f.get("system_name"),
                       "label": f.get("label"), "glpi_type": f.get("type"), "kind": kind, "note": note})
    plugin_fields = []
    containers = {c.get("id"): c for c in custom.get("plugin_containers") or []}
    for f in custom.get("plugin_fields") or []:
        if f.get("type") == "header":
            continue
        kind, note = custom_field_kind(f, glpi11=False)
        c = containers.get(f.get("plugin_fields_containers_id")) or {}
        plugin_fields.append({"container": c.get("name"), "itemtypes": source._json_list(c.get("itemtypes")),
                              "name": f.get("name"), "label": f.get("label"), "glpi_type": f.get("type"),
                              "kind": kind, "note": note})
    v = source.version(snapshot)
    return {
        "instance": snapshot.get("instance"), "read_at": snapshot.get("read_at"),
        "version": v, "major": source.major(snapshot),
        "api": snapshot.get("api") or {},
        "entities": [{**e, "records": per_entity.get(str(e.get("id")), 0)} for e in snapshot.get("entities") or []],
        "itemtypes": itemtypes,
        "custom_assets": [{"system_name": d.get("system_name"), "label": d.get("label") or d.get("system_name"),
                           "itemtype": source.custom_itemtype(d), "active": bool(d.get("is_active", True)),
                           "records": len(items.get(source.custom_itemtype(d)) or [])}
                          for d in custom.get("asset_definitions") or []],
        "custom_fields": fields,
        "plugin_fields": plugin_fields,
        "generic_types": [{"itemtype": g.get("itemtype"), "name": g.get("name")} for g in custom.get("generic_types") or []],
        "plugins": plugins,
        "capabilities": {
            "custom_assets": bool(custom.get("asset_definitions")),
            "custom_fields": bool(custom.get("custom_fields")),
            "plugin_fields": "fields" in active or bool(custom.get("plugin_containers")),
            "genericobject": "genericobject" in active or bool(custom.get("generic_types")),
            "high_level_api": (snapshot.get("api") or {}).get("high_level"),
            "documents": "Document" in items,
        },
    }
