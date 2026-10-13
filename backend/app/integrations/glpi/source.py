"""Reading GLPI: what it exposes, into a snapshot every later step works from.

A snapshot is plain JSON (so a test can be one, and an import can be repeated from one):

    instance       the GLPI base URL
    read_at        when it was read (ISO 8601)
    api            {"legacy": bool, "high_level": "<version>" | None, "notes": [...]}
    config         what getGlpiConfig said (version among it)
    entities       [{id, name, completename, entities_id}]
    plugins        [{directory, name, version, state}]
    items          itemtype -> [rows as the legacy API returns them, dropdowns as ids]
    dropdowns      itemtype -> {id: name}            (types, models, manufacturers, states, users, groups…)
    unavailable    itemtype -> why it could not be read (no right, unknown to this version, disabled)
    custom         {"asset_definitions": [...], "custom_fields": [...],            (GLPI 11)
                    "plugin_containers": [...], "plugin_fields": [...],            (GLPI 10, plugin "fields")
                    "plugin_values": {container: {itemtype: [rows]}},
                    "generic_types": [...]}                                        (plugin "genericobject")
    files          {document id: base64}              (only in fixtures; a live import downloads)

Only the legacy REST API (apirest.php) is read: GLPI 10 and 11 both have it. The high-level API of GLPI 11
(api.php/v2) is detected and recorded, not read: an installation that has turned the legacy API off is told
so rather than half-imported.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

# What the importer reads, in the order it needs them (dropdowns before what names them).
DROPDOWNS = ["Manufacturer", "ComputerType", "ComputerModel", "NetworkEquipmentType", "NetworkEquipmentModel",
             "State", "User", "Group", "SoftwareCategory", "ContractType"]
STANDARD = ["Location", "Supplier", "Computer", "NetworkEquipment", "Monitor", "Printer", "Peripheral", "Phone",
            "Rack", "NetworkPort", "IPAddress", "Software", "SoftwareVersion", "Item_SoftwareVersion",
            "SoftwareLicense", "Contract", "Contract_Item", "Contract_Supplier", "Ticket", "Problem", "Change",
            "Item_Ticket", "Item_Problem", "Change_Item", "Document", "Document_Item"]
GLPI11_DEFINITIONS = "Glpi\\Asset\\AssetDefinition"
GLPI11_FIELDS = "Glpi\\Asset\\CustomFieldDefinition"
PLUGIN_ITEMTYPES = ["PluginFieldsContainer", "PluginFieldsField", "PluginGenericobjectType"]
PAGE = 200


class GlpiError(RuntimeError):
    """GLPI could not be read: unreachable, refused the credentials, or the API is off."""


def empty(instance: str) -> dict:
    return {"instance": instance.rstrip("/"), "read_at": datetime.now(timezone.utc).isoformat(),
            "api": {"legacy": False, "high_level": None, "notes": []}, "config": {}, "entities": [],
            "plugins": [], "items": {}, "dropdowns": {}, "unavailable": {},
            "custom": {"asset_definitions": [], "custom_fields": [], "plugin_containers": [], "plugin_fields": [],
                       "plugin_values": {}, "generic_types": []}, "files": {}}


def load_fixture(path: Path | str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    base = empty(data.get("instance", "https://glpi.invalid"))
    base.update(data)
    base["custom"] = {**empty("")["custom"], **(data.get("custom") or {})}
    return base


def version(snapshot: dict) -> Optional[str]:
    cfg = snapshot.get("config") or {}
    return cfg.get("version") or (cfg.get("cfg_glpi") or {}).get("version")


def major(snapshot: dict) -> Optional[int]:
    v = version(snapshot)
    try:
        return int(str(v).split(".")[0]) if v else None
    except ValueError:
        return None


def file_bytes(snapshot: dict, document_id) -> Optional[bytes]:
    b = (snapshot.get("files") or {}).get(str(document_id))
    return base64.b64decode(b) if b else None


# --------------------------------------------------------------------------- the legacy REST API

class LegacyClient:
    """GLPI's legacy REST API (apirest.php), with a user token and, if the installation asks for one, an
    application token. Read only: the session is opened without write rights. `session` is a
    requests.Session-like object (a test gives a fake one)."""

    def __init__(self, base_url: str, user_token: str, app_token: Optional[str] = None, *, verify: bool = True,
                 timeout: float = 30.0, session=None):
        import requests
        self.base = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.http.verify = verify
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if app_token:
            self.headers["App-Token"] = app_token
        self._user_token = user_token
        self.token: Optional[str] = None

    def _url(self, path: str) -> str:
        return f"{self.base}/apirest.php/{path}"

    def open(self) -> None:
        r = self.http.get(self._url("initSession/"), headers={**self.headers,
                                                              "Authorization": f"user_token {self._user_token}"},
                          timeout=self.timeout)
        if r.status_code == 404:
            raise GlpiError("GLPI's REST API (apirest.php) is not there: is it enabled (Setup > General > API)?")
        if r.status_code in (400, 401, 403):
            raise GlpiError(f"GLPI refused the session ({r.status_code}): {_message(r)}")
        r.raise_for_status()
        self.token = r.json()["session_token"]
        self.headers["Session-Token"] = self.token

    def close(self) -> None:
        if self.token:
            try:
                self.http.get(self._url("killSession/"), headers=self.headers, timeout=self.timeout)
            finally:
                self.token = None
                self.headers.pop("Session-Token", None)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def get(self, path: str, params: Optional[dict] = None):
        return self.http.get(self._url(path), headers=self.headers, params=params or {}, timeout=self.timeout)

    def all(self, itemtype: str, params: Optional[dict] = None) -> tuple[Optional[list], Optional[str]]:
        """Every row of an itemtype, page by page: (rows, None), or (None, why it cannot be read)."""
        rows: list = []
        start = 0
        while True:
            r = self.get(quote(itemtype, safe="") + "/", {"range": f"{start}-{start + PAGE - 1}",
                                                          "expand_dropdowns": "false", **(params or {})})
            if r.status_code in (400, 401, 403, 404):
                return None, f"{r.status_code} {_message(r)}"
            r.raise_for_status()
            page = r.json() if r.content else []
            if isinstance(page, dict):          # some versions wrap a single row
                page = [page]
            rows.extend(page)
            total = _total(r.headers.get("Content-Range"))
            start += len(page)                  # GLPI may give fewer than asked (its own maximum range)
            if not page or total is None or start >= total:
                return rows, None

    def high_level(self) -> Optional[str]:
        """The high-level API's version, when GLPI 11's api.php answers."""
        try:
            r = self.http.get(f"{self.base}/api.php/v2/status", timeout=self.timeout)
        except Exception:                                    # noqa: BLE001 — absent is the answer
            return None
        if r.status_code in (200, 401):
            return "v2"
        return None

    def document(self, document_id) -> bytes:
        r = self.get(f"Document/{document_id}", {"alt": "media"})
        r.raise_for_status()
        return r.content


def _message(r) -> str:
    try:
        body = r.json()
        if isinstance(body, list) and body:
            return " ".join(str(x) for x in body)
        return str(body)
    except ValueError:
        return (r.text or "")[:200]


def _total(content_range: Optional[str]) -> Optional[int]:
    # "0-199/1234"
    if not content_range or "/" not in content_range:
        return None
    try:
        return int(content_range.rsplit("/", 1)[1])
    except ValueError:
        return None


def read(client: LegacyClient, itemtypes: Optional[list[str]] = None) -> dict:
    """A snapshot of what this GLPI exposes to the token, read through its legacy REST API."""
    snap = empty(client.base)
    snap["api"]["legacy"] = True
    snap["api"]["high_level"] = client.high_level()
    r = client.get("getGlpiConfig/")
    if r.status_code == 200:
        cfg = (r.json() or {}).get("cfg_glpi") or {}
        snap["config"] = {k: cfg.get(k) for k in ("version", "dbversion", "url_base", "language", "timezone")
                          if k in cfg}
    else:
        snap["api"]["notes"].append(f"getGlpiConfig: {r.status_code} {_message(r)}")
    rows, why = client.all("Entity")
    if rows is None:
        r = client.get("getMyEntities/", {"is_recursive": "true"})
        rows = (r.json() or {}).get("myentities", []) if r.status_code == 200 else []
        snap["api"]["notes"].append(f"Entity: {why}; entities from getMyEntities only")
    snap["entities"] = [{"id": e.get("id"), "name": e.get("name"), "completename": e.get("completename") or e.get("name"),
                         "entities_id": e.get("entities_id")} for e in rows]
    plugins, why = client.all("Plugin")
    if plugins is not None:
        snap["plugins"] = [{k: p.get(k) for k in ("directory", "name", "version", "state")} for p in plugins]
    else:
        snap["unavailable"]["Plugin"] = why
    for itemtype in DROPDOWNS:
        rows, why = client.all(itemtype)
        if rows is None:
            snap["unavailable"][itemtype] = why
            continue
        names = {}
        for row in rows:
            label = row.get("completename") or row.get("name")
            if itemtype == "User":
                label = row.get("name")                     # the login
                snap.setdefault("users", {})[str(row["id"])] = {
                    "login": row.get("name"), "realname": row.get("realname"), "firstname": row.get("firstname")}
            names[str(row["id"])] = label
        snap["dropdowns"][itemtype] = names
    for itemtype in itemtypes or STANDARD:
        rows, why = client.all(itemtype)
        if rows is None:
            snap["unavailable"][itemtype] = why
        else:
            snap["items"][itemtype] = rows
    _read_custom(client, snap)
    return snap


def _read_custom(client: LegacyClient, snap: dict) -> None:
    custom = snap["custom"]
    defs, why = client.all(GLPI11_DEFINITIONS)
    if defs is not None:
        custom["asset_definitions"] = defs
        fields, why_f = client.all(GLPI11_FIELDS)
        custom["custom_fields"] = fields or []
        if fields is None:
            snap["unavailable"][GLPI11_FIELDS] = why_f
        for d in defs:
            itemtype = custom_itemtype(d)
            rows, why_i = client.all(itemtype)
            if rows is None:
                snap["unavailable"][itemtype] = why_i
            else:
                snap["items"][itemtype] = rows
    else:
        snap["unavailable"][GLPI11_DEFINITIONS] = why
    containers, why = client.all("PluginFieldsContainer")
    if containers is not None:
        custom["plugin_containers"] = containers
        fields, _ = client.all("PluginFieldsField")
        custom["plugin_fields"] = fields or []
        for c in containers:
            for itemtype in _json_list(c.get("itemtypes")):
                for candidate in plugin_value_itemtypes(itemtype, c.get("name") or ""):
                    rows, _w = client.all(candidate)
                    if rows is not None:
                        custom["plugin_values"].setdefault(c["name"], {})[itemtype] = rows
                        break
                else:
                    snap["unavailable"][f"PluginFields values {c.get('name')} on {itemtype}"] = \
                        "the plugin's value itemtype could not be read through the API"
    # The values of custom dropdown fields, so a proposal can offer them as options.
    wanted = {f.get("itemtype") for f in custom["custom_fields"] if str(f.get("type", "")).endswith("DropdownType")}
    wanted |= {f"PluginFields{str(f.get('name')).capitalize()}Dropdown" for f in custom["plugin_fields"]
               if f.get("type") == "dropdown"}
    for itemtype in sorted(w for w in wanted if w):
        rows, why_d = client.all(itemtype)
        if rows is None:
            snap["unavailable"][itemtype] = why_d
        else:
            snap["dropdowns"][itemtype] = {str(r["id"]): r.get("completename") or r.get("name") for r in rows}
    generic, _ = client.all("PluginGenericobjectType")
    if generic is not None:
        custom["generic_types"] = generic
        for g in generic:
            if g.get("itemtype"):
                rows, why_g = client.all(g["itemtype"])
                if rows is None:
                    snap["unavailable"][g["itemtype"]] = why_g
                else:
                    snap["items"][g["itemtype"]] = rows


def custom_itemtype(definition: dict) -> str:
    """The class of a GLPI 11 custom asset definition's items: Glpi\\CustomAsset\\<SystemName>Asset."""
    return definition.get("itemtype") or f"Glpi\\CustomAsset\\{definition['system_name']}Asset"


def plugin_value_itemtypes(itemtype: str, container: str) -> list[str]:
    """The itemtypes the fields plugin may give one container's values on one itemtype, by version."""
    short = itemtype.split("\\")[-1].lower()
    name = "".join(ch for ch in container.lower() if ch.isalnum())
    return list(dict.fromkeys([f"PluginFields{short.capitalize()}{name}",
                               f"PluginFields{short.capitalize()}{name.rstrip('s')}"]))


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value or "[]")
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []
