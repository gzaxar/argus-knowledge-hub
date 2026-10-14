"""A package's representative queries (`queries:`), run against its fixtures.

Each query is a question a domain asks of its records, with the records it is asked of (a fixture file in
the package) and the answer expected. They are the package's executable documentation: the tests load every
shipped package's fixtures into a fresh workspace with that package installed, run each query as a person
would (advanced queries through app/services/jql, graph walks over the projected relations, visibility applied), and
compare the keys. A fixture's keys are local to it; in the workspace they are prefixed with its id.

Fixture format (YAML):

    records:   [{key, type, name, attributes, classification}]   # object records
    relations: [{from, verb, to}]                                 # asserted, through the ledger
    tickets:   [{key, kind, title, state, attributes, classification}]
"""
from __future__ import annotations

import uuid
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.packages.model import Package


def fixture(package: Package, name: str) -> dict:
    return yaml.safe_load((package.path / name).read_text(encoding="utf-8")) or {}


def load(db: Session, workspace_id: str, package: Package, name: str, actor: str = "fixture") -> dict[str, str]:
    """Create a fixture's records, relations and tickets in the workspace. Returns local key -> uid."""
    from app.ledger import service
    from app.models.issue import Issue
    from app.packages.install import kind_uid
    from app.services import asset_types
    data = fixture(package, name)
    usable = asset_types.resolve_type_uids(db, workspace_id)
    uids: dict[str, str] = {}
    for r in data.get("records") or []:
        attrs = dict(r.get("attributes") or {})
        for k, v in list(attrs.items()):           # a reference written as a fixture key (or a list of them)
            if isinstance(v, str) and v.startswith("@"):
                attrs[k] = uids[v[1:]]
            elif isinstance(v, list) and any(isinstance(x, str) and x.startswith("@") for x in v):
                attrs[k] = [uids[x[1:]] if isinstance(x, str) and x.startswith("@") else x for x in v]
        if r.get("classification"):
            attrs["classification"] = f"restricted:{r['classification']}"
        if r["type"] not in usable:
            raise KeyError(f"{package.id} fixture {name}: no type {r['type']!r} in the workspace")
        rec = service.create_record(db, workspace_id, actor, uid=str(uuid.uuid4()), key=f"{workspace_id}-{r['key']}",
                                    name=r.get("name") or r["key"], schema_uid=usable[r["type"]],
                                    type_name=r["type"], attributes=attrs)
        uids[r["key"]] = rec.uid
    for rel in data.get("relations") or []:
        service.relate(db, workspace_id, actor, uids[rel["from"]], rel["verb"], uids[rel["to"]], present=True)
    for t in data.get("tickets") or []:
        attrs = dict(t.get("attributes") or {})
        if t.get("classification"):
            attrs["classification"] = f"restricted:{t['classification']}"
        uid = str(uuid.uuid4())
        attrs["argus_source_key"] = f"{workspace_id}-{t['key']}"
        issue = Issue(uid=uid, workspace_id=workspace_id, title=t.get("title") or t["key"],
                      schema_uid=kind_uid(workspace_id, "ticket_types", t["kind"]) if t.get("kind") else None,
                      state="new", attributes=attrs, labels=[])
        db.add(issue)
        db.flush()
        from app.services import workflows        # the state as its workflow has it (a done state closes it)
        workflows.apply_state(issue, workflows.workflow_for(db, workspace_id, issue.schema_uid), t.get("state") or "new")
        uids[t["key"]] = uid
    db.flush()
    return uids


def run(db: Session, workspace_id: str, query: dict, grants=None) -> list[str]:
    """The fixture keys the query returns, in order, as a viewer with these grants sees them."""
    from app.services import visibility
    grants = grants if grants is not None else visibility.Grants.all()
    prefix = f"{workspace_id}-"
    if query["entity"] == "graph":
        keys = _walk(db, workspace_id, query, grants)
    else:
        from app.services import jql
        found = jql.run(db, query["entity"], query["jql"], user_ids=[], workspaces=[workspace_id],
                        current_workspace=workspace_id, visible=lambda r: visibility.can_see(r, grants),
                        grants=grants, limit=500)
        keys = [getattr(r, "key", None) or (r.attributes or {}).get("argus_source_key") for r in found["rows"]]
    return [k[len(prefix):] if k and k.startswith(prefix) else k for k in keys]


def _walk(db: Session, workspace_id: str, query: dict, grants) -> list[str]:
    """Records reached from `from` along `relation` (out: as stored; in: against it), up to `depth` hops,
    sorted by key; a record the viewer may not see is neither returned nor walked through."""
    from app.models.asset import Asset, Relation
    from app.services import visibility
    start = db.scalar(select(Asset).where(Asset.key == f"{workspace_id}-{query['from']}"))
    if start is None:
        return []
    verbs = query["relation"] if isinstance(query["relation"], list) else [query["relation"]]
    outward = query.get("direction", "out") == "out"
    depth = int(query.get("depth") or 1)
    seen, frontier, found = {start.uid}, [start.uid], []
    for _ in range(depth):
        nxt = []
        for uid in frontier:
            col, other = (Relation.from_asset_uid, Relation.to_asset_uid) if outward else \
                (Relation.to_asset_uid, Relation.from_asset_uid)
            for target in db.scalars(select(other).where(col == uid, Relation.relation_type.in_(verbs))):
                if target in seen:
                    continue
                seen.add(target)
                rec = db.get(Asset, target)
                if rec is None or not visibility.asset_visible_in(rec, workspace_id, grants):
                    continue
                found.append(rec.key)
                nxt.append(target)
        frontier = nxt
    return sorted(found)


def shipped_queries(package_ids: Optional[list[str]] = None) -> list[tuple[Package, dict]]:
    from app.packages.loader import available
    out = []
    for p in available().values():
        if package_ids is None or p.id in package_ids:
            out += [(p, q) for q in p.section("queries") or []]
    return out
