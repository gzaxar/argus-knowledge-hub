"""Reading catalogue collections from disk: safely (no YAML tags that make objects), noting where each entry is."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

MANIFEST = "collection.yaml"
MANIFEST_KEYS = {"id", "version", "name", "description", "domain", "owner", "license", "requires", "contents",
                 "origin"}
# `classifications`: ARGUS's metadata for a model defined elsewhere (a NetBox device type), by the same id.
SECTIONS = {"vendors", "models", "moved", "classifications"}


@dataclass
class Problem:
    """One thing wrong with a collection: in which file, where in it, and what."""
    collection: str
    file: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.collection}: {self.file}" + (f" › {self.where}" if self.where else "") + f": {self.message}"


@dataclass
class Entry:
    """A vendor or a model as written, with the file it is in."""
    kind: str                      # vendor | model
    data: dict
    file: str

    @property
    def id(self) -> str:
        return str(self.data.get("id") or "")


@dataclass
class Collection:
    id: str
    version: str
    name: str
    domain: str
    owner: str
    license: str
    description: str
    requires_packages: dict[str, str]
    requires_collections: dict[str, str]
    path: Path
    checksum: str
    vendors: list[Entry] = field(default_factory=list)
    models: list[Entry] = field(default_factory=list)
    # Tombstones: an entry that moved to another collection ({id, moved_to}).
    moved: list[Entry] = field(default_factory=list)
    classifications: list[Entry] = field(default_factory=list)
    # The packages whose workspaces its models are for (`domain`: one package id, a list of them, or
    # `catalogue` for every workspace — vendors). `domain` is them joined, for display.
    domains: list[str] = field(default_factory=list)
    read_problems: list[Problem] = field(default_factory=list)
    # Where it came from when not written as collection files: e.g. "netbox" for device types read from a
    # NetBox library at a pinned revision (app/catalogue/sources.py).
    origin: Optional[str] = None

    def entries(self) -> list[Entry]:
        return [*self.vendors, *self.models]

    def summary(self) -> str:
        def n(count: int, word: str) -> str:
            return f"{count} {word}{'' if count == 1 else 's'}" if count else ""
        parts = [n(len(self.vendors), "vendor"), n(len(self.models), "model"), f"{len(self.moved)} moved" if self.moved else "",
                 n(len(self.classifications), "classification")]
        return ", ".join(p for p in parts if p) or "empty"


def catalogue_dir() -> Path:
    """Where this installation's collections are: `ARGUS_CATALOGUE_DIR`, else `backend/catalogue`."""
    configured = os.environ.get("ARGUS_CATALOGUE_DIR")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "catalogue"


def _read(path: Path, cid: str, problems: list[Problem]) -> Optional[dict]:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problems.append(Problem(cid, path.name, where, f"not valid YAML: {getattr(e, 'problem', e)}"))
        return None
    except OSError as e:
        problems.append(Problem(cid, path.name, "", f"cannot be read: {e.strerror or e}"))
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        problems.append(Problem(cid, path.name, "", "must be a mapping of sections"))
        return None
    return data


def _ranges(value: Any, cid: str, where: str, problems: list[Problem]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(Problem(cid, MANIFEST, where, "must map ids to version ranges"))
        return {}
    return {str(k): str(v) for k, v in value.items()}


def load(path: Path | str) -> Collection:
    """A collection as written. Never raises for what is wrong inside it: that is in `read_problems`, and
    `validate` finds the rest."""
    root = Path(path)
    problems: list[Problem] = []
    manifest = _read(root / MANIFEST, root.name, problems) or {}
    cid = str(manifest.get("id") or root.name)
    for key in sorted(set(manifest) - MANIFEST_KEYS):
        problems.append(Problem(cid, MANIFEST, str(key), "unknown key in the manifest"))
    requires = manifest.get("requires") or {}
    if not isinstance(requires, dict) or set(requires) - {"packages", "collections"}:
        problems.append(Problem(cid, MANIFEST, "requires", "may only name `packages` and `collections`"))
        requires = requires if isinstance(requires, dict) else {}
    files = [MANIFEST]
    found: dict[str, list[Entry]] = {"vendors": [], "models": [], "moved": [], "classifications": []}
    contents = manifest.get("contents") or []
    if not isinstance(contents, list):
        problems.append(Problem(cid, MANIFEST, "contents", "must be a list of file names"))
        contents = []
    for entry in contents:
        rel = str(entry)
        target = (root / rel).resolve()
        if root.resolve() not in target.parents or target.suffix not in (".yaml", ".yml"):
            problems.append(Problem(cid, MANIFEST, f"contents › {rel}", "must be a .yaml file inside the collection"))
            continue
        files.append(rel)
        data = _read(target, cid, problems)
        if data is None:
            continue
        for section, items in data.items():
            if section not in SECTIONS:
                problems.append(Problem(cid, rel, str(section), f"unknown section (one of {', '.join(sorted(SECTIONS))})"))
                continue
            if not isinstance(items, list):
                problems.append(Problem(cid, rel, section, "must be a list"))
                continue
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    problems.append(Problem(cid, rel, f"{section}[{i}]", "must be a mapping"))
                    continue
                found[section].append(Entry(section.rstrip("s") if section != "moved" else "moved", item, rel))
    digest = hashlib.sha256()
    for rel in files:
        p = root / rel
        if p.is_file():
            digest.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    raw_domain = manifest.get("domain")
    domains = [str(d) for d in raw_domain] if isinstance(raw_domain, list) else ([str(raw_domain)] if raw_domain else [])
    return Collection(
        id=cid, version=str(manifest.get("version") or ""), name=str(manifest.get("name") or cid),
        domain=", ".join(domains), domains=domains, owner=str(manifest.get("owner") or ""),
        license=str(manifest.get("license") or ""), description=str(manifest.get("description") or ""),
        requires_packages=_ranges(requires.get("packages"), cid, "requires › packages", problems),
        requires_collections=_ranges(requires.get("collections"), cid, "requires › collections", problems),
        path=root, checksum=digest.hexdigest(), vendors=found["vendors"], models=found["models"],
        origin=str(manifest["origin"]) if manifest.get("origin") else None,
        moved=found["moved"], classifications=found["classifications"], read_problems=problems)


# Trees read from the pinned sources, by folder: such a folder is named after its lock's checksum and never
# changes, so it is read once per process (the whole NetBox library takes seconds to read). Collections are
# read-only once loaded.
_MATERIALIZED: dict[str, dict] = {}


def load_tree(root: Path | str | None = None) -> dict[str, Collection]:
    """id -> collection, for every collection directory under `root`. By default, this installation's: the
    sources its lock file pins (app/catalogue/sources.py), read at their commits, or else the collection
    folders in its catalogue directory."""
    base = Path(root) if root is not None else catalogue_dir()
    if root is None:
        from app.catalogue.sources import lock_path, materialize
        if lock_path(base).is_file():
            base = materialize(lock_path(base))
    fixed = (base / ".complete").is_file()
    if fixed and str(base) in _MATERIALIZED:
        return dict(_MATERIALIZED[str(base)])
    out: dict[str, Collection] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if (child / MANIFEST).is_file():
            c = load(child)
            out[c.id] = c
    if fixed:
        _MATERIALIZED[str(base)] = out
        return dict(out)
    return out
