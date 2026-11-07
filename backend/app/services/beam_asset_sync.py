"""Beamline asset synchronization (docs/beam-asset-sync.md): matching a beam model's components to the
physical assets the hub knows, proposing bindings, and recording what people decide.

    preview   run the matcher against the workspace's physical assets and the bindings already known;
              writes nothing
    apply     record decisions: accept (confirm) chosen proposals — or every auto-acceptable one — reject
              others, keep proposals for review; a confirmed `implemented_by` binding is also an
              Installation, so the position's equipment, power, controls, documents and history follow
    status    the summary: confirmed, proposed, ambiguous, unmatched, rejected, by family
    bindings  every binding with its status, authority, evidence and provenance

Confirmed bindings are never replaced by a later sync: differences (asset gone, renamed, moved, a better
candidate) are reported for a person to act on. Rejected pairs are never proposed again. Auto-acceptance
happens only when configured (`ARGUS_BEAM_ASSET_SYNC_AUTO=accept_high_confidence`) and then only for
proposals the matcher marks auto-acceptable; those bindings say `authority: auto_accepted`.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.beam_model_core import matching as M
from app.beam_model_core.schema import Document
from app.ledger import engine
from app.models.asset import Asset, Relation
from app.models.beam_model import BeamAssetBinding
from app.services import beam_model_v2 as v2

RELATION_PREDICATE = {"mounted_on": "mounted on", "contained_in": "contained in", "measured_by": "measured by",
                      "associated_with": "associated with"}


class SyncError(ValueError):
    pass


def _physical_types() -> set[str]:
    """The catalogue's physical plane: everything under Asset (magnets, instruments, valves, supports…)."""
    from app.services.asset_types import BY_NAME
    out = set()
    for name in BY_NAME:
        cur = name
        while cur is not None and cur != "Asset":
            cur = BY_NAME[cur].parent
        if cur == "Asset":
            out.add(name)
    return out


def candidate_assets(db: Session, workspace_id: str) -> list[dict]:
    """The workspace's physical assets as the matcher reads them: name, type, aliases, attributes (beamline,
    s, x/y/z, lattice or control name, component type, family) and the places it is in."""
    types = _physical_types()
    rows = list(db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.type.in_(types))))
    uids = [a.uid for a in rows]
    places: dict[str, list[str]] = {}
    if uids:
        for r in db.scalars(select(Relation).where(Relation.from_asset_uid.in_(uids),
                                                   Relation.relation_type.in_(("located in", "part of")))):
            t = db.get(Asset, r.to_asset_uid)
            if t is not None and t.name:
                places.setdefault(r.from_asset_uid, []).append(t.name)
    out = []
    for a in rows:
        attrs = {k: v for k, v in (a.attributes or {}).items() if not k.startswith("argus_")}
        out.append({"id": a.uid, "name": a.name, "type": a.type, "aliases": list(attrs.get("aliases") or []),
                    "attributes": attrs, "locations": places.get(a.uid, []),
                    "retired": a.deleted_at is not None or a.record_status in ("Retired", "Merged")})
    return out


def _component_uids(db: Session, workspace_id: str, model_id: str) -> dict[str, str]:
    """A model's components by their id in it, from the import's identity bindings (not from their keys, which
    follow the workspace's Record keys pattern)."""
    from app.services.beam_model import model_ids
    live = {a.uid for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id))}
    return {ident: uid for uid, ident in model_ids(db, workspace_id, model_id, "element").items() if uid in live}


def existing_bindings(db: Session, workspace_id: str, model_id: str, comp_uids: dict[str, str]) -> list[dict]:
    """What is already known: the sync's own records, and confirmed Installations made any other way (a
    person on the position's page, an inventory link) — those count as human-confirmed."""
    out = []
    seen = set()
    for b in db.scalars(select(BeamAssetBinding).where(BeamAssetBinding.workspace_id == workspace_id,
                                                       BeamAssetBinding.model_id == model_id)):
        out.append({"component": b.component_id, "asset": b.asset_uid, "relation": b.relation, "status": b.status,
                    "authority": b.authority, "confidence": b.confidence, "evidence": b.evidence,
                    "snapshot": b.snapshot or {}})
        if b.status == "confirmed":
            seen.add((b.component_id, b.asset_uid))
    from app.ledger import temporal
    t = engine.now()
    for cid, uid in comp_uids.items():
        for v in engine.installations(db, position_uid=uid, status="Confirmed"):
            if v["asset_uid"] and (cid, v["asset_uid"]) not in seen and temporal.covers(v["interval"], t) != "none":
                unit = db.get(Asset, v["asset_uid"])
                out.append({"component": cid, "asset": v["asset_uid"], "relation": "implemented_by",
                            "status": "confirmed", "authority": "human_confirmed",
                            "snapshot": {"name": unit.name if unit else None}, "installation_uid": v["uid"]})
    return out


def config(options: Optional[dict] = None) -> M.Config:
    o = dict(options or {})
    cfg = M.Config()
    for k in ("propose_threshold", "auto_threshold", "margin", "s_tolerance", "xyz_tolerance"):
        if o.get(k) is not None:
            setattr(cfg, k, float(o[k]))
    cfg.naming_rules = list(o.get("naming_rules") or [])
    return cfg


def _load(db: Session, workspace_id: str, model_id: str) -> Document:
    doc = v2.document(db, workspace_id, model_id)
    if doc is None:
        raise SyncError(f"no beam model {model_id} in this workspace (import it first)")
    return doc


def preview(db: Session, workspace_id: str, model_id: str, options: Optional[dict] = None) -> dict:
    """What the matcher proposes now, against what is already bound. Writes nothing."""
    doc = _load(db, workspace_id, model_id)
    comp_uids = _component_uids(db, workspace_id, model_id)
    existing = existing_bindings(db, workspace_id, model_id, comp_uids)
    rules = (options or {}).get("naming_rules") or _stored_rules(db, workspace_id, model_id)
    result = M.run(doc, candidate_assets(db, workspace_id), existing, config({**(options or {}), "naming_rules": rules}),
                   dataset=(options or {}).get("dataset"))
    for p in result["proposals"]:
        p["component_uid"] = comp_uids.get(p["component"])
    result["model"] = model_id
    return result


def _stored_rules(db: Session, workspace_id: str, model_id: str) -> list[dict]:
    """Naming rules travel with the model (`provenance.asset_sync.naming_rules`)."""
    row = v2.current(db, workspace_id, model_id)
    return list((((row.document if row else {}).get("provenance") or {}).get("asset_sync") or {}).get(
        "naming_rules") or [])


def _row(db: Session, workspace_id: str, model_id: str, component: str, relation: str,
         asset_uid: str) -> BeamAssetBinding:
    row = db.scalar(select(BeamAssetBinding).where(
        BeamAssetBinding.workspace_id == workspace_id, BeamAssetBinding.model_id == model_id,
        BeamAssetBinding.component_id == component, BeamAssetBinding.relation == relation,
        BeamAssetBinding.asset_uid == asset_uid))
    if row is None:
        row = BeamAssetBinding(workspace_id=workspace_id, model_id=model_id, component_id=component,
                               relation=relation, asset_uid=asset_uid, status="proposed", evidence=[], candidates=[],
                               snapshot={})
        db.add(row)
    return row


def _snapshot(a: Asset) -> dict:
    attrs = a.attributes or {}
    return {k: v for k, v in (("name", a.name), ("type", a.type), ("s", attrs.get("s") or attrs.get("s_position")))
            if v is not None}


def _install(db: Session, workspace_id: str, actor: str, position_uid: str, asset_uid: str) -> str:
    """The binding as an Installation: new, or a swap when another unit is installed there now."""
    from app.ledger import service
    now_iso = engine.now().isoformat()
    when = {"kind": "date", "nominal": now_iso, "precision": "instant"}
    current = engine.installations_at(db, engine.now(), position_uid=position_uid)
    if any(v["asset_uid"] == asset_uid for v in current):
        return next(v["uid"] for v in current if v["asset_uid"] == asset_uid)
    if current:
        return service.swap(db, workspace_id, actor, position_uid, asset_uid, when,
                            reason="Replaced (beam asset sync)")["installation_uid"]
    uid = service.new_installation_claims(db, workspace_id, actor, position_uid, asset_uid, when)
    service.confirm_installation(db, workspace_id, actor, uid)
    return uid


def apply(db: Session, workspace_id: str, model_id: str, actor: str, body: dict, *, auto: bool = False) -> dict:
    """Record decisions.

    body = {"accept": [{"component", "asset", "relation"?}], "reject": [...],
            "accept_high_confidence": bool, "keep_proposals": bool, "options": {...}}

    Accepting confirms the binding (a person's decision: `human_confirmed`; with `auto`, the configured policy's:
    `auto_accepted`). An accepted pair need not be the matcher's proposal: a person may bind what they know.
    `keep_proposals` stores proposed and ambiguous entries so the next sync can say what changed."""
    result = preview(db, workspace_id, model_id, body.get("options"))
    doc = _load(db, workspace_id, model_id)
    by_comp = {p["component"]: p for p in result["proposals"]}
    comp_uids = _component_uids(db, workspace_id, model_id)
    now = datetime.now(timezone.utc)
    accept = list(body.get("accept") or [])
    if body.get("accept_high_confidence"):
        accept += [{"component": p["component"], "asset": p["asset"]["id"], "via": "high_confidence"}
                   for p in result["proposals"] if p["status"] == "proposed" and p["auto_acceptable"]]
    done = {"confirmed": [], "rejected": [], "kept": 0, "problems": []}
    for a in accept:
        comp, asset_uid, rel = a.get("component"), a.get("asset"), a.get("relation") or "implemented_by"
        unit = db.get(Asset, asset_uid) if asset_uid else None
        pos = comp_uids.get(comp)
        if unit is None or unit.workspace_id != workspace_id or pos is None:
            done["problems"].append(f"{comp} → {asset_uid}: unknown component or asset")
            continue
        if rel not in ("implemented_by", *RELATION_PREDICATE):
            done["problems"].append(f"{comp}: relation {rel} is not a binding relation")
            continue
        model_side = getattr(next((c for c in doc.components if c.id == comp), None), rel, None) \
            if rel in ("mounted_on", "contained_in") else None
        if model_side:
            done["problems"].append(f"{comp} is {rel} {model_side} in the model: bind {model_side} to the physical "
                                    "asset (implemented_by) instead")
            continue
        p = by_comp.get(comp) or {}
        cand = next((c for c in p.get("candidates") or [] if c["asset"]["id"] == asset_uid), None)
        chosen = p.get("asset") and p["asset"].get("id") == asset_uid
        row = _row(db, workspace_id, model_id, comp, rel, asset_uid)
        row.component_uid = pos
        row.status = "confirmed"
        row.authority = "auto_accepted" if auto else "human_confirmed"
        row.confidence = p.get("confidence") if chosen else (cand or {}).get("confidence")
        row.evidence = p.get("evidence") if chosen else [e["kind"] for e in (cand or {}).get("evidence", [])]
        row.method = "asset_sync" if (chosen or cand) else "manual"
        row.matcher, row.matcher_version = result["matcher"], result["matcher_version"]
        row.snapshot = _snapshot(unit)
        row.decided_by, row.decided_at = actor, now
        row.note = "accepted with the high-confidence batch" if a.get("via") == "high_confidence" else a.get("note")
        try:
            with db.begin_nested():          # a refused binding leaves the others intact
                if rel == "implemented_by":
                    row.installation_uid = _install(db, workspace_id, actor, pos, asset_uid)
                else:
                    _relate(db, workspace_id, actor, pos, RELATION_PREDICATE[rel], asset_uid)
        except Exception as e:  # noqa: BLE001 — the ledger refused (an invariant): report, keep going
            row.status = "proposed"
            done["problems"].append(f"{comp} → {unit.name}: {e}")
            continue
        # A component implemented by a new unit: older confirmed rows for it are history now.
        if rel == "implemented_by":
            for old in db.scalars(select(BeamAssetBinding).where(
                    BeamAssetBinding.workspace_id == workspace_id, BeamAssetBinding.model_id == model_id,
                    BeamAssetBinding.component_id == comp, BeamAssetBinding.relation == rel,
                    BeamAssetBinding.status == "confirmed", BeamAssetBinding.asset_uid != asset_uid)):
                old.status, old.note = "superseded", f"replaced by {unit.name} on {now.date()}"
        done["confirmed"].append({"component": comp, "asset": unit.name, "relation": rel,
                                  "authority": row.authority})
    for r in body.get("reject") or []:
        comp, asset_uid = r.get("component"), r.get("asset")
        if not comp or not asset_uid:
            continue
        row = _row(db, workspace_id, model_id, comp, r.get("relation") or "implemented_by", asset_uid)
        if row.status == "confirmed":
            done["problems"].append(f"{comp}: a confirmed binding is ended on the position, not rejected here")
            continue
        row.component_uid = comp_uids.get(comp)
        row.status, row.authority = "rejected", None
        row.decided_by, row.decided_at, row.note = actor, now, r.get("reason")
        done["rejected"].append({"component": comp, "asset": asset_uid})
    if body.get("keep_proposals"):
        decided = {(c["component"]) for c in done["confirmed"]} | {r["component"] for r in done["rejected"]}
        for p in result["proposals"]:
            if p["component"] in decided or p["status"] not in ("proposed", "ambiguous"):
                continue
            targets = [p["asset"]] if p["asset"] else [c["asset"] for c in p["candidates"][:3]]
            for t in targets:
                row = _row(db, workspace_id, model_id, p["component"], "implemented_by", t["id"])
                if row.status in ("confirmed", "rejected", "superseded"):
                    continue
                row.component_uid = p.get("component_uid")
                row.status = p["status"]
                row.authority = "suggestion"
                row.confidence = p["confidence"] if p["asset"] else next(
                    (c["confidence"] for c in p["candidates"] if c["asset"]["id"] == t["id"]), None)
                row.evidence = p["evidence"]
                row.candidates = [{"asset": c["asset"], "confidence": c["confidence"]} for c in p["candidates"][:5]]
                row.matcher, row.matcher_version = result["matcher"], result["matcher_version"]
                done["kept"] += 1
    db.flush()
    done["summary"] = status(db, workspace_id, model_id)["summary"]
    return done


def _relate(db: Session, workspace_id: str, actor: str, component_uid: str, predicate: str, asset_uid: str) -> None:
    from app.ledger.engine import ParsedClaim
    stream = engine.person_stream(db, workspace_id, actor)
    engine.add_manual_claims(db, stream, [ParsedClaim(f"uid:{component_uid}", f"rel:{predicate}",
                                                      {"ref": f"uid:{asset_uid}"}, method="manual")],
                             cause=f"beam asset binding by {actor}")
    engine.project_subject(db, component_uid, f"beam asset binding by {actor}")


def status(db: Session, workspace_id: str, model_id: str, group: Optional[str] = None,
           options: Optional[dict] = None) -> dict:
    """The synchronization view: a fresh preview, filtered (by family group or status), with its summary
    and the counts per filter group."""
    from app.beam_model_core import vocabulary as V
    r = preview(db, workspace_id, model_id, options)
    proposals = M.filter_proposals(r["proposals"], group)
    groups = {g: len(M.filter_proposals([p for p in r["proposals"] if p["expects_asset"]], g)) for g in V.FILTER_GROUPS}
    return {"model": model_id, "summary": r["summary"], "groups": groups, "proposals": proposals,
            "unmodelled_assets": r["unmodelled_assets"], "stale_bindings": r["stale_bindings"],
            "matcher": r["matcher"], "matcher_version": r["matcher_version"], "generated_at": r["generated_at"]}


def bindings(db: Session, workspace_id: str, model_id: str, status_: Optional[str] = None) -> list[dict]:
    q = select(BeamAssetBinding).where(BeamAssetBinding.workspace_id == workspace_id,
                                       BeamAssetBinding.model_id == model_id)
    if status_:
        q = q.where(BeamAssetBinding.status == status_)
    out = []
    for b in db.scalars(q.order_by(BeamAssetBinding.component_id)):
        a = db.get(Asset, b.asset_uid)
        out.append({**v2.binding_json(b), "asset": {"uid": b.asset_uid, "name": a.name if a else None,
                                                     "type": a.type if a else None},
                    "component_uid": b.component_uid, "installation_uid": b.installation_uid, "note": b.note,
                    "candidates": b.candidates or [], "updated_at": b.updated_at.isoformat() if b.updated_at else None})
    return out


def auto_after_import(db: Session, workspace_id: str, model_id: str) -> Optional[dict]:
    """Run after an import when configured: `propose` keeps proposals for review; `accept_high_confidence`
    also confirms auto-acceptable ones (authority auto_accepted). Default: off."""
    mode = os.environ.get("ARGUS_BEAM_ASSET_SYNC_AUTO", "off").strip().lower()
    if mode not in ("propose", "accept_high_confidence"):
        return None
    return apply(db, workspace_id, model_id, "asset-sync", {
        "keep_proposals": True, "accept_high_confidence": mode == "accept_high_confidence"}, auto=True)
