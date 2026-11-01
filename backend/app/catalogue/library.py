"""The models of the pinned sources as a library to search and install from, one at a time
(docs/netbox-whole-library.md, N2b).

* **The index** is what a search needs and nothing more — catalogue id, vendor, model code, name, part number,
  collection and its domains — read from the folder the sources were materialized into (which never changes:
  its name is its lock's checksum), once per process. The whole NetBox library is a few MB here, where the full
  tree is about 220 MB; the full tree is read only to preview or install a collection.
* **Search** answers the models installed in the catalogue first, then the library's models not yet installed,
  best first (the model code exactly, then at the start, then inside it, then the name). A workspace is offered
  the models of its domains (docs/system-catalogue.md, C4) unless it asks for every model.
* **Installing one** goes through the collection installer's own entry (`install._Run.entry`): its vendor first
  when the catalogue does not have it, then the model, through the ledger, with its catalogue id. An existing
  record that looks like it is never overwritten: the install stops and names it, to be chosen instead. The
  collection is recorded as partly installed (its domains kept), which never counts as installed: a later full
  install still runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue.loader import MANIFEST, Collection, Entry
from app.catalogue.validate import code_key

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_INDEX: dict[str, "Index"] = {}


@dataclass(frozen=True)
class Item:
    catalogue_id: str
    vendor: str
    vendor_name: str
    model_code: str
    name: str
    part_number: Optional[str]
    collection: str
    file: str

    @property
    def key(self) -> str:
        return code_key(self.model_code)


@dataclass
class Index:
    root: Path
    items: list[Item]
    collections: dict[str, dict]                # id -> {version, checksum?, domains, origin, path}


class LibraryProblem(ValueError):
    def __init__(self, message: str, candidate: Optional[dict] = None):
        super().__init__(message)
        self.candidate = candidate


def _read(path: Path) -> dict:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER) or {}
    except (OSError, yaml.YAMLError):
        return {}


def index(root: Optional[Path] = None) -> Index:
    """The library of the installation's pinned sources (or of `root`), read once per folder."""
    if root is None:
        from app.catalogue.loader import catalogue_dir
        from app.catalogue.sources import lock_path, materialize
        base = catalogue_dir()
        root = materialize(lock_path(base)) if lock_path(base).is_file() else base
    key = str(root)
    fixed = (Path(root) / ".complete").is_file()
    if fixed and key in _INDEX:
        return _INDEX[key]
    # A folder that never changes keeps its index beside it, so a new process reads a few MB of JSON instead of
    # parsing the collections again (the NetBox library's models file is 5.5 MB of YAML, a 220 MB peak to parse).
    saved = Path(root) / ".library-index.json"
    if fixed and saved.is_file():
        import json
        try:
            data = json.loads(saved.read_text(encoding="utf-8"))
            out = Index(Path(root), [Item(*i) for i in data["items"]],
                        {cid: {**c, "path": Path(root) / c["path"]} for cid, c in data["collections"].items()})
            _INDEX[key] = out
            return out
        except (OSError, ValueError, KeyError, TypeError):
            pass
    vendor_names: dict[str, str] = {}
    collections: dict[str, dict] = {}
    raw: list[tuple[dict, str, str]] = []
    for child in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        manifest = _read(child / MANIFEST)
        if not manifest.get("id"):
            continue
        cid = str(manifest["id"])
        d = manifest.get("domain")
        collections[cid] = {"version": str(manifest.get("version") or ""), "origin": manifest.get("origin"),
                            "domains": [str(x) for x in d] if isinstance(d, list) else ([str(d)] if d else []),
                            "path": child}
        for rel in manifest.get("contents") or []:
            data = _read(child / str(rel))
            for v in data.get("vendors") or []:
                if isinstance(v, dict) and v.get("id"):
                    vendor_names[str(v["id"])] = str(v.get("name") or v["id"])
            for m in data.get("models") or []:
                if isinstance(m, dict) and m.get("id"):
                    raw.append((m, cid, str(rel)))
    items = [Item(str(m["id"]), str(m.get("vendor") or ""), vendor_names.get(str(m.get("vendor") or ""), str(m.get("vendor") or "")),
                  str(m.get("model_code") or ""), str(m.get("name") or m["id"]),
                  str(m["part_number"]) if m.get("part_number") else None, cid, rel) for m, cid, rel in raw]
    out = Index(Path(root), items, collections)
    if fixed:
        _INDEX[key] = out
        import json
        try:
            tmp = saved.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "items": [[i.catalogue_id, i.vendor, i.vendor_name, i.model_code, i.name, i.part_number, i.collection, i.file]
                          for i in items],
                "collections": {cid: {**{k: v for k, v in c.items() if k != "path"}, "path": c["path"].name}
                                for cid, c in collections.items()}}), encoding="utf-8")
            tmp.replace(saved)
        except OSError:
            pass                                       # read-only: built again by the next process
    return out


# --------------------------------------------------------------------------- search

def _rank(q: str, words: list[str], code: str, text: str) -> Optional[int]:
    if q and code == q:
        return 0
    if q and code.startswith(q):
        return 1
    if q and q in code:
        return 2
    if words and all(w in text for w in words):
        return 3
    return None


def search(db: Session, q: str, *, workspace_id: Optional[str] = None, every: bool = False, limit: int = 30,
           lib: Optional[Index] = None) -> dict:
    """The models installed in the catalogue, then the library's not yet installed, that match `q`: best first.
    For a workspace, those of its domains only, unless `every`."""
    from app.catalogue.install import catalogue_workspace, entries
    from app.catalogue.system import offered
    from app.models.asset import Asset
    from app.services.catalogue_mapping import catalogue_types
    q = (q or "").strip()
    qk = code_key(q)
    words = [w for w in q.lower().split() if w]
    if len(qk) < 2:                                   # a letter matches everything: two at least
        return {"installed": [], "library": [], "more": False}
    cat = catalogue_workspace(db)
    if cat is None:
        return {"installed": [], "library": [], "more": False}
    model_schema, _ = catalogue_types(db, cat)
    rows = entries(db, cat)
    by_record = {r.record_uid: r for r in rows.values()}
    hidden: set[str] = set()
    packages: set[str] = set()
    filtering = bool(workspace_id and not every)
    if filtering:
        o = offered(db, workspace_id)
        hidden, packages = set(o["hidden"]), set(o["packages"])

    found = []
    for a in db.scalars(select(Asset).where(Asset.workspace_id == cat, Asset.schema_uid == model_schema.uid,
                                            Asset.deleted_at.is_(None), Asset.record_status.notin_(("Merged", "Retired")))):
        if a.uid in hidden:
            continue
        attrs = a.attributes or {}
        text = " ".join(str(x or "") for x in (a.name, attrs.get("model_code"), attrs.get("vendor"),
                                                 attrs.get("part_number"), a.key)).lower()
        r = _rank(qk, words, code_key(attrs.get("model_code")), text)
        if r is None:
            r = 3 if qk and qk in code_key(attrs.get("part_number")) else None
        if r is not None:
            e = by_record.get(a.uid)
            found.append((r, a.name.lower(), {"uid": a.uid, "key": a.key, "name": a.name, "vendor": attrs.get("vendor"),
                                              "model_code": attrs.get("model_code"),
                                              "catalogue_id": e.catalogue_id if e else None}))
    found.sort(key=lambda x: (x[0], x[1]))

    lib = lib or index()
    have = set(rows)
    # A library model that is a model already here (the same vendor and model code, a record made before the
    # catalogue had it) is not offered twice: the record is.
    from app.services.catalogue_mapping import norm
    here = {(norm(x["vendor"]), code_key(x["model_code"])) for _, _, x in found}
    here |= {(norm((a.attributes or {}).get("vendor")), code_key((a.attributes or {}).get("model_code")))
             for a in db.scalars(select(Asset).where(Asset.workspace_id == cat, Asset.schema_uid == model_schema.uid,
                                                     Asset.deleted_at.is_(None)))}
    hits = []
    for it in lib.items:
        if it.catalogue_id in have or (norm(it.vendor_name), it.key) in here:
            continue
        domains = lib.collections.get(it.collection, {}).get("domains") or []
        if filtering and domains and "catalogue" not in domains and not (packages & set(domains)):
            continue
        r = _rank(qk, words, it.key, f"{it.vendor_name} {it.model_code} {it.name} {it.part_number or ''}".lower())
        if r is None and qk and it.part_number and qk in code_key(it.part_number):
            r = 3
        if r is not None:
            hits.append((r, it.name.lower(), it))
    hits.sort(key=lambda x: (x[0], x[1]))
    room = max(limit - len(found), 0)
    return {"installed": [x[2] for x in found[:limit]],
            "library": [{"catalogue_id": it.catalogue_id, "name": it.name, "vendor": it.vendor_name,
                         "model_code": it.model_code, "part_number": it.part_number, "collection": it.collection,
                         "source": "netbox" if lib.collections.get(it.collection, {}).get("origin") == "netbox"
                         else "argus"} for _, _, it in hits[:room]],
            "more": len(found) + len(hits) > limit}


# --------------------------------------------------------------------------- installing one

def _collection(lib: Index, cid: str) -> Collection:
    """The collection, without its entries: what the installer needs to name the release."""
    from app.catalogue.loader import load
    c = load(lib.collections[cid]["path"]) if lib.collections[cid].get("origin") != "netbox" else None
    if c is not None:
        return c
    # A NetBox collection is large: only its manifest and checksum, not its 12,760 entries.
    import hashlib
    path: Path = lib.collections[cid]["path"]
    digest = hashlib.sha256()
    manifest = _read(path / MANIFEST)
    for rel in [MANIFEST, *(manifest.get("contents") or [])]:
        p = path / str(rel)
        if p.is_file():
            digest.update(str(rel).encode() + b"\0" + p.read_bytes() + b"\0")
    d = manifest.get("domain")
    domains = [str(x) for x in d] if isinstance(d, list) else ([str(d)] if d else [])
    return Collection(id=cid, version=str(manifest.get("version") or ""), name=str(manifest.get("name") or cid),
                      domain=", ".join(domains), domains=domains, owner=str(manifest.get("owner") or ""),
                      license=str(manifest.get("license") or ""), description=str(manifest.get("description") or ""),
                      requires_packages=dict((manifest.get("requires") or {}).get("packages") or {}),
                      requires_collections=dict((manifest.get("requires") or {}).get("collections") or {}),
                      path=path, checksum=digest.hexdigest(), origin=manifest.get("origin"))


def _entry(lib: Index, cid: str, kind: str, eid: str) -> Optional[Entry]:
    manifest = _read(lib.collections[cid]["path"] / MANIFEST)
    for rel in manifest.get("contents") or []:
        for item in _read(lib.collections[cid]["path"] / str(rel)).get(f"{kind}s") or []:
            if isinstance(item, dict) and str(item.get("id")) == eid:
                return Entry(kind, item, str(rel))
    return None


def install_one(db: Session, catalogue_id: str, *, actor: str, lib: Optional[Index] = None) -> dict:
    """Install one model of the library (and its vendor, when the catalogue does not have it). The caller
    commits. Returns the model's record."""
    from app.catalogue import install as inst
    from app.models.catalogue_entry import CatalogueInstallation
    from app.models.asset import Asset
    lib = lib or index()
    cat = inst.catalogue_workspace(db)
    if cat is None:
        raise LibraryProblem("this installation has no catalogue")
    rows = inst.entries(db, cat)
    if catalogue_id in rows:
        a = db.get(Asset, rows[catalogue_id].record_uid)
        return {"uid": a.uid, "key": a.key, "name": a.name, "installed": False}
    item = next((it for it in lib.items if it.catalogue_id == catalogue_id), None)
    if item is None:
        raise LibraryProblem(f"no model {catalogue_id!r} in the catalogue's sources at their pinned commits")
    c = _collection(lib, item.collection)
    inst._check_packages(db, cat, c)
    run = inst._Run(db, cat, actor, {}, apply=True)
    if item.vendor not in run.vendor_uids:
        vendor_home = next((cid for cid in lib.collections if _entry(lib, cid, "vendor", item.vendor)), None)
        if vendor_home is None:
            raise LibraryProblem(f"{catalogue_id}: its vendor {item.vendor!r} is in no source")
        vc = c if vendor_home == item.collection else _collection(lib, vendor_home)
        ve = _entry(lib, vendor_home, "vendor", item.vendor)
        run.vendor_entries[ve.id] = ve
        # A vendor record already here by the same name is that company: linked, keeping its own values (as
        # "Link all matching vendors" does on a preview).
        run.decisions[ve.id] = {"action": "link", "fields": {k: "local" for k in run.vendor_keys | {"name", "aliases"}}}
        done = run.entry(vc, ve)
        if done.needs_decision:
            raise LibraryProblem(f"the vendor {ve.data.get('name')} may be {done.record_name}, already here: a "
                                 f"catalogue maintainer links it or creates it on Administration › Catalogue",
                                 {"uid": done.record_uid, "name": done.record_name})
        _partial(db, cat, vc, actor, ve.id)
    else:
        ve = _entry(lib, next((cid for cid in lib.collections if _entry(lib, cid, "vendor", item.vendor)), item.collection),
                    "vendor", item.vendor)
        if ve is not None:
            run.vendor_entries[ve.id] = ve
    me = _entry(lib, item.collection, "model", catalogue_id)
    done = run.entry(c, me)
    if done.needs_decision:
        raise LibraryProblem(f"{done.record_name} is already here and looks like {item.name}: choose it instead "
                             f"(a catalogue maintainer can link the two)", {"uid": done.record_uid, "name": done.record_name})
    _partial(db, cat, c, actor, catalogue_id)
    db.flush()
    a = db.get(Asset, done.record_uid)
    return {"uid": a.uid, "key": a.key, "name": a.name, "installed": True}


def _partial(db: Session, cat: str, c: Collection, actor: str, catalogue_id: str) -> None:
    from app.models.catalogue_entry import CatalogueInstallation
    db.add(CatalogueInstallation(workspace_id=cat, collection_id=c.id, from_version=None, version=c.version,
                                 checksum=c.checksum, installed_by=actor, domains=list(c.domains) or None,
                                 result={"partial": True, "entries": [catalogue_id]}))
    db.flush()
