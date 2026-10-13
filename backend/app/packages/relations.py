"""The typed relations packages declare (`relation_types`): a verb, the types it goes from and to, and what
it means to the causal model (layer, which way a failure flows, what it carries).

A declared verb joins the causal model's semantics and the ledger registry's endpoint rules when ARGUS
starts; asserting one between records of the wrong types is refused (`check`). A verb ARGUS defines itself
is never redefined by a package (the package validator refuses it).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=None)
def declared() -> dict[str, dict]:
    """verb -> its declaration, with the package that declares it."""
    from app.packages import defaults
    from app.packages.loader import available
    out: dict[str, dict] = {}
    for pid in defaults.ordered():
        for x in available()[pid].section("relation_types") or []:
            verb = str(x["verb"]).strip().lower()
            out[verb] = {"id": x["id"], "verb": verb, "package": pid, "description": x.get("description") or "",
                         "from": _names(x.get("from")), "to": _names(x.get("to")), "layer": x.get("layer"),
                         "flows": x.get("flows", "none"), "carries": x.get("carries"),
                         "inverse": x.get("inverse")}
    return out


def _names(value) -> tuple:
    return tuple(value if isinstance(value, list) else [value]) if value is not None else ("*",)


def semantics() -> dict:
    from app.services.causal_model import RelationSemantics
    return {verb: RelationSemantics(d["layer"], d["flows"], d["carries"], note=d["description"])
            for verb, d in declared().items()}


@lru_cache(maxsize=None)
def _descendants() -> dict[str, set]:
    """type name -> itself and every type under it, across the shipped packages."""
    from app.packages import defaults
    children: dict[str, list] = {}
    for t in defaults.object_types():
        children.setdefault(t.parent, []).append(t.name)
    out: dict[str, set] = {}
    for t in defaults.object_types():
        seen, todo = set(), [t.name]
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo += children.get(n, [])
        out[t.name] = seen
    return out


def endpoints() -> dict:
    """verb -> (from rule, to rule) in the ledger registry's form."""
    tree = _descendants()
    out = {}
    for verb, d in declared().items():
        rules = []
        for end in (d["from"], d["to"]):
            rules.append(None if "*" in end else ("in", set().union(*(tree.get(n, {n}) for n in end))))
        out[verb] = tuple(rules)
    return out


def check(db, verb: str, from_schema_uid: Optional[str], to_schema_uid: Optional[str]) -> Optional[str]:
    """What is wrong with relating records of these types by a declared verb, or None (also for verbs no
    package declares). A type counts as any type it is under, workspace types included."""
    d = declared().get((verb or "").strip().lower())
    if d is None:
        return None
    for end, uid, side in (("from", from_schema_uid, "source"), ("to", to_schema_uid, "target")):
        allowed = d[end]
        if "*" in allowed:
            continue
        if not set(_lineage(db, uid)) & set(allowed):
            return f"“{d['verb']}” goes from {', '.join(d['from'])} to {', '.join(d['to'])}: the {side} is not one"
    return None


def _lineage(db, schema_uid: Optional[str]) -> list[str]:
    from app.models.schema import Schema
    out, seen = [], set()
    while schema_uid and schema_uid not in seen:
        seen.add(schema_uid)
        s = db.get(Schema, schema_uid)
        if s is None:
            break
        out.append(s.name)
        schema_uid = s.parent_schema_uid
    return out
