"""The definitions ARGUS's seeding reads, from the packages that ship with it.

Before packages these were Python constants; they are read from the YAML now, compiled once per process.
Object types come from every package that defines some, in dependency order (core-objects first, then the
domains: it, accelerator, electrical, hydraulic, hvac, plant). The accelerator catalogue — what the code
has always called the catalogue — is the accelerator package with everything it stands on.

A package that does not load or validate stops ARGUS from starting with the reason, rather than seeding a
workspace from half a catalogue.
"""
from __future__ import annotations

from functools import lru_cache

from app.packages import compile as c
from app.packages.loader import available, get
from app.packages.validate import validate

CORE = "core-facility"
OBJECTS = "core-objects"
ACCELERATOR = "accelerator"


class PackageError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def package(package_id: str):
    p = get(package_id)
    problems = validate(p)
    if problems:
        raise PackageError(f"package {package_id} is not valid:\n" + "\n".join(f"  {x}" for x in problems))
    return p


@lru_cache(maxsize=None)
def ordered() -> tuple[str, ...]:
    """Every shipped package, each after what it depends on (ties by id, for a stable order)."""
    shipped = available()
    out: list[str] = []

    def visit(pid: str, trail: tuple) -> None:
        if pid in out or pid in trail or pid not in shipped:
            return
        for dep in sorted(shipped[pid].depends):
            visit(dep, trail + (pid,))
        out.append(pid)

    for pid in sorted(shipped):
        visit(pid, ())
    return tuple(out)


def closure(package_id: str) -> tuple[str, ...]:
    """A package and everything it stands on, in dependency order."""
    shipped = available()
    wanted: set[str] = set()

    def walk(pid: str) -> None:
        if pid in wanted or pid not in shipped:
            return
        wanted.add(pid)
        for dep in shipped[pid].depends:
            walk(dep)
    walk(package_id)
    return tuple(p for p in ordered() if p in wanted)


@lru_cache(maxsize=None)
def _sets() -> dict:
    return c.option_sets([package(p) for p in ordered()])


def option_sets() -> dict:
    return dict(_sets())


@lru_cache(maxsize=None)
def object_types_of(package_id: str) -> tuple:
    return tuple(c.object_types(package(package_id), _sets()))


@lru_cache(maxsize=None)
def object_types(package_id: str = "*") -> tuple:
    """Object types, in dependency order: of every shipped package ("*"), or of a package with everything it
    stands on."""
    ids = ordered() if package_id == "*" else closure(package_id)
    return tuple(t for pid in ids for t in object_types_of(pid))


def object_section() -> dict:
    """beamline_roots and former_names, gathered from every package that says any."""
    roots: list = []
    former: dict = {}
    for pid in ordered():
        section = package(pid).section("object_types") or {}
        roots += [r for r in section.get("beamline_roots") or [] if r not in roots]
        former.update(section.get("former_names") or {})
    return {"beamline_roots": roots, "former_names": former}


def reference_relations() -> dict:
    out: dict = {}
    for pid in ordered():
        out.update(package(pid).section("reference_relations") or {})
    return out


def equipment_classes() -> dict:
    """The Other Equipment vocabulary (core-objects), with any classes a domain package adds."""
    out: dict = {"classes": [], "already_a_type": {}}
    for pid in ordered():
        section = package(pid).section("equipment_classes") or {}
        out["classes"] += [x for x in section.get("classes") or [] if x not in out["classes"]]
        out["already_a_type"].update(section.get("already_a_type") or {})
        if section.get("unclassified"):
            out["unclassified"] = section["unclassified"]
    return out


@lru_cache(maxsize=None)
def ticket_types() -> c.KindSet:
    return c.kind_set(package(CORE), "ticket_types", _sets())


@lru_cache(maxsize=None)
def document_types() -> c.KindSet:
    return c.kind_set(package(CORE), "document_types", _sets())


def enumerations() -> list[dict]:
    return c.enumerations(package(CORE), _sets())


def default_workflow() -> dict:
    """The ticket workflow a type without its own follows, in the shape workflows.as_dict gives."""
    flows = package(CORE).section("workflows") or []
    w = next((f for f in flows if f.get("default")), flows[0])
    return {"uid": None, "name": w["name"], "initial": w["initial"], "is_default": True,
            "states": [dict(s) for s in w["states"]],
            "transitions": [{"from": t["from"], "to": t["to"], "name": t["name"]} for t in w["transitions"]]}
