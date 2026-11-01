"""GLPI's installed devices matched to catalogue models, through review (docs/catalogue-collections.md §8).

A GLPI sync makes the units, with GLPI's manufacturer and model as text (`manufacturer`, `model`). For each
unit of a workspace that has no `product_model` yet, this proposes the shared catalogue's Product Model that
GLPI's text names:

    exact   the vendor (its name or an alias) and the model code or part number, case, spaces and punctuation
            aside;
    near    the same vendor, and a model code close to GLPI's (a ratio of at least 0.85), or the model's code
            inside GLPI's model text — scored below an exact match.

Two equally good models are no proposal at all: the GLPI model is listed as ambiguous. A proposal is a
`product_model` claim with method `inferred` (rule `match.glpi_model/1`) from the workspace's matcher stream,
with its evidence — GLPI's text, the catalogue id, the kind of match and the score — so it waits in the review
queue until a person accepts or rejects it; nothing is set on a unit by itself. A GLPI model that matches
nothing is listed, with its units, as a candidate for a new catalogue entry.
"""
from __future__ import annotations

import difflib
import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue.validate import code_key
from app.ledger import engine
from app.ledger.engine import ParsedClaim, canonical
from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.catalogue_entry import CatalogueEntry
from app.models.ledger import JobRun
from app.services.catalogue_mapping import catalogue_types, norm

RULE = "match.glpi_model/1"
NEAR = 0.85


def _catalogue(db: Session, catalogue_ws: str) -> list[dict]:
    """The shared Product Models, each with every name its vendor goes by and its codes."""
    model_schema, vendor_schema = catalogue_types(db, catalogue_ws)
    live = select(Asset).where(Asset.workspace_id == catalogue_ws, Asset.deleted_at.is_(None),
                               Asset.record_status.notin_(("Retired", "Merged")))
    vendors = {v.uid: v for v in db.scalars(live.where(Asset.schema_uid == vendor_schema.uid))}
    aliases: dict[str, set[str]] = {}
    for uid, value in db.execute(select(AssetLabel.asset_uid, AssetLabel.value).where(
            AssetLabel.asset_uid.in_(list(vendors)), AssetLabel.type == "alias")):
        aliases.setdefault(uid, set()).add(value)
    ids = {e.record_uid: e.catalogue_id for e in db.scalars(select(CatalogueEntry).where(
        CatalogueEntry.workspace_id == catalogue_ws))}
    out = []
    for m in db.scalars(live.where(Asset.schema_uid == model_schema.uid)):
        a = m.attributes or {}
        vendor = vendors.get(a.get("vendor_ref"))
        names = {a.get("vendor")} | ({vendor.name} | aliases.get(vendor.uid, set()) if vendor else set())
        codes = {code_key(a.get("model_code")), code_key(a.get("part_number"))} - {""}
        if not codes:
            continue
        out.append({"uid": m.uid, "name": m.name, "catalogue_id": ids.get(m.uid),
                    "vendors": {norm(n) for n in names if n and norm(n)}, "codes": codes})
    return out


def _score(model: dict, manufacturer: str, glpi_model: str) -> Optional[tuple[str, float]]:
    if norm(manufacturer) not in model["vendors"]:
        return None
    text = code_key(glpi_model)
    if text in model["codes"]:
        return "exact", 1.0
    best = max(difflib.SequenceMatcher(None, text, c).ratio() for c in model["codes"])
    if best >= NEAR:
        return "near", round(0.9 * best, 3)
    if any(len(c) >= 4 and c in text for c in model["codes"]):
        return "near", 0.8
    return None


def units_to_match(db: Session, workspace_id: str) -> list[Asset]:
    """The workspace's units from GLPI with a manufacturer and a model."""
    return [u for u in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None),
                                                      Asset.attributes["argus_source"].astext == "GLPI")
                                                .order_by(Asset.uid))
            if (u.attributes or {}).get("manufacturer") and (u.attributes or {}).get("model")]


def match(db: Session, workspace_id: str, catalogue_ws: str) -> dict:
    """Propose a model for every GLPI unit that has none; report the ambiguous and the unmatched."""
    models = _catalogue(db, catalogue_ws)
    proposals, ambiguous, unmatched = [], {}, {}
    exact = near = 0
    for u in units_to_match(db, workspace_id):
        a = u.attributes
        key = (str(a["manufacturer"]), str(a["model"]))
        has = a.get("product_model")
        scored = sorted(((s[1], s[0], m) for m in models if (s := _score(m, *key))), key=lambda x: -x[0])
        if has and (not scored or scored[0][2]["uid"] != has):
            continue                    # someone set its model: never proposed over
        if not scored:
            unmatched.setdefault(key, []).append(u.uid)
            continue
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            ambiguous.setdefault(key, sorted({x[2]["catalogue_id"] or x[2]["name"] for x in scored
                                              if x[0] == scored[0][0]}))
            continue
        # A unit whose model is the match (an accepted proposal) keeps its claim, so the next run, which states
        # every proposal again, never withdraws what a person accepted.
        score, kind, model = scored[0]
        exact += kind == "exact"
        near += kind == "near"
        proposals.append({"source_ref": f"uid:{u.uid}", "predicate": "attr:product_model", "value": model["uid"],
                          "method": "inferred", "rule_id": RULE, "confidence": score,
                          "evidence": {"glpi_manufacturer": key[0], "glpi_model": key[1], "match": kind,
                                       "score": score, "catalogue_id": model["catalogue_id"],
                                       "model_name": model["name"]}})
    report = {"proposals": len(proposals), "exact": exact, "near": near,
              "ambiguous": [{"manufacturer": k[0], "model": k[1], "candidates": v} for k, v in sorted(ambiguous.items())],
              "unmatched": [{"manufacturer": k[0], "model": k[1], "units": len(v)}
                            for k, v in sorted(unmatched.items(), key=lambda kv: (-len(kv[1]), kv[0]))]}
    # In a fixed order: the same proposals are the same run, however the database returns the units.
    proposals.sort(key=lambda p: p["source_ref"])
    digest = hashlib.sha256(canonical(proposals).encode()).hexdigest()
    last = db.scalar(select(JobRun).where(JobRun.stage == "catalogue-match", JobRun.scope == workspace_id)
                     .order_by(JobRun.id.desc()).limit(1))
    if last is not None and last.input_digest == digest:
        report["status"] = "unchanged"
        return report
    db.add(JobRun(stage="catalogue-match", stage_version="glpi-match/1", scope=workspace_id, input_digest=digest,
                  status="ran", counts={"proposals": len(proposals), "exact": exact, "near": near}, at=engine.now()))
    db.flush()
    stream = engine.register_stream(db, f"catalogue-match:{workspace_id}", workspace_id, "resolver")
    engine.ingest(db, stream.id, revision=digest[:12], content=canonical(proposals).encode(), observed_at=engine.now(),
                  parser="resolved", cause="catalogue match")
    report["status"] = "ran"
    return report


def unmatched(db: Session, workspace_id: str, catalogue_ws: str) -> list[dict]:
    """What a match run would leave without a proposal (read only)."""
    models = _catalogue(db, catalogue_ws)
    out: dict[tuple, int] = {}
    for u in units_to_match(db, workspace_id):
        key = (str(u.attributes["manufacturer"]), str(u.attributes["model"]))
        if not u.attributes.get("product_model") and not any(_score(m, *key) for m in models):
            out[key] = out.get(key, 0) + 1
    return [{"manufacturer": k[0], "model": k[1], "units": n} for k, n in sorted(out.items(), key=lambda kv: -kv[1])]
