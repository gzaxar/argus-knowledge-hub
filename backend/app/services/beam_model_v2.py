"""Importing, storing and exporting `argus.beam-model/2` in the hub (docs/beam-model.md §8).

The canonical library (`app.beam_model_core`) validates and reads a document; this module turns it into
what the hub keeps:

* ledger claims (rule `beam-model.canonical/1`): systems, beams, paths (with their placement order),
  components as positions of the catalogue's types, observables, datasets, and relations — `part of` the
  first path and `placed on` every path a component is on, the beam network between components
  (`upstream of`, `closes to`, `branches to`, `merges into`, `continues to`), `observes`, `mounted on`,
  `contained in`, `fiducial of`;
* rows of `beam_model_values`: per (dataset, component, path) — s, the reference trajectory, physics,
  optics, native parameters, value provenance;
* the document itself (`beam_model_documents`), so an export gives back definitions, boundaries, materials,
  states, measurement models and fields along paths whole, and the model's own queries run on it.

A v1 document arrives already upgraded. When a v1 document updates a model whose stored document is v2 (an
editor or an old client), what v1 cannot say is carried over from the stored document, so nothing is lost.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.beam_model_core import vocabulary as V
from app.beam_model_core.network import Network, resolve
from app.beam_model_core.schema import Document

# Canonical component types → the catalogue type a position of that type is (docs/beam-model-format.md §5).
_BY_TYPE = {
    "dipole": "Dipole", "quadrupole": "Quadrupole", "sextupole": "Sextupole", "corrector": "Corrector",
    "solenoid": "Solenoid", "kicker": "Kicker", "septum": "Septum", "undulator": "Undulator", "wiggler": "Undulator",
    "rf_cavity": "RF Cavity", "buncher": "RF Cavity", "crab_cavity": "RF Cavity", "decelerating_structure": "RF Cavity",
    "generic_rf": "RF Cavity", "accelerating_structure": "Accelerating Structure", "rf_deflector": "RF Deflector",
    "rf_gun": "RF Gun", "bpm": "Beam Position Monitor", "screen": "Screen Station", "wire_scanner": "Wire Scanner",
    "current_transformer": "Beam Charge Monitor", "dc_current_transformer": "Beam Charge Monitor",
    "wall_current_monitor": "Beam Charge Monitor", "faraday_cup": "Faraday Cup",
    "beam_loss_monitor": "Beam Loss Monitor", "spectrometer": "Spectrometer Station",
    "bunch_length_monitor": "Bunch Length Monitor", "beam_arrival_monitor": "Beam Arrival Monitor",
    "emittance_meter": "Emittance Meter", "collimator": "Collimator", "scraper": "Collimator", "mask": "Collimator",
    "absorber": "Collimator", "protection_block": "Collimator", "beam_stopper": "Beam Stopper",
    "beam_dump": "Beam Dump", "mirror": "Mirror", "lens": "Lens", "beam_splitter": "Beam Splitter", "drift": "Drift",
}
_BY_FAMILY = {"diagnostic": "Generic Monitor", "vacuum": "Vacuum Element", "material": "Material Element",
              "injection_extraction": "Material Element", "interception": "Material Element",
              "optical": "Optical Element", "mechanical": "Support Element"}
_SOURCES = {"electron_source", "positron_source", "ion_source", "proton_source", "laser_source", "photon_source",
            "generic_source"}
_EDGE = {"next": "upstream of", "closes": "closes to", "branch": "branches to", "merge": "merges into",
         "continue": "continues to"}


def catalogue_type(t: str) -> str:
    t = V.normalise_type(t)
    if t in _BY_TYPE:
        return _BY_TYPE[t]
    if t in _SOURCES:
        return "Beam Source"
    if t in ("injection_element", "extraction_element", "multipole", "octupole", "generic_magnet"):
        return "Generic Beam Element"
    return _BY_FAMILY.get(V.family(t), "Generic Beam Element")


def _ref(ws, model, kind, ident):
    return f"beam-model:{ws}:{model}:{kind}:{ident}"


def _key(ws, model, ident):
    return f"{ws}:{model}/{ident}"


def claims(ws: str, doc: Document, rule: str) -> list[dict]:
    """The ledger claims for a document: what it says exists and how it is joined."""
    mid = doc.model.id
    ev = {"model": mid, "source": doc.model.source, "version": doc.model.version, "git_commit": doc.model.git_commit}
    base = {"method": "stated", "rule_id": rule, "evidence": {k: v for k, v in ev.items() if v}}
    out: list[dict] = []
    res = resolve(doc)
    net = Network.of(doc)

    def record(ref, type_name, name, key, attrs: dict, rels: dict):
        out.append({"source_ref": ref, "predicate": "exists", "value": {"type": type_name, "key": key, "name": name},
                    **base})
        out.append({"source_ref": ref, "predicate": "name", "value": name, **base})
        # Which model it belongs to, now that its key no longer says.
        out.append({"source_ref": ref, "predicate": "attr:beam_model", "value": mid, **base})
        for k, v in attrs.items():
            if v not in (None, "", []):
                out.append({"source_ref": ref, "predicate": f"attr:{k}", "value": v, **base})
        for rel, targets in rels.items():
            for t in targets if isinstance(targets, list) else [targets]:
                if t:
                    out.append({"source_ref": ref, "predicate": f"rel:{rel}", "value": {"ref": t}, **base})

    def el(cid: str) -> str:
        return _ref(ws, mid, "element", cid)

    quantities = dict(V.OBSERVABLES)
    for o in doc.observables:
        quantities[o.quantity] = (o.unit or "", o.domain or "any", o.plane or "none")
    used = {q for c in doc.components for q in c.observes} | {o.quantity for o in doc.observables}
    for q in sorted(used):
        unit, domain, plane = quantities.get(q, ("", "any", "none"))
        record(_ref(ws, mid, "observable", q), "Observable", q, f"{ws}:observable/{q}",
               {"quantity": q, "unit": unit, "domain": domain, "plane": plane}, {})
    for s in doc.systems:
        record(_ref(ws, mid, "system", s.id), "Beam System", s.name or s.id, _key(ws, mid, s.id),
               {"system_kind": _system_kind(s.kind), "model_id": mid, "model_name": doc.model.name,
                "model_source": doc.model.source, "model_version": doc.model.version,
                "model_git_commit": doc.model.git_commit, "model_simulator": doc.model.simulator}, {})
    carriers: dict[str, set] = {}
    for s in doc.systems:
        for b in s.beams:
            carriers.setdefault(b, set()).add(s.id)
    for b in doc.beams:
        systems = sorted(set(b.systems) | carriers.get(b.id, set()))
        attrs = {"model_id": mid, **{k: getattr(b, k) for k in ("species", "charge", "reference_energy",
                                                               "reference_momentum", "rest_mass", "wavelength")},
                 **b.parameters}
        if b.kind == "photon" and attrs.get("species") == "photon":
            del attrs["species"]
        record(_ref(ws, mid, "beam", b.id), "Photon Beam" if b.kind == "photon" else "Particle Beam",
               b.name or b.id, _key(ws, mid, f"beam/{b.id}"), attrs,
               {"beam of": [_ref(ws, mid, "system", x) for x in systems]})
    paths_of = {c: net.paths_of(c) for c in res}
    first_path = {}
    for p in doc.paths:
        for n in net.order(p.id):
            first_path.setdefault(n.component, p.id)
    for c in doc.components:
        r = res[c.id]
        rels = {"observes": [_ref(ws, mid, "observable", q) for q in c.observes],
                "mounted on": el(c.mounted_on) if c.mounted_on else None,
                "contained in": el(c.contained_in) if c.contained_in else None,
                "part of": _ref(ws, mid, "path", first_path[c.id]) if c.id in first_path else None,
                "placed on": [_ref(ws, mid, "path", p) for p in paths_of[c.id]]}
        record(el(c.id), catalogue_type(r.type), c.name or c.id, _key(ws, mid, c.id),
               {"model_name": c.id, "element_kind": r.type, "component_family": r.family,
                "capabilities": r.capabilities, "native_type": c.native.type if c.native else None,
                "native_source": (c.native.format if c.native else None) or doc.model.simulator,
                "definition": c.definition, "aliases": sorted(c.aliases), "virtual": r.virtual or None}, rels)
    for c in doc.components:
        for f in c.fiducials:
            out.append({"source_ref": el(f), "predicate": "rel:fiducial of", "value": {"ref": el(c.id)}, **base})
    for p in doc.paths:
        row = net.order(p.id)
        reference = p.reference or (row[0].component if row else None)
        if reference and "#" not in reference and reference not in {n.component for n in row}:
            reference = next((n.component for n in row if n.placement_id == reference), None)
        record(_ref(ws, mid, "path", p.id), "Beam Path", p.name or p.id, _key(ws, mid, f"path/{p.id}"),
               {"topology": p.topology, "length": p.length, "direction": p.direction, "model_id": mid,
                "sequence": [n.placement_id for n in row]},
               {"part of": _ref(ws, mid, "system", p.system) if p.system else None,
                "starts at": el(reference) if reference else None})
    closes_from, closes_to = set(), set()
    for a, b, kind in sorted(net.component_edges()):
        rel = _EDGE[kind]
        if rel == "closes to":
            if a in closes_from or b in closes_to:      # 1:1 — a component closing two rings keeps the first
                continue
            closes_from.add(a)
            closes_to.add(b)
        out.append({"source_ref": el(a), "predicate": f"rel:{rel}", "value": {"ref": el(b)}, **base})
    for d in doc.datasets:
        target = _ref(ws, mid, "path", d.path) if d.path else (
            _ref(ws, mid, "system", doc.systems[0].id) if doc.systems else None)
        record(_ref(ws, mid, "dataset", d.id), "Model Dataset", d.name or d.id, _key(ws, mid, f"dataset/{d.id}"),
               {"dataset_kind": d.kind, "model_id": mid, "source": d.source or doc.model.source,
                "version": d.version or doc.model.version, "git_commit": d.git_commit or doc.model.git_commit,
                "simulator": d.simulator or doc.model.simulator, "simulator_version": d.simulator_version,
                "generated_at": d.generated_at, "valid_from": d.valid_from, "valid_until": d.valid_until},
               {"models": target})
    return _dedupe(out)


def _system_kind(kind: Optional[str]) -> str:
    known = {"Storage ring", "Synchrotron", "Accumulator", "Linac", "Transfer line", "Laser transport", "FEL line"}
    if not kind:
        return "Other"
    return next((k for k in known if k.lower() == kind.lower()), "Other")


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = json.dumps([r["source_ref"], r["predicate"], r["value"]], sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def value_rows(doc: Document) -> list[tuple[str, Optional[str], str, dict]]:
    """(dataset id, path id, component id, values) for every dataset value, placement ids resolved."""
    net = Network.of(doc)
    out = []
    for d in doc.datasets:
        pid_to_comp = {n.placement_id: n.component for n in net.order(d.path)} if d.path else {}
        for key, v in d.values.items():
            comp = pid_to_comp.get(key, key)
            out.append((d.id, d.path, comp, v))
    return out


# --------------------------------------------------------------------------- the stored document

def revision(doc_json: dict) -> str:
    return hashlib.sha256(json.dumps(doc_json, sort_keys=True).encode()).hexdigest()[:12]


def store(db: Session, workspace_id: str, doc: Document, report: dict, actor: str, native: str) -> str:
    from app.models.beam_model import BeamModelDocument
    body = doc.to_json()
    body.setdefault("provenance", {})["native_format"] = native
    rev = revision(body)
    existing = db.scalar(select(BeamModelDocument).where(BeamModelDocument.workspace_id == workspace_id,
                                                         BeamModelDocument.model_id == doc.model.id,
                                                         BeamModelDocument.revision == rev))
    db.execute(update(BeamModelDocument).where(BeamModelDocument.workspace_id == workspace_id,
                                               BeamModelDocument.model_id == doc.model.id)
               .values(current=False))
    if existing is not None:
        existing.current = True
    else:
        db.add(BeamModelDocument(workspace_id=workspace_id, model_id=doc.model.id, revision=rev, current=True,
                                 document=body, report=report, imported_by=actor))
    db.flush()
    return rev


def current(db: Session, workspace_id: str, model_id: str):
    from app.models.beam_model import BeamModelDocument
    return db.scalar(select(BeamModelDocument).where(BeamModelDocument.workspace_id == workspace_id,
                                                     BeamModelDocument.model_id == model_id,
                                                     BeamModelDocument.current.is_(True)))


def document(db: Session, workspace_id: str, model_id: str) -> Optional[Document]:
    row = current(db, workspace_id, model_id)
    return Document.model_validate(row.document) if row is not None else None


_V2_ONLY_COMPONENT = ("definition", "family", "aliases", "parameters", "geometry", "boundaries", "material", "states",
                      "measurement_model", "mounted_on", "contained_in", "fiducials", "provenance", "tags",
                      "description")


def carry_over(new: dict, old: dict) -> dict:
    """A v1 update of a model stored as v2: keep what v1 cannot say. Components v1 still lists keep their
    v2-only fields (and their v2 type when v1's coarser kind is the same family); definitions, boundaries,
    connections other than branches, beams' details, components off any path (supports, fiducials) and
    bindings are kept from the stored document."""
    out = copy.deepcopy(new)
    old_comps = {c["id"]: c for c in old.get("components") or []}
    new_ids = {c["id"] for c in out.get("components") or []}
    for c in out.get("components") or []:
        prev = old_comps.get(c["id"])
        if prev is None:
            continue
        for k in _V2_ONLY_COMPONENT:
            if k in prev and k not in c:
                c[k] = copy.deepcopy(prev[k])
        if prev.get("type") and V.family(prev["type"]) == V.family(c.get("type", "")) or c.get("type") in (
                "generic", "generic_monitor"):
            c["type"] = prev["type"]
    placed = {pl if isinstance(pl, str) else pl.get("component") for p in out.get("paths") or []
              for pl in p.get("placements") or []}
    for cid, c in old_comps.items():
        if cid not in new_ids and cid not in placed and not any(
                cid in [pl if isinstance(pl, str) else pl.get("component") for pl in p.get("placements") or []]
                for p in old.get("paths") or []):
            out.setdefault("components", []).append(copy.deepcopy(c))     # supports, fiducials: off every path
    for k in ("facility", "definitions", "boundaries", "external_bindings"):
        if old.get(k) and not out.get(k):
            out[k] = copy.deepcopy(old[k])
    keep = [c for c in old.get("connections") or [] if c.get("kind") != "branch"]
    out["connections"] = [*(out.get("connections") or []), *keep]
    old_beams = {b["id"]: b for b in old.get("beams") or []}
    for b in out.get("beams") or []:
        for k, v in (old_beams.get(b["id"]) or {}).items():
            b.setdefault(k, copy.deepcopy(v))
    old_ds = {d["id"]: d for d in old.get("datasets") or []}
    have = {d["id"] for d in out.get("datasets") or []}
    for d in out.get("datasets") or []:
        prev = old_ds.get(d["id"])
        if prev:
            for k in ("fields", "boundaries", "category", "configuration"):
                if prev.get(k) and not d.get(k):
                    d[k] = copy.deepcopy(prev[k])
            for cid, v in (prev.get("values") or {}).items():
                if cid in (d.get("values") or {}) and v.get("provenance"):
                    d["values"][cid].setdefault("provenance", v["provenance"])
    out["datasets"] = [*(out.get("datasets") or []), *(copy.deepcopy(d) for i, d in old_ds.items()
                                                      if i not in have and not d.get("values"))]
    return out


def native_format(db: Session, workspace_id: str, model_id: str) -> str:
    row = current(db, workspace_id, model_id)
    return ((row.document.get("provenance") or {}).get("native_format") or "2") if row is not None else "1"


def export(db: Session, workspace_id: str, model_id: str) -> Optional[dict]:
    """The model as it was imported (v2), with the bindings the hub holds now: confirmed bindings, with
    their authority and provenance, replace the document's own (the hub is where they are decided)."""
    from app.models.beam_model import BeamAssetBinding
    row = current(db, workspace_id, model_id)
    if row is None:
        return None
    body = copy.deepcopy(row.document)
    (body.get("provenance") or {}).pop("native_format", None)
    rows = list(db.scalars(select(BeamAssetBinding).where(BeamAssetBinding.workspace_id == workspace_id,
                                                          BeamAssetBinding.model_id == model_id,
                                                          BeamAssetBinding.status == "confirmed")))
    if rows:
        decided = {(b.component_id, b.relation) for b in rows}
        kept = [b for b in body.get("external_bindings") or [] if (b["component"], b.get("relation", "implemented_by"))
                not in decided]
        body["external_bindings"] = kept + [binding_json(b) for b in rows]
    return body


def binding_json(b) -> dict:
    """A hub binding as the document's `external_bindings` entry (no copy of the asset's own data)."""
    return {k: v for k, v in {
        "component": b.component_id, "relation": b.relation,
        "target": {"namespace": "kh", "id": b.asset_uid, **({"name": b.snapshot.get("name")} if b.snapshot else {})},
        "status": b.status, "authority": b.authority, "confidence": b.confidence,
        "evidence": b.evidence or [], "source": {"method": b.method, "matcher": b.matcher,
                                                 "matcher_version": b.matcher_version},
        "confirmed_by": {"type": "user", "id": b.decided_by} if b.decided_by else None,
        "timestamp": b.decided_at.isoformat() if b.decided_at else None}.items() if v not in (None, [], {})}
