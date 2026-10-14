"""The relation registry in warn mode (asset-model-revision §6, §13 S3b).

Every edge is checked against the registry: deprecated verbs, the types
its ends may have, its cardinality (at any instant for derived edges), the
relations that must stay acyclic, and edges to retired or merged records.
In warn mode nothing is refused; the report is what stewards triage, and
the legacy migration's I-MIG-5 compares it before and after a plan.

Only the entries whose constraints are unambiguous are checked; the others
are listed as unchecked so the report says what it did not look at.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.engine import ACCESS_POINT, INSTALLABLE, INSTALLATION
from app.models.asset import Asset, Relation
from app.models.workspace import Workspace

MODE = "warn"
POS = INSTALLABLE
CONTROL = {"Control Device", "IOC"}
NOT_EQUIPMENT = POS | CONTROL | {INSTALLATION, ACCESS_POINT, "Location", "Facility", "Section", "Area",
                                 "Machine Module", "Product Model", "Work Package", "Equipment Port"}
DEPRECATED = {"replaced", "carried by", "on line", "spare for"}


def _beam_elements() -> set:
    from app.services.asset_types import BY_NAME
    out = set()
    for name in BY_NAME:
        cur = name
        while cur is not None and cur != "Beam Element":
            cur = BY_NAME[cur].parent
        if cur == "Beam Element":
            out.add(name)
    return out - {"Beam Element"}


BEAM_ELEMENTS = _beam_elements()

# name: (source rule, target rule); a rule is ("in", types) or ("not in", types) or None.
ENDPOINTS = {
    "installed at": (("in", {INSTALLATION}), ("in", POS)),
    "installation of": (("in", {INSTALLATION}), ("not in", NOT_EQUIPMENT)),
    "realized by": (("in", POS), ("not in", NOT_EQUIPMENT)),
    "assigned to": (("in", {ACCESS_POINT}), ("in", POS)),
    "powers": (("in", POS), ("not in", {INSTALLATION, ACCESS_POINT})),
    "acts on": (("in", CONTROL), ("not in", {INSTALLATION, ACCESS_POINT})),
    "port of": (("in", {"Equipment Port"}), ("not in", NOT_EQUIPMENT - {"Equipment Port"})),
    "runs on": (("in", {"IOC"}), None),
    "part of": (None, ("not in", {"Location"})),
    # The beam model (docs/beam-model.md).
    "branches to": (("in", BEAM_ELEMENTS), ("in", BEAM_ELEMENTS)),
    "closes to": (("in", BEAM_ELEMENTS), ("in", BEAM_ELEMENTS)),
    "observes": (("in", BEAM_ELEMENTS), ("in", {"Observable"})),
    "signal of": (("in", {"Control Signal"}), ("in", CONTROL)),
    "signal for": (("in", {"Control Signal"}), ("not in", {INSTALLATION, ACCESS_POINT, "Control Signal"})),
    "starts at": (("in", {"Beam Path"}), ("in", BEAM_ELEMENTS)),
    "beam of": (("in", {"Particle Beam", "Photon Beam"}), ("in", {"Beam System"})),
    "models": (("in", {"Model Dataset"}), ("in", {"Beam Path", "Beam System"})),
    # argus.beam-model/2: a component on several paths, paths joined by merges and continuations, and the
    # mechanical relations between components (or from a component to the physical support it sits on).
    "placed on": (("in", BEAM_ELEMENTS), ("in", {"Beam Path"})),
    "merges into": (("in", BEAM_ELEMENTS), ("in", BEAM_ELEMENTS)),
    "continues to": (("in", BEAM_ELEMENTS), ("in", BEAM_ELEMENTS)),
    "mounted on": (("in", BEAM_ELEMENTS), ("not in", {INSTALLATION, ACCESS_POINT, "Beam Path", "Beam System"})),
    "contained in": (("in", BEAM_ELEMENTS), ("not in", {INSTALLATION, ACCESS_POINT, "Beam Path", "Beam System"})),
    "fiducial of": (("in", BEAM_ELEMENTS), ("in", BEAM_ELEMENTS)),
    # A model component and a physical asset that is not what implements it (docs/beam-asset-sync.md).
    "measured by": (("in", BEAM_ELEMENTS), ("not in", {INSTALLATION, ACCESS_POINT, "Beam Path", "Beam System"})),
    "associated with": (("in", BEAM_ELEMENTS), ("not in", {INSTALLATION, ACCESS_POINT})),
}
# name: (at most per source, at most per target); None is unbounded.
CARDINALITY = {
    "installed at": (1, None),
    "installation of": (1, None),
    "realized by": (1, 1),
    "assigned to": (1, None),
    "part of": (1, None),
    "composed of": (None, 1),
    "runs on": (1, None),
    "closes to": (1, 1),
    "starts at": (1, None),
    "signal of": (1, None),
    "models": (1, None),
    "mounted on": (1, None),
    "contained in": (1, None),
}
ACYCLIC = {"part of", "composed of", "mounted on", "contained in"}
# Edges that may keep pointing at a retired record (history of the retired thing itself).
RETIRE_EXEMPT_SOURCES = {INSTALLATION}



def _with_extensions() -> None:
    """Endpoint types and cardinality declared by extensions (§13 S8)."""
    from app import extensions
    from app.packages import relations
    ENDPOINTS.update({k: v for k, v in relations.endpoints().items() if k not in ENDPOINTS})
    endpoints, cardinality = extensions.registry_rules()
    ENDPOINTS.update({k: v for k, v in endpoints.items() if k not in ENDPOINTS})
    CARDINALITY.update({k: v for k, v in cardinality.items() if k not in CARDINALITY})


_with_extensions()

def _ok(rule, type_name: str) -> bool:
    if rule is None:
        return True
    op, types = rule
    return type_name in types if op == "in" else type_name not in types


def _gone(a: Asset) -> bool:
    return a.record_status == "Retired" or a.merged_into_uid is not None or a.deleted_at is not None


def report(db: Session, workspace_ids: Iterable[str], detail_limit: int = 200) -> dict:
    ws = list(set(workspace_ids))
    rels = list(db.scalars(select(Relation).join(Asset, Asset.uid == Relation.from_asset_uid)
                           .where(Asset.workspace_id.in_(ws))))
    uids = {r.from_asset_uid for r in rels} | {r.to_asset_uid for r in rels}
    records = {a.uid: a for a in db.scalars(select(Asset).where(Asset.uid.in_(uids)))} if uids else {}
    violations: list[dict] = []

    explained = explanations(db, ws)

    def add(rule: str, r: Optional[Relation], message: str, **extra):
        v = {"rule": rule, "relation": r.relation_type if r else extra.pop("relation", None),
             "from": r.from_asset_uid if r else None, "to": r.to_asset_uid if r else None,
             "message": message, **extra}
        v["id"] = violation_id(v)
        v["explained_by"] = explained.get(v["id"])
        violations.append(v)

    per_source, per_target, graph = Counter(), Counter(), defaultdict(lambda: defaultdict(set))
    for r in rels:
        a, b = records.get(r.from_asset_uid), records.get(r.to_asset_uid)
        if a is None or b is None:
            add("dangling", r, "an end of the relation does not exist")
            continue
        name = r.relation_type
        if name in DEPRECATED or (name == "assigned to" and b.type == "Work Package"):
            add("deprecated", r, f"'{name}' is deprecated: remove it, or replace it with a current relation")
        ends = ENDPOINTS.get(name)
        if ends and not _ok(ends[0], a.type):
            add("source_type", r, f"'{name}' cannot start at type {a.type}")
        if ends and not _ok(ends[1], b.type):
            add("target_type", r, f"'{name}' cannot point to type {b.type}")
        if _gone(b) and not _gone(a) and a.type not in RETIRE_EXEMPT_SOURCES:
            add("retired_end", r, f"'{name}' points to a retired or merged record")
        if name in CARDINALITY:
            per_source[(name, r.from_asset_uid)] += 1
            per_target[(name, r.to_asset_uid)] += 1
        if name in ACYCLIC:
            graph[name][r.from_asset_uid].add(r.to_asset_uid)

    for (name, uid), n in per_source.items():
        limit = CARDINALITY[name][0]
        if limit is not None and n > limit:
            add("cardinality", None, f"{n} '{name}' edges from one record (at most {limit})", relation=name, record=uid)
    for (name, uid), n in per_target.items():
        limit = CARDINALITY[name][1]
        if limit is not None and n > limit:
            add("cardinality", None, f"{n} '{name}' edges to one record (at most {limit})", relation=name, record=uid)

    for name, edges in graph.items():
        seen, on_path = set(), set()

        def visit(u) -> bool:
            if u in on_path:
                return True
            if u in seen:
                return False
            seen.add(u)
            on_path.add(u)
            cyclic = any(visit(v) for v in edges.get(u, ()))
            on_path.discard(u)
            return cyclic

        for start in list(edges):
            if start not in seen and visit(start):
                add("cycle", None, f"'{name}' contains a cycle", relation=name, record=start)

    counts = Counter(v["rule"] for v in violations)
    by_relation = Counter(v["relation"] for v in violations)
    unexplained = [v for v in violations if not v["explained_by"]]
    modes = sorted({m for m in db.scalars(select(Workspace.registry_mode).where(Workspace.id.in_(ws)))})
    violations.sort(key=lambda v: bool(v["explained_by"]))          # what still needs a person first
    return {"mode": modes[0] if len(modes) == 1 else modes, "workspaces": sorted(ws), "relations": len(rels),
            "total": len(violations), "unexplained": len(unexplained),
            "counts": dict(counts), "by_relation": dict(by_relation),
            "checked": sorted(set(ENDPOINTS) | set(CARDINALITY) | ACYCLIC | DEPRECATED),
            "violations": violations[:detail_limit]}


def compare(before: dict, after: dict) -> dict:
    """I-MIG-5: the number of violations must not grow. A rule that grew
    while the total fell is reported, not failed: fixing one kind of edge
    can expose another."""
    rules = set(before.get("counts", {})) | set(after.get("counts", {}))
    grew = {r: [before.get("counts", {}).get(r, 0), after.get("counts", {}).get(r, 0)] for r in sorted(rules)
            if after.get("counts", {}).get(r, 0) > before.get("counts", {}).get(r, 0)}
    return {"ok": after.get("total", 0) <= before.get("total", 0), "before": before.get("total", 0),
            "after": after.get("total", 0), "grew": grew}



# --------------------------------------------------------------------------- enforce mode (§13 S7)

def violation_id(v: dict) -> str:
    import hashlib
    from app.ledger.engine import canonical
    key = [v["rule"], v.get("relation"), v.get("from"), v.get("to"), v.get("record")]
    return hashlib.sha256(canonical(key).encode()).hexdigest()[:24]


def explanations(db: Session, workspace_ids: Iterable[str]) -> dict[str, str]:
    """violation id -> the decision that accepts it as it is (an exception
    the registry's owners agreed to), unless that decision was revoked."""
    from app.ledger import engine
    from app.models.ledger import Decision
    out = {}
    for w in set(workspace_ids):
        ended = engine._ended(db, w)
        for d in db.scalars(select(Decision).where(Decision.workspace_id == w, Decision.kind == "registry_exception")):
            if d.decision_id not in ended:
                out[(d.target or {}).get("violation")] = d.decision_id
    return out


def edge_violations(db: Session, a: Asset, name: str, b: Asset) -> list[str]:
    """What adding the edge a —name→ b would break, given the edges that exist."""
    from app.ledger.engine import SINGLE_RELATIONS
    out = []
    if name in DEPRECATED or (name == "assigned to" and b.type == "Work Package"):
        out.append(f"'{name}' is deprecated")
    ends = ENDPOINTS.get(name)
    if ends and not _ok(ends[0], a.type):
        out.append(f"'{name}' cannot start at type {a.type}")
    if ends and not _ok(ends[1], b.type):
        out.append(f"'{name}' cannot point to type {b.type}")
    if _gone(b) and a.type not in RETIRE_EXEMPT_SOURCES:
        out.append(f"'{name}' cannot point to a retired or merged record")
    if name in CARDINALITY:
        per_source, per_target = CARDINALITY[name]
        existing = list(db.scalars(select(Relation).where(Relation.relation_type == name,
                                                          (Relation.from_asset_uid == a.uid)
                                                          | (Relation.to_asset_uid == b.uid))))
        # A single-valued relation is replaced, not added to.
        from_a = [r for r in existing if r.from_asset_uid == a.uid and r.to_asset_uid != b.uid]
        to_b = [r for r in existing if r.to_asset_uid == b.uid and r.from_asset_uid != a.uid]
        if per_source is not None and f"rel:{name}" not in SINGLE_RELATIONS and len(from_a) + 1 > per_source:
            out.append(f"'{name}' allows {per_source} edge(s) from one record")
        if per_target is not None and len(to_b) + 1 > per_target:
            out.append(f"'{name}' allows {per_target} edge(s) to one record")
    if name in ACYCLIC:
        seen, todo = set(), [b.uid]
        while todo:
            u = todo.pop()
            if u == a.uid:
                out.append(f"'{name}' would close a cycle")
                break
            if u not in seen:
                seen.add(u)
                todo += list(db.scalars(select(Relation.to_asset_uid).where(Relation.from_asset_uid == u,
                                                                            Relation.relation_type == name)))
    return out


def enforce_decision(db: Session, record: Asset, item: dict) -> None:
    """In an enforce-mode workspace a decision that asserts a new edge must
    satisfy the registry (I-REG)."""
    from app.ledger.engine import InvariantError, resolve_ref
    predicate = item.get("predicate") or ""
    if not predicate.startswith("rel:"):
        return
    w = db.get(Workspace, record.workspace_id)
    if w is None or w.registry_mode != "enforce":
        return
    value, member = item.get("value"), item.get("member")
    if isinstance(value, dict) and value.get("ref"):
        ref = value["ref"]
    elif value == "present" and member:
        ref = member
    else:
        return                                   # removing an edge never breaks the registry
    target_uid = resolve_ref(db, ref)
    target = db.get(Asset, target_uid) if target_uid else None
    if target is None:
        return
    problems = edge_violations(db, record, predicate[4:], target)
    if problems:
        raise InvariantError("I-REG", f"the relation registry is enforced here: {'; '.join(problems)}")
