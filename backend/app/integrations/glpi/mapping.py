"""GLPI items onto ARGUS's own types: the standard mapping, the entity mapping, and the custom-field kinds.

ARGUS owns its schema: GLPI's standard item types map onto the IT, core-objects and core-records types,
field by field (`STANDARD_MAP`, `map_item`). What GLPI has that a mapping does not use is never dropped: it
is kept on the record, as GLPI gave it, in `glpi_unmapped`. References to other GLPI items (a location, a
product, a supplier) are given as GLPI references and resolved to ARGUS records once those exist.

Every record is named by a stable reference — glpi:<instance>:<itemtype>:<id> — which the ledger binds to the
ARGUS record, so importing again finds the same record whatever was renamed on either side.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

# itemtype -> what ARGUS makes of it. `classify` picks a more precise type from a dropdown's name.
STANDARD_MAP: dict[str, dict] = {
    "Computer": {"argus": "Computing Node", "abbr": "CMP", "hostname": True,
                 "classify": ("ComputerType", "computertypes_id", [
                     (("server", "virtual machine", "vm"), "Server"),
                     (("laptop", "desktop", "workstation", "notebook", "portable", "pc"), "Workstation")]),
                 "model": ("ComputerModel", "computermodels_id")},
    "NetworkEquipment": {"argus": "Network Device", "abbr": "NET", "hostname": True,
                         "classify": ("NetworkEquipmentType", "networkequipmenttypes_id", [
                             (("switch",), "Switch"), (("router",), "Router"), (("firewall",), "Firewall"),
                             (("access point", "wifi", "wi-fi", "wireless"), "Wireless Access Point")]),
                         "model": ("NetworkEquipmentModel", "networkequipmentmodels_id")},
    "Monitor": {"argus": "IT Peripheral", "abbr": "MON", "fixed": {"peripheral_kind": "Monitor"}},
    "Printer": {"argus": "IT Peripheral", "abbr": "PRN", "fixed": {"peripheral_kind": "Printer"}},
    "Peripheral": {"argus": "IT Peripheral", "abbr": "PER", "fixed": {"peripheral_kind": "Other"}},
    "Phone": {"argus": "IT Peripheral", "abbr": "PHN", "fixed": {"peripheral_kind": "Phone"}},
    "Rack": {"argus": "Rack", "abbr": "RCK"},
    "Location": {"argus": "Location", "abbr": "LOC"},
    "Supplier": {"argus": "Organization", "abbr": "ORG"},
    "Software": {"argus": "Software Product", "abbr": "SW"},
    "SoftwareVersion": {"argus": "Software Version", "abbr": "SWV"},
    "SoftwareLicense": {"argus": "Software License", "abbr": "LIC"},
    "Contract": {"argus": "Contract", "abbr": "CTR"},
    "NetworkPort": {"argus": "Equipment Port", "abbr": "PORT"},
    "Ticket": {"argus": "ticket"},
    "Problem": {"argus": "ticket", "kind": "Problem"},
    "Change": {"argus": "ticket", "kind": "Change"},
    "Document": {"argus": "attachment"},
}
EQUIPMENT = ("Computer", "NetworkEquipment", "Monitor", "Printer", "Peripheral", "Phone", "Rack")
# Fields that say where an item sits in GLPI rather than what it is: never mapped, never kept.
BOOKKEEPING = {"id", "entities_id", "is_recursive", "is_deleted", "is_template", "template_name", "links",
               "is_dynamic", "date_creation", "autoupdatesystems_id", "ticket_tco", "is_global", "users_id_tech",
               "groups_id_tech"}
SCALE = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high", 6: "Major"}
PRIORITY = {1: "Low", 2: "Low", 3: "Medium", 4: "High", 5: "Critical", 6: "Blocker"}
# CommonITILObject's statuses, and the state each has here (the default workflow, or the IT change one).
STATUS_NAMES = {1: "New", 2: "Processing (assigned)", 3: "Processing (planned)", 4: "Pending", 5: "Solved",
                6: "Closed", 7: "Accepted", 8: "Observed", 9: "Evaluation", 10: "Approval", 11: "Testing",
                12: "Qualification", 13: "Refused", 14: "Cancelled"}
TICKET_STATE = {1: "new", 2: "in_progress", 3: "in_progress", 4: "pending", 5: "resolved", 6: "closed",
                7: "in_progress", 8: "in_progress", 9: "in_progress", 10: "pending", 11: "in_progress",
                12: "in_progress", 13: "closed", 14: "closed"}
CHANGE_STATE = {1: "requested", 9: "assessed", 10: "assessed", 7: "approved", 2: "approved", 3: "scheduled",
                4: "scheduled", 11: "implemented", 12: "implemented", 5: "implemented", 6: "closed",
                13: "refused", 14: "refused"}


def instance_id(base_url: str) -> str:
    host = re.sub(r"^https?://", "", base_url.rstrip("/")).lower()
    return re.sub(r"[^a-z0-9.]+", "-", host).strip("-")


def ref(instance: str, itemtype: str, item_id) -> str:
    return f"glpi:{instance}:{itemtype}:{item_id}"


def url(base: str, itemtype: str, item_id, system_name: Optional[str] = None) -> str:
    base = base.rstrip("/")
    if itemtype.startswith("Glpi\\CustomAsset\\"):
        return f"{base}/front/asset/asset.form.php?class={system_name or itemtype.rsplit(chr(92), 1)[-1]}&id={item_id}"
    if itemtype.startswith("PluginGenericobject"):
        return f"{base}/plugins/genericobject/front/object.form.php?itemtype={itemtype}&id={item_id}"
    return f"{base}/front/{itemtype.lower()}.form.php?id={item_id}"


def text(value) -> Optional[str]:
    """GLPI's rich text (HTML, sometimes entity-encoded twice) as plain text."""
    if value in (None, ""):
        return None
    s = html.unescape(html.unescape(str(value)))
    s = re.sub(r"<\s*br\s*/?>|</p>|</div>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip() or None


def _day(value) -> Optional[str]:
    if not value or str(value).startswith("0000"):
        return None
    return str(value)[:10]


def _add_months(day: str, months: int) -> Optional[str]:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    from calendar import monthrange
    return date(year, month, min(d.day, monthrange(year, month)[1])).isoformat()


# --------------------------------------------------------------------------- entities

def entity_targets(snapshot: dict, entity_map: list[dict]) -> dict[str, Optional[str]]:
    """GLPI entity id -> the ARGUS workspace its items go to (None: outside the map). An entry maps one
    entity, and with `recursive` everything under it unless a deeper entry says otherwise."""
    parents = {str(e["id"]): (str(e["entities_id"]) if e.get("entities_id") not in (None, "", -1) else None)
               for e in snapshot.get("entities") or []}
    mapped = {str(m["entity_id"]): m for m in entity_map}
    out: dict[str, Optional[str]] = {}
    for eid in parents:
        target, cur, first = None, eid, True
        while cur is not None:
            m = mapped.get(cur)
            if m is not None and (first or m.get("recursive")):
                target = m.get("workspace_id")
                break
            cur, first = parents.get(cur), False
            if cur == eid:
                break
        out[eid] = target
    return out


def default_entity_map(snapshot: dict, workspace_id: str) -> list[dict]:
    """A first proposal: the topmost entities the token sees, with everything under them, to this workspace."""
    ids = {str(e["id"]) for e in snapshot.get("entities") or []}
    roots = [e for e in snapshot.get("entities") or []
             if e.get("entities_id") in (None, "", -1) or str(e.get("entities_id")) not in ids]
    return [{"entity_id": e["id"], "entity": e.get("completename") or e.get("name"), "recursive": True,
             "workspace_id": workspace_id} for e in roots]


# --------------------------------------------------------------------------- people

class People:
    """GLPI users and groups as ARGUS references: a GLPI login matched to an ARGUS user (by username or
    e-mail), a GLPI group to an ARGUS group of the same name. One that matches nothing stays a name."""

    def __init__(self, snapshot: dict, users: dict[str, str], groups: dict[str, str]):
        self.glpi_users = snapshot.get("users") or {}
        self.user_names = (snapshot.get("dropdowns") or {}).get("User") or {}
        self.group_names = (snapshot.get("dropdowns") or {}).get("Group") or {}
        self.users = {k.lower(): v for k, v in users.items()}         # username or e-mail -> ARGUS user id
        self.groups = {k.lower(): v for k, v in groups.items()}       # name -> ARGUS group uid

    def login(self, glpi_id) -> Optional[str]:
        if glpi_id in (None, 0, "0", ""):
            return None
        return (self.glpi_users.get(str(glpi_id)) or {}).get("login") or self.user_names.get(str(glpi_id))

    def user(self, glpi_id) -> Optional[str]:
        login = self.login(glpi_id)
        return self.users.get(login.lower()) if login else None

    def group(self, glpi_id) -> Optional[str]:
        name = self.group_names.get(str(glpi_id)) if glpi_id not in (None, 0, "0", "") else None
        return self.groups.get(name.lower()) if name else None


# --------------------------------------------------------------------------- records

@dataclass
class Mapped:
    """One GLPI item as an ARGUS record (registry form), with what still has to be resolved."""
    ref: str
    itemtype: str
    glpi_id: str
    entity: Optional[str]
    type: str
    key: str
    name: str
    attributes: dict
    unmapped: dict
    references: dict = field(default_factory=dict)      # attribute key -> ref or [refs]
    relations: dict = field(default_factory=dict)       # verb -> [refs]
    coordinates: Optional[tuple] = None                 # (latitude, longitude)
    deleted: bool = False                               # in GLPI's trash

    def registry(self) -> dict:
        attrs = dict(self.attributes)
        if self.unmapped:
            attrs["glpi_unmapped"] = json.dumps(self.unmapped, sort_keys=True, ensure_ascii=False, default=str)
        return {"ref": self.ref, "type": self.type, "key": self.key, "name": self.name, "attributes": attrs,
                "relations": {k: sorted(v) for k, v in self.relations.items() if v}}


def _dropdown(snapshot: dict, itemtype: str, value) -> Optional[str]:
    if value in (None, 0, "0", ""):
        return None
    return ((snapshot.get("dropdowns") or {}).get(itemtype) or {}).get(str(value)) or str(value)


def _classify(snapshot: dict, spec: dict, row: dict) -> str:
    if "classify" not in spec:
        return spec["argus"]
    dropdown, column, rules = spec["classify"]
    name = (_dropdown(snapshot, dropdown, row.get(column)) or "").lower()
    for words, target in rules:
        if any(w in name for w in words):
            return target
    return spec["argus"]


def _rest(row: dict, used: set, snapshot: dict) -> dict:
    """The fields of a row no mapping used, as GLPI gave them (a dropdown id with its name)."""
    out = {}
    for k, v in row.items():
        if k in used or k in BOOKKEEPING or v in (None, "", [], {}):
            continue
        if k.endswith("_id") and isinstance(v, (int, str)) and str(v) not in ("0", ""):
            dropdown = _dropdown_for(k)
            if dropdown and (snapshot.get("dropdowns") or {}).get(dropdown):
                v = {"id": v, "name": _dropdown(snapshot, dropdown, v)}
        out[k] = v
    return out


def _dropdown_for(column: str) -> Optional[str]:
    names = {"states_id": "State", "manufacturers_id": "Manufacturer", "computertypes_id": "ComputerType",
             "computermodels_id": "ComputerModel", "networkequipmenttypes_id": "NetworkEquipmentType",
             "networkequipmentmodels_id": "NetworkEquipmentModel", "users_id": "User", "groups_id": "Group",
             "softwarecategories_id": "SoftwareCategory", "contracttypes_id": "ContractType"}
    return names.get(column)


def map_item(snapshot: dict, itemtype: str, row: dict, ctx: "Context") -> Optional[Mapped]:
    spec = STANDARD_MAP.get(itemtype)
    if spec is None or spec["argus"] in ("ticket", "attachment") or row.get("is_template") in (1, "1"):
        return None
    inst, gid = ctx.instance, str(row["id"])
    r = ref(inst, itemtype, gid)
    used = {"name", "comment", "date_mod"}
    attrs: dict = {"argus_source": "GLPI", "glpi_url": url(snapshot["instance"], itemtype, gid)}
    if row.get("date_mod"):
        attrs["argus_source_ref"] = str(row["date_mod"])
    if text(row.get("comment")):
        attrs["description"] = text(row.get("comment"))
    m = Mapped(ref=r, itemtype=itemtype, glpi_id=gid, entity=_entity(row), type=_classify(snapshot, spec, row),
               key=f"{ctx.prefix}-{spec['abbr']}-{gid}", name=str(row.get("name") or f"{itemtype} {gid}"),
               attributes=attrs, unmapped={}, deleted=row.get("is_deleted") in (1, "1", True))
    if itemtype in EQUIPMENT:
        _equipment(snapshot, itemtype, row, spec, m, used, ctx)
    elif itemtype == "Location":
        m.name = str(row.get("completename") or row.get("name") or m.name)
        used |= {"completename", "locations_id", "latitude", "longitude", "altitude", "building", "level", "sons_cache",
                 "ancestors_cache"}
        if row.get("building"):
            attrs["site"] = str(row["building"])
        if row.get("locations_id") not in (None, 0, "0"):
            m.relations.setdefault("part of", []).append(ref(inst, "Location", row["locations_id"]))
        lat, lon = row.get("latitude"), row.get("longitude")
        try:
            if lat not in (None, "") and lon not in (None, ""):
                m.coordinates = (float(lat), float(lon))
        except (TypeError, ValueError):
            pass
    elif itemtype == "Supplier":
        used |= {"website", "suppliertypes_id"}
        attrs["org_kind"] = "Company"
        if row.get("website"):
            attrs["website"] = str(row["website"])
        country = str(row.get("country") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country):
            attrs["country"] = country
            used.add("country")
    elif itemtype == "Software":
        used |= {"manufacturers_id", "softwarecategories_id"}
        if _dropdown(snapshot, "Manufacturer", row.get("manufacturers_id")):
            attrs["publisher"] = _dropdown(snapshot, "Manufacturer", row.get("manufacturers_id"))
        if _dropdown(snapshot, "SoftwareCategory", row.get("softwarecategories_id")):
            attrs["software_category"] = _dropdown(snapshot, "SoftwareCategory", row.get("softwarecategories_id"))
    elif itemtype == "SoftwareVersion":
        used |= {"softwares_id"}
        attrs["version_label"] = str(row.get("name") or "")
        product = ctx.names.get(ref(inst, "Software", row.get("softwares_id")))
        m.name = f"{product} {row.get('name')}".strip() if product else m.name
        m.references["of_product"] = ref(inst, "Software", row.get("softwares_id"))
    elif itemtype == "SoftwareLicense":
        used |= {"softwares_id", "number", "serial", "expire"}
        if row.get("softwares_id") not in (None, 0, "0"):
            m.references["licensed_product"] = ref(inst, "Software", row["softwares_id"])
        if row.get("number") not in (None, ""):
            attrs["seats"] = int(row["number"])
        if row.get("serial"):
            attrs["license_key"] = str(row["serial"])
        if _day(row.get("expire")):
            attrs["end_date"] = _day(row["expire"])
    elif itemtype == "Contract":
        used |= {"num", "begin_date", "duration", "renewal"}
        if row.get("num"):
            attrs["contract_number"] = str(row["num"])
        start = _day(row.get("begin_date"))
        if start:
            attrs["start_date"] = start
            if int(row.get("duration") or 0) > 0:
                attrs["end_date"] = _add_months(start, int(row["duration"]))
        renewal = {0: "None", 1: "Tacit", 2: "On request"}.get(int(row.get("renewal") or 0))
        if renewal:
            attrs["renewal"] = renewal
    elif itemtype == "NetworkPort":
        owner = ctx.owner_keys.get(ref(inst, row.get("itemtype") or "", row.get("items_id")))
        if owner is None:                       # a port of something not imported (or in the trash)
            owner = f"{ctx.prefix}-?-{row.get('items_id')}"
        used |= {"itemtype", "items_id", "logical_number", "mac", "instantiation_type"}
        label = str(row.get("name") or row.get("logical_number") or gid)
        m.key, m.name = f"{owner}:{label}", label
        attrs["port_label"] = label
        if row.get("mac"):
            attrs["mac"] = str(row["mac"]).lower()
        m.relations.setdefault("port of", []).append(ref(inst, row["itemtype"], row["items_id"]))
    m.unmapped = {**_rest(row, used, snapshot), **m.unmapped}
    return m


def _slug_abbr(system_name: str) -> str:
    """A key abbreviation for a GLPI custom type: its system name, in capitals, letters and digits only."""
    return re.sub(r"[^A-Z0-9]", "", str(system_name).upper())[:12] or "CA"


def _entity(row: dict) -> Optional[str]:
    return str(row["entities_id"]) if row.get("entities_id") is not None else None


def _equipment(snapshot: dict, itemtype: str, row: dict, spec: dict, m: Mapped, used: set, ctx: "Context") -> None:
    attrs = m.attributes
    used |= {"serial", "otherserial", "manufacturers_id", "locations_id", "users_id", "groups_id"}
    if spec.get("hostname") and row.get("name"):
        attrs["hostname"] = str(row["name"])
    if row.get("serial"):
        attrs["serial"] = str(row["serial"])
    if row.get("otherserial"):
        attrs["inventory_number"] = str(row["otherserial"])
    if _dropdown(snapshot, "Manufacturer", row.get("manufacturers_id")):
        attrs["manufacturer"] = _dropdown(snapshot, "Manufacturer", row.get("manufacturers_id"))
    if spec.get("model"):
        dropdown, column = spec["model"]
        used |= {column}
        if _dropdown(snapshot, dropdown, row.get(column)):
            attrs["model"] = _dropdown(snapshot, dropdown, row.get(column))
    if "classify" in spec:
        used.add(spec["classify"][1])
    if itemtype == "Rack":
        used.add("number_units")
        if row.get("number_units"):
            attrs["rack_units"] = int(row["number_units"])
    if row.get("locations_id") not in (None, 0, "0"):
        if itemtype == "Rack":
            m.relations.setdefault("part of", []).append(ref(ctx.instance, "Location", row["locations_id"]))
        else:
            m.references["argus_location"] = ref(ctx.instance, "Location", row["locations_id"])
    person = ctx.people.user(row.get("users_id"))
    if person:
        attrs["argus_responsible"] = person
    elif ctx.people.login(row.get("users_id")):
        m.unmapped["users_id"] = {"id": row.get("users_id"), "login": ctx.people.login(row.get("users_id"))}
    group = ctx.people.group(row.get("groups_id"))
    if group:
        attrs["argus_owner"] = group
    elif row.get("groups_id") not in (None, 0, "0"):
        m.unmapped["groups_id"] = {"id": row.get("groups_id"),
                                   "name": _dropdown(snapshot, "Group", row.get("groups_id"))}
    for k, v in (spec.get("fixed") or {}).items():
        attrs[k] = v


@dataclass
class Context:
    instance: str
    prefix: str
    people: People
    names: dict = field(default_factory=dict)        # ref -> name (for version names)
    owner_keys: dict = field(default_factory=dict)   # ref -> key (ports are named after their owner)


# --------------------------------------------------------------------------- custom fields

GLPI11_KINDS = {"StringType": "string", "TextType": "text", "NumberType": "float", "DateType": "date",
                "DateTimeType": "datetime", "URLType": "string", "BooleanType": "boolean",
                "DropdownType": "enumeration"}
PLUGIN_KINDS = {"text": "string", "textarea": "text", "richtext": "text", "number": "float", "url": "string",
                "date": "date", "datetime": "datetime", "yesno": "boolean", "dropdown": "enumeration"}


def custom_field_kind(f: dict, glpi11: bool) -> tuple[Optional[str], Optional[str]]:
    """The ARGUS attribute type a GLPI custom field becomes, or (None, why it is not supported)."""
    t = str(f.get("type") or "")
    if glpi11:
        kind = GLPI11_KINDS.get(t.rsplit("\\", 1)[-1])
        if kind == "enumeration" and f.get("itemtype") and not str(f.get("itemtype")).endswith("Dropdown"):
            return "string", f"points at {f.get('itemtype')} items: kept as their names"
        return (kind, None) if kind else (None, f"GLPI field type {t!r} has no ARGUS equivalent")
    if t.startswith("dropdown-"):
        return "string", f"points at {t[9:]} items: kept as their names"
    kind = PLUGIN_KINDS.get(t)
    return (kind, None) if kind else (None, f"fields-plugin type {t!r} has no ARGUS equivalent")


def ticket_fields(snapshot: dict, itemtype: str, row: dict, ctx: Context) -> dict:
    """A GLPI ticket, problem or change as an ARGUS ticket: kind, title, text, state, priority, fields."""
    status = int(row.get("status") or 1)
    if itemtype == "Ticket":
        kind = "Incident" if int(row.get("type") or 1) == 1 else "Service Request"
    else:
        kind = STANDARD_MAP[itemtype]["kind"]
    state = CHANGE_STATE.get(status, "requested") if itemtype == "Change" else TICKET_STATE.get(status, "new")
    gid = str(row["id"])
    attrs = {"argus_source": "GLPI", "argus_source_key": ref(ctx.instance, itemtype, gid),
             "argus_source_url": url(snapshot["instance"], itemtype, gid),
             "argus_source_status": STATUS_NAMES.get(status, str(status)), "argus_source_type": kind}
    if row.get("date"):
        attrs["argus_source_created"] = str(row["date"])
    if row.get("date_mod"):
        attrs["argus_source_updated"] = str(row["date_mod"])
    if row.get("urgency") and itemtype != "Problem":
        attrs["urgency"] = SCALE.get(int(row["urgency"]))
    if row.get("impact") and kind in ("Incident", "Problem"):
        attrs["impact_level"] = SCALE.get(int(row["impact"]))
    used = {"id", "name", "content", "status", "type", "date", "date_mod", "urgency", "impact", "priority",
            "entities_id", "is_deleted", "links", "closedate", "solvedate"}
    return {"ref": ref(ctx.instance, itemtype, gid), "itemtype": itemtype, "glpi_id": gid, "entity": _entity(row),
            "kind": kind, "title": str(row.get("name") or f"{itemtype} {gid}"), "description": text(row.get("content")),
            "state": state, "priority": PRIORITY.get(int(row.get("priority") or 3)), "attributes": attrs,
            "unmapped": _rest(row, used, snapshot), "closed_at": row.get("closedate"),
            "deleted": row.get("is_deleted") in (1, "1", True)}
