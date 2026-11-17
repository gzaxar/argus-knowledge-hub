"""Exporting a workspace's Vendors and Product Models as catalogue collections, with the installation's
migration manifest and a report (docs/catalogue-collections.md §6). It only reads.

    python -m app.catalogue export --workspace accelerator-infn --out catalogue-export/

It writes:

* `collections/<id>/…` — candidate entries, **portable** (no ARGUS uid or key), to be reviewed and merged in
  Git into `backend/catalogue/`: entries for a collection that ships go in `models.yaml` beside a note naming
  the file they join; a collection that does not ship yet also gets a draft `collection.yaml`.
* `migration-<workspace>.yaml` — **this installation's** manifest, never part of a collection: which record
  each catalogue id is (an entry exported from it, or a shipped entry it matches), the duplicates to merge into
  it, the proposed field decisions, the values that stay local, and the references each record has, which
  the install checks again afterwards.
* `report.md` and `report.csv` — one line per record: what it becomes, and what a person has to look at.

Before writing, the candidates are put together with the shipped collections and validated: the report lists
what the validator would refuse.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.catalogue.loader import MANIFEST, catalogue_dir, load_tree
from app.catalogue.validate import DESCRIPTION_MAX, DEVICE_CLASSES, code_key, object_types, tree_problems
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetLabel
from app.models.document import DocumentRelation
from app.services.catalogue_mapping import COMPANY_SUFFIX, catalogue_types, norm

# Spellings in use for one device class (the production inventory, 2026-10-31).
DEVICE_CLASS_SPELLINGS = {"switch": "network switch", "host": "server", "chassi": "chassis",
                          "controller motor": "motion controller", "hw": None}
# Where a model goes: by the type of the units that are of it, else by its device class.
COLLECTION_OF_UNIT_TYPE = {
    "Motion Controller": "motion", "Motor Axis": "motion", "Primary Pump": "vacuum", "Turbo Pump": "vacuum",
    "Vacuum Gauge": "vacuum", "Vacuum Valve": "vacuum", "Chiller": "vacuum", "Camera": "accelerator-diagnostics",
    "Serial Converter": "it-network", "Network Switch": "it-network", "Server": "it-compute"}
COLLECTION_OF_CLASS = {
    "vacuum": "vacuum", "vacuum chamber": "vacuum", "ion pump controller": "vacuum",
    "motor": "motion", "motion controller": "motion",
    "bpm": "accelerator-diagnostics", "camera": "accelerator-diagnostics", "adc": "accelerator-diagnostics",
    "laser": "accelerator-diagnostics",
    "power supply": "accelerator-power", "modulator": "accelerator-power", "plasma": "accelerator-power",
    "rf": "accelerator-rf", "timing": "timing-control", "io": "timing-control",
    "network switch": "it-network", "converter": "it-network",
    "server": "it-compute", "nas": "it-compute", "desktop computer": "it-compute", "monitor": "it-compute",
    "chassis": "it-compute", "cable": "it-compute"}
COLLECTION_NAMES = {"motion": "Motion: motors, stages and their controllers", "it-compute": "IT compute and storage",
                    "accelerator-rf": "Accelerator RF", "timing-control": "Timing and control"}
SOLD_BY = re.compile(r"^\s*(sold by|venduto da|fornitore)\b.*$", re.I | re.M)
URL = re.compile(r"^https?://\S+$")


def slug(s: str) -> str:
    s = str(s or "").lower().replace("+", "-plus").replace("&", " and ")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9.]+", "-", s)).strip("-.") or "x"


def vendor_slug(name: str) -> str:
    s = COMPANY_SUFFIX.sub(" ", str(name or "").lower().replace("&", " and "))
    return slug(s)


@dataclass
class Row:
    """One record of the workspace, and what it becomes."""
    uid: str
    key: str
    kind: str
    name: str
    becomes: str = ""                    # export | link | merge | skip | already
    catalogue_id: Optional[str] = None
    collection: Optional[str] = None
    flags: list = field(default_factory=list)
    refs: dict = field(default_factory=dict)


def reference_counts(db: Session, uids: list[str]) -> dict[str, dict]:
    """What points at each record: units (any attribute holding its uid), relations, labels, document links."""
    wanted = set(uids)
    out = {u: {"units": 0, "relations": 0, "labels": 0, "documents": 0} for u in uids}
    if not wanted:
        return out
    for a in db.scalars(select(Asset).where(Asset.deleted_at.is_(None)).execution_options(yield_per=2000)):
        if a.uid in wanted:
            continue
        hit = set()
        for v in (a.attributes or {}).values():
            for x in (v if isinstance(v, list) else [v]):
                if isinstance(x, str) and x in wanted:
                    hit.add(x)
        for u in hit:
            out[u]["units"] += 1
    for frm, to in db.execute(select(Relation.from_asset_uid, Relation.to_asset_uid)):
        for u in (frm, to):
            if u in wanted:
                out[u]["relations"] += 1
    for (u,) in db.execute(select(AssetLabel.asset_uid).where(AssetLabel.asset_uid.in_(wanted))):
        out[u]["labels"] += 1
    for (u,) in db.execute(select(DocumentRelation.to_uid).where(DocumentRelation.to_uid.in_(wanted))):
        out[u]["documents"] += 1
    return out


def _description_flags(text_: Any) -> list[str]:
    """Descriptions are not exported: what is in them today is the manufacturer's text (a datasheet or a shop
    page, pasted in), which a public collection cannot republish, and the seller. They stay on the record."""
    if not isinstance(text_, str) or not text_.strip():
        return []
    flags = ["names the seller (stays on the record)"] if SOLD_BY.search(text_) else []
    if len(text_) > DESCRIPTION_MAX:
        flags.append("description is datasheet text: put the figures in specifications, and link the datasheet")
    return flags


class _Export:
    def __init__(self, db: Session, workspace_id: str):
        self.db, self.ws = db, workspace_id
        self.model_schema, self.vendor_schema = catalogue_types(db, workspace_id)
        self.tree = load_tree()
        self.types = object_types()
        live = select(Asset).where(Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None),
                                   Asset.record_status.notin_(("Merged",)))
        self.vendors = list(self.db.scalars(live.where(Asset.schema_uid == self.vendor_schema.uid).order_by(Asset.key)))
        self.models = list(self.db.scalars(live.where(Asset.schema_uid == self.model_schema.uid).order_by(Asset.key)))
        from app.catalogue.install import entries
        self.installed = {e.record_uid: e.catalogue_id for e in entries(db, workspace_id).values()}
        self.refs = reference_counts(db, [r.uid for r in [*self.vendors, *self.models]])
        self.rows: list[Row] = []
        self.vendor_entries: dict[str, dict] = {}          # new vendor id -> entry
        self.model_entries: dict[str, list] = defaultdict(list)   # collection -> entries
        self.vendor_id: dict[str, str] = {}                # vendor record uid -> catalogue id
        self.links: dict[str, dict] = {}
        self.merges: dict[str, list] = defaultdict(list)
        self.local_values: dict[str, dict] = {}
        self.today = date.today()

    # ---------------------------------------------------------------- vendors
    def _shipped_vendor(self, names: list[str]) -> Optional[str]:
        keys = {norm(n) for n in names if norm(n)}
        for c in self.tree.values():
            for v in c.vendors:
                if keys & {norm(str(x)) for x in [v.data.get("name"), *(v.data.get("aliases") or [])]}:
                    return v.id
        return None

    def vendors_pass(self) -> None:
        seen: dict[str, str] = {}                           # normalised name -> catalogue id
        for v in self.vendors:
            row = Row(v.uid, v.key, "vendor", v.name, refs=self.refs.get(v.uid, {}))
            self.rows.append(row)
            if v.uid in self.installed:
                row.becomes, row.catalogue_id = "already", self.installed[v.uid]
                self.vendor_id[v.uid] = row.catalogue_id
                continue
            shipped = self._shipped_vendor([v.name])
            if shipped:
                row.becomes, row.catalogue_id = "link", shipped
                self._link_or_merge(row, shipped, v, {})
                self.vendor_id[v.uid] = shipped
                continue
            key = norm(v.name)
            if key in seen:
                row.becomes, row.catalogue_id = "merge", seen[key]
                self.merges[seen[key]].append(self._merge_item(v))
                self.vendor_id[v.uid] = seen[key]
                continue
            vid = vendor_slug(v.name)
            while vid in self.vendor_entries or any(x.id == vid for c in self.tree.values() for x in c.vendors):
                vid += "-2"
            entry = {"id": vid, "name": v.name}
            if (v.attributes or {}).get("website") and URL.match(str(v.attributes["website"])):
                entry["website"] = v.attributes["website"]
            entry["sources"] = [{"kind": "argus-export", "ref": f"{self.ws}/{v.key}", "checked": self.today}]
            self.vendor_entries[vid] = entry
            seen[key] = vid
            row.becomes, row.catalogue_id, row.collection = "export", vid, "vendors"
            self.vendor_id[v.uid] = vid
            self.links[vid] = {"record_uid": v.uid, "key": v.key, "fields": {}}

    def _merge_item(self, a: Asset) -> dict:
        return {"record_uid": a.uid, "key": a.key, "name": a.name, "references": self.refs.get(a.uid, {})}

    def _differing(self, cid: str, a: Asset) -> dict:
        """The fields where this record says something else than the shipped entry: proposed local, so the
        record keeps its value until a person decides otherwise."""
        entry = next((e.data for c in self.tree.values() for e in c.entries() if e.id == cid), {})
        attrs = a.attributes or {}
        out = {}
        for f in ("name", "model_code", "device_class", "datasheet_url", "firmware_version", "website",
                  "description"):
            if f not in entry:
                continue
            mine = a.name if f == "name" else attrs.get(f)
            if mine not in (None, "") and str(mine).strip() != str(entry[f]).strip():
                out[f] = "local"
        return out

    def _link_or_merge(self, row: Row, cid: str, a: Asset, fields: dict) -> None:
        """A record that is a shipped entry: the first one links, any other is a duplicate merged into it."""
        fields = {**self._differing(cid, a), **fields}
        if cid in self.links:
            row.becomes = "merge"
            self.merges[cid].append(self._merge_item(a))
        else:
            self.links[cid] = {"record_uid": a.uid, "key": a.key, "fields": fields}

    # ---------------------------------------------------------------- models
    def _vendor_of(self, m: Asset) -> Optional[str]:
        a = m.attributes or {}
        if a.get("vendor_ref") in self.vendor_id:
            return self.vendor_id[a["vendor_ref"]]
        if a.get("vendor"):
            for v in self.vendors:
                if norm(v.name) == norm(a["vendor"]) and v.uid in self.vendor_id:
                    return self.vendor_id[v.uid]
            return self._shipped_vendor([a["vendor"]])
        return None

    def _shipped_model(self, vendor: str, code: str, name: str) -> tuple[Optional[str], bool]:
        """The shipped entry this record is: (id, exact). Exact is the same vendor and model code. A code found
        only inside the record's name ("TwisTorr 305 FS" inside "TwisTorr 305 FS CTR", the pump's controller) is
        a candidate for a person, never a link or a merge by itself."""
        inside = []
        for c in self.tree.values():
            for e in c.models:
                if e.data.get("vendor") != vendor:
                    continue
                k = code_key(e.data.get("model_code"))
                if k and k == code:
                    return e.id, True
                if k and len(k) >= 4 and k in code_key(name):
                    inside.append(e.id)
        return (inside[0], False) if len(inside) == 1 else (None, False)

    def _unit_types(self, uid: str) -> Counter:
        pm = Asset.attributes["product_model"].astext
        return Counter(t for (t,) in self.db.execute(select(Asset.type).where(pm == uid, Asset.deleted_at.is_(None))))

    def models_pass(self) -> None:
        vendor_names = {norm(v.name) for v in self.vendors}
        groups: dict[tuple, list[tuple[Asset, Row]]] = defaultdict(list)
        for m in self.models:
            a = m.attributes or {}
            row = Row(m.uid, m.key, "model", m.name, refs=self.refs.get(m.uid, {}))
            self.rows.append(row)
            if m.uid in self.installed:
                row.becomes, row.catalogue_id = "already", self.installed[m.uid]
                continue
            if "synthetic-demo" in (a.get("argus_keywords") or []):
                row.becomes = "skip"
                row.flags.append("synthetic demo data")
                continue
            if norm(m.name) in vendor_names:
                row.becomes = "skip"
                row.flags.append("the name is a company's: not a product — fix or retire it")
                continue
            vendor = self._vendor_of(m)
            if not vendor:
                row.becomes = "skip"
                row.flags.append("no vendor: give it one, then export again")
                continue
            code = a.get("model_code")
            if not code:
                code = m.name.strip()
                row.flags.append(f"model code proposed from the name: {code!r} — confirm it")
            shipped, exact = self._shipped_model(vendor, code_key(code), m.name)
            if shipped and not exact:
                row.becomes, row.catalogue_id = "review", shipped
                row.flags.append(f"may be {shipped} (its code is inside the name), or another product: a person "
                                 "decides — on the Catalogue collections page, or by adding it to the manifest")
                continue
            if shipped:
                row.becomes, row.catalogue_id = "link", shipped
                # Matched with the same vendor: its record is the vendor, or a duplicate merged into it.
                self._link_or_merge(row, shipped, m, {"vendor": "managed"})
                continue
            groups[(vendor, code_key(code))].append((m, row, code))
        for (vendor, _k), members in groups.items():
            members.sort(key=lambda x: (-x[1].refs.get("units", 0), x[0].key))
            (m, row, code), dupes = members[0], members[1:]
            self._model_entry(m, row, vendor, code)
            for d, drow, _c in dupes:
                drow.becomes, drow.catalogue_id, drow.collection = "merge", row.catalogue_id, row.collection
                self.merges[row.catalogue_id].append(self._merge_item(d))

    def _model_entry(self, m: Asset, row: Row, vendor: str, code: str) -> None:
        a = m.attributes or {}
        cid = f"{vendor}/{slug(code)}"
        taken = {e["id"] for es in self.model_entries.values() for e in es} | \
                {e.id for c in self.tree.values() for e in c.models}
        while cid in taken:
            cid += "-2"
        raw_class = str(a.get("device_class") or "").strip().lower()
        device_class = DEVICE_CLASS_SPELLINGS.get(raw_class, raw_class) or None
        fields = {"vendor": "managed"}          # its vendor's record, or a duplicate of it that the install merges
        if device_class and device_class != a.get("device_class"):
            fields["device_class"] = "managed"
            row.flags.append(f"device class {a.get('device_class')!r} → {device_class!r}")
        if device_class not in DEVICE_CLASSES:
            row.flags.append(f"device class {a.get('device_class')!r} is not one of the list: choose one")
        types = self._unit_types(m.uid)
        instance_type = next((t for t, _ in types.most_common() if t in self.types and not self.types[t][1]), None)
        collection = (COLLECTION_OF_UNIT_TYPE.get(instance_type or "") or COLLECTION_OF_CLASS.get(device_class or "")
                      or "unsorted")
        if collection == "unsorted":
            row.flags.append("no collection follows from its units or device class: choose one")
        shipped = self.tree.get(collection)
        if instance_type and shipped is not None:
            from app.catalogue.validate import _package_closure
            package = self.types[instance_type][0]
            if package not in _package_closure(shipped.requires_packages):
                row.flags.append(f"its units are {instance_type} ({package}), which {collection} does not "
                                 f"require: instance type left out")
                instance_type = None
        entry: dict = {"id": cid, "vendor": vendor, "model_code": code, "name": m.name.strip()}
        if device_class:
            entry["device_class"] = device_class
        if instance_type:
            entry["instance_type"] = instance_type
        row.flags += _description_flags(a.get("description"))
        if a.get("description"):
            self.local_values[m.uid] = {"description": "kept on the record: not stated by the collection"}
        for k in ("datasheet_url", "firmware_version"):
            if a.get(k) and (k != "datasheet_url" or URL.match(str(a[k]))):
                entry[k] = a[k]
        if a.get("eol_date"):
            try:
                entry["eol_date"] = date.fromisoformat(str(a["eol_date"])[:10])
            except ValueError:
                row.flags.append(f"end-of-life date {a['eol_date']!r} is not a date")
        entry["sources"] = [{"kind": "argus-export", "ref": f"{self.ws}/{m.key}", "checked": self.today}]
        self.model_entries[collection].append(entry)
        row.becomes, row.catalogue_id, row.collection = "export", cid, collection
        self.links[cid] = {"record_uid": m.uid, "key": m.key, "fields": fields}

    # ---------------------------------------------------------------- output
    def _requires(self, collection: str) -> dict:
        shipped = self.tree.get(collection)
        if shipped is not None:
            return {"packages": shipped.requires_packages, "collections": shipped.requires_collections}
        packages = {"core-objects": ">=2.1,<3"}
        for e in self.model_entries[collection]:
            t = self.types.get(e.get("instance_type", ""))
            if t and t[0] != "core-objects":
                packages[t[0]] = ">=1.0"
        return {"packages": packages, "collections": {"vendors": self._vendors_range()}}

    def _vendors_range(self) -> str:
        """The vendors a new collection needs: the shipped vendors' version, up to its next major."""
        vendors = self.tree.get("vendors")
        try:
            major, minor = (int(x) for x in str(vendors.version).split(".")[:2])
        except (AttributeError, ValueError):
            return ">=0.1,<1"
        return f">={major}.{minor},<{major + 1}"

    def candidates(self, out: Path) -> None:
        base = out / "collections"
        if self.vendor_entries:
            (base / "vendors").mkdir(parents=True, exist_ok=True)
            _dump(base / "vendors" / "vendors.yaml", {"vendors": list(self.vendor_entries.values())},
                  "Add to backend/catalogue/vendors/vendors.yaml after review.")
        for collection, es in sorted(self.model_entries.items()):
            d = base / collection
            d.mkdir(parents=True, exist_ok=True)
            if collection in self.tree:
                note = f"Add to backend/catalogue/{collection}/ (the collection ships) after review."
            else:
                note = "A new collection: review the manifest beside this file too."
                _dump(d / MANIFEST, {"id": collection, "version": "0.1.0",
                                     "name": COLLECTION_NAMES.get(collection, collection.replace("-", " ").title()),
                                     "description": "Exported from ARGUS: a draft for review.",
                                     "domain": "catalogue", "owner": "INFN ARGUS", "license": "CC0-1.0",
                                     "requires": self._requires(collection), "contents": ["models.yaml"]},
                      "A draft manifest.")
            _dump(d / "models.yaml", {"models": sorted(es, key=lambda e: e["id"])}, note)

    def check(self) -> list[str]:
        """The shipped collections with the candidates added, through the validator."""
        tmp = Path(tempfile.mkdtemp(prefix="catalogue-export-"))
        try:
            from app.catalogue.sources import lock_path, materialize
            base = materialize(lock_path()) if lock_path().is_file() else catalogue_dir()
            shutil.copytree(base, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".complete"))
            additions = {"vendors": {"vendors": list(self.vendor_entries.values())},
                         **{c: {"models": es} for c, es in self.model_entries.items()}}
            for cid, sections in additions.items():
                d = tmp / cid
                if (d / MANIFEST).is_file():
                    manifest = yaml.safe_load((d / MANIFEST).read_text())
                    target = d / manifest["contents"][0]
                    data = yaml.safe_load(target.read_text()) or {}
                    for k, v in sections.items():
                        data[k] = [*(data.get(k) or []), *v]
                    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
                else:
                    d.mkdir(parents=True, exist_ok=True)
                    (d / MANIFEST).write_text(yaml.safe_dump({
                        "id": cid, "version": "0.1.0", "name": cid, "domain": "catalogue", "owner": "INFN ARGUS",
                        "license": "CC0-1.0", "requires": self._requires(cid), "contents": ["models.yaml"]}))
                    (d / "models.yaml").write_text(yaml.safe_dump(sections, sort_keys=False, allow_unicode=True))
            report = tree_problems(load_tree(tmp))
            return [str(p) for ps in report.values() for p in ps]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def manifest(self) -> dict:
        refs = {}
        for cid, link in self.links.items():
            uids = [link["record_uid"], *[m["record_uid"] for m in self.merges.get(cid, [])]]
            refs[cid] = {k: sum(self.refs.get(u, {}).get(k, 0) for u in uids)
                         for k in ("units", "relations", "documents")}
        return {"workspace": self.ws, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "note": "This installation's migration manifest. It names records of this ARGUS installation: keep "
                        "it with the installation's operations records, never in a catalogue collection.",
                "links": dict(sorted(self.links.items())), "merge": dict(sorted(self.merges.items())),
                "local_values": self.local_values, "references": refs}


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):                     # a reviewer reads every value where it is
        return True


def _dump(path: Path, data: dict, note: str) -> None:
    body = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=110)
    path.write_text(f"# {note}\n{body}", encoding="utf-8")


BECOMES = {"export": "a new catalogue entry", "link": "adopted by a shipped entry", "merge": "a duplicate, merged",
           "review": "a possible match, for a person",
           "skip": "not exported", "already": "already linked"}


def report_md(ex: _Export, problems: list[str]) -> str:
    rows = ex.rows
    count = Counter(r.becomes for r in rows)
    out = [f"# Catalogue export: `{ex.ws}`", "", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
           "Read-only: nothing in ARGUS was changed.", "",
           "| | Vendors | Models |", "|---|---|---|"]
    for b in ("export", "link", "review", "merge", "skip", "already"):
        v = sum(1 for r in rows if r.becomes == b and r.kind == "vendor")
        m = sum(1 for r in rows if r.becomes == b and r.kind == "model")
        if v or m:
            out.append(f"| {BECOMES[b]} | {v} | {m} |")
    out += ["", f"New collections: {', '.join(sorted(c for c in ex.model_entries if c not in ex.tree)) or 'none'}.", "",
            "Descriptions are not exported: they hold manufacturers' text and sellers, which a public collection "
            "cannot republish. They stay on the records. A reviewer may write a short description of their own.", "",
            "IT devices (the `it-network` and `it-compute` candidates) belong in the NetBox Device Type Library "
            "fork, as device types checked against the manufacturer's documentation, with their ARGUS "
            "classification in `it-classification`: the candidates here are their identity only.", ""]
    out += ["## What the validator says about the candidates", ""]
    out += ([f"- {p}" for p in problems] or ["Nothing: the candidates and the shipped collections validate together."])
    flagged = [r for r in rows if r.flags]
    out += ["", f"## To look at ({len(flagged)})", ""]
    for r in sorted(flagged, key=lambda r: (r.becomes, r.kind, r.name.lower())):
        refs = r.refs
        out.append(f"- **{r.name}** (`{r.key}`, {r.kind}) → {r.catalogue_id or BECOMES[r.becomes]}"
                   f" · {refs.get('units', 0)} units, {refs.get('relations', 0)} relations")
        out += [f"  - {f}" for f in r.flags]
    if ex.merges:
        out += ["", "## Duplicates to merge", ""]
        for cid, ms in sorted(ex.merges.items()):
            survivor = ex.links.get(cid, {})
            out.append(f"- `{cid}` ← keeps `{survivor.get('key')}`; merges "
                       + ", ".join(f"`{m['key']}` {m['name']!r} ({m['references'].get('units', 0)} units)" for m in ms))
    out += ["", f"Totals: {dict(count)}.", ""]
    return "\n".join(out)


def report_csv(ex: _Export) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "key", "name", "becomes", "catalogue_id", "collection", "units", "relations", "labels",
                "documents", "flags"])
    for r in ex.rows:
        w.writerow([r.kind, r.key, r.name, r.becomes, r.catalogue_id or "", r.collection or "",
                    r.refs.get("units", 0), r.refs.get("relations", 0), r.refs.get("labels", 0),
                    r.refs.get("documents", 0), " | ".join(r.flags)])
    return buf.getvalue()


def export(db: Session, workspace_id: str, out: Path | str) -> dict:
    """Write the candidates, the manifest and the report for one workspace. Read-only on the database."""
    out = Path(out)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    try:
        ex = _Export(db, workspace_id)
        ex.vendors_pass()
        ex.models_pass()
        problems = ex.check()
        out.mkdir(parents=True, exist_ok=True)
        ex.candidates(out)
        _dump(out / f"migration-{workspace_id}.yaml", ex.manifest(),
              "Installation-specific: never commit this file to a catalogue collection.")
        (out / "report.md").write_text(report_md(ex, problems), encoding="utf-8")
        (out / "report.csv").write_text(report_csv(ex), encoding="utf-8")
        return {"rows": len(ex.rows), "becomes": dict(Counter(r.becomes for r in ex.rows)), "problems": len(problems),
                "collections": sorted(ex.model_entries), "out": str(out)}
    finally:
        db.rollback()


def manifest_decisions(manifest: dict) -> tuple[dict, dict, dict]:
    """A migration manifest as install inputs: (decisions per catalogue id, merges, expected references)."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("links", {}), dict):
        raise ValueError("not a migration manifest: it needs `links`")
    decisions = {cid: {"action": "link", "record_uid": v["record_uid"], "fields": v.get("fields") or {}}
                 for cid, v in (manifest.get("links") or {}).items() if isinstance(v, dict) and v.get("record_uid")}
    merges = {cid: [m["record_uid"] for m in ms if isinstance(m, dict) and m.get("record_uid")]
              for cid, ms in (manifest.get("merge") or {}).items()}
    return decisions, merges, manifest.get("references") or {}
