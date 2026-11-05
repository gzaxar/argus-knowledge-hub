"""Checking catalogue collections: each one, the whole tree together, and a release against the one before.

Every rule here is one a reviewer would otherwise have to remember (docs/catalogue-collections.md):

* one manufacturer, one entry: a vendor's names and aliases may not normalise to another vendor's;
* one product, one entry: a model id is unique across every collection, and so is vendor + model code;
* a model's vendor, an instance type, a relation's target and a replacement exist, and the collection
  requires what they come from;
* a transfer is stated on both sides (`transferred_from` in the new collection, `moved_to` in the old);
* against the previous release: nothing disappears without being retired or transferred, and content that
  changed carries a newer version.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from app.catalogue.loader import MANIFEST, Collection, Entry, Problem

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MODEL_ID = re.compile(r"^([a-z0-9][a-z0-9-]*)/[a-z0-9][a-z0-9.+-]*$")
SPEC_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
URL = re.compile(r"^https?://\S+$")

VENDOR_KEYS = {"id", "name", "aliases", "website", "country", "description", "sources", "retired",
               "transferred_from", "former_ids"}
MODEL_KEYS = {"id", "vendor", "model_code", "part_number", "name", "description", "device_class", "instance_type",
              "specifications", "datasheet_url", "eol_date", "firmware_version", "typical_spares",
              "components", "notes", "relations", "sources", "retired", "transferred_from", "former_ids"}
MOVED_KEYS = {"id", "moved_to"}
# What ARGUS states about a model another source defines (a NetBox device type): never its physical definition.
CLASSIFICATION_KEYS = {"id", "device_class", "instance_type", "eol_date", "typical_spares", "relations", "sources"}
RETIRED_KEYS = {"since", "reason", "replaced_by"}
SOURCE_KEYS = {"kind", "ref", "revision", "checked", "note"}
SOURCE_KINDS = {"netbox-devicetype-library", "datasheet", "manufacturer-page", "argus-export", "other"}
RELATION_VERBS = {"successor-of", "compatible-with", "accessory-of"}
# The device classes in use (the production inventory, 2026-10-31), with spelling variants merged: "switch" and
# "network switch", "host" and "server", "chassi", "controller motor". Adoption maps the old spellings (§6).
# Bench and test instruments (2026-11-05): multimeter, oscilloscope, signal generator, spectrum analyzer.
DEVICE_CLASSES = {"adc", "bpm", "cable", "camera", "chassis", "converter", "desktop computer", "io",
                  "ion pump controller", "laser", "modulator", "monitor", "motion controller", "motor", "multimeter",
                  "nas", "network switch", "oscilloscope", "plasma", "power supply", "rf", "server",
                  "signal generator", "spectrum analyzer", "timing", "vacuum", "vacuum chamber"}
# A description says what the product is. A copied datasheet is not ours to license: facts go in
# `specifications`, and the datasheet is linked.
DESCRIPTION_MAX = 500


class _Report:
    def __init__(self, cid: str):
        self.cid, self.problems = cid, []

    def add(self, file: str, where: str, message: str) -> None:
        self.problems.append(Problem(self.cid, file, where, message))


def _norm_name(name: Any) -> str:
    from app.services.catalogue_mapping import norm
    return norm(str(name or ""))


def code_key(code: Any) -> str:
    """A model code for matching: case, spaces and punctuation do not count, but a `+` does — Libera
    Brilliance and Libera Brilliance+ are two products."""
    return re.sub(r"[^a-z0-9]+", "", str(code or "").lower().replace("+", "plus"))


_norm_code = code_key


def object_types() -> dict[str, tuple[str, bool]]:
    """Every object type the shipped packages define: name -> (package id, abstract)."""
    from app.packages.loader import available
    out = {}
    for pid, p in available().items():
        for t in (p.section("object_types") or {}).get("types") or []:
            out[str(t.get("name"))] = (pid, bool(t.get("abstract", False)))
    return out


def _package_closure(requires: dict[str, str]) -> set[str]:
    """The packages a collection requires, and everything they depend on."""
    from app.packages.loader import available
    shipped, out, todo = available(), set(), list(requires)
    while todo:
        pid = todo.pop()
        if pid in out or pid not in shipped:
            continue
        out.add(pid)
        todo.extend(shipped[pid].depends)
    return out


def _collection_closure(c: Collection, tree: dict[str, Collection]) -> set[str]:
    out, todo = set(), [c.id]
    while todo:
        cid = todo.pop()
        if cid in out or cid not in tree:
            continue
        out.add(cid)
        todo.extend(tree[cid].requires_collections)
    return out


def _check_ranges(r: _Report, ranges: dict[str, str], versions: dict[str, str], what: str) -> None:
    for dep, spec in ranges.items():
        if dep not in versions:
            r.add(MANIFEST, f"requires › {what} › {dep}", f"no {what[:-1]} {dep!r} is shipped")
            continue
        try:
            ok = spec.strip() in ("", "*") or Version(versions[dep]) in SpecifierSet(spec)
        except (InvalidSpecifier, InvalidVersion):
            r.add(MANIFEST, f"requires › {what} › {dep}", f"{spec!r} is not a version range")
            continue
        if not ok:
            r.add(MANIFEST, f"requires › {what} › {dep}", f"needs {spec}, and {versions[dep]} is shipped")


def _sources(r: _Report, e: Entry, where: str) -> None:
    sources = e.data.get("sources")
    if sources is None:
        return
    if not isinstance(sources, list):
        r.add(e.file, f"{where} › sources", "must be a list")
        return
    for i, s in enumerate(sources):
        at = f"{where} › sources[{i}]"
        if not isinstance(s, dict):
            r.add(e.file, at, "must be a mapping")
            continue
        for k in sorted(set(s) - SOURCE_KEYS):
            r.add(e.file, at, f"unknown key {k!r}")
        if s.get("kind") not in SOURCE_KINDS:
            r.add(e.file, at, f"kind must be one of {', '.join(sorted(SOURCE_KINDS))}")
        if not s.get("ref"):
            r.add(e.file, at, "needs a ref: where the value can be checked")


class _AnyModel(set):
    """Every model id: what a tree read in part assumes of the models it did not read."""
    def __contains__(self, item) -> bool:
        return True


def _retired(r: _Report, e: Entry, where: str, model_ids: set[str]) -> None:
    retired = e.data.get("retired")
    if retired is None:
        return
    if not isinstance(retired, dict) or not retired.get("since") or not retired.get("reason"):
        r.add(e.file, f"{where} › retired", "must say since (a version) and reason")
        return
    for k in sorted(set(retired) - RETIRED_KEYS):
        r.add(e.file, f"{where} › retired", f"unknown key {k!r}")
    if retired.get("replaced_by") and retired["replaced_by"] not in model_ids:
        r.add(e.file, f"{where} › retired › replaced_by", f"no model {retired['replaced_by']!r} in the catalogue")


def _specifications(r: _Report, e: Entry, where: str) -> None:
    specs = e.data.get("specifications")
    if specs is None:
        return
    if not isinstance(specs, dict):
        r.add(e.file, f"{where} › specifications", "must map keys to values")
        return
    scalar = (str, int, float, bool)
    for k, v in specs.items():
        at = f"{where} › specifications › {k}"
        if not SPEC_KEY.match(str(k)):
            r.add(e.file, at, "a key is lowercase words joined by _")
        ok = (isinstance(v, scalar) or v is None
              or (isinstance(v, list) and all(isinstance(x, scalar) for x in v))
              or (isinstance(v, dict) and all(SPEC_KEY.match(str(kk)) and isinstance(vv, scalar) for kk, vv in v.items())))
        if not ok:
            r.add(e.file, at, "a value is a number, text, a list of them, or a mapping of them (e.g. {value, unit})")


def _components(r: _Report, e: Entry, where: str) -> None:
    """A model's components (its interfaces, console and power ports, bays…): lists of items, each a mapping of
    plain values, as NetBox writes them."""
    comps = e.data.get("components")
    if comps is None:
        return
    if not isinstance(comps, dict):
        r.add(e.file, f"{where} › components", "must map a kind of component to a list of them")
        return
    scalar = (str, int, float, bool)
    for k, items in comps.items():
        at = f"{where} › components › {k}"
        if not SPEC_KEY.match(str(k)):
            r.add(e.file, at, "a kind is lowercase words joined by _ (interfaces, console_ports…)")
        if not isinstance(items, list) or not all(isinstance(i, dict) and all(isinstance(v, scalar) for v in i.values())
                                                  for i in items):
            r.add(e.file, at, "a list of items, each a mapping of plain values (name, type…)")


def validate_collection(c: Collection, tree: dict[str, Collection]) -> list[Problem]:
    """What is wrong with one collection, given every other one in the tree."""
    from app.packages.loader import available
    r = _Report(c.id)
    r.problems.extend(c.read_problems)
    if not SLUG.match(c.id):
        r.add(MANIFEST, "id", "must be lowercase letters, digits and dashes")
    try:
        Version(c.version)
    except InvalidVersion:
        r.add(MANIFEST, "version", f"{c.version!r} is not a version (e.g. 1.0.0)")
    for key in ("name", "owner", "license", "domain"):
        if not getattr(c, key):
            r.add(MANIFEST, key, "is required")
    for d in c.domains:
        if d != "catalogue" and d not in available():
            r.add(MANIFEST, "domain", f"{d!r} is not a package id (or `catalogue`, for every workspace)")
    if "catalogue" in c.domains and len(c.domains) > 1:
        r.add(MANIFEST, "domain", "`catalogue` is for every workspace: it is not listed with packages")
    _check_ranges(r, c.requires_packages, {pid: p.version for pid, p in available().items()}, "packages")
    _check_ranges(r, c.requires_collections, {cid: o.version for cid, o in tree.items()}, "collections")
    if c.id in c.requires_collections:
        r.add(MANIFEST, "requires › collections", "a collection does not require itself")

    reachable = _collection_closure(c, tree)
    vendor_ids = {v.id for cid in reachable for v in tree[cid].vendors}
    all_models = {m.id for o in tree.values() for m in o.models}
    # A tree with a NetBox library read in part (the running application's) cannot say a model is missing.
    in_part = any(o.partial for o in tree.values())
    if in_part:
        all_models = _AnyModel()
    types, packages = object_types(), _package_closure(c.requires_packages)

    for e in c.vendors:
        where = f"vendors › {e.id or '?'}"
        for k in sorted(set(e.data) - VENDOR_KEYS):
            r.add(e.file, where, f"unknown key {k!r}")
        if not SLUG.match(e.id):
            r.add(e.file, where, "id must be lowercase letters, digits and dashes (e.g. moxa)")
        if not e.data.get("name"):
            r.add(e.file, where, "needs a name")
        if e.data.get("aliases") is not None and not isinstance(e.data["aliases"], list):
            r.add(e.file, f"{where} › aliases", "must be a list")
        if e.data.get("website") and not URL.match(str(e.data["website"])):
            r.add(e.file, f"{where} › website", "must be an http(s) address")
        if e.data.get("country") and not re.match(r"^[A-Z]{2}$", str(e.data["country"])):
            r.add(e.file, f"{where} › country", "an ISO 3166 code, two capital letters (e.g. IT)")
        _sources(r, e, where)
        _retired(r, e, where, all_models)

    for e in c.models:
        d, where = e.data, f"models › {e.id or '?'}"
        for k in sorted(set(d) - MODEL_KEYS):
            r.add(e.file, where, f"unknown key {k!r}")
        m = MODEL_ID.match(e.id)
        if not m:
            r.add(e.file, where, "id must be vendor/model (e.g. moxa/nport-5450)")
        elif m.group(1) != d.get("vendor"):
            r.add(e.file, where, f"the id starts with {m.group(1)!r}, and the vendor is {d.get('vendor')!r}")
        if not d.get("vendor"):
            r.add(e.file, where, "needs a vendor")
        elif d["vendor"] not in vendor_ids:
            r.add(e.file, f"{where} › vendor", f"no vendor {d['vendor']!r} in this collection or one it requires")
        if not d.get("name"):
            r.add(e.file, where, "needs a name")
        if not str(d.get("model_code") or "").strip():
            r.add(e.file, where, "needs a model_code: the manufacturer's designation, which is how a duplicate is found")
        # A NetBox device type carries its identity and physical definition; ARGUS's device class comes from a
        # classification, given to the models people use (docs/netbox-whole-library.md): not required of it.
        if not d.get("device_class"):
            if c.origin != "netbox":
                r.add(e.file, where, "needs a device_class")
        elif d["device_class"] not in DEVICE_CLASSES:
            r.add(e.file, f"{where} › device_class", f"{d['device_class']!r} is not one of: {', '.join(sorted(DEVICE_CLASSES))}")
        if len(str(d.get("description") or "")) > DESCRIPTION_MAX:
            r.add(e.file, f"{where} › description", f"longer than {DESCRIPTION_MAX} characters: put the figures in "
                  "specifications and link the datasheet rather than copy it")
        if d.get("instance_type"):
            t = types.get(str(d["instance_type"]))
            if t is None:
                r.add(e.file, f"{where} › instance_type", f"no object type {d['instance_type']!r} in the packages")
            elif t[1]:
                r.add(e.file, f"{where} › instance_type", f"{d['instance_type']!r} is abstract: units cannot be of it")
            elif t[0] not in packages:
                r.add(e.file, f"{where} › instance_type", f"{d['instance_type']!r} comes from {t[0]!r}: add it to requires › packages")
        for key in ("typical_spares", "former_ids"):
            if d.get(key) is not None and not isinstance(d[key], list):
                r.add(e.file, f"{where} › {key}", "must be a list")
        if d.get("datasheet_url") and not URL.match(str(d["datasheet_url"])):
            r.add(e.file, f"{where} › datasheet_url", "must be an http(s) address")
        if d.get("eol_date") is not None and not isinstance(d["eol_date"], date):
            r.add(e.file, f"{where} › eol_date", "must be a date (YYYY-MM-DD)")
        for i, rel in enumerate(d.get("relations") or []):
            at = f"{where} › relations[{i}]"
            if not isinstance(rel, dict) or set(rel) != {"verb", "model"}:
                r.add(e.file, at, "must be {verb, model}")
                continue
            if rel["verb"] not in RELATION_VERBS:
                r.add(e.file, at, f"verb must be one of {', '.join(sorted(RELATION_VERBS))}")
            if rel["model"] not in all_models:
                r.add(e.file, at, f"no model {rel['model']!r} in the catalogue")
            if rel["model"] == e.id:
                r.add(e.file, at, "a model does not relate to itself")
        _specifications(r, e, where)
        _components(r, e, where)
        if d.get("notes") is not None and not isinstance(d["notes"], str):
            r.add(e.file, f"{where} › notes", "must be text")
        _sources(r, e, where)
        _retired(r, e, where, all_models)

    for e in c.classifications:
        d, where = e.data, f"classifications › {e.id or '?'}"
        for k in sorted(set(d) - CLASSIFICATION_KEYS):
            r.add(e.file, where, f"unknown key {k!r} (a classification holds ARGUS's metadata only)")
        if not MODEL_ID.match(e.id):
            r.add(e.file, where, "id must be vendor/model (e.g. moxa/nport-5450)")
        if not d.get("device_class"):
            r.add(e.file, where, "needs a device_class")
        elif d["device_class"] not in DEVICE_CLASSES:
            r.add(e.file, f"{where} › device_class", f"{d['device_class']!r} is not one of: {', '.join(sorted(DEVICE_CLASSES))}")
        if d.get("instance_type"):
            t = types.get(str(d["instance_type"]))
            if t is None:
                r.add(e.file, f"{where} › instance_type", f"no object type {d['instance_type']!r} in the packages")
            elif t[1]:
                r.add(e.file, f"{where} › instance_type", f"{d['instance_type']!r} is abstract: units cannot be of it")
            elif t[0] not in packages:
                r.add(e.file, f"{where} › instance_type", f"{d['instance_type']!r} comes from {t[0]!r}: add it to requires › packages")
        if d.get("eol_date") is not None and not isinstance(d["eol_date"], date):
            r.add(e.file, f"{where} › eol_date", "must be a date (YYYY-MM-DD)")
        _sources(r, e, where)

    for e in c.moved:
        where = f"moved › {e.id or '?'}"
        for k in sorted(set(e.data) - MOVED_KEYS):
            r.add(e.file, where, f"unknown key {k!r}")
        target = tree.get(str(e.data.get("moved_to") or ""))
        if target is None:
            r.add(e.file, where, f"moved_to {e.data.get('moved_to')!r} is not a collection")
        elif not any(x.id == e.id and x.data.get("transferred_from") == c.id for x in target.entries()):
            r.add(e.file, where, f"{target.id!r} does not carry it with transferred_from: {c.id}")
    for e in c.entries():
        origin = e.data.get("transferred_from")
        if not origin:
            continue
        source = tree.get(str(origin))
        if source is None:
            r.add(e.file, f"{e.kind}s › {e.id}", f"transferred_from {origin!r} is not a collection")
        elif not any(t.id == e.id and t.data.get("moved_to") == c.id for t in source.moved):
            r.add(e.file, f"{e.kind}s › {e.id}", f"{origin!r} has no `moved: {{id: {e.id}, moved_to: {c.id}}}`")
    return r.problems


def validate_tree(tree: dict[str, Collection]) -> dict[str, list[Problem]]:
    """Every collection's own problems, and what is wrong only across them (duplicates)."""
    out = {cid: validate_collection(c, tree) for cid, c in tree.items()}

    def add(c: Collection, e: Entry, message: str) -> None:
        out[c.id].append(Problem(c.id, e.file, f"{e.kind}s › {e.id}", message))

    # A classification belongs to a model another source defines. Only checked when that source is in the tree
    # (ARGUS reading its pinned sources): the catalogue repository's own CI does not have it.
    if any(c.origin == "netbox" for c in tree.values()) and not any(c.partial for c in tree.values()):
        defined = {m.id: c for c in tree.values() for m in c.models}
        for c in tree.values():
            for e in c.classifications:
                owner = defined.get(e.id)
                if owner is None:
                    out[c.id].append(Problem(c.id, e.file, f"classifications › {e.id}",
                                             "no model with this id in any source: nothing to classify"))
                elif owner.origin != "netbox":
                    out[c.id].append(Problem(c.id, e.file, f"classifications › {e.id}",
                                             f"{owner.id} defines this model itself: state its metadata there"))
    seen_class: dict[str, str] = {}
    for c in tree.values():
        for e in c.classifications:
            if e.id in seen_class:
                out[c.id].append(Problem(c.id, e.file, f"classifications › {e.id}",
                                         f"already classified in {seen_class[e.id]!r}: one classification per model"))
            seen_class.setdefault(e.id, c.id)
    seen_ids: dict[str, str] = {}
    vendor_names: dict[str, tuple[str, str]] = {}
    products: dict[tuple[str, str], tuple[str, str]] = {}
    # A manufacturer the NetBox library brought, then stated in an Argus collection (a model of it proposed
    # there): the same id is the same company, and the Argus entry is the one that counts. The library's copy
    # goes when the fork is next regenerated against the Argus vendors.
    netbox_vendors = {v.id for c in tree.values() if c.origin == "netbox" for v in c.vendors}
    argus_vendors = {v.id for c in tree.values() if c.origin != "netbox" for v in c.vendors}
    restated = netbox_vendors & argus_vendors
    for c in tree.values():
        for e in c.entries():
            for ident in [e.id, *(e.data.get("former_ids") or [])]:
                if not ident:
                    continue
                if ident in seen_ids and e.kind == "vendor" and ident in restated:
                    continue
                if ident in seen_ids:
                    add(c, e, f"{ident!r} is already used in {seen_ids[ident]!r}: an id names one thing, everywhere")
                else:
                    seen_ids[ident] = c.id
        for e in c.vendors:
            for name in [e.data.get("name"), *(e.data.get("aliases") or [])]:
                key = _norm_name(name)
                if not key:
                    continue
                other = vendor_names.get(key)
                if other and other[1] != e.id:
                    add(c, e, f"{name!r} is the same company as vendor {other[1]!r} in {other[0]!r}: one manufacturer, one entry")
                else:
                    vendor_names[key] = (c.id, e.id)
        for e in c.models:
            code = _norm_code(e.data.get("model_code"))
            if not code:
                continue
            key = (str(e.data.get("vendor")), code)
            if key in products and products[key][1] != e.id:
                add(c, e, f"the same product as {products[key][1]!r} in {products[key][0]!r} (vendor and model code)")
            else:
                products[key] = (c.id, e.id)
    return out


def compare(previous: dict[str, Collection], current: dict[str, Collection]) -> dict[str, list[Problem]]:
    """A release against the one before: every entry is still there, retired, or transferred with a
    tombstone; and a collection whose content changed has a newer version."""
    out: dict[str, list[Problem]] = {cid: [] for cid in current}
    for cid, before in previous.items():
        now = current.get(cid)
        if now is None:
            out.setdefault(cid, []).append(Problem(cid, MANIFEST, "", "the collection is gone: collections are "
                                                   "never removed; retire or transfer what it holds"))
            continue
        if before.checksum != now.checksum:
            try:
                newer = Version(now.version) > Version(before.version)
            except InvalidVersion:
                newer = True                      # reported by validate_collection
            if not newer:
                out[cid].append(Problem(cid, MANIFEST, "version",
                                        f"the content changed and the version did not go up from {before.version}"))
        kept = {e.id for e in now.entries()}
        tombstones = {e.id for e in now.moved}
        for e in before.entries():
            if e.id not in kept and e.id not in tombstones:
                out[cid].append(Problem(cid, e.file, f"{e.kind}s › {e.id}",
                                        "is no longer in the collection: retire it (`retired:`), transfer it "
                                        "(`moved:` here and `transferred_from:` there), or put it back"))
    return out


def merge(*reports: dict[str, list[Problem]]) -> dict[str, list[Problem]]:
    out: dict[str, list[Problem]] = {}
    for rep in reports:
        for cid, problems in rep.items():
            out.setdefault(cid, []).extend(problems)
    return out


def tree_problems(tree: dict[str, Collection], previous: Optional[dict[str, Collection]] = None) -> dict[str, list[Problem]]:
    return merge(validate_tree(tree), compare(previous, tree)) if previous is not None else validate_tree(tree)
