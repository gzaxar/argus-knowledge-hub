"""The definitions ARGUS's seeding reads, from the packages that ship with it (core-facility, accelerator).

Before packages these were Python constants; they are read from the YAML now, compiled once per process.
A package that does not load or validate stops ARGUS from starting with the reason, rather than seeding a
workspace from half a catalogue.
"""
from __future__ import annotations

from functools import lru_cache

from app.packages import compile as c
from app.packages.loader import get
from app.packages.validate import validate

CORE = "core-facility"
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
def _sets() -> dict:
    return c.option_sets([package(CORE), package(ACCELERATOR)])


@lru_cache(maxsize=None)
def object_types() -> tuple:
    return tuple(c.object_types(package(ACCELERATOR), _sets()))


def object_section() -> dict:
    return package(ACCELERATOR).section("object_types") or {}


def reference_relations() -> dict:
    return dict(package(ACCELERATOR).section("reference_relations") or {})


def equipment_classes() -> dict:
    return dict(package(ACCELERATOR).section("equipment_classes") or {})


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
