"""What is wrong with a package, said precisely: which file, where in it, what.

Checked: the manifest (id, semantic version, owner, dependencies that exist, are satisfied and do not go in
a circle), every key against what a section may hold (so site data and anything executable has nowhere to
go), duplicate ids, parents that exist and come first, references to types that exist, option sets and
defaults, regular expressions, icons that ship with ARGUS, map layers, workflows' states, and behaviour ids
ARGUS implements.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from app.packages.behaviors import BEHAVIORS
from app.packages.loader import MANIFEST, available
from app.packages.model import Package, Problem

ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ATTRIBUTE_TYPES = {"string", "text", "integer", "float", "boolean", "date", "datetime", "enumeration", "user",
                   "group", "reference"}
ATTRIBUTE_KEYS = {"key", "name", "type", "required", "indexed", "multi", "unique", "readonly", "options",
                  "option_set", "reference", "include_children", "regex", "renamed_from"}
OPTION_KEYS = {"id", "value", "responsible", "meaning"}
TYPE_KEYS = {"name", "parent", "description", "abstract", "aliases", "icon", "behaviors", "map_layer", "locatable",
             "attributes"}
OBJECT_SECTION_KEYS = {"types", "beamline_roots", "former_names"}
KIND_SECTION_KEYS = {"base", "kinds"}
BASE_KEYS = {"name", "description", "icon", "attributes"}
KIND_KEYS = {"name", "description", "icon"}
ENUMERATION_KEYS = {"key", "name", "applies_to", "type", "default", "options", "option_set"}
WORKFLOW_KEYS = {"id", "name", "initial", "default", "states", "transitions"}
STATE_KEYS = {"key", "name", "category"}
STATE_CATEGORIES = {"open", "active", "waiting", "done"}
TRANSITION_KEYS = {"from", "to", "name"}
CLASS_SECTION_KEYS = {"classes", "already_a_type", "unclassified"}
LAYER_KEYS = {"id", "name", "description"}
APPLIES_TO = {"objects", "tickets", "documents"}
ICON_DIR = Path(__file__).resolve().parents[1] / "catalogue_icons"


class _Report:
    def __init__(self, package: Package):
        self.package = package
        self.problems: list[Problem] = list(package.read_problems)

    def add(self, section: Optional[str], where: str, message: str) -> None:
        file = self.package.origin.get(section, MANIFEST) if section else MANIFEST
        self.problems.append(Problem(self.package.id, file, where, message))

    def keys(self, section: str, where: str, value, allowed: set) -> bool:
        if not isinstance(value, dict):
            self.add(section, where, "must be a mapping")
            return False
        for k in sorted(set(value) - allowed, key=str):
            self.add(section, f"{where} › {k}" if where else str(k), "unknown key")
        return True


def _dependencies(package: Package, catalog: dict[str, Package], report: _Report) -> list[Package]:
    """The packages this one stands on, nearest last, checked: they exist, their versions satisfy, no cycle."""
    out: list[Package] = []
    seen: set[str] = set()

    def walk(p: Package, trail: list[str]) -> None:
        for dep_id, spec in p.depends.items():
            if dep_id in trail:
                report.add(None, f"depends › {dep_id}", f"circular dependency: {' → '.join(trail + [dep_id])}")
                continue
            dep = catalog.get(dep_id)
            if dep is None:
                report.add(None, f"depends › {dep_id}", "no such package")
                continue
            try:
                if spec.strip() not in ("", "*") and Version(dep.version) not in SpecifierSet(spec):
                    report.add(None, f"depends › {dep_id}",
                               f"needs {dep_id} {spec}, this installation has {dep.version}")
            except (InvalidSpecifier, InvalidVersion):
                report.add(None, f"depends › {dep_id}", f"not a version range: {spec!r} (e.g. \">=1.0,<2\")")
            if dep_id not in seen:
                seen.add(dep_id)
                walk(dep, trail + [dep_id])
                out.append(dep)

    walk(package, [package.id])
    return out


def _attributes(report: _Report, section: str, where: str, attrs, sets: dict, types: set[str]) -> None:
    if attrs is None:
        return
    if not isinstance(attrs, list):
        report.add(section, where, "attributes must be a list")
        return
    keys: set[str] = set()
    for i, a in enumerate(attrs):
        at = f"{where} › attributes[{i}]"
        if not report.keys(section, at, a, ATTRIBUTE_KEYS):
            continue
        key = a.get("key")
        if not key or not KEY.match(str(key)):
            report.add(section, at, f"key {key!r} must be letters, digits and _")
            continue
        at = f"{where} › {key}"
        if key in keys:
            report.add(section, at, "duplicate attribute key")
        keys.add(key)
        if a.get("renamed_from") is not None and (not KEY.match(str(a["renamed_from"])) or a["renamed_from"] == key):
            report.add(section, at, "renamed_from names the attribute's previous key")
        if a.get("renamed_from") and any(isinstance(b, dict) and b.get("key") == a["renamed_from"] for b in attrs):
            report.add(section, at, f"renamed_from {a['renamed_from']!r} is still an attribute here")
        kind = a.get("type", "string")
        if kind not in ATTRIBUTE_TYPES:
            report.add(section, at, f"unsupported type {kind!r} (one of {', '.join(sorted(ATTRIBUTE_TYPES))})")
        if a.get("options") is not None and a.get("option_set"):
            report.add(section, at, "options and option_set: give one")
        if a.get("option_set") and a["option_set"] not in sets:
            report.add(section, at, f"no option set {a['option_set']!r}")
        if a.get("options") is not None:
            _options(report, section, at, a["options"])
        if kind == "enumeration" and a.get("options") is None and not a.get("option_set"):
            report.add(section, at, "an enumeration needs options or an option_set")
        if kind == "reference":
            target = a.get("reference")
            if not target:
                report.add(section, at, "a reference names the type it points to (reference: <type>)")
            elif target not in types:
                report.add(section, at, f"refers to {target!r}, which no package here defines")
        elif a.get("reference"):
            report.add(section, at, "reference is only for type: reference")
        if a.get("regex"):
            try:
                re.compile(str(a["regex"]))
            except re.error as e:
                report.add(section, at, f"regex does not compile: {e}")


def _options(report: _Report, section: str, where: str, options) -> None:
    if not isinstance(options, list) or not options:
        report.add(section, where, "options must be a non-empty list")
        return
    ids: set[str] = set()
    for i, o in enumerate(options):
        at = f"{where} › options[{i}]"
        if not report.keys(section, at, o, OPTION_KEYS):
            continue
        if not o.get("id") or not o.get("value"):
            report.add(section, at, "an option has an id and a value")
            continue
        if str(o["id"]) in ids:
            report.add(section, at, f"duplicate option id {o['id']!r}")
        ids.add(str(o["id"]))


def _icon(report: _Report, section: str, where: str, icon) -> None:
    if icon is None:
        return
    if not isinstance(icon, str) or not re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+", icon):
        report.add(section, where, f"icon {icon!r} must be <set>/<name>, e.g. tabler/box")
    elif not (ICON_DIR / f"{icon}.svg").is_file():
        report.add(section, where, f"no icon {icon} ships with ARGUS (app/catalogue_icons/{icon}.svg)")


def validate(package: Package, catalog: Optional[dict[str, Package]] = None) -> list[Problem]:
    """Everything wrong with this package, in the context of the packages it depends on. Empty: valid."""
    catalog = dict(catalog if catalog is not None else available())
    catalog.setdefault(package.id, package)
    r = _Report(package)

    if not package.id or not ID.match(package.id):
        r.add(None, "id", f"{package.id!r} must be lower-case words joined by -, e.g. core-facility")
    if package.path.name != package.id:
        r.add(None, "id", f"the package's directory is {package.path.name!r}: it must be named after its id")
    try:
        Version(package.version)
    except InvalidVersion:
        r.add(None, "version", f"{package.version!r} is not a version (e.g. 1.0.0)")
    if not package.owner.strip():
        r.add(None, "owner", "say who answers for the package")
    deps = _dependencies(package, catalog, r)
    stack = deps + [package]

    # What the package and those it stands on define, for references across them.
    sets: dict = {}
    for p in stack:
        sets.update(p.section("option_sets") or {})
    dep_types: dict[str, str] = {}
    dep_layers: set[str] = set()
    dep_behaviors: dict[str, str] = {}
    for p in deps:
        for t in (p.section("object_types") or {}).get("types") or []:
            if isinstance(t, dict) and t.get("name"):
                dep_types[str(t["name"])] = p.id
                for b in t.get("behaviors") or []:
                    dep_behaviors[str(b)] = f"{t['name']} in {p.id}"
        dep_layers |= {str(m.get("id")) for m in p.section("map_layers") or [] if isinstance(m, dict)}

    # option sets
    raw_sets = package.section("option_sets")
    if raw_sets is not None:
        if not isinstance(raw_sets, dict):
            r.add("option_sets", "", "must be a mapping of name → options")
        else:
            for name, options in raw_sets.items():
                _options(r, "option_sets", str(name), options)

    # map layers
    layers = set(dep_layers)
    for i, m in enumerate(package.section("map_layers") or []):
        at = f"map_layers[{i}]"
        if not r.keys("map_layers", at, m, LAYER_KEYS):
            continue
        lid = str(m.get("id") or "")
        if not ID.match(lid):
            r.add("map_layers", at, f"layer id {lid!r} must be lower-case words joined by -")
        elif lid in layers:
            r.add("map_layers", at, f"duplicate layer id {lid!r}")
        layers.add(lid)

    # object types
    objects = package.section("object_types")
    own_types: list[dict] = []
    if objects is not None and r.keys("object_types", "", objects, OBJECT_SECTION_KEYS):
        own_types = [t for t in objects.get("types") or [] if isinstance(t, dict)]
    names = {str(t.get("name")) for t in own_types if t.get("name")} | set(dep_types)
    defined: set[str] = set(dep_types)
    behaviors = dict(dep_behaviors)
    seen_names: set[str] = set()
    for i, t in enumerate((objects or {}).get("types") or [] if isinstance(objects, dict) else []):
        at = f"types[{i}]"
        if not r.keys("object_types", at, t, TYPE_KEYS):
            continue
        name = t.get("name")
        if not name or not isinstance(name, str):
            r.add("object_types", at, "a type has a name")
            continue
        at = name
        if name in seen_names:
            r.add("object_types", at, "duplicate type name")
        elif name in dep_types:
            r.add("object_types", at, f"already defined by {dep_types[name]}")
        seen_names.add(name)
        parent = t.get("parent")
        if parent is not None:
            if parent not in names:
                r.add("object_types", at, f"parent {parent!r} is not defined")
            elif parent not in defined:
                r.add("object_types", at, f"parent {parent!r} is defined later: list parents before children")
        defined.add(name)
        _attributes(r, "object_types", at, t.get("attributes"), sets, names)
        _icon(r, "object_types", at, t.get("icon"))
        for b in t.get("behaviors") or []:
            if b not in BEHAVIORS:
                r.add("object_types", at, f"unsupported behaviour {b!r} (one of {', '.join(BEHAVIORS)})")
            elif BEHAVIORS[b][0] != name:
                r.add("object_types", at, f"behaviour {b!r} is bound to the type {BEHAVIORS[b][0]!r} in this release")
            elif b in behaviors:
                r.add("object_types", at, f"behaviour {b!r} is already {behaviors[b]}")
            else:
                behaviors[b] = name
        if t.get("map_layer") is not None:
            if t["map_layer"] not in layers:
                r.add("object_types", at, f"no map layer {t['map_layer']!r}")
            if not t.get("locatable"):
                r.add("object_types", at, "a map layer is for a locatable type (locatable: true)")
    # a parent chain that loops back
    parent_of = {str(t["name"]): t.get("parent") for t in own_types if t.get("name")}
    for name in parent_of:
        trail, cur = [name], parent_of.get(name)
        while cur is not None and cur in parent_of:
            if cur in trail:
                r.add("object_types", name, f"parents go in a circle: {' → '.join(trail + [cur])}")
                break
            trail.append(cur)
            cur = parent_of.get(cur)
    if isinstance(objects, dict):
        for root in objects.get("beamline_roots") or []:
            if root not in names:
                r.add("object_types", f"beamline_roots › {root}", "not a type")
        for new, old in (objects.get("former_names") or {}).items():
            if new not in names:
                r.add("object_types", f"former_names › {new}", "not a type")

    # ticket and document types
    for section_name in ("ticket_types", "document_types"):
        section = package.section(section_name)
        if section is None or not r.keys(section_name, "", section, KIND_SECTION_KEYS):
            continue
        base = section.get("base")
        if base is not None and r.keys(section_name, "base", base, BASE_KEYS):
            if not base.get("name"):
                r.add(section_name, "base", "the base type has a name")
            _attributes(r, section_name, "base", base.get("attributes"), sets, names)
            _icon(r, section_name, "base", base.get("icon"))
        kinds: set[str] = set()
        for i, k in enumerate(section.get("kinds") or []):
            at = f"kinds[{i}]"
            if not r.keys(section_name, at, k, KIND_KEYS):
                continue
            if not k.get("name"):
                r.add(section_name, at, "a kind has a name")
                continue
            if k["name"] in kinds:
                r.add(section_name, k["name"], "duplicate kind")
            kinds.add(k["name"])
            _icon(r, section_name, k["name"], k.get("icon"))

    # enumerations
    seen_enums: set[tuple] = set()
    for i, e in enumerate(package.section("enumerations") or []):
        at = f"enumerations[{i}]"
        if not r.keys("enumerations", at, e, ENUMERATION_KEYS):
            continue
        at = f"{e.get('applies_to')}.{e.get('key')}"
        if e.get("applies_to") not in APPLIES_TO:
            r.add("enumerations", at, f"applies_to must be one of {', '.join(sorted(APPLIES_TO))}")
        if not e.get("key") or not KEY.match(str(e["key"])):
            r.add("enumerations", at, "a key of letters, digits and _")
        if (e.get("applies_to"), e.get("key")) in seen_enums:
            r.add("enumerations", at, "duplicate enumeration")
        seen_enums.add((e.get("applies_to"), e.get("key")))
        if e.get("option_set") and e["option_set"] not in sets:
            r.add("enumerations", at, f"no option set {e['option_set']!r}")
        options = sets.get(e["option_set"]) if e.get("option_set") else e.get("options")
        if e.get("options") is not None:
            _options(r, "enumerations", at, e["options"])
        if e.get("default") is not None and not any(
                isinstance(o, dict) and str(o.get("id")) == str(e["default"]) for o in options or []):
            r.add("enumerations", at, f"default {e['default']!r} is not one of its options")

    # workflows
    wf_ids: set[str] = set()
    defaults = 0
    for i, w in enumerate(package.section("workflows") or []):
        at = f"workflows[{i}]"
        if not r.keys("workflows", at, w, WORKFLOW_KEYS):
            continue
        at = str(w.get("id") or at)
        if not w.get("id") or not ID.match(str(w["id"])):
            r.add("workflows", at, "a workflow has an id: lower-case words joined by -")
        if w.get("id") in wf_ids:
            r.add("workflows", at, "duplicate workflow id")
        wf_ids.add(w.get("id"))
        defaults += 1 if w.get("default") else 0
        states: set[str] = set()
        for j, s in enumerate(w.get("states") or []):
            sat = f"{at} › states[{j}]"
            if not r.keys("workflows", sat, s, STATE_KEYS):
                continue
            if not s.get("key") or s["key"] in states:
                r.add("workflows", sat, "each state has its own key")
            states.add(s.get("key"))
            if s.get("category") not in STATE_CATEGORIES:
                r.add("workflows", sat, f"category must be one of {', '.join(sorted(STATE_CATEGORIES))}")
        if not states:
            r.add("workflows", at, "a workflow has states")
        if w.get("initial") not in states:
            r.add("workflows", at, f"initial state {w.get('initial')!r} is not one of its states")
        for j, tr in enumerate(w.get("transitions") or []):
            tat = f"{at} › transitions[{j}]"
            if not r.keys("workflows", tat, tr, TRANSITION_KEYS):
                continue
            for end in ("from", "to"):
                if tr.get(end) != "*" and tr.get(end) not in states:
                    r.add("workflows", tat, f"{end} {tr.get(end)!r} is not a state")
    if defaults > 1:
        r.add("workflows", "", "only one workflow can be the default")

    # equipment classes
    classes = package.section("equipment_classes")
    if classes is not None and r.keys("equipment_classes", "", classes, CLASS_SECTION_KEYS):
        listed = [str(c) for c in classes.get("classes") or []]
        if len(set(listed)) != len(listed):
            r.add("equipment_classes", "classes", "a class is listed twice")
        if classes.get("unclassified") and classes["unclassified"] not in listed:
            r.add("equipment_classes", "unclassified", "must be one of the classes")
        for cls, type_name in (classes.get("already_a_type") or {}).items():
            if cls not in listed:
                r.add("equipment_classes", f"already_a_type › {cls}", "not one of the classes")
            if type_name not in names:
                r.add("equipment_classes", f"already_a_type › {cls}", f"no type {type_name!r}")

    # reference relations: each names a reference attribute some type has
    refs = package.section("reference_relations")
    if refs is not None:
        if not isinstance(refs, dict):
            r.add("reference_relations", "", "must be a mapping of attribute key → verb")
        else:
            reference_keys = {a.get("key") for p in stack for t in (p.section("object_types") or {}).get("types") or []
                              if isinstance(t, dict) for a in t.get("attributes") or []
                              if isinstance(a, dict) and a.get("type") == "reference"}
            for key, verb in refs.items():
                if key not in reference_keys:
                    r.add("reference_relations", str(key), "no type has a reference attribute with this key")
                if not isinstance(verb, str) or not verb.strip():
                    r.add("reference_relations", str(key), "the verb is text, e.g. located in")
    return r.problems


def validate_all(packages: Iterable[Package]) -> list[Problem]:
    catalog = {p.id: p for p in packages}
    out: list[Problem] = []
    for p in catalog.values():
        out.extend(validate(p, catalog))
    return out
