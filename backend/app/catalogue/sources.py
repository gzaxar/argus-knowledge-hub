"""The catalogue's sources: Git repositories pinned by a lock file, read at exactly that commit
(docs/catalogue-collections.md §A).

    backend/catalogue/sources.lock.yaml

    sources:
      - id: argus
        kind: argus-collections                     # collections in this format, under collections/
        repo: https://github.com/infn-argus/argus-catalogue.git
        ref: v0.1.0                                 # a tag: it must still point at `commit`
        commit: 688a6fb…                            # the full commit: what is read
      - id: netbox
        kind: netbox-devicetype-library
        repo: https://github.com/infn-argus/devicetype-library.git
        ref: infn
        commit: 25e998f…
        select: ["Moxa/NPort-5*", "Basler/*"]        # device-types/<Manufacturer>/<file>, without .yaml ("*": all)
        exclude: ["Some-Maker/*"]                     # optional: left out even when `select` matches
        collection: {id: it-devices, version: 0.1.0, name: …, requires: {…}}

Each repository is fetched into a bare cache (only the pinned commit) and read in one batch with
`git cat-file --batch`; nothing is checked out, and no file of a repository is executed. A NetBox device type
becomes an entry of the collection the lock names: its id is the vendor's id and its slug without the
manufacturer's prefix, its vendor the `argus` source's vendor whose name or alias is its manufacturer — or, when
none is, a vendor of that collection made from the manufacturer itself (its NetBox name, citing its NetBox
folder) — and its physical definition (height, weight, ports, power) its specifications. What ARGUS says about it — device class, the type of its
units, end of life — comes from a `classifications` entry of the `argus` source with the same id.

The result is written once per lock (its checksum names the folder) as ordinary collection files, which
`load_tree` reads and the validator checks over both sources together.

The lock file shipped in the image is the floor. A catalogue maintainer can move a source pinned by a release tag
to a newer release of the same repository from *Administration › Catalogue* (app/catalogue/pins.py): that pin is
kept in the database (`catalogue_pins`) and read here, so a catalogue release needs no ARGUS release. It applies
only while it is newer than the lock's: an ARGUS release that ships a newer pin wins on its own.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml

from app.catalogue.loader import MANIFEST

LOCK = "sources.lock.yaml"
KINDS = ("argus-collections", "netbox-devicetype-library")
SHA = re.compile(r"^[0-9a-f]{40}$")


class SourceProblem(RuntimeError):
    """A source cannot be read as pinned: the person who maintains the lock can act on it."""


def lock_path(base: Optional[Path] = None) -> Path:
    from app.catalogue.loader import catalogue_dir
    return (base or catalogue_dir()) / LOCK


def tag_version(ref: Optional[str]):
    """The version of a release tag (`v0.3.0`), or None for a branch or anything else."""
    from packaging.version import InvalidVersion, Version
    if not ref or not re.fullmatch(r"v\d+(\.\d+){0,2}", str(ref)):
        return None
    try:
        return Version(str(ref)[1:])
    except InvalidVersion:
        return None


def stored_pins() -> dict[str, dict]:
    """The pins a catalogue maintainer set (app/catalogue/pins.py), by source id; none without a database."""
    try:
        from app.db import SessionLocal
        from app.models.catalogue_entry import CataloguePin
        with SessionLocal() as db:
            return {p.source_id: {"ref": p.ref, "commit": p.commit, "pinned_by": p.pinned_by,
                                  "pinned_at": p.pinned_at.isoformat() if p.pinned_at else None,
                                  "previous_ref": p.previous_ref}
                    for p in db.query(CataloguePin).all()}
    except Exception as e:                                 # the command line, CI: no database, the lock alone
        import logging
        logging.getLogger(__name__).debug("catalogue pins not read: %s", e)
        return {}


def _over(source: dict, pin: Optional[dict]) -> dict:
    """The source as pinned: the stored release when it is newer than the lock's, else the lock's."""
    if not pin:
        return source
    newer, shipped = tag_version(pin.get("ref")), tag_version(source.get("ref"))
    if newer is None or shipped is None or newer <= shipped or not SHA.match(str(pin.get("commit") or "")):
        return source
    return {**source, "ref": pin["ref"], "commit": pin["commit"]}


def _is_installations(lock: Path) -> bool:
    try:
        return lock.resolve() == lock_path().resolve()
    except Exception:
        return False


def effective(lock: Optional[Path] = None, pins: Optional[dict[str, dict]] = None) -> list[dict]:
    """The sources read: the lock's, with the installation's stored pins over them (only for its own lock)."""
    lock = lock or lock_path()
    sources = read_lock(lock)
    if pins is None:
        pins = stored_pins() if _is_installations(lock) else {}
    return [_over(s, pins.get(s["id"])) for s in sources]


def releases(source: dict) -> list[dict]:
    """The release tags of a source's repository (`vX.Y.Z`), newest first, each with the commit it points at."""
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", source["repo"]], capture_output=True, timeout=60,
                             check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout.decode()
    except subprocess.CalledProcessError as e:
        raise SourceProblem(f"{source['id']}: its releases cannot be listed: "
                            f"{e.stderr.decode(errors='replace').strip()[:300]}")
    except subprocess.TimeoutExpired:
        raise SourceProblem(f"{source['id']}: its releases cannot be listed: no answer within a minute")
    tags: dict[str, str] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        sha, ref = line.split("\t", 1)
        name = ref[len("refs/tags/"):]
        peeled = name.endswith("^{}")
        name = name[:-3] if peeled else name
        if tag_version(name) is None:
            continue
        if peeled or name not in tags:                     # an annotated tag: the commit, not the tag object
            tags[name] = sha
    return [{"tag": t, "commit": c} for t, c in sorted(tags.items(), key=lambda kv: tag_version(kv[0]), reverse=True)]


def cache_dir() -> Path:
    return Path(os.environ.get("ARGUS_CATALOGUE_CACHE") or "/tmp/argus-catalogue-cache")


def read_lock(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    seen = set()
    for s in sources:
        for k in ("id", "kind", "repo", "commit"):
            if not s.get(k):
                raise SourceProblem(f"{path.name}: a source needs `{k}`")
        if s["kind"] not in KINDS:
            raise SourceProblem(f"{path.name}: {s['id']}: kind is one of {', '.join(KINDS)}")
        if not SHA.match(str(s["commit"])):
            raise SourceProblem(f"{path.name}: {s['id']}: `commit` is a full 40-character commit id")
        if s["id"] in seen:
            raise SourceProblem(f"{path.name}: two sources are called {s['id']!r}")
        seen.add(s["id"])
        if s["kind"] == "netbox-devicetype-library" and not (s.get("select") and s.get("collection")):
            raise SourceProblem(f"{path.name}: {s['id']}: a NetBox source needs `select` and `collection`")
        for k in ("select", "exclude"):
            if s.get(k) is not None and not (isinstance(s[k], list) and all(isinstance(p, str) for p in s[k])):
                raise SourceProblem(f"{path.name}: {s['id']}: `{k}` is a list of patterns")
    if sum(1 for s in sources if s["kind"] == "argus-collections") > 1:
        raise SourceProblem(f"{path.name}: one argus-collections source: the vendors and classifications live there")
    return sources


# --------------------------------------------------------------------------- git, read only

def _git(repo: Path, *args: str, binary: bool = False) -> Any:
    try:
        out = subprocess.run(["git", "--git-dir", str(repo), *args], capture_output=True, timeout=300, check=True,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.CalledProcessError as e:
        raise SourceProblem(f"git {args[0]}: {e.stderr.decode(errors='replace').strip()[:300]}")
    except subprocess.TimeoutExpired:
        raise SourceProblem(f"git {args[0]}: no answer within 5 minutes")
    return out.stdout if binary else out.stdout.decode()


def fetch(source: dict, cache: Path) -> Path:
    """A bare repository holding the pinned commit. A tag (`ref`) must still point at it."""
    repo = cache / f"{source['id']}.git"
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True, capture_output=True)
    commit = source["commit"]
    have = subprocess.run(["git", "--git-dir", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True).returncode == 0
    if not have:
        # The commit and its trees, without the files' contents: the NetBox library is 1 GB, almost all of it rack
        # elevation images, and 14 MB of device types. The files read are fetched by `_fetch_files`.
        _git(repo, "-c", "protocol.version=2", "fetch", "-q", "--depth", "1", "--filter=blob:none", source["repo"], commit)
        for k, v in (("remote.origin.url", source["repo"]), ("remote.origin.promisor", "true"),
                     ("remote.origin.partialclonefilter", "blob:none")):
            _git(repo, "config", k, v)
    ref = source.get("ref")
    if ref and ref.startswith("v"):                    # a release tag: it must not have moved
        lines = _git(repo, "ls-remote", source["repo"], f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}").split("\n")
        pointed = {l.split()[0] for l in lines if l.strip()}
        if pointed and commit not in pointed:
            raise SourceProblem(f"{source['id']}: the tag {ref} no longer points at the pinned commit "
                                f"{commit[:12]}: someone moved it; check the release before pinning again")
    return repo


def _files(repo: Path, commit: str, prefix: str) -> list[str]:
    return [p for p in _git(repo, "ls-tree", "-r", "--name-only", commit, "--", prefix).split("\n") if p]


def _show(repo: Path, commit: str, path: str) -> bytes:
    return _git(repo, "show", f"{commit}:{path}", binary=True)


def _fetch_files(repo: Path, commit: str, paths: list[str], chunk: int = 1000) -> None:
    """Fetch the contents of these files at the commit, in a few requests (a repository fetched without them);
    those already here cost nothing."""
    wanted = set(paths)
    if not wanted:
        return
    tops = sorted({p.split("/")[0] + "/" for p in paths})
    oids = [line.split()[2] for line in _git(repo, "ls-tree", "-r", commit, "--", *tops).split("\n")
            if line.strip() and line.split("\t", 1)[-1] in wanted]
    # Only those missing (a repository fetched whole, or read before, has them): `--missing=print` names them
    # without fetching anything.
    missing = {line[1:] for line in _git(repo, "rev-list", "--objects", "--missing=print", commit, "--", *tops)
               .split("\n") if line.startswith("?")}
    oids = [o for o in oids if o in missing]
    for i in range(0, len(oids), chunk):
        _git(repo, "-c", "protocol.version=2", "fetch", "-q", "--no-write-fetch-head", "--filter=blob:none", "origin",
             *oids[i:i + chunk])


def _show_many(repo: Path, commit: str, paths: list[str]) -> dict[str, bytes]:
    """Many files at the commit, in one `git cat-file --batch` (12,760 NetBox device types in seconds, where one
    `git show` each took minutes)."""
    if not paths:
        return {}
    try:
        out = subprocess.run(["git", "--git-dir", str(repo), "cat-file", "--batch"],
                             input="".join(f"{commit}:{p}\n" for p in paths).encode(), capture_output=True,
                             timeout=300, check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout
    except subprocess.CalledProcessError as e:
        raise SourceProblem(f"git cat-file: {e.stderr.decode(errors='replace').strip()[:300]}")
    except subprocess.TimeoutExpired:
        raise SourceProblem("git cat-file: no answer within 5 minutes")
    result, pos = {}, 0
    for p in paths:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        pos = end + 1
        if len(header) < 3 or header[-1] == b"missing":
            raise SourceProblem(f"{p}: not at {commit[:12]}")
        size = int(header[2])
        result[p] = out[pos:pos + size]
        pos += size + 1                                   # the content, then a newline
    return result


# The C parser when PyYAML has it (12,760 device types parse in seconds rather than half a minute); both are safe.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _selected(name: str, select: list[str], exclude: Optional[list[str]]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in select) and not any(fnmatch.fnmatch(name, p) for p in exclude or [])


def manufacturer_vendor(manufacturer: str, folder: str, commit: str, taken: set[str]) -> dict:
    """A vendor made from a NetBox manufacturer that no ARGUS vendor is (by name or alias): its NetBox name, an id
    from it (not one already taken), and its NetBox folder as source."""
    base = _slug(manufacturer) or _slug(folder) or "vendor"
    vid, n = base, 2
    while vid in taken:
        vid, n = f"{base}-{n}", n + 1
    return {"id": vid, "name": str(manufacturer),
            "sources": [{"kind": "netbox-devicetype-library", "ref": f"device-types/{folder}", "revision": commit[:12]}]}


# --------------------------------------------------------------------------- NetBox device types

def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s).lower())).strip("-")


def _vendor_for(manufacturer: str, vendors: list[dict]) -> Optional[dict]:
    from app.services.catalogue_mapping import norm
    key = norm(manufacturer)
    for v in vendors:
        if key in {norm(n) for n in [v.get("name"), *(v.get("aliases") or [])] if n}:
            return v
    return None


def _count(items: Any) -> int:
    return len(items) if isinstance(items, list) else 0


# A device type's components, as NetBox lists them (schema/components.json): every one is kept, as written.
COMPONENT_LISTS = ("interfaces", "console-ports", "console-server-ports", "power-ports", "power-outlets",
                   "front-ports", "rear-ports", "port-mappings", "module-bays", "device-bays", "inventory-items")
_FIRST_URL = re.compile(r"https?://[^\s)\]>]+")


def _components(doc: dict) -> dict:
    """Each component list of a device type, its items' scalar properties as NetBox writes them."""
    out = {}
    for key in COMPONENT_LISTS:
        items = [{k: v for k, v in i.items() if isinstance(v, (str, int, float, bool))}
                 for i in doc.get(key) or [] if isinstance(i, dict)]
        if items:
            out[key.replace("-", "_")] = items
    return out


def netbox_entry(doc: dict, path: str, commit: str, vendors: list[dict]) -> tuple[Optional[dict], Optional[str]]:
    """A NetBox device type as a catalogue entry (without ARGUS's classification), or why it cannot be one."""
    manufacturer, model, slug = doc.get("manufacturer"), doc.get("model"), doc.get("slug")
    if not (manufacturer and model and slug):
        return None, f"{path}: not a device type (manufacturer, model and slug)"
    vendor = _vendor_for(manufacturer, vendors)
    if vendor is None:
        return None, (f"{path}: no vendor named {manufacturer!r} (or with that alias) in the catalogue: add it to "
                      f"collections/vendors/vendors.yaml")
    prefix = _slug(manufacturer) + "-"
    rest = slug[len(prefix):] if slug.startswith(prefix) else slug
    entry: dict = {"id": f"{vendor['id']}/{rest}", "vendor": vendor["id"], "model_code": str(model),
                   "name": f"{vendor['name']} {model}"}
    if doc.get("part_number"):
        entry["part_number"] = str(doc["part_number"])
    if doc.get("description"):
        entry["description"] = str(doc["description"])[:500]
    if doc.get("comments"):
        # NetBox's notes (Markdown): often the datasheet's link, which is then the model's datasheet.
        entry["notes"] = str(doc["comments"])
        url = _FIRST_URL.search(str(doc["comments"]))
        if url:
            entry["datasheet_url"] = url.group(0).rstrip(".,;")
    spec: dict = {}
    if doc.get("u_height"):
        spec["rack_units"] = doc["u_height"]
        spec["full_depth"] = bool(doc.get("is_full_depth"))
    if doc.get("airflow"):
        spec["airflow"] = doc["airflow"]
    if doc.get("weight") is not None:
        spec["weight"] = {"value": doc["weight"], "unit": doc.get("weight_unit") or "kg"}
    if doc.get("is_powered") is False:
        spec["is_powered"] = False
    if doc.get("subdevice_role"):
        spec["subdevice_role"] = doc["subdevice_role"]
    draws = [p.get("maximum_draw") for p in doc.get("power-ports") or [] if isinstance(p, dict)
             and isinstance(p.get("maximum_draw"), (int, float))]
    if draws:
        spec["maximum_draw_w"] = max(draws)
    interfaces = [i for i in doc.get("interfaces") or [] if isinstance(i, dict)]
    physical = [i for i in interfaces if i.get("type") not in ("virtual", "lag", "bridge")]
    if physical:
        spec["network_ports"] = len(physical)
        kinds: dict[str, int] = {}
        for i in physical:
            kinds[i["type"]] = kinds.get(i["type"], 0) + 1
        spec["interface_types"] = [f"{n} × {t}" if n > 1 else t for t, n in sorted(kinds.items())]
        poe = sorted({i["poe_type"] for i in physical if i.get("poe_mode") == "pd" and i.get("poe_type")})
        if poe:
            spec["poe_powered"] = poe if len(poe) > 1 else poe[0]
    for key, label in (("console-server-ports", "serial_ports"), ("console-ports", "console_ports"),
                       ("power-ports", "power_inputs"), ("power-outlets", "power_outlets")):
        if _count(doc.get(key)):
            spec[label] = _count(doc[key])
    if spec:
        entry["specifications"] = spec
    components = _components(doc)
    if components:
        entry["components"] = components
    entry["sources"] = [{"kind": "netbox-devicetype-library", "ref": path, "revision": commit[:12]}]
    return entry, None


# --------------------------------------------------------------------------- the tree

def _lock_key(sources: list[dict]) -> str:
    return hashlib.sha256(yaml.safe_dump(sources, sort_keys=True).encode()).hexdigest()[:16]


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def materialize(lock: Optional[Path] = None, cache: Optional[Path] = None, sources: Optional[list[dict]] = None
                ) -> Path:
    """The collections of every pinned source, as files in one folder (made once per set of pins). `sources`:
    read these instead of the lock's (a release being checked before it is pinned)."""
    cache = cache or cache_dir()
    if sources is None:
        sources = effective(lock or lock_path())
    out = cache / f"tree-{_lock_key(sources)}"
    if (out / ".complete").exists():
        return out
    work = cache / f".building-{_lock_key(sources)}-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        argus = next((s for s in sources if s["kind"] == "argus-collections"), None)
        vendors: list[dict] = []
        classified: dict[str, dict] = {}
        if argus is not None:
            repo = fetch(argus, cache)
            files = [p for p in _files(repo, argus["commit"], "collections/") if p.endswith((".yaml", ".yml"))]
            _fetch_files(repo, argus["commit"], files)
            read = _show_many(repo, argus["commit"], files)
            for path in files:
                target = work / path[len("collections/"):]
                target.parent.mkdir(parents=True, exist_ok=True)
                content = read[path]
                target.write_bytes(content)
                data = yaml.safe_load(content) if not path.endswith(MANIFEST) else None
                if isinstance(data, dict):
                    vendors += [v for v in data.get("vendors") or [] if isinstance(v, dict)]
                    for c_ in data.get("classifications") or []:
                        if isinstance(c_, dict) and c_.get("id"):
                            classified[str(c_["id"])] = c_
        for s in (s for s in sources if s["kind"] == "netbox-devicetype-library"):
            repo = fetch(s, cache)
            problems, made = [], []
            taken = {str(v.get("id")) for v in vendors}
            wanted = [path for path in _files(repo, s["commit"], "device-types/")
                      if path.endswith((".yaml", ".yml"))
                      and _selected(path[len("device-types/"):].rsplit(".", 1)[0], s["select"], s.get("exclude"))]
            _fetch_files(repo, s["commit"], wanted)
            spec = s["collection"]
            d = work / spec["id"]
            (d / "models").mkdir(parents=True, exist_ok=True)
            # One manufacturer folder at a time, its models written to one file per vendor (models/<vendor>.yaml):
            # every component of 12,760 device types is too much to hold, or to read, at once.
            by_folder: dict[str, list[str]] = {}
            for path in wanted:
                by_folder.setdefault(path.split("/")[1], []).append(path)
            shards: set[str] = set()
            count = 0
            for folder in sorted(by_folder):
                contents = _show_many(repo, s["commit"], by_folder[folder])
                found: dict[str, list[dict]] = {}
                for path in by_folder[folder]:
                    try:
                        doc = yaml.load(contents[path], Loader=_LOADER)
                    except yaml.YAMLError as e:
                        problems.append(f"{path}: not valid YAML ({getattr(e, 'problem', e)})")
                        continue
                    doc = doc if isinstance(doc, dict) else {}
                    manufacturer = doc.get("manufacturer")
                    if manufacturer and _vendor_for(manufacturer, vendors) is None:
                        v = manufacturer_vendor(manufacturer, path.split("/")[1], s["commit"], taken)
                        taken.add(v["id"])
                        vendors.append(v)
                        made.append(v)
                    entry, why = netbox_entry(doc, path, s["commit"], vendors)
                    if why:
                        problems.append(why)
                        continue
                    meta = classified.get(entry["id"], {})
                    for k in ("device_class", "instance_type", "eol_date", "typical_spares", "relations"):
                        if meta.get(k) is not None:
                            entry[k] = meta[k]
                    found.setdefault(entry["vendor"], []).append(entry)
                del contents
                for vid, items in found.items():
                    shard = d / "models" / f"{vid}.yaml"
                    if shard.is_file():                  # a vendor two folders name (an alias)
                        items = (yaml.load(shard.read_text(), Loader=_LOADER) or {}).get("models", []) + items
                    shard.write_text(yaml.dump({"models": sorted(items, key=lambda e: e["id"])},
                                               Dumper=_Dumper, sort_keys=False, allow_unicode=True))
                    shards.add(f"models/{vid}.yaml")
                    count += len(found[vid])
            if problems:
                raise SourceProblem(f"{s['id']}: " + "; ".join(problems))
            if not count:
                raise SourceProblem(f"{s['id']}: `select` matches no device type at {s['commit'][:12]}")
            manifest = {"id": spec["id"], "version": str(spec["version"]),
                        "name": spec.get("name") or spec["id"],
                        "description": f"Device types of {s['repo']} at {s['commit'][:12]}, read by ARGUS.",
                        "domain": spec.get("domain", "catalogue"), "owner": spec.get("owner", "INFN ARGUS"),
                        "license": spec.get("license", "CC0-1.0"), "origin": "netbox",
                        "requires": spec.get("requires") or {},
                        "contents": sorted(shards) + (["vendors.yaml"] if made else [])}
            (d / MANIFEST).write_text(yaml.dump(manifest, Dumper=_Dumper, sort_keys=False))
            if made:
                (d / "vendors.yaml").write_text(yaml.dump({"vendors": sorted(made, key=lambda v: v["id"])},
                                                          Dumper=_Dumper, sort_keys=False, allow_unicode=True))
        (work / ".complete").write_text(yaml.safe_dump(sources))
        shutil.rmtree(out, ignore_errors=True)
        work.rename(out)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return out


def describe(lock: Optional[Path] = None) -> list[dict]:
    """The pins, as the collections page shows them: what is read, what the lock ships, and who moved it."""
    path = lock or lock_path()
    if not path.is_file():
        return []
    pins = stored_pins() if _is_installations(path) else {}
    out = []
    for shipped in read_lock(path):
        s = _over(shipped, pins.get(shipped["id"]))
        moved = s is not shipped
        out.append({"id": s["id"], "kind": s["kind"], "repo": s["repo"], "ref": s.get("ref"), "commit": s["commit"],
                    "select": s.get("select"), "shipped_ref": shipped.get("ref"), "shipped_commit": shipped["commit"],
                    "pinned_in": "administration" if moved else "lock",
                    "pinned_by": pins[s["id"]]["pinned_by"] if moved else None,
                    "pinned_at": pins[s["id"]]["pinned_at"] if moved else None,
                    "releasable": tag_version(shipped.get("ref")) is not None})
    return out
