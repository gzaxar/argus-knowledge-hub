"""Installing catalogue collections in the catalogue workspace: preview, install, upgrade
(docs/catalogue-collections.md §3).

One comparison does all three: each entry of each release against the record it is (a `catalogue_entries`
row), or the record it may be (a link candidate), or nothing yet. Every entry falls in one category:

    add        a new vendor or model: created, global, every field it states managed
    change     a managed field the release changed, and nobody changed here: written
    link       a record that is the same product and has no catalogue id: a person decides (link or create),
               and for a field whose values differ, whether it is managed, a local override, or a correction
               proposed back to Git
    conflict   the release changes a local override, or a field edited here since: the record keeps its value,
               and the conflict is kept on the entry for review
    transfer   the entry moved to another collection: the entry follows, the record does not change
    retire     `retired:` in this release: the entry is marked retired; the record stays, with its references
    unchanged

Absence never retires or removes anything: the validator refuses a release that drops an entry. Writes go
through the ledger, as the administrator who installs, with the collection and version as the reason, so the
history of each value says which release set it. A release is installed in one transaction, with a lock on
the collection, and installing the same version again changes nothing.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.catalogue.loader import Collection, Entry, load_tree
from app.catalogue.validate import tree_problems
from app.models.asset import Asset
from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation
from app.models.schema import Schema
from app.catalogue.validate import code_key
from app.services.catalogue_mapping import norm

# What an entry states, and the record field each one is. `vendor` is the vendor's record (vendor_ref), with its
# name in `vendor` beside it, as the Product Model type keeps both.
VENDOR_FIELDS = ("name", "website", "description")
MODEL_FIELDS = ("name", "vendor", "model_code", "device_class", "datasheet_url", "firmware_version", "eol_date",
                "typical_spares", "description",
                # Its hardware (core-objects 2.3): from the entry's part number, specifications, components, notes.
                "part_number", "rack_units", "full_depth", "airflow", "weight_kg", "maximum_draw_w", "port_summary",
                "components", "source_notes")
# Stated by the format, kept in the collection and shown on the model's page: no field on the Product Model type
# holds them whole (its height, weight, airflow and draw are taken from the specifications into fields).
NOT_STORED = ("instance_type", "specifications", "relations")
_WEIGHT_KG = {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523125}
# Interfaces that are not a socket on the box (NetBox's virtual kinds).
VIRTUAL_INTERFACES = {"virtual", "lag", "bridge"}
FIELD_DECISIONS = ("managed", "local", "propose")


class CatalogueProblem(ValueError):
    """Why a release cannot be installed here, as a person can act on it."""

    def __init__(self, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.details = details or []


@dataclass
class Item:
    catalogue_id: str
    kind: str
    collection: str
    category: str
    record_uid: Optional[str] = None
    record_name: Optional[str] = None
    fields: list = field(default_factory=list)      # [{field, record, release, action}]
    notes: list = field(default_factory=list)
    needs_decision: bool = False

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("catalogue_id", "kind", "collection", "category", "record_uid",
                                               "record_name", "fields", "notes", "needs_decision")}


@dataclass
class Release:
    collection: str
    from_version: Optional[str]
    version: str
    checksum: str
    already: bool = False
    items: list = field(default_factory=list)
    not_stored: dict = field(default_factory=dict)

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for i in self.items:
            out[i.category] = out.get(i.category, 0) + 1
        return out

    def as_dict(self) -> dict:
        return {"collection": self.collection, "from_version": self.from_version, "version": self.version,
                "checksum": self.checksum, "already_installed": self.already, "counts": self.counts(),
                "not_stored": self.not_stored, "items": [i.as_dict() for i in self.items]}


@dataclass
class Plan:
    workspace_id: str
    releases: list = field(default_factory=list)

    def undecided(self) -> list[str]:
        return [i.catalogue_id for r in self.releases for i in r.items if i.needs_decision]

    def as_dict(self) -> dict:
        totals: dict[str, int] = {}
        for r in self.releases:
            for k, v in r.counts().items():
                totals[k] = totals.get(k, 0) + v
        return {"workspace_id": self.workspace_id, "counts": totals, "undecided": self.undecided(),
                "releases": [r.as_dict() for r in self.releases]}


# --------------------------------------------------------------------------- where, and what is there

def catalogue_workspace(db: Session) -> Optional[str]:
    """The installation's catalogue workspace: the one designated (app/catalogue/system.py), or None."""
    from app.catalogue.system import designated
    return designated(db)


def installed(db: Session, workspace_id: str) -> dict[str, CatalogueInstallation]:
    """The release of each collection this workspace has: the latest installation row. A collection only partly
    installed (models installed one at a time, app/catalogue/library.py) is not installed."""
    out: dict[str, CatalogueInstallation] = {}
    for row in db.scalars(select(CatalogueInstallation).where(CatalogueInstallation.workspace_id == workspace_id)
                          .order_by(CatalogueInstallation.id)):
        if (row.result or {}).get("partial"):
            continue
        out[row.collection_id] = row
    return out


def history(db: Session, workspace_id: str) -> list[CatalogueInstallation]:
    return list(db.scalars(select(CatalogueInstallation).where(CatalogueInstallation.workspace_id == workspace_id)
                           .order_by(CatalogueInstallation.id.desc())))


def entries(db: Session, workspace_id: str) -> dict[str, CatalogueEntry]:
    return {e.catalogue_id: e for e in db.scalars(select(CatalogueEntry).where(
        CatalogueEntry.workspace_id == workspace_id))}


def _types(db: Session, workspace_id: str) -> tuple[Schema, Schema]:
    from app.services.catalogue_mapping import MappingError, catalogue_types
    try:
        return catalogue_types(db, workspace_id)
    except MappingError as e:
        raise CatalogueProblem(str(e))


def _attribute_keys(db: Session, schema: Schema) -> set[str]:
    from app.services.attribute_validation import effective_attributes
    return {a.get("key") or a.get("name") for a in effective_attributes(db, schema)} - {None}


def _live(db: Session, workspace_id: str, schema: Schema) -> list[Asset]:
    return list(db.scalars(select(Asset).where(
        Asset.schema_uid == schema.uid, Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None),
        Asset.record_status.notin_(("Retired", "Merged")))))


def _order(tree: dict[str, Collection], wanted: list[str]) -> list[Collection]:
    """The collections asked for and those they require, each after what it requires."""
    out: list[Collection] = []

    def visit(cid: str, path: tuple) -> None:
        if cid in path:
            raise CatalogueProblem(f"collections require each other in a circle: {' → '.join([*path, cid])}")
        if any(c.id == cid for c in out):
            return
        c = tree.get(cid)
        if c is None:
            raise CatalogueProblem(f"this installation ships no collection {cid!r}")
        for dep in sorted(c.requires_collections):
            visit(dep, (*path, cid))
        out.append(c)

    for cid in wanted:
        visit(cid, ())
    return out


def _check_packages(db: Session, workspace_id: str, c: Collection) -> None:
    from app.packages.install import installed as packages_installed
    have = packages_installed(db, workspace_id)
    for pid, spec in c.requires_packages.items():
        row = have.get(pid)
        if row is None:
            raise CatalogueProblem(f"{c.id} needs the package {pid} ({spec}), and {workspace_id} does not have it: "
                                   f"install it on the workspace's Packages page first")
        try:
            ok = Version(row.version) in SpecifierSet(spec)
        except (InvalidVersion, InvalidSpecifier):
            ok = False
        if not ok:
            raise CatalogueProblem(f"{c.id} needs {pid} {spec}, and {workspace_id} has {row.version}: "
                                   f"upgrade it on the workspace's Packages page first")


def _lock(db: Session, workspace_id: str, collection_id: str) -> None:
    """Two installs of one collection queue rather than race; released when the transaction ends."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                    {"k": f"catalogue:{workspace_id}:{collection_id}"})


# --------------------------------------------------------------------------- values

def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def _same(a: Any, b: Any) -> bool:
    if _blank(a) and _blank(b):
        return True
    return str(a).strip() == str(b).strip() if isinstance(a, (str, int, float)) and isinstance(b, (str, int, float)) \
        else a == b


def _hardware(d: dict) -> dict:
    """A model's hardware as Product Model fields: from its part number, specifications, components and notes."""
    spec = d.get("specifications") if isinstance(d.get("specifications"), dict) else {}
    out: dict = {"part_number": d.get("part_number"), "source_notes": d.get("notes")}
    if isinstance(spec.get("rack_units"), (int, float)):
        out["rack_units"] = spec["rack_units"]
        if isinstance(spec.get("full_depth"), bool):
            out["full_depth"] = spec["full_depth"]
    if spec.get("airflow"):
        out["airflow"] = str(spec["airflow"])
    w = spec.get("weight")
    if isinstance(w, dict) and isinstance(w.get("value"), (int, float)) and str(w.get("unit") or "kg") in _WEIGHT_KG:
        out["weight_kg"] = round(w["value"] * _WEIGHT_KG[str(w.get("unit") or "kg")], 3)
    elif isinstance(w, (int, float)):
        out["weight_kg"] = w
    if isinstance(spec.get("maximum_draw_w"), (int, float)):
        out["maximum_draw_w"] = int(spec["maximum_draw_w"])
    comps = d.get("components") if isinstance(d.get("components"), dict) else {}
    if comps:
        out["components"] = json.dumps(comps, sort_keys=True, ensure_ascii=False)
        out["port_summary"] = port_summary(comps)
    return out


def port_summary(comps: dict) -> Optional[str]:
    """Its sockets in one line: 24 × 1000base-t, 2 × cisco-stackwise, 1 management, 2 console, 2 power."""
    parts = []
    physical = [i for i in comps.get("interfaces") or [] if i.get("type") not in VIRTUAL_INTERFACES]
    data = [i for i in physical if not i.get("mgmt_only")]
    kinds: dict[str, int] = {}
    for i in data:
        kinds[str(i.get("type") or "?")] = kinds.get(str(i.get("type") or "?"), 0) + 1
    parts += [f"{n} × {t}" for t, n in sorted(kinds.items(), key=lambda x: (-x[1], x[0]))]
    for label, items in (("management", [i for i in physical if i.get("mgmt_only")]),
                         ("serial", comps.get("console_server_ports")), ("console", comps.get("console_ports")),
                         ("power", comps.get("power_ports")), ("outlet", comps.get("power_outlets")),
                         ("module bay", comps.get("module_bays")), ("front port", comps.get("front_ports"))):
        if items:
            parts.append(f"{len(items)} {label}")
    return ", ".join(parts) or None


def _statement(e: Entry, vendor_uids: dict[str, str], keys: set[str]) -> dict:
    """What an entry states, as the record's fields."""
    d = e.data
    if e.kind == "vendor":
        out = {f: d.get(f) for f in VENDOR_FIELDS}
    else:
        out = {f: d.get(f) for f in MODEL_FIELDS}
        out.update(_hardware(d))
        out["vendor"] = vendor_uids.get(str(d.get("vendor")))
        if d.get("eol_date") is not None:
            out["eol_date"] = str(d["eol_date"])
        if isinstance(d.get("typical_spares"), list):
            out["typical_spares"] = ", ".join(str(x) for x in d["typical_spares"])
    return {k: v for k, v in out.items() if not _blank(v) and (k in ("name", "vendor") or k in keys)}


def _current(record: Asset, f: str) -> Any:
    if f == "name":
        return record.name
    if f == "vendor":
        return (record.attributes or {}).get("vendor_ref")
    return (record.attributes or {}).get(f)


def _changes(db: Session, values: dict) -> dict:
    """Record fields as ledger predicates."""
    out = {}
    for f, v in values.items():
        if f == "name":
            out["name"] = v
        elif f == "vendor":
            vendor = db.get(Asset, v) if v and not str(v).startswith("new:") else None
            out["attr:vendor_ref"] = v
            if vendor is not None:
                out["attr:vendor"] = vendor.name
        else:
            out[f"attr:{f}"] = v
    return out


# --------------------------------------------------------------------------- link candidates

class _Candidates:
    """Records of the catalogue workspace with no catalogue id that may be an entry's product."""

    def __init__(self, db: Session, workspace_id: str, model_schema: Schema, vendor_schema: Schema,
                 taken: set[str]):
        self.vendors: dict[str, Asset] = {}
        for v in _live(db, workspace_id, vendor_schema):
            if v.uid not in taken and norm(v.name):
                self.vendors.setdefault(norm(v.name), v)
        self.models: dict[tuple, Asset] = {}
        # Per vendor, every record's name as a code key: a model whose code is only inside its name
        # ("TPG 366 control unit") is still a candidate, for a person to decide.
        self.names: dict[str, list[tuple[str, Asset]]] = {}
        names = {v.uid: v.name for v in _live(db, workspace_id, vendor_schema)}
        for m in _live(db, workspace_id, model_schema):
            if m.uid in taken:
                continue
            a = m.attributes or {}
            vendor_keys = {norm(a.get("vendor")), norm(names.get(a.get("vendor_ref")))} - {""}
            ref = a.get("vendor_ref")
            keys = vendor_keys | ({f"uid:{ref}"} if ref else set())
            for code in {code_key(a.get("model_code")), code_key(m.name)} - {""}:
                for vk in keys:
                    self.models.setdefault((vk, code), m)
            for vk in keys:
                self.names.setdefault(vk, []).append((code_key(m.name), m))

    def vendor(self, e: Entry) -> Optional[Asset]:
        for name in [e.data.get("name"), *(e.data.get("aliases") or [])]:
            hit = self.vendors.get(norm(str(name or "")))
            if hit is not None:
                return hit
        return None

    def model(self, e: Entry, vendor_entry: Optional[Entry], vendor_uid: Optional[str]) -> Optional[Asset]:
        code = code_key(e.data.get("model_code"))
        if not code:
            return None
        keys = []
        if vendor_uid and not vendor_uid.startswith("new:"):
            keys.append((f"uid:{vendor_uid}", code))
        if vendor_entry is not None:
            for name in [vendor_entry.data.get("name"), *(vendor_entry.data.get("aliases") or [])]:
                keys.append((norm(str(name or "")), code))
        for k in keys:
            if k in self.models:
                return self.models[k]
        if len(code) < 4:                                       # too short to find inside a name
            return None
        inside = {m.uid: m for vk, _ in keys for name, m in self.names.get(vk, []) if code in name}
        return next(iter(inside.values())) if len(inside) == 1 else None


# --------------------------------------------------------------------------- the comparison

class _Run:
    def __init__(self, db: Session, workspace_id: str, actor: str, decisions: dict, apply: bool,
                 merges: Optional[dict] = None):
        self.db, self.ws, self.actor, self.apply = db, workspace_id, actor, apply
        self.decisions = decisions or {}
        # From a migration manifest: per catalogue id, the duplicates merged into its record.
        self.merges = merges or {}
        self.model_schema, self.vendor_schema = _types(db, workspace_id)
        self.model_keys = _attribute_keys(db, self.model_schema)
        self.vendor_keys = _attribute_keys(db, self.vendor_schema)
        self.rows = entries(db, workspace_id)
        self.candidates = _Candidates(db, workspace_id, self.model_schema, self.vendor_schema,
                                      {r.record_uid for r in self.rows.values()})
        self.claimed: set[str] = set()                                # records linked in this run
        self.vendor_uids = {cid: r.record_uid for cid, r in self.rows.items() if r.kind == "vendor"}
        self.vendor_entries: dict[str, Entry] = {}

    # ---------------------------------------------------------------- writing
    def _reason(self, c: Collection) -> str:
        return f"catalogue {c.id} {c.version}"

    def _create(self, c: Collection, e: Entry, values: dict) -> str:
        from app.ledger import service as ledger_service
        from app.services import asset_keys
        from app.services.attribute_validation import validate_attributes
        schema = self.vendor_schema if e.kind == "vendor" else self.model_schema
        attrs = {p[5:]: v for p, v in _changes(self.db, values).items() if p.startswith("attr:")}
        validate_attributes(self.db, schema, attrs, self.ws, Asset)
        uid = str(uuid.uuid4())
        ledger_service.create_record(self.db, self.ws, self.actor, uid=uid, schema_uid=schema.uid,
                                     key=asset_keys.allocate(self.db, self.ws, schema), name=values["name"],
                                     type_name=schema.name, attributes=attrs, is_global=True)
        return uid

    def _write(self, c: Collection, uid: str, values: dict) -> None:
        from app.ledger import service as ledger_service
        if values:
            ledger_service.edit_values(self.db, self.ws, self.actor, uid, _changes(self.db, values),
                                       reason=self._reason(c))

    def _merge(self, c: Collection, survivor: str, losers: list[str]) -> None:
        """The ledger's merge: the survivor keeps its uid, every reference to a duplicate moves to it, and the
        duplicate stays as a Merged tombstone that still resolves."""
        from app.ledger.identity import merge
        for loser in losers:
            record = self.db.get(Asset, loser)
            if record is None or record.workspace_id != self.ws:
                raise CatalogueProblem(f"the manifest names {loser} to merge, and {self.ws} has no such record")
            if record.record_status == "Merged":
                continue
            if any(r.record_uid == loser for r in self.rows.values()):
                raise CatalogueProblem(f"{record.name} has a catalogue id of its own: it is not merged")
            merge(self.db, self.ws, self.actor, survivor, loser, reason=self._reason(c) + ": a duplicate")

    def _labels(self, uid: str, e: Entry) -> None:
        from app.ledger.identity import add_label
        add_label(self.db, uid, "catalogue_id", e.id, "catalogue")
        for alias in e.data.get("aliases") or []:
            add_label(self.db, uid, "alias", str(alias), "catalogue")

    def _row(self, c: Collection, e: Entry, uid: str, stated: dict, managed: list, adopted: bool) -> CatalogueEntry:
        from app.ledger.engine import now
        row = CatalogueEntry(catalogue_id=e.id, record_uid=uid, workspace_id=self.ws, kind=e.kind,
                             collection_id=c.id, collection_version=c.version, collection_checksum=c.checksum,
                             stated=stated, managed_fields=sorted(managed), corrections={}, conflicts={},
                             status="retired" if e.data.get("retired") else "active",
                             retired=e.data.get("retired"),
                             adopted_at=now() if adopted else None, adopted_by=self.actor if adopted else None)
        self.db.add(row)
        self.db.flush()
        self.rows[e.id] = row
        return row

    # ---------------------------------------------------------------- one entry
    def entry(self, c: Collection, e: Entry) -> Item:
        keys = self.vendor_keys if e.kind == "vendor" else self.model_keys
        stated = _statement(e, self.vendor_uids, keys)
        item = Item(e.id, e.kind, c.id, "unchanged")
        row = self.rows.get(e.id)
        if row is None:
            item = self._new(c, e, stated, item)
        else:
            item = self._existing(c, e, row, stated, item)
        losers = [u for u in self.merges.get(e.id, []) if u != item.record_uid]
        if losers:
            item.notes.append(f"merges {len(losers)} duplicate{'s' if len(losers) > 1 else ''} into it "
                              "(the migration manifest)")
            if self.apply and item.record_uid:
                self._merge(c, item.record_uid, losers)
        if e.kind == "vendor" and item.record_uid:
            self.vendor_uids[e.id] = item.record_uid
        elif e.kind == "vendor":
            self.vendor_uids.setdefault(e.id, f"new:{e.id}")
        return item

    def _new(self, c: Collection, e: Entry, stated: dict, item: Item) -> Item:
        decision = self.decisions.get(e.id) or {}
        candidate = None
        if decision.get("record_uid"):
            candidate = self.db.get(Asset, decision["record_uid"])
            schema = self.vendor_schema if e.kind == "vendor" else self.model_schema
            if candidate is None or candidate.workspace_id != self.ws or candidate.schema_uid != schema.uid:
                raise CatalogueProblem(f"{e.id}: {decision['record_uid']} is not a {schema.name} of {self.ws}")
            if any(r.record_uid == candidate.uid for r in self.rows.values()):
                raise CatalogueProblem(f"{e.id}: {candidate.name} already has a catalogue id")
        elif e.kind == "vendor":
            candidate = self.candidates.vendor(e)
        else:
            vendor_id = str(e.data.get("vendor"))
            candidate = self.candidates.model(e, self.vendor_entries.get(vendor_id), self.vendor_uids.get(vendor_id))
        if candidate is not None and candidate.uid in self.claimed:
            candidate = None                                           # an earlier entry took it in this run
        if e.data.get("retired") and candidate is None:
            item.category = "retire"
            item.notes.append("retired before this workspace had it: not created")
            return item
        if candidate is None or decision.get("action") == "create":
            item.category = "add"
            item.fields = [{"field": f, "record": None, "release": v, "action": "managed"} for f, v in stated.items()]
            if self.apply:
                uid = self._create(c, e, stated)
                self._labels(uid, e)
                self._row(c, e, uid, stated, list(stated), adopted=False)
                item.record_uid = uid
            return item

        item.category, item.record_uid, item.record_name = "link", candidate.uid, candidate.name
        if decision.get("action") not in ("link",):
            item.needs_decision = True
            item.notes.append("the same product as an existing record: link it, or create a separate one")
        self.claimed.add(candidate.uid)
        chosen = decision.get("fields") or {}
        managed, writes, corrections = [], {}, {}
        for f, v in stated.items():
            cur = _current(candidate, f)
            if _same(cur, v) or _blank(cur):                   # agreeing, or empty here: the collection's
                action = "managed"
            else:
                action = chosen.get(f)
                if action not in FIELD_DECISIONS:
                    item.needs_decision = True
                    action = None
            item.fields.append({"field": f, "record": cur, "release": v, "action": action})
            if action == "managed":
                managed.append(f)
                if not _same(cur, v):
                    writes[f] = v
            elif action == "propose":
                corrections[f] = {"value": cur, "by": self.actor, "release": v}
        if self.apply and not item.needs_decision:
            from app.ledger.engine import now
            self._write(c, candidate.uid, writes)
            self._labels(candidate.uid, e)
            row = self._row(c, e, candidate.uid, stated, managed, adopted=True)
            row.corrections = {f: {**v, "at": now().isoformat()} for f, v in corrections.items()}
        return item

    def _existing(self, c: Collection, e: Entry, row: CatalogueEntry, stated: dict, item: Item) -> Item:
        record = self.db.get(Asset, row.record_uid)
        item.record_uid, item.record_name = row.record_uid, record.name if record else None
        if row.collection_id != c.id:
            if e.data.get("transferred_from") != row.collection_id:
                raise CatalogueProblem(f"{e.id} is in {row.collection_id} here; {c.id} does not say it was "
                                       f"transferred from there")
            item.category = "transfer"
            item.notes.append(f"from {row.collection_id}")
        managed = set(row.managed_fields or [])
        conflicts = dict(row.conflicts or {})
        corrections = dict(row.corrections or {})
        writes: dict = {}
        changed = False
        for f in sorted(set(stated) | set(row.stated or {})):
            new, old = stated.get(f), (row.stated or {}).get(f)
            cur = _current(record, f) if record is not None else None
            entry = {"field": f, "record": cur, "release": new, "action": None}
            if f not in stated:                                        # the release no longer states it
                if f in managed:
                    managed.discard(f)
                    entry["action"] = "local"
                    item.fields.append(entry)
                    item.notes.append(f"{f}: no longer in the collection; the record keeps its value")
                    changed = True
                continue
            if f in corrections and _same(corrections[f].get("value"), new):
                corrections.pop(f)
                managed.add(f)
                item.notes.append(f"{f}: the correction proposed back is in this release")
                changed = True
            if f in managed:
                if _same(cur, new):
                    conflicts.pop(f, None)
                    if not _same(old, new):
                        changed = True
                    continue
                if _same(cur, old) or (old is None and _blank(cur)):
                    writes[f] = new
                    entry["action"] = "managed"
                    item.fields.append(entry)
                    conflicts.pop(f, None)
                    continue
                entry["action"] = "conflict"                           # edited here since the last release
            elif old is None and row.adopted_at is None:               # newly stated, on a record we made
                managed.add(f)
                if not _same(cur, new):
                    writes[f] = new
                    entry["action"] = "managed"
                    item.fields.append(entry)
                changed = True
                continue
            elif old is None:                                          # newly stated, on an adopted record
                if _blank(cur) or _same(cur, new):
                    managed.add(f)
                    changed = True
                    if not _same(cur, new):
                        writes[f] = new
                        entry["action"] = "managed"
                        item.fields.append(entry)
                    continue
                entry["action"] = "conflict"
            elif not _same(old, new) and not _same(cur, new):
                entry["action"] = "conflict"                           # a local override the release changes
            else:
                if not _same(old, new):
                    changed = True
                continue
            item.fields.append(entry)
            conflicts[f] = {"release": new, "record": cur, "version": c.version}
        if any(x["action"] == "conflict" for x in item.fields):
            item.category = "conflict" if item.category == "unchanged" else item.category
            item.notes.append("kept the record's value where the release differs from a local one; queued for review")
        elif writes and item.category == "unchanged":
            item.category = "change"
        retired = e.data.get("retired")
        if retired and row.status != "retired":
            item.category = "retire"
            units = _units_using(self.db, row.record_uid) if e.kind == "model" else 0
            if units:
                item.notes.append(f"{units} units are of this model: it stays, marked retired"
                                  + (f", replaced by {retired['replaced_by']}" if retired.get("replaced_by") else ""))
        elif not retired and row.status == "retired":
            item.category = "change" if item.category == "unchanged" else item.category
            item.notes.append("no longer retired")
        if self.apply:
            self._write(c, row.record_uid, writes)
            if e.kind == "vendor":
                self._labels(row.record_uid, e)
            row.collection_id, row.collection_version, row.collection_checksum = c.id, c.version, c.checksum
            row.stated, row.managed_fields = stated, sorted(managed)
            row.conflicts, row.corrections = conflicts, corrections
            row.status = "retired" if retired else "active"
            row.retired = retired
        if changed and item.category == "unchanged":
            item.notes.append("what the collection states changed; the record already has those values")
        return item

    def tombstone(self, c: Collection, e: Entry) -> Optional[Item]:
        row = self.rows.get(e.id)
        if row is None or row.collection_id != c.id:
            return None                                                # already moved, or never here
        item = Item(e.id, row.kind, c.id, "transfer", record_uid=row.record_uid)
        item.notes.append(f"moving to {e.data.get('moved_to')}: stays with {c.id} until that release is installed")
        if self.apply:
            row.status = "transferring"
            row.collection_version, row.collection_checksum = c.version, c.checksum
        return item


def _units_using(db: Session, model_uid: str) -> int:
    return db.scalar(select(func.count()).select_from(Asset).where(
        Asset.attributes["product_model"].astext == model_uid, Asset.deleted_at.is_(None))) or 0


# --------------------------------------------------------------------------- entry points

def plan(db: Session, workspace_id: str, collection_ids: list[str], *, actor: str, decisions: Optional[dict] = None,
         apply: bool = False, tree: Optional[dict[str, Collection]] = None, merges: Optional[dict] = None,
         expected: Optional[dict] = None) -> Plan:
    """Compare the releases with the records; with `apply`, also write them. The caller commits or rolls back."""
    if tree is None:
        from app.catalogue.sources import SourceProblem
        # Of a NetBox library, the models this catalogue has: an upgrade of those, never all 12,760 installed.
        have_ids: dict[str, set[str]] = {}
        for r in entries(db, workspace_id).values():
            have_ids.setdefault(r.collection_id, set()).add(r.catalogue_id)
        try:
            tree = load_tree(netbox_models=have_ids)
        except SourceProblem as e:
            raise CatalogueProblem(f"the catalogue's sources cannot be read as pinned: {e}")
    order = _order(tree, collection_ids)
    report = tree_problems(tree)
    bad = [str(p) for c in order for p in report.get(c.id, [])]
    if bad:
        raise CatalogueProblem("the collections are not valid: run `python -m app.catalogue validate`", bad)
    have = installed(db, workspace_id)
    run = _Run(db, workspace_id, actor, decisions or {}, apply, merges)
    for c in tree.values():                       # every vendor, so a model finds its vendor's entry
        for v in c.vendors:
            run.vendor_entries[v.id] = v
    out = Plan(workspace_id)
    for c in order:
        _check_packages(db, workspace_id, c)
        before = have.get(c.id)
        release = Release(c.id, before.version if before else None, c.version, c.checksum)
        if before is not None:
            if Version(c.version) < Version(before.version):
                raise CatalogueProblem(f"{c.id}: {workspace_id} has {before.version}; {c.version} is older")
            if before.version == c.version:
                if before.checksum != c.checksum:
                    raise CatalogueProblem(f"{c.id} {c.version} is installed with other content (checksum "
                                           f"{before.checksum[:12]}, now {c.checksum[:12]}): a change needs a "
                                           f"new version")
                release.already = True
                out.releases.append(release)
                continue
        for dep, spec in c.requires_collections.items():
            got = have.get(dep)
            version = tree[dep].version if any(o.id == dep for o in order) else (got.version if got else None)
            if version is None or Version(version) not in SpecifierSet(spec):
                raise CatalogueProblem(f"{c.id} needs the collection {dep} {spec}")
        if apply:
            _lock(db, workspace_id, c.id)
        for e in [*c.vendors, *c.models]:
            release.items.append(run.entry(c, e))
        for e in c.moved:
            item = run.tombstone(c, e)
            if item is not None:
                release.items.append(item)
        for key in NOT_STORED:
            n = sum(1 for m in c.models if m.data.get(key))
            if n:
                release.not_stored[key] = n
        out.releases.append(release)
        if apply and out.undecided():
            raise CatalogueProblem("some entries need a decision first (link or create, and the fields that "
                                   "differ)", out.undecided())
        if apply:
            db.add(CatalogueInstallation(workspace_id=workspace_id, collection_id=c.id, from_version=release.from_version,
                                         version=c.version, checksum=c.checksum, installed_by=actor,
                                         domains=list(c.domains) or None,
                                         result={"counts": release.counts(),
                                                 "attention": [i.as_dict() for i in release.items
                                                               if i.category in ("conflict", "retire", "transfer")]}))
            db.flush()
    if apply and expected:
        _check_references(db, out, run, expected)
    return out


def _check_references(db: Session, out: Plan, run: _Run, expected: dict) -> None:
    """After an install with a manifest: each adopted record (with its merged duplicates) is pointed at by at
    least the units and document links the export counted. Fewer means a reference was lost, and nothing is
    kept. Relations are not compared: a merge rightly folds two identical edges (each duplicate's edge to the
    same vendor) into one."""
    from app.catalogue.export import reference_counts
    linked = {i.catalogue_id: i.record_uid for r in out.releases for i in r.items if i.record_uid}
    # A reference to a merged duplicate still resolves: the tombstone redirects to the survivor
    # (merged_into_uid). So a record's references are its own and its tombstones'.
    merged: dict[str, list[str]] = {}
    for uid, into in db.execute(select(Asset.uid, Asset.merged_into_uid).where(
            Asset.merged_into_uid.in_(list(linked.values())))):
        merged.setdefault(into, []).append(uid)
    counts = reference_counts(db, [*linked.values(), *(u for us in merged.values() for u in us)])
    lost = []
    for cid, want in expected.items():
        uid = linked.get(cid)
        if uid is None:
            continue
        have = {k: sum(counts.get(u, {}).get(k, 0) for u in [uid, *merged.get(uid, [])])
                for k in ("units", "documents")}
        for k in ("units", "documents"):
            if have.get(k, 0) < int((want or {}).get(k, 0)):
                lost.append(f"{cid}: {k} {have.get(k, 0)}, the export counted {want[k]}")
    if lost:
        raise CatalogueProblem("references would be lost: nothing was installed", lost)


def preview(db: Session, workspace_id: str, collection_ids: list[str], *, actor: str,
            decisions: Optional[dict] = None, tree: Optional[dict[str, Collection]] = None,
            merges: Optional[dict] = None, expected: Optional[dict] = None) -> dict:
    """What installing would do. When every decision is made, the installation also runs for real and is
    rolled back, so whatever would make it fail (an attribute a type refuses) shows here."""
    shown = plan(db, workspace_id, collection_ids, actor=actor, decisions=decisions, tree=tree, merges=merges)
    out = shown.as_dict()
    out["trial"] = None
    if not shown.undecided():
        savepoint = db.begin_nested()
        try:
            plan(db, workspace_id, collection_ids, actor=actor, decisions=decisions, apply=True, tree=tree,
                 merges=merges, expected=expected)
            out["trial"] = "ok"
        except Exception as exc:                                      # reported, never kept
            out["trial"] = f"failed: {exc}"
        finally:
            savepoint.rollback()
    return out


def install(db: Session, workspace_id: str, collection_ids: list[str], *, actor: str,
            decisions: Optional[dict] = None, tree: Optional[dict[str, Collection]] = None,
            merges: Optional[dict] = None, expected: Optional[dict] = None) -> dict:
    """Install or upgrade, all or nothing: the caller commits on success. With a migration manifest's merges
    and expected references, duplicates are merged and the references checked before anything is kept."""
    return plan(db, workspace_id, collection_ids, actor=actor, decisions=decisions, apply=True, tree=tree,
                merges=merges, expected=expected).as_dict()
