"""Reading packages from disk: safely (no YAML tags that make objects), and noting where everything came from."""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from app.packages.model import Package, Problem

MANIFEST = "package.yaml"
MANIFEST_KEYS = {"id", "version", "name", "description", "owner", "depends", "provides", "contents", "license"}
SECTIONS = {"option_sets", "enumerations", "object_types", "ticket_types", "document_types", "workflows",
            "equipment_classes", "reference_relations", "map_layers"}


def packages_dir() -> Path:
    """Where this installation's packages are: `ARGUS_PACKAGES_DIR`, else `backend/packages`."""
    configured = os.environ.get("ARGUS_PACKAGES_DIR")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "packages"


def _read(path: Path, package: str, problems: list[Problem]) -> Optional[dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problems.append(Problem(package, path.name, where, f"not valid YAML: {getattr(e, 'problem', e)}"))
        return None
    except OSError as e:
        problems.append(Problem(package, path.name, "", f"cannot be read: {e.strerror or e}"))
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        problems.append(Problem(package, path.name, "", "must be a mapping of sections"))
        return None
    return data


def load(path: Path | str) -> Package:
    """A package as written. Never raises for what is wrong inside it: that is in `read_problems`, and
    `validate` finds the rest."""
    root = Path(path)
    problems: list[Problem] = []
    name = root.name
    manifest = _read(root / MANIFEST, name, problems) or {}
    pid = str(manifest.get("id") or name)
    for key in sorted(set(manifest) - MANIFEST_KEYS):
        problems.append(Problem(pid, MANIFEST, key, "unknown key in the manifest"))
    files = [MANIFEST]
    sections: dict = {}
    origin: dict = {}
    contents = manifest.get("contents") or []
    if not isinstance(contents, list):
        problems.append(Problem(pid, MANIFEST, "contents", "must be a list of file names"))
        contents = []
    for entry in contents:
        rel = str(entry)
        target = (root / rel).resolve()
        if root.resolve() not in target.parents or target.suffix not in (".yaml", ".yml"):
            problems.append(Problem(pid, MANIFEST, f"contents › {rel}", "must be a .yaml file inside the package"))
            continue
        files.append(rel)
        data = _read(target, pid, problems)
        if data is None:
            continue
        for section, content in data.items():
            if section not in SECTIONS:
                problems.append(Problem(pid, rel, str(section), "unknown section"))
                continue
            if section in sections:
                problems.append(Problem(pid, rel, section, f"already defined in {origin[section]}"))
                continue
            sections[section] = content
            origin[section] = rel
    digest = hashlib.sha256()
    for rel in files:
        p = root / rel
        if p.is_file():
            digest.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    depends = manifest.get("depends") or {}
    provides = manifest.get("provides") or []
    return Package(
        id=pid, version=str(manifest.get("version") or ""), name=str(manifest.get("name") or pid),
        description=str(manifest.get("description") or ""), owner=str(manifest.get("owner") or ""),
        depends={str(k): str(v) for k, v in depends.items()} if isinstance(depends, dict) else {},
        provides=[str(p) for p in provides] if isinstance(provides, list) else [],
        path=root, checksum=digest.hexdigest(), sections=sections, origin=origin, read_problems=problems)


@lru_cache(maxsize=8)
def _available(directory: str) -> dict[str, Package]:
    out: dict[str, Package] = {}
    root = Path(directory)
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir()):
        if (child / MANIFEST).is_file():
            p = load(child)
            out[p.id] = p
    return out


def available() -> dict[str, Package]:
    """id -> package, for every package this installation ships."""
    return _available(str(packages_dir()))


def get(package_id: str) -> Package:
    try:
        return available()[package_id]
    except KeyError:
        raise KeyError(f"no package {package_id!r} in {packages_dir()}") from None


def reload() -> None:
    _available.cache_clear()
