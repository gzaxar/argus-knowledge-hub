"""From a package as written to the shapes the rest of ARGUS stores: an attribute definition, a type, an
enumeration's options. One place, so a package and the forms agree on what a field is."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.packages.model import Package, option_list


def options_of(spec: dict, option_sets: dict) -> Optional[list[dict]]:
    if spec.get("option_set"):
        return option_list(option_sets.get(spec["option_set"]))
    if spec.get("options") is not None:
        return option_list(spec["options"])
    return None


def attribute(spec: dict, option_sets: dict) -> dict:
    """One attribute definition as schemas store it (the shape the type editor and the forms read)."""
    key = str(spec["key"])
    out = {
        "id": key, "key": key, "name": str(spec.get("name") or key), "type": str(spec.get("type") or "string"),
        "required": bool(spec.get("required", False)), "multiValue": bool(spec.get("multi", False)),
        "unique": bool(spec.get("unique", False)), "readOnly": bool(spec.get("readonly", False)),
        "indexed": bool(spec.get("indexed", False)),
    }
    options = options_of(spec, option_sets)
    if options is not None:
        out["options"] = options
    if spec.get("reference"):
        out["referenceType"] = str(spec["reference"])
        out["includeChildren"] = bool(spec.get("include_children", False))
    if spec.get("regex"):
        out["regex"] = str(spec["regex"])
    if spec.get("unit"):
        out["unit"] = str(spec["unit"])
    return out


def option_sets(packages: Iterable[Package]) -> dict:
    """Named option lists, from these packages (a later one may use an earlier one's)."""
    out: dict = {}
    for p in packages:
        out.update(p.section("option_sets") or {})
    return out


@dataclass
class ObjectType:
    name: str
    parent: Optional[str]
    description: str
    attributes: list
    abstract: bool = False
    aliases: list = field(default_factory=list)
    icon: Optional[str] = None
    behaviors: list = field(default_factory=list)
    map_layer: Optional[str] = None
    locatable: bool = False
    package: str = ""


def object_types(package: Package, sets: dict) -> list[ObjectType]:
    section = package.section("object_types") or {}
    out = []
    for t in section.get("types") or []:
        out.append(ObjectType(
            name=str(t["name"]), parent=t.get("parent"), description=str(t.get("description") or ""),
            attributes=[attribute(a, sets) for a in t.get("attributes") or []], abstract=bool(t.get("abstract")),
            aliases=[str(a) for a in t.get("aliases") or []], icon=t.get("icon"),
            behaviors=[str(b) for b in t.get("behaviors") or []], map_layer=t.get("map_layer"),
            locatable=bool(t.get("locatable", False)), package=package.id))
    return out


@dataclass
class KindSet:
    """A base type (ticket or document) and the kinds under it."""
    base_name: str
    base_description: str
    base_attributes: list
    base_icon: Optional[str]
    kinds: list  # [(name, description or None, icon or None)]


def kind_set(package: Package, section_name: str, sets: dict) -> Optional[KindSet]:
    section = package.section(section_name)
    if not section:
        return None
    base = section.get("base") or {}
    return KindSet(
        base_name=str(base.get("name") or ""), base_description=str(base.get("description") or ""),
        base_attributes=[attribute(a, sets) for a in base.get("attributes") or []], base_icon=base.get("icon"),
        kinds=[(str(k["name"]), k.get("description"), k.get("icon")) for k in section.get("kinds") or []])


def enumerations(package: Package, sets: dict) -> list[dict]:
    out = []
    for e in package.section("enumerations") or []:
        out.append({"key": str(e["key"]), "name": str(e.get("name") or e["key"]),
                    "applies_to": str(e["applies_to"]), "type": str(e.get("type") or "enumeration"),
                    "default": e.get("default"), "options": options_of(e, sets) or []})
    return out
