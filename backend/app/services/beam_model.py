"""The beam model: a simulator-independent physics model linked to the facility the hub knows.

The hub is not a simulator and a lattice file is not the authority on equipment. What this adds is the
physics *positions* (a quadrupole QUAA101 at a place in a ring), how they are joined (paths, branches, the
closing of a ring), what diagnostics observe, and the datasets whose values depend on the optics; and the
link from each position to the hardware installed at it, through the Installations the hub already keeps.

    Physics model     Beam System ── Beam ── Beam Path ── Beam Element ── observes ── Observable
                                                              │ installed at / realized by (an Installation)
    Equipment                                           Physical asset ── powers / acts on …
    Control                                       Control Device ── provided by ── IOC
                                                       └─ signal of ── Control Signal ── measures ── Observable
    Knowledge                               documents, tickets, history (the asset's own)
    Telemetry                               outside: EPICS, !CHAOS, the archiver hold the values

Where each concept lives (docs/beam-model.md):

* systems, beams, paths, elements, observables and datasets are records of the catalogue's types, written
  by the canonical import as ledger claims (rule `beam-model.canonical/1`), so they carry provenance and
  history, and an import that would retire too much is held by the ledger's guard;
* topology is relations: `upstream of` between neighbours, `branches to` from a branch point to the first
  element of a branch path, `closes to` from a closed path's last element to its first. `s` orders a path
  and places it; it is never the topology;
* the values that depend on the optics (s, geometry, strengths, Twiss, the simulator's own parameters) are
  rows of `beam_model_values`, one per (dataset, element, path), never attributes of hardware;
* the binding of a position to hardware is an Installation (with its validity interval, so the position
  stays while the hardware changes); a name match only *proposes* one (rule `beam-model.bind-by-name/1`).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from typing import Iterable, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ledger import engine
from app.models.ledger import IdentityBinding
from app.models.asset import Asset, Relation
from app.models.beam_model import BeamModelValue

FORMAT = "argus.beam-model/1"
RULE = "beam-model.canonical/1"
BIND_RULE = "beam-model.bind-by-name/1"

# Normalised element kinds → the catalogue type a position of that kind is, and what it does by default.
ELEMENT_TYPES = {
    "drift": "Drift", "dipole": "Dipole", "quadrupole": "Quadrupole", "sextupole": "Sextupole",
    "corrector": "Corrector", "kicker": "Kicker", "septum": "Septum", "rf_cavity": "RF Cavity",
    "bpm": "Beam Position Monitor", "screen": "Screen Station", "source": "Beam Source", "dump": "Beam Dump",
    "mirror": "Mirror", "lens": "Lens", "beam_splitter": "Beam Splitter", "generic_monitor": "Generic Monitor",
    "solenoid": "Solenoid", "collimator": "Collimator", "undulator": "Undulator", "generic": "Generic Beam Element",
}
DEFAULT_CAPABILITIES = {
    "drift": ["beam_transport"],
    "dipole": ["beam_transport", "bending", "powered", "alignment_sensitive"],
    "quadrupole": ["beam_transport", "focusing", "powered", "alignment_sensitive"],
    "sextupole": ["beam_transport", "chromatic_correction", "powered", "alignment_sensitive"],
    "corrector": ["beam_transport", "steering", "powered"],
    "kicker": ["beam_transport", "steering", "pulsed", "powered"],
    "septum": ["beam_transport", "branching", "powered"],
    "rf_cavity": ["beam_transport", "acceleration", "powered"],
    "bpm": ["diagnostic", "beam_position_measurement"],
    "screen": ["diagnostic", "beam_profile_measurement", "interceptive"],
    "generic_monitor": ["diagnostic"],
    "source": ["beam_source"], "dump": ["beam_dump", "interceptive"],
    "mirror": ["photon_transport", "steering", "alignment_sensitive"],
    "lens": ["photon_transport", "focusing", "alignment_sensitive"],
    "beam_splitter": ["photon_transport", "branching"],
    "solenoid": ["beam_transport", "focusing", "powered"], "collimator": ["beam_transport", "interceptive"],
    "undulator": ["beam_transport", "radiation"], "generic": [],
}
BEAM_EDGES = ("upstream of", "branches to", "closes to", "merges into", "continues to")
DIAGNOSTIC_KINDS = {"bpm", "screen", "generic_monitor"}
BASE_OBSERVABLES = {
    "beam.position.x": ("mm", "particle", "x"), "beam.position.y": ("mm", "particle", "y"),
    "beam.size.x": ("mm", "particle", "x"), "beam.size.y": ("mm", "particle", "y"),
    "beam.intensity": ("mA", "particle", "none"), "beam.energy": ("MeV", "particle", "none"),
    "beam.loss": ("", "particle", "none"), "optical.power": ("W", "optical", "none"),
    "optical.profile": ("", "optical", "none"),
}


class BeamModelError(ValueError):
    """A canonical model that cannot be imported, said in a way a person can act on."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------- the canonical representation

class _Native(BaseModel):
    source: Optional[str] = None
    type: Optional[str] = None
    parameters: dict = Field(default_factory=dict)


class _Geometry(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    roll: Optional[float] = None


class _Values(BaseModel):
    s: Optional[float] = None
    geometry: Optional[_Geometry] = None
    physics: dict = Field(default_factory=dict)
    optics: dict = Field(default_factory=dict)
    native: Optional[_Native] = None


class _Element(_Values):
    id: str
    name: Optional[str] = None
    type: str
    capabilities: Optional[list[str]] = None
    observes: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in ELEMENT_TYPES:
            raise ValueError(f"unknown element type '{v}'; use one of {sorted(ELEMENT_TYPES)} "
                             "(a simulator's own type goes in native.type)")
        return v


class _Beam(BaseModel):
    id: str
    name: Optional[str] = None
    kind: str                                   # particle | photon
    parameters: dict = Field(default_factory=dict)


class _Branch(BaseModel):
    at: str                                     # the branch point, an element of this path
    to_path: str


class _Path(BaseModel):
    id: str
    name: Optional[str] = None
    system: str
    topology: str                               # open | closed
    elements: list[str]                         # in beam order
    reference: Optional[str] = None             # s = 0; the first element when not given
    length: Optional[float] = None
    direction: Optional[str] = None
    branches: list[_Branch] = Field(default_factory=list)


class _System(BaseModel):
    id: str
    name: Optional[str] = None
    kind: str = "Other"
    beams: list[_Beam] = Field(default_factory=list)


class _Observable(BaseModel):
    quantity: str
    unit: Optional[str] = None
    domain: Optional[str] = None
    plane: Optional[str] = None


class _Dataset(BaseModel):
    id: str
    name: Optional[str] = None
    kind: str = "design"
    path: str
    source: Optional[str] = None
    version: Optional[str] = None
    git_commit: Optional[str] = None
    simulator: Optional[str] = None
    simulator_version: Optional[str] = None
    generated_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    values: dict[str, _Values] = Field(default_factory=dict)


class _Model(BaseModel):
    id: str
    name: Optional[str] = None
    source: Optional[str] = None
    version: Optional[str] = None
    git_commit: Optional[str] = None
    simulator: Optional[str] = None
    # Where element-level values (s, physics, native) belong: one of `datasets`, or a design dataset of that id
    # made from the model; when not given, one per path, named after the model and its version.
    dataset: Optional[str] = None


class CanonicalModel(BaseModel):
    format: str = FORMAT
    model: _Model
    systems: list[_System]
    paths: list[_Path]
    elements: list[_Element]
    observables: list[_Observable] = Field(default_factory=list)
    datasets: list[_Dataset] = Field(default_factory=list)


def validate(doc: dict) -> CanonicalModel:
    """The canonical model, checked for what a schema cannot say: references, and one path per element."""
    try:
        m = CanonicalModel.model_validate(doc)
    except Exception as e:  # pydantic's own message names the field
        raise BeamModelError([str(e)]) from e
    problems: list[str] = []
    if m.format != FORMAT:
        problems.append(f"format must be '{FORMAT}'")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", m.model.id):
        problems.append("model.id must be letters, digits, '.', '_' or '-'")
    systems = {s.id for s in m.systems}
    elements = {e.id for e in m.elements}
    paths = {p.id: p for p in m.paths}
    quantities = {o.quantity for o in m.observables} | set(BASE_OBSERVABLES)
    if len(elements) != len(m.elements):
        problems.append("element ids must be unique")
    member_of: dict[str, str] = {}
    for p in m.paths:
        if p.system not in systems:
            problems.append(f"path {p.id}: unknown system {p.system}")
        if p.topology not in ("open", "closed"):
            problems.append(f"path {p.id}: topology must be open or closed")
        for e in p.elements:
            if e not in elements:
                problems.append(f"path {p.id}: unknown element {e}")
            elif e in member_of:
                # A branch is its own path, joined by `branches to`: sharing members would make `s` ambiguous.
                problems.append(f"element {e} is on paths {member_of[e]} and {p.id}: give the branch its own elements")
            else:
                member_of[e] = p.id
        if p.reference and p.reference not in p.elements:
            problems.append(f"path {p.id}: the reference {p.reference} is not one of its elements")
        for b in p.branches:
            if b.at not in p.elements:
                problems.append(f"path {p.id}: branch point {b.at} is not one of its elements")
            if b.to_path not in paths or not paths[b.to_path].elements:
                problems.append(f"path {p.id}: branch to unknown or empty path {b.to_path}")
    for e in m.elements:
        for q in e.observes:
            if q not in quantities:
                problems.append(f"element {e.id} observes {q}, which is not among the observables")
    for d in m.datasets:
        if d.path not in paths:
            problems.append(f"dataset {d.id}: unknown path {d.path}")
        for eid in d.values:
            if eid not in elements:
                problems.append(f"dataset {d.id}: values for unknown element {eid}")
    if problems:
        raise BeamModelError(problems)
    return m


# --------------------------------------------------------------------------- import

def _ref(ws: str, model: str, kind: str, ident: str) -> str:
    """The ledger's name for an imported record. Identity bindings are installation-wide, so the workspace is
    part of it: the same model imported into two workspaces is two sets of records."""
    return f"beam-model:{ws}:{model}:{kind}:{ident}"


def _key(ws: str, model: str, ident: str) -> str:
    return f"{ws}:{model}/{ident}"


def _claims(ws: str, m: CanonicalModel) -> list[dict]:
    mid = m.model.id
    ev = {"model": mid, "source": m.model.source, "version": m.model.version, "git_commit": m.model.git_commit}
    base = {"method": "stated", "rule_id": RULE, "evidence": {k: v for k, v in ev.items() if v}}
    out: list[dict] = []

    def record(ref, type_name, name, key, attrs: dict, rels: dict):
        out.append({"source_ref": ref, "predicate": "exists", "value": {"type": type_name, "key": key, "name": name},
                    **base})
        out.append({"source_ref": ref, "predicate": "name", "value": name, **base})
        for k, v in attrs.items():
            if v not in (None, "", []):
                out.append({"source_ref": ref, "predicate": f"attr:{k}", "value": v, **base})
        for rel, targets in rels.items():
            for t in targets if isinstance(targets, list) else [targets]:
                if t:
                    out.append({"source_ref": ref, "predicate": f"rel:{rel}", "value": {"ref": t}, **base})

    quantities = {q: (u, d, p) for q, (u, d, p) in BASE_OBSERVABLES.items()}
    for o in m.observables:
        quantities[o.quantity] = (o.unit or "", o.domain or "any", o.plane or "none")
    used = {q for e in m.elements for q in e.observes} | {o.quantity for o in m.observables}
    for q in sorted(used):
        unit, domain, plane = quantities[q]
        record(_ref(ws, mid, "observable", q), "Observable", q, f"{ws}:observable/{q}",
               {"quantity": q, "unit": unit, "domain": domain, "plane": plane}, {})
    for s in m.systems:
        sref = _ref(ws, mid, "system", s.id)
        record(sref, "Beam System", s.name or s.id, _key(ws, mid, s.id),
               {"system_kind": s.kind, "model_id": mid, "model_name": m.model.name, "model_source": m.model.source,
                "model_version": m.model.version, "model_git_commit": m.model.git_commit,
                "model_simulator": m.model.simulator}, {})
        for b in s.beams:
            kind = "Photon Beam" if b.kind == "photon" else "Particle Beam"
            record(_ref(ws, mid, "beam", b.id), kind, b.name or b.id, _key(ws, mid, f"beam/{b.id}"),
                   {"model_id": mid, **b.parameters}, {"beam of": sref})
    for e in m.elements:
        caps = e.capabilities if e.capabilities is not None else DEFAULT_CAPABILITIES[e.type]
        record(_ref(ws, mid, "element", e.id), ELEMENT_TYPES[e.type], e.name or e.id, _key(ws, mid, e.id),
               {"model_name": e.id, "element_kind": e.type, "capabilities": sorted(caps),
                "native_type": e.native.type if e.native else None,
                "native_source": (e.native.source if e.native else None) or m.model.simulator},
               {"observes": [_ref(ws, mid, "observable", q) for q in e.observes]})
    first = {p.id: p.elements[0] for p in m.paths if p.elements}
    for p in m.paths:
        pref = _ref(ws, mid, "path", p.id)
        reference = p.reference or (p.elements[0] if p.elements else None)
        record(pref, "Beam Path", p.name or p.id, _key(ws, mid, f"path/{p.id}"),
               {"topology": p.topology, "length": p.length, "direction": p.direction, "model_id": mid},
               {"part of": _ref(ws, mid, "system", p.system),
                "starts at": _ref(ws, mid, "element", reference) if reference else None})
        for eid in p.elements:
            out.append({"source_ref": _ref(ws, mid, "element", eid), "predicate": "rel:part of", "value": {"ref": pref},
                        **base})
        for a, b in zip(p.elements, p.elements[1:]):
            out.append({"source_ref": _ref(ws, mid, "element", a), "predicate": "rel:upstream of",
                        "value": {"ref": _ref(ws, mid, "element", b)}, **base})
        if p.topology == "closed" and len(p.elements) > 1:
            out.append({"source_ref": _ref(ws, mid, "element", p.elements[-1]), "predicate": "rel:closes to",
                        "value": {"ref": _ref(ws, mid, "element", p.elements[0])}, **base})
        for br in p.branches:
            out.append({"source_ref": _ref(ws, mid, "element", br.at), "predicate": "rel:branches to",
                        "value": {"ref": _ref(ws, mid, "element", first[br.to_path])}, **base})
    for d in _datasets(m):
        record(_ref(ws, mid, "dataset", d.id), "Model Dataset", d.name or d.id, _key(ws, mid, f"dataset/{d.id}"),
               {"dataset_kind": d.kind, "model_id": mid, "source": d.source or m.model.source,
                "version": d.version or m.model.version, "git_commit": d.git_commit or m.model.git_commit,
                "simulator": d.simulator or m.model.simulator, "simulator_version": d.simulator_version,
                "generated_at": d.generated_at, "valid_from": d.valid_from, "valid_until": d.valid_until},
               {"models": _ref(ws, mid, "path", d.path)})
    return out


def _datasets(m: CanonicalModel) -> list[_Dataset]:
    """The datasets, with element-level values filed so nothing in the file is dropped: into `model.dataset`
    when named, else into the first dataset of the element's path, else into one made for that path. A
    dataset's own values for an element win over the element's."""
    out = [d.model_copy(deep=True) for d in m.datasets]
    by_id = {d.id: d for d in out}
    path_of = {e: p.id for p in m.paths for e in p.elements}
    first_of_path = {}
    for d in out:
        first_of_path.setdefault(d.path, d.id)
    for e in m.elements:
        # An element's native type and source say what it is (kept on the element); only native *parameters*
        # are values, which depend on the model version like the rest.
        native = e.native if e.native is not None and e.native.parameters else None
        own = _Values(s=e.s, geometry=e.geometry, physics=e.physics, optics=e.optics, native=native)
        if own.s is None and own.geometry is None and not own.physics and not own.optics and own.native is None:
            continue
        target_id = m.model.dataset or first_of_path.get(path_of.get(e.id)) or \
            f"{m.model.id}@{m.model.version or 'source'}:{path_of.get(e.id, 'none')}"
        if target_id not in by_id:
            if e.id not in path_of:
                continue
            by_id[target_id] = _Dataset(id=target_id, name=f"{m.model.name or m.model.id} (as imported)",
                                        kind="design", path=path_of[e.id])
            out.append(by_id[target_id])
        target = by_id[target_id]
        if e.id not in target.values:
            target.values[e.id] = own
    return out


def awaiting_policy(db: Session, stream_id: str) -> bool:
    """Whether the active authority policy has yet to cover this source. A new external source's claims wait
    (pending) until governance activates a policy that includes it (POST /v1/ledger/policy/activate); then
    they take effect. The import never bypasses that. A model a signed-in person brings is not external."""
    from app.models.ledger import LedgerStream
    stream = db.get(LedgerStream, stream_id)
    if stream is not None and stream.kind in engine.INTERNAL_KINDS:
        return False
    _policy, row = engine.active_policy(db)
    vocab = row.vocabulary or {}
    return stream_id not in set(vocab.get("streams") or []) or RULE not in set(vocab.get("rules") or [])


V1_KIND = {"beam_dump": "dump", "generic_source": "source", "electron_source": "source",
           "positron_source": "source", "ion_source": "source", "proton_source": "source", "laser_source": "source",
           "photon_source": "source"}


def _v1_kind(t: str) -> str:
    """A v2 component type as the v1 format can say it (an export in v1 must import again)."""
    t = V1_KIND.get(t, t)
    if t in ELEMENT_TYPES:
        return t
    from app.beam_model_core import vocabulary as voc
    return "generic_monitor" if voc.family(t) == "diagnostic" else "generic"


def prepare(doc, db: Optional[Session] = None, workspace_id: Optional[str] = None):
    """Any supported version, as a validated v2 document with its report. A v1 document is held to the v1
    rules (its closed list of kinds, one path per element), then upgraded; when it updates a model the hub
    stores as v2, what v1 cannot say is carried over from the stored document."""
    from app.beam_model_core import validation as core
    from app.beam_model_core.upgrade import V1, upgrade, version_of
    from app.services import beam_model_v2 as v2
    version = version_of(doc)
    if version == V1:
        validate(doc)
        body = upgrade(doc)
        if db is not None and workspace_id is not None:
            stored = v2.current(db, workspace_id, (doc.get("model") or {}).get("id"))
            if stored is not None and (stored.document.get("provenance") or {}).get("native_format") == "2":
                body = v2.carry_over(body, stored.document)
        native = "1"
    else:
        body, native = doc, "2"
    parsed, report = core.load(body)
    if not report.ok:
        raise BeamModelError(report.errors)
    return parsed, report, native


def import_canonical(db: Session, workspace_id: str, doc: dict, actor: str = "import", *,
                     trusted: bool = False) -> dict:
    """Bring a canonical beam model into a workspace: its records and topology as ledger claims, then the
    values of its datasets. Importing the same model again updates it; what it no longer lists retires.

    Where it comes from decides how it is governed, once, when the model is first imported: a machine source
    (the Accelerator Model Toolbox, an API token) is external and waits for the authority policy to cover it;
    a model a signed-in person uploads or writes in ARGUS (`trusted`) is theirs, as a record they create is,
    and takes effect at once. Every revision names who brought it."""
    from app.services import beam_model_v2 as v2
    m, check, native = prepare(doc, db, workspace_id)
    claims = v2.claims(workspace_id, m, RULE)
    types = sorted({c["value"]["type"] for c in claims if c["predicate"] == "exists"})
    # The catalogue's types, not bare ones the ledger would make: a workspace seeded before the beam model
    # existed is told what to run.
    from app.services.asset_types import resolve_type_uids
    missing = [t for t in types if t not in resolve_type_uids(db, workspace_id)]
    if missing:
        raise BeamModelError([f"this workspace cannot use the catalogue's {', '.join(missing)} type(s): run "
                              f"`scripts/seed_asset_types.py global <catalogue>` and `scripts/seed_asset_types.py "
                              f"beamline {workspace_id} --catalogue <catalogue>` (or `all {workspace_id}`) first"])
    stream = engine.register_stream(db, f"beam-model:{workspace_id}:{m.model.id}", workspace_id,
                                    "system" if trusted else "beam-model", may_create=types)
    stream.may_create = sorted(set(stream.may_create or []) | set(types))
    content = engine.canonical(sorted(claims, key=engine.canonical)).encode()
    digest = hashlib.sha256(content).hexdigest()
    result = engine.ingest(db, stream.id, revision=digest[:12], content=content, observed_at=engine.now(),
                           parser="resolved", cause=f"beam model {m.model.id} imported by {actor}")
    report = {"model": m.model.id, "state": result.get("state"), "revision": result.get("revision_id"),
              "format": native, "systems": len(m.systems), "paths": len(m.paths), "elements": len(m.components),
              "datasets": 0, "values": 0, "stream": stream.id, "awaiting_policy": awaiting_policy(db, stream.id),
              "levels": check.levels, "warnings": check.warnings}
    if result.get("state") != "published":
        # Held by the ledger's guard (it would retire too much): nothing below is written until a person
        # approves the revision and the import is run again.
        db.flush()
        return report
    resolved: dict[tuple, Optional[str]] = {}

    def uid(kind: str, ident: Optional[str]) -> Optional[str]:
        if ident is None:
            return None
        if (kind, ident) not in resolved:
            resolved[(kind, ident)] = engine.resolve_ref(db, _ref(workspace_id, m.model.id, kind, ident))
        return resolved[(kind, ident)]

    rows = v2.value_rows(m)
    for d in m.datasets:
        dataset_uid = uid("dataset", d.id)
        if dataset_uid is None:
            continue
        db.execute(delete(BeamModelValue).where(BeamModelValue.dataset_uid == dataset_uid))
        report["datasets"] += 1
    for dataset_id, path_id, comp, v in rows:
        dataset_uid, subject = uid("dataset", dataset_id), uid("element", comp)
        if dataset_uid is None or subject is None:
            continue
        g = v.geometry
        own_native = v.native.model_dump(mode="json", exclude_none=True) if v.native else {}
        if own_native.get("format"):
            own_native["source"] = own_native.pop("format")
        physics = dict(v.physics or {})          # value provenance stays in the stored document
        db.add(BeamModelValue(workspace_id=workspace_id, dataset_uid=dataset_uid, subject_uid=subject,
                              path_uid=uid("path", path_id), s=v.s, x=g.x if g else None, y=g.y if g else None,
                              z=g.z if g else None, yaw=g.yaw if g else None, pitch=g.pitch if g else None,
                              roll=g.roll if g else None, physics=physics, optics=v.optics or {}, native=own_native))
        report["values"] += 1
    report["document_revision"] = v2.store(db, workspace_id, m, check.to_dict(), actor, native)
    db.flush()
    return report


def remove_model(db: Session, workspace_id: str, model_id: str, actor: str) -> Optional[dict]:
    """Take a whole model out of a workspace. Its records (systems, paths, elements, datasets) retire through the
    ledger — the model's stream publishes a revision that lists nothing, approved by the person removing it,
    since the ledger's guard holds any revision that would retire this much — so their history and any ticket
    or installation that points at them stay intact. What the import wrote beside the ledger goes: the
    datasets' values, the stored model documents and the asset bindings. Importing the model again brings it
    back as the same records. None when the workspace has no such model."""
    from app.models.ledger import LedgerStream
    from app.models.beam_model import BeamAssetBinding, BeamModelDocument
    stream_id = f"beam-model:{workspace_id}:{model_id}"
    stream = db.get(LedgerStream, stream_id)
    documents = db.scalar(select(func.count()).select_from(BeamModelDocument).where(
        BeamModelDocument.workspace_id == workspace_id, BeamModelDocument.model_id == model_id)) or 0
    records = [a for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                                          Asset.deleted_at.is_(None)))
               if (a.attributes or {}).get("model_id") == model_id]
    if stream is None and not documents and not records:
        return None
    report = {"model": model_id, "retired": 0, "values": 0, "documents": documents, "bindings": 0}
    if stream is not None:
        before = sum(1 for a in records if _live(a))
        result = engine.ingest(db, stream_id, revision=f"removed-{engine.ulid()[:12]}", content=b"[]",
                               observed_at=engine.now(), parser="resolved",
                               cause=f"beam model {model_id} removed by {actor}")
        if result.get("state") == "held":
            engine.approve_revision(db, result["revision_id"], actor)
        elif result.get("state") != "published":
            raise BeamModelError([f"the model could not be removed: its source is {result.get('state')}"
                                  + (f" ({result['reason']})" if result.get("reason") else "")])
        db.flush()
        for a in records:
            db.refresh(a)
        report["retired"] = before - sum(1 for a in records if _live(a))
    datasets = [a.uid for a in records if a.type == "Model Dataset"]
    if datasets:
        report["values"] = db.execute(delete(BeamModelValue).where(BeamModelValue.dataset_uid.in_(datasets))).rowcount
    report["bindings"] = db.execute(delete(BeamAssetBinding).where(BeamAssetBinding.workspace_id == workspace_id,
                                                                   BeamAssetBinding.model_id == model_id)).rowcount
    db.execute(delete(BeamModelDocument).where(BeamModelDocument.workspace_id == workspace_id,
                                               BeamModelDocument.model_id == model_id))
    db.flush()
    return report


# --------------------------------------------------------------------------- bindings: position ↔ hardware

def _tag(text: str) -> Optional[tuple]:
    """A name reduced to letters and its number, so FI33-V-PMP-TRB-001, QUAA101 and quaa-101 compare."""
    m = re.match(r"^([A-Za-z]+[A-Za-z0-9]*?)[-_ ]?0*(\d+)$", re.sub(r"[^A-Za-z0-9]", "", text or ""))
    return (m.group(1).upper(), int(m.group(2))) if m else None


def propose_bindings(db: Session, workspace_id: str) -> dict:
    """For each beam position with nothing installed or proposed, a physical asset of the same workspace whose
    name names it, alone, is *proposed* as installed there. The proposal waits in the review queue: equal
    names do not make the same thing, a person says they do."""
    from app.ledger.engine import INSTALLABLE, installations
    positions = [a for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                                           Asset.type.in_(INSTALLABLE),
                                                           Asset.record_status.notin_(("Retired", "Merged"))))
                 if (a.attributes or {}).get("model_name")]
    taken_types = set(INSTALLABLE) | {"Installation", "Access Point", "Control Device", "IOC", "Control Signal",
                                      "Observable", "Model Dataset", "Beam Path", "Beam System", "Drift"}
    candidates: dict[tuple, list[Asset]] = defaultdict(list)
    for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                            Asset.record_status.notin_(("Retired", "Merged")))):
        if a.type in taken_types or a.type.endswith("Beam"):
            continue
        for text in {a.name, (a.attributes or {}).get("lattice_name")} - {None}:
            t = _tag(str(text))
            if t:
                candidates[t].append(a)
    proposals, report = [], {"proposed": 0, "ambiguous": [], "unmatched": 0, "already": 0}
    for pos in positions:
        if installations(db, position_uid=pos.uid):
            report["already"] += 1
            continue
        t = _tag(pos.attributes["model_name"])
        hits = {a.uid: a for a in candidates.get(t, [])} if t else {}
        if len(hits) != 1:
            if hits:
                report["ambiguous"].append({"position": pos.name, "candidates": [a.name for a in hits.values()]})
            else:
                report["unmatched"] += 1
            continue
        unit = next(iter(hits.values()))
        ref = f"bind:inst:{pos.uid}|{unit.uid}"
        common = {"rule_id": BIND_RULE, "evidence": {"position": pos.name, "asset": unit.name,
                                                    "matched_on": "name"}, "confidence": 0.6}
        # Its existence is the proposal (advisory, waits for a person); where and what project at once, so a
        # reviewer sees exactly what is proposed.
        proposals += [
            {"source_ref": ref, "predicate": "exists", "value": {"type": "Installation"}, "method": "inferred", **common},
            {"source_ref": ref, "predicate": "rel:installed at", "value": {"ref": f"uid:{pos.uid}"},
             "method": "resolved", **common},
            {"source_ref": ref, "predicate": "rel:installation of", "value": {"ref": f"uid:{unit.uid}"},
             "method": "resolved", **common},
            {"source_ref": ref, "predicate": "attr:valid_from",
             "value": {"kind": "before_records", "bound": engine.now().isoformat()}, "method": "resolved", **common},
        ]
        report["proposed"] += 1
    if proposals:
        content = engine.canonical(sorted(proposals, key=engine.canonical)).encode()
        stream = engine.register_stream(db, f"bind:beam-model:{workspace_id}", workspace_id, "resolver",
                                        may_create=["Installation"])
        engine.ingest(db, stream.id, revision=hashlib.sha256(content).hexdigest()[:12], content=content,
                      observed_at=engine.now(), parser="resolved", cause="beam-model binding by name")
    db.flush()
    return report


def bindings(db: Session, workspace_id: str) -> list[dict]:
    """Every position's bindings to hardware, with their state: confirmed and current, historical (ended),
    proposed (waiting for a person), or rejected/withdrawn."""
    from app.ledger import temporal
    from app.ledger.engine import INSTALLABLE, installations
    out = []
    t = engine.now()
    for pos in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.type.in_(INSTALLABLE))):
        for v in installations(db, position_uid=pos.uid):
            unit = db.get(Asset, v["asset_uid"]) if v["asset_uid"] else None
            current = v["status"] == "Confirmed" and temporal.covers(v["interval"], t) != "none"
            state = ("confirmed" if current else "historical") if v["status"] == "Confirmed" else \
                {"Proposed": "proposed"}.get(v["status"], v["status"].lower())
            out.append({"installation_uid": v["uid"], "state": state, "position": _summary(pos),
                        "asset": _summary(unit) if unit else None, "valid_from": v["valid_from"],
                        "valid_until": v["valid_until"], "proposed_by": _proposer(db, v["uid"])})
    return out


def _proposer(db: Session, installation_uid: str) -> Optional[str]:
    """How the binding came about: a name match, an inventory link, or a person (None)."""
    from app.models.ledger import IdentityBinding
    for b in db.scalars(select(IdentityBinding).where(IdentityBinding.uid == installation_uid)):
        if b.source_ref.startswith("bind:inst:"):
            return BIND_RULE
        if b.source_ref.startswith("resolve:inst:"):
            return "resolve.asset_url/1"
    return None


# --------------------------------------------------------------------------- reading the model

def _summary(a: Optional[Asset]) -> Optional[dict]:
    if a is None:
        return None
    attrs = a.attributes or {}
    out = {"uid": a.uid, "key": a.key, "name": a.name, "type": a.type}
    for k in ("model_name", "element_kind", "capabilities", "serial", "manufacturer", "model", "quantity",
              "address", "role", "signal_system", "topology", "system_kind", "dataset_kind", "model_id"):
        if attrs.get(k) not in (None, "", []):
            out[k] = attrs[k]
    return out


class _Graph:
    """The workspace's beam-model edges, loaded once per request."""

    def __init__(self, db: Session, workspace_id: str):
        self.db = db
        self.ws = workspace_id
        self.out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.inn: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.member: dict[str, str] = {}
        self.placed: dict[str, set] = defaultdict(set)      # element → every path it is placed on (v2)
        self.start: dict[str, str] = {}
        self.observes: dict[str, list[str]] = defaultdict(list)
        rels = (*BEAM_EDGES, "part of", "placed on", "starts at", "observes")
        for r in db.scalars(select(Relation).where(Relation.workspace_id == workspace_id,
                                                   Relation.relation_type.in_(rels))):
            if r.relation_type in BEAM_EDGES:
                self.out[r.from_asset_uid].append((r.relation_type, r.to_asset_uid))
                self.inn[r.to_asset_uid].append((r.relation_type, r.from_asset_uid))
            elif r.relation_type == "part of":
                self.member[r.from_asset_uid] = r.to_asset_uid
            elif r.relation_type == "placed on":
                self.placed[r.from_asset_uid].add(r.to_asset_uid)
            elif r.relation_type == "starts at":
                self.start[r.from_asset_uid] = r.to_asset_uid
            else:
                self.observes[r.from_asset_uid].append(r.to_asset_uid)
        self._assets: dict[str, Optional[Asset]] = {}

    def asset(self, uid: str) -> Optional[Asset]:
        if uid not in self._assets:
            self._assets[uid] = self.db.get(Asset, uid)
        return self._assets[uid]

    def members(self, path_uid: str) -> list[str]:
        return sorted({e for e, p in self.member.items() if p == path_uid}
                      | {e for e, ps in self.placed.items() if path_uid in ps})

    def sequence(self, path_uid: str) -> Optional[list[str]]:
        """A v2 path's placements in order, as element uids (a component passed twice appears twice)."""
        path = self.asset(path_uid)
        seq = (path.attributes or {}).get("sequence") if path is not None else None
        if not seq:
            return None
        # The path's model, and its components by their id in it, from the identity bindings of the import.
        ref = self.db.scalar(select(IdentityBinding.source_ref).where(IdentityBinding.uid == path_uid,
                                                                      IdentityBinding.source_ref.like("beam-model:%")))
        if ref is None:
            return None
        _, ws, model, _rest = ref.split(":", 3)
        by_id = {ident: uid for uid, ident in model_ids(self.db, ws, model, "element").items()}
        out = []
        for pid in seq:
            uid = by_id.get(pid.split('#', 1)[0])
            if uid is not None:
                out.append(uid)
        return out


def path_of(db: Session, element_uid: str) -> Optional[str]:
    return db.scalar(select(Relation.to_asset_uid).where(Relation.from_asset_uid == element_uid,
                                                         Relation.relation_type == "part of").limit(1))


def ordered_elements(g: _Graph, path_uid: str) -> list[str]:
    """A path's elements in beam order, from its reference element along `upstream of` (and, for a ring,
    round to where `closes to` returns). Branches leave by `branches to` and are not followed here."""
    members = set(g.members(path_uid))
    if not members:
        return []
    seq = g.sequence(path_uid)
    if seq:
        live = [u for u in dict.fromkeys(seq) if _live(g.asset(u))]
        return live + sorted(m for m in members - set(live) if _live(g.asset(m)))
    start = g.start.get(path_uid)
    if start not in members:
        heads = [e for e in members if not any(t == "upstream of" and src in members for t, src in g.inn[e])]
        start = sorted(heads, key=lambda u: (g.asset(u).name if g.asset(u) else u))[0] if heads else sorted(members)[0]
    order, seen, cur = [], set(), start
    while cur is not None and cur not in seen:
        order.append(cur)
        seen.add(cur)
        nxt = [t for rel, t in g.out[cur] if rel in ("upstream of", "closes to") and t in members]
        cur = nxt[0] if nxt else None
    # Anything not reached (a model with a gap) still belongs to the path: listed after, said so by the caller.
    return order + sorted(members - seen)


def _values(db: Session, dataset_uid: Optional[str], subjects: Iterable[str]) -> dict[str, BeamModelValue]:
    subjects = list(subjects)
    if not dataset_uid or not subjects:
        return {}
    return {v.subject_uid: v for v in db.scalars(select(BeamModelValue).where(
        BeamModelValue.dataset_uid == dataset_uid, BeamModelValue.subject_uid.in_(subjects)))}


def default_dataset(db: Session, workspace_id: str, path_uid: str) -> Optional[str]:
    """The dataset a reader means when they name none: the path's design optics, else its first dataset."""
    rows = list(db.scalars(select(Asset).join(Relation, Relation.from_asset_uid == Asset.uid).where(
        Relation.relation_type == "models", Relation.to_asset_uid == path_uid, Asset.workspace_id == workspace_id,
        Asset.record_status.notin_(("Retired", "Merged")))))
    rows.sort(key=lambda a: ((a.attributes or {}).get("dataset_kind") != "design", a.name or ""))
    return rows[0].uid if rows else None


def _value_view(v: Optional[BeamModelValue]) -> Optional[dict]:
    if v is None:
        return None
    geometry = {k: getattr(v, k) for k in ("x", "y", "z", "yaw", "pitch", "roll") if getattr(v, k) is not None}
    return {"dataset_uid": v.dataset_uid, "path_uid": v.path_uid, "s": v.s, "geometry": geometry or None,
            "physics": v.physics or {}, "optics": v.optics or {}, "native": v.native or {}}


def path_graph(db: Session, workspace_id: str, path_uid: str, dataset_uid: Optional[str] = None) -> dict:
    """A path for a viewer: its elements in order with their kind and, from a dataset, `s` and geometry; the
    edges between them; and where branches leave and join, as edges, not coordinates."""
    g = _Graph(db, workspace_id)
    path = g.asset(path_uid)
    order = ordered_elements(g, path_uid)
    members = set(order)
    dataset_uid = dataset_uid or default_dataset(db, workspace_id, path_uid)
    vals = _values(db, dataset_uid, order)
    def drawn(v: BeamModelValue) -> dict:
        """What a viewer draws an element with: where, how long, how much it bends, and the optics there."""
        physics, optics = v.physics or {}, v.optics or {}
        return {"s": v.s, "geometry": _value_view(v)["geometry"], "length": physics.get("length"),
                "angle": physics.get("angle"),
                "optics": {k: optics[k] for k in ("beta_x", "beta_y", "dx") if optics.get(k) is not None} or None}

    nodes = [{**_summary(g.asset(u)), "index": i, **(drawn(vals[u]) if u in vals else {})}
             for i, u in enumerate(order)]
    edges, branches_out, branches_in = [], [], []
    for u in order:
        for rel, t in g.out[u]:
            if t in members:
                edges.append({"from": u, "to": t, "relation": rel})
            elif rel == "branches to":
                branches_out.append({"from": u, "to": t, "to_path": _summary(g.asset(g.member.get(t, "")))
                                     if g.member.get(t) else None})
        for rel, src in g.inn[u]:
            if src not in members and rel == "branches to":
                branches_in.append({"from": src, "to": u, "from_path": _summary(g.asset(g.member.get(src, "")))
                                    if g.member.get(src) else None})
    attrs = (path.attributes or {}) if path else {}
    return {"path": _summary(path), "topology": attrs.get("topology"), "length": attrs.get("length"),
            "direction": attrs.get("direction"), "reference": g.start.get(path_uid), "dataset_uid": dataset_uid,
            "nodes": nodes, "edges": edges, "branches_out": branches_out, "branches_in": branches_in}


def neighbours(db: Session, workspace_id: str, element_uid: str, direction: str, n: int = 1,
               g: Optional[_Graph] = None) -> list[dict]:
    """What is upstream (or downstream) of an element, nearest first, up to n steps: across a branch point
    into the path it branched from, round a ring through `closes to`, and down every branch."""
    g = g or _Graph(db, workspace_id)
    edges = g.inn if direction == "upstream" else g.out
    seen, out, queue = {element_uid}, [], deque([(element_uid, 0)])
    while queue:
        cur, d = queue.popleft()
        if d >= n:
            continue
        for rel, nxt in edges[cur]:
            if nxt in seen:
                continue
            seen.add(nxt)
            out.append({**_summary(g.asset(nxt)), "distance": d + 1, "via": rel,
                        "path_uid": g.member.get(nxt)})
            queue.append((nxt, d + 1))
    return out


def between(db: Session, workspace_id: str, a: str, b: str) -> Optional[list[dict]]:
    """The elements strictly between a and b along the beam, or None if neither reaches the other. In a ring
    both reach each other; the shorter way round is the one meant."""
    g = _Graph(db, workspace_id)
    found = []
    for src, dst in ((a, b), (b, a)):
        prev, queue = {src: None}, deque([src])
        while queue:
            cur = queue.popleft()
            if cur == dst:
                chain, x = [], prev[dst]
                while x is not None and x != src:
                    chain.append(x)
                    x = prev[x]
                found.append(list(reversed(chain)))
                break
            for _rel, nxt in g.out[cur]:
                if nxt not in prev:
                    prev[nxt] = cur
                    queue.append(nxt)
    if not found:
        return None
    return [_summary(g.asset(u)) for u in min(found, key=len)]


def _is_diagnostic(a: Asset) -> bool:
    attrs = a.attributes or {}
    return attrs.get("element_kind") in DIAGNOSTIC_KINDS or "diagnostic" in (attrs.get("capabilities") or [])


def diagnostics(db: Session, workspace_id: str, path_uid: Optional[str] = None,
                quantity: Optional[str] = None) -> list[dict]:
    """The diagnostic positions (of a path, or all), with what each observes; only those observing a quantity
    when one is given (`beam.position.x`)."""
    g = _Graph(db, workspace_id)
    pool = ordered_elements(g, path_uid) if path_uid else [
        a.uid for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                                      Asset.record_status.notin_(("Retired", "Merged"))))]
    out = []
    for uid in pool:
        a = g.asset(uid)
        if a is None or not _is_diagnostic(a):
            continue
        observed = [g.asset(o) for o in g.observes.get(uid, [])]
        quantities = [(o.attributes or {}).get("quantity") for o in observed if o is not None]
        if quantity and quantity not in quantities:
            continue
        out.append({**_summary(a), "observes": quantities, "path_uid": g.member.get(uid)})
    return out


PLANE_CAPABILITY = {"x": "horizontal_steering", "y": "vertical_steering"}


def correctors_upstream(db: Session, workspace_id: str, element_uid: str, plane: str = "x",
                        max_steps: int = 500) -> list[dict]:
    """The steering elements upstream of a position that act in a plane, nearest first. The plane comes from
    the element's capabilities (`horizontal_steering`, `vertical_steering`), else its catalogue `plane`
    (H, V, Combined); a steering element that says neither is listed with `plane_known: false` rather than
    guessed from its name."""
    want_cap = PLANE_CAPABILITY.get(plane)
    want_plane = {"x": {"H", "Combined"}, "y": {"V", "Combined"}}.get(plane, {"H", "V", "Combined"})
    out = []
    for n in neighbours(db, workspace_id, element_uid, "upstream", max_steps):
        a = db.get(Asset, n["uid"])
        attrs = (a.attributes or {}) if a else {}
        caps = set(attrs.get("capabilities") or [])
        if not (caps & {"steering", *PLANE_CAPABILITY.values()}) and a.type not in ("Corrector", "Kicker"):
            continue
        planes = caps & set(PLANE_CAPABILITY.values())
        if planes:
            if want_cap not in planes:
                continue
            out.append({**n, "plane_known": True})
        elif attrs.get("plane"):
            if attrs["plane"] not in want_plane:
                continue
            out.append({**n, "plane_known": True})
        else:
            out.append({**n, "plane_known": False})
    return out


def observables_of(db: Session, workspace_id: str, element_uid: str) -> list[dict]:
    """What a position observes, and, for each, the control signals that carry its measured value there."""
    g = _Graph(db, workspace_id)
    sigs = signals_for(db, workspace_id, element_uid)
    out = []
    for o in g.observes.get(element_uid, []):
        obs = g.asset(o)
        if obs is None:
            continue
        q = (obs.attributes or {}).get("quantity")
        out.append({**_summary(obs), "measured_by": [s for s in sigs if q in s.get("measures", [])]})
    return out


def signals_for(db: Session, workspace_id: str, subject_uid: str) -> list[dict]:
    """The control signals that say they are for this element or asset, with the observable each measures
    and the device that provides it."""
    out = []
    for r in db.scalars(select(Relation).where(Relation.relation_type == "signal for",
                                               Relation.to_asset_uid == subject_uid)):
        sig = db.get(Asset, r.from_asset_uid)
        if sig is None or sig.workspace_id != workspace_id:
            continue
        measures, device = [], None
        for e in db.scalars(select(Relation).where(Relation.from_asset_uid == sig.uid,
                                                   Relation.relation_type.in_(("measures", "signal of")))):
            target = db.get(Asset, e.to_asset_uid)
            if target is None:
                continue
            if e.relation_type == "measures":
                measures.append((target.attributes or {}).get("quantity") or target.name)
            else:
                device = _summary(target)
        out.append({**_summary(sig), "measures": measures, "device": device})
    return out


def _sources(db: Session, rel: str, targets: Iterable[str]) -> list[Asset]:
    targets = [t for t in targets if t]
    if not targets:
        return []
    return [a for a in (db.get(Asset, r.from_asset_uid) for r in db.scalars(select(Relation).where(
        Relation.relation_type == rel, Relation.to_asset_uid.in_(targets)))) if a is not None]


def _targets(db: Session, rel: str, sources: Iterable[str]) -> list[Asset]:
    sources = [s for s in sources if s]
    if not sources:
        return []
    return [a for a in (db.get(Asset, r.to_asset_uid) for r in db.scalars(select(Relation).where(
        Relation.relation_type == rel, Relation.from_asset_uid.in_(sources)))) if a is not None]


def equipment(db: Session, workspace_id: str, element_uid: str, at: Optional[str] = None) -> dict:
    """The hardware at a position: what is installed now (or at a past instant), and every installation it has
    had, with its state. The position stays; the hardware changes."""
    from app.ledger.engine import installations, installations_at
    now_or_then = installations_at(db, at or engine.now(), position_uid=element_uid)
    installed = [{"asset": _summary(db.get(Asset, v["asset_uid"])), "certainty": v["certainty"],
                  "installation_uid": v["uid"], "valid_from": v["valid_from"], "valid_until": v["valid_until"]}
                 for v in now_or_then if v["asset_uid"]]
    history = [{"asset": _summary(db.get(Asset, v["asset_uid"])) if v["asset_uid"] else None, "status": v["status"],
                "valid_from": v["valid_from"], "valid_until": v["valid_until"], "installation_uid": v["uid"]}
               for v in installations(db, position_uid=element_uid)]
    return {"at": at, "installed": installed, "history": history}


def controls(db: Session, workspace_id: str, element_uid: str) -> dict:
    """The control chain of a position: the unit installed there, what powers it (and the position), the
    control devices acting on either or on their supplies, the IOCs providing those devices, and every
    control signal's identity — never its value."""
    eq = equipment(db, workspace_id, element_uid)
    units = [i["asset"]["uid"] for i in eq["installed"] if i["asset"]]
    subjects = [element_uid, *units]
    supplies = _sources(db, "powers", subjects)
    acted = subjects + [p.uid for p in supplies]
    devices = {d.uid: d for d in _sources(db, "acts on", acted) if d.type == "Control Device"}
    iocs = {i.uid: i for i in _targets(db, "provided by", devices)}
    iocs.update({i.uid: i for i in _sources(db, "drives", acted) if i.type == "IOC"})
    signals = {}
    for s in [*(x for sub in subjects for x in signals_for(db, workspace_id, sub))]:
        signals[s["uid"]] = s
    for sig in _sources(db, "signal of", list(devices) + list(iocs)):
        if sig.uid not in signals and sig.workspace_id == workspace_id:
            signals[sig.uid] = {**_summary(sig), "measures": [], "device": None}
    return {"units": [i["asset"] for i in eq["installed"]], "power_supplies": [_summary(p) for p in supplies],
            "control_devices": [_summary(d) for d in devices.values()], "iocs": [_summary(i) for i in iocs.values()],
            "signals": list(signals.values()), "connected_electronics": [
                _summary(x) for x in _targets(db, "connected to", units)]}


def context(db: Session, workspace_id: str, element_uid: str, dataset_uid: Optional[str] = None,
            access=None) -> dict:
    """Everything a viewer shows when a position is selected: its physics (from every dataset that has it,
    the chosen one first), the hardware installed and its history, power, controls, documentation and tickets
    of the installed unit, and the observables it is a diagnostic of."""
    from app.services import knowledge_hub as hub
    g = _Graph(db, workspace_id)
    el = g.asset(element_uid)
    path_uid = g.member.get(element_uid)
    rows = list(db.scalars(select(BeamModelValue).where(BeamModelValue.subject_uid == element_uid)))
    chosen = dataset_uid or (default_dataset(db, workspace_id, path_uid) if path_uid else None)
    rows.sort(key=lambda v: v.dataset_uid != chosen)
    datasets = [{**_summary(db.get(Asset, v.dataset_uid)), **_value_view(v)} for v in rows]
    eq = equipment(db, workspace_id, element_uid)
    ctl = controls(db, workspace_id, element_uid)
    documents, tickets = [], []
    for unit in [i["asset"] for i in eq["installed"] if i["asset"]] + [_summary(el)]:
        a = db.get(Asset, unit["uid"])
        if a is None:
            continue
        if access is None or access.documents:
            documents += [{**d, "for": unit["name"]} for d in hub.documents_for_asset(db, workspace_id, a)]
        if access is None or access.tickets:
            tickets += [{**hub.ticket_summary(t), "for": unit["name"]}
                        for t in hub.tickets_for_assets(db, workspace_id, [a.uid])]
    return {
        "element": _summary(el), "path": _summary(g.asset(path_uid)) if path_uid else None,
        "physics": datasets[0] if datasets else None, "datasets": datasets,
        "equipment": eq, "power": ctl["power_supplies"], "controls": {k: ctl[k] for k in (
            "control_devices", "iocs", "signals", "connected_electronics")},
        "observables": observables_of(db, workspace_id, element_uid) if _is_diagnostic(el) else [],
        "documentation": documents, "tickets": tickets, "asset_bindings": _asset_bindings(db, element_uid),
        "upstream": neighbours(db, workspace_id, element_uid, "upstream", 1, g),
        "downstream": neighbours(db, workspace_id, element_uid, "downstream", 1, g),
    }


def _asset_bindings(db: Session, element_uid: str) -> list[dict]:
    """The physical assets bound to a position by asset synchronization, with status and authority."""
    from app.models.beam_model import BeamAssetBinding
    from app.services.beam_model_v2 import binding_json
    out = []
    for b in db.scalars(select(BeamAssetBinding).where(
            BeamAssetBinding.component_uid == element_uid,
            BeamAssetBinding.status.in_(("confirmed", "proposed", "ambiguous")))):
        out.append({**binding_json(b), "asset": _summary(db.get(Asset, b.asset_uid))})
    order = {"confirmed": 0, "proposed": 1, "ambiguous": 2}
    return sorted(out, key=lambda x: (order.get(x["status"], 9), -(x.get("confidence") or 0)))


def dataset_view(db: Session, workspace_id: str, dataset_uid: str) -> Optional[dict]:
    d = db.get(Asset, dataset_uid)
    if d is None or d.workspace_id != workspace_id or d.type != "Model Dataset":
        return None
    rows = list(db.scalars(select(BeamModelValue).where(BeamModelValue.dataset_uid == dataset_uid)))
    models = _targets(db, "models", [dataset_uid])
    names = {a.uid: a for a in (db.get(Asset, r.subject_uid) for r in rows) if a is not None}
    values = sorted(({"element": _summary(names.get(r.subject_uid)), **_value_view(r)} for r in rows),
                    key=lambda v: (v["s"] is None, v["s"] or 0))
    return {**_summary(d), "attributes": {k: v for k, v in (d.attributes or {}).items() if not k.startswith("argus_")},
            "models": [_summary(m) for m in models], "values": values}


def ensure_signal(db: Session, workspace_id: str, actor: str, *, name: str, address: str, role: str,
                  device_uid: Optional[str] = None, for_uid: Optional[str] = None, measures: Optional[str] = None,
                  quantity: Optional[str] = None, unit: Optional[str] = None, system: str = "EPICS") -> str:
    """A control signal's identity, stated by a person: what PV carries what, for which position. The value
    is read from the control system; only the meaning is kept here."""
    from app.ledger.engine import ParsedClaim
    ref = f"person:signal:{workspace_id}:{address}"
    claims = [ParsedClaim(ref, "exists", {"type": "Control Signal", "key": f"{workspace_id}:signal/{address}",
                                          "name": name}, method="manual"),
              ParsedClaim(ref, "name", name, method="manual")]
    for k, v in (("address", address), ("role", role), ("signal_system", system), ("quantity", quantity),
                 ("unit", unit)):
        if v:
            claims.append(ParsedClaim(ref, f"attr:{k}", v, method="manual"))
    if device_uid:
        claims.append(ParsedClaim(ref, "rel:signal of", {"ref": f"uid:{device_uid}"}, method="manual"))
    if for_uid:
        claims.append(ParsedClaim(ref, "rel:signal for", {"ref": f"uid:{for_uid}"}, method="manual"))
    if measures:
        obs = db.scalar(select(Asset).where(Asset.workspace_id == workspace_id, Asset.type == "Observable",
                                            Asset.name == measures))
        if obs is None:
            raise BeamModelError([f"no observable {measures} in this workspace; import a model that uses it first"])
        claims.append(ParsedClaim(ref, "rel:measures", {"ref": f"uid:{obs.uid}"}, method="manual"))
    stream = engine.person_stream(db, workspace_id, actor)
    stream.may_create = sorted(set(stream.may_create or []) | {"Control Signal"})
    engine.add_manual_claims(db, stream, claims, cause=f"control signal by {actor}")
    uid = engine.resolve_ref(db, ref)
    engine.project_subject(db, uid, f"control signal by {actor}")
    return uid


# --------------------------------------------------------------------------- several models; export

BUNDLE_FORMAT = "argus.beam-model-bundle/1"


def models_of(doc) -> list[dict]:
    """The models in what was sent: one model, a bundle (v1 `format` or v2 `schema_version`
    argus.beam-model-bundle/…, with "models"), or a plain list of models."""
    from app.beam_model_core.upgrade import models_of as _models_of
    return _models_of(doc)


def check_all(docs: list[dict]) -> list[dict]:
    """Each model's verdict without writing anything: its problems, or what it holds."""
    out, seen = [], set()
    for i, d in enumerate(docs):
        mid = ((d or {}).get("model") or {}).get("id") if isinstance(d, dict) else None
        try:
            m, rep, native = prepare(d)
            problems = [] if m.model.id not in seen else [f"model {m.model.id} is given twice"]
            seen.add(m.model.id)
            out.append({"index": i, "model": m.model.id, "ok": not problems, "problems": problems,
                        "format": native, "levels": rep.levels, "warnings": rep.warnings, "gaps": rep.gaps,
                        "summary": {"systems": len(m.systems), "paths": len(m.paths), "elements": len(m.components),
                                    "components": len(m.components), "definitions": len(m.definitions),
                                    "datasets": len(m.datasets), "observables": len({q for c in m.components
                                                                                     for q in c.observes}),
                                    **{k: rep.summary.get(k) for k in ("placements", "connections", "boundaries",
                                                                       "shared_components") if k in rep.summary}}})
        except BeamModelError as e:
            out.append({"index": i, "model": mid, "ok": False, "problems": e.problems, "summary": None})
    return out


def model_ids(db: Session, workspace_id: str, model_id: str, kind: Optional[str] = None) -> dict[str, str]:
    """uid -> the record's id in its model (of one kind: element, path, system…), from the identity binding the
    import made: what it was called in the model, whatever its key now says."""
    head = f"beam-model:{workspace_id}:{model_id}:" + (f"{kind}:" if kind else "")
    out = {}
    for ref, uid in db.execute(select(IdentityBinding.source_ref, IdentityBinding.uid)
                               .where(IdentityBinding.source_ref.like(head + "%"))):
        if not ref.startswith(head):          # `_` in a LIKE matches any character
            continue
        rest = ref[len(head):]
        out[uid] = rest if kind else rest.split(":", 1)[-1]
    return out


def _local(db: Session, a: Asset, ws: str, model: str, prefix: str = "") -> str:
    """A record's id in its model: from its identity binding, else from a key of the old form (ws:model/id)."""
    ident = model_ids(db, ws, model).get(a.uid)
    if ident:
        return ident
    head = f"{ws}:{model}/{prefix}"
    return a.key[len(head):] if a.key and a.key.startswith(head) else (a.attributes or {}).get("model_name") or a.name


def _live(a: Optional[Asset]) -> bool:
    return a is not None and a.deleted_at is None and a.record_status not in ("Retired", "Merged")


def list_models(db: Session, workspace_id: str) -> list[dict]:
    """The beam models in a workspace, by model id, with what each holds."""
    by_model: dict[str, dict] = {}
    for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id,
                                            Asset.type.in_(("Beam System", "Beam Path", "Model Dataset")))):
        mid = (a.attributes or {}).get("model_id")
        if not mid or not _live(a):
            continue
        entry = by_model.setdefault(mid, {"model_id": mid, "systems": [], "paths": 0, "datasets": 0, "elements": 0,
                                          "name": None, "source": None, "version": None})
        if a.type == "Beam System":
            attrs = a.attributes or {}
            entry["systems"].append(_summary(a))
            entry["name"] = entry["name"] or attrs.get("model_name")
            entry["source"] = entry["source"] or attrs.get("model_source")
            entry["version"] = entry["version"] or attrs.get("model_version")
        elif a.type == "Beam Path":
            entry["paths"] += 1
            entry["elements"] += sum(1 for e in bm_members(db, a.uid))
        else:
            entry["datasets"] += 1
    return sorted(by_model.values(), key=lambda m: m["model_id"])


def bm_members(db: Session, path_uid: str) -> list[Asset]:
    return [a for a in (db.get(Asset, r.from_asset_uid) for r in db.scalars(select(Relation).where(
        Relation.relation_type == "part of", Relation.to_asset_uid == path_uid))) if _live(a)]


def export_canonical(db: Session, workspace_id: str, model_id: str, fmt: Optional[str] = None) -> Optional[dict]:
    """A model as canonical JSON, in the format it was imported in unless `fmt` says ("1" or "2").

    v2: the stored document with the hub's current bindings — everything it said (definitions, boundaries,
    states, supports, fields along paths) comes back. v1: rebuilt from what the hub holds now, so edits made
    since the import are in it; what v1 cannot say is left out. Either imports again, here or in another
    hub, as the same model. Retired elements are left out."""
    from app.services import beam_model_v2 as v2
    fmt = fmt or v2.native_format(db, workspace_id, model_id)
    if fmt == "2":
        out = v2.export(db, workspace_id, model_id)
        if out is not None:
            return out
        legacy = export_canonical(db, workspace_id, model_id, "1")
        if legacy is None:
            return None
        from app.beam_model_core.upgrade import upgrade
        return upgrade(legacy)
    ws, mid = workspace_id, model_id

    def of_type(t: str) -> list[Asset]:
        return [a for a in db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.type == t))
                if _live(a) and (a.attributes or {}).get("model_id") == mid]

    systems = sorted(of_type("Beam System"), key=lambda a: a.key)
    if not systems:
        return None
    head = systems[0].attributes or {}
    g = _Graph(db, ws)
    clean = lambda attrs, drop=(): {k: v for k, v in (attrs or {}).items()  # noqa: E731
                                    if not k.startswith("argus_") and k not in ("model_id", "description", *drop)
                                    and v not in (None, "", [])}
    out_systems = []
    for s in systems:
        beams = []
        for b in bm_sources(db, "beam of", s.uid):
            beams.append({"id": _local(db, b, ws, mid, "beam/"), **({"name": b.name} if b.name != _local(db, b, ws, mid, "beam/") else {}),
                          "kind": "photon" if b.type == "Photon Beam" else "particle", "parameters": clean(b.attributes)})
        sid = _local(db, s, ws, mid)
        out_systems.append({"id": sid, **({"name": s.name} if s.name != sid else {}),
                            "kind": (s.attributes or {}).get("system_kind") or "Other", "beams": beams})
    paths = sorted(of_type("Beam Path"), key=lambda a: a.key)
    path_id = {p.uid: _local(db, p, ws, mid, "path/") for p in paths}
    system_id = {s.uid: _local(db, s, ws, mid) for s in systems}
    elements, out_paths, observed = [], [], {}
    for p in paths:
        order = [u for u in ordered_elements(g, p.uid) if _live(g.asset(u))]
        attrs = p.attributes or {}
        sys_uid = next((t for t in [g.member.get(p.uid)] if t), None)
        branches = []
        for u in order:
            for rel, t in g.out[u]:
                if rel == "branches to" and g.member.get(t) in path_id:
                    branches.append({"at": (g.asset(u).attributes or {}).get("model_name"),
                                     "to_path": path_id[g.member[t]]})
        ref = g.start.get(p.uid)
        out_paths.append({"id": path_id[p.uid], **({"name": p.name} if p.name != path_id[p.uid] else {}),
                          "system": system_id.get(sys_uid, ""), "topology": attrs.get("topology") or "open",
                          "elements": [(g.asset(u).attributes or {}).get("model_name") for u in order],
                          **({"reference": (g.asset(ref).attributes or {}).get("model_name")} if ref in order else {}),
                          **({"length": attrs["length"]} if attrs.get("length") is not None else {}),
                          **({"direction": attrs["direction"]} if attrs.get("direction") else {}),
                          **({"branches": branches} if branches else {})})
        for u in order:
            a = g.asset(u)
            ea = a.attributes or {}
            observes = []
            for o in g.observes.get(u, []):
                obs = g.asset(o)
                if _live(obs):
                    q = (obs.attributes or {}).get("quantity")
                    observes.append(q)
                    observed[q] = obs
            el = {"id": ea.get("model_name"), "type": _v1_kind(ea.get("element_kind") or "generic")}
            if a.name != ea.get("model_name"):
                el["name"] = a.name
            if ea.get("capabilities") is not None:
                el["capabilities"] = ea["capabilities"]
            if ea.get("native_type") or ea.get("native_source"):
                el["native"] = {k: v for k, v in (("source", ea.get("native_source")), ("type", ea.get("native_type"))) if v}
            if observes:
                el["observes"] = sorted(observes)
            elements.append(el)
    observables = [{"quantity": q, **{k: v for k, v in (("unit", (o.attributes or {}).get("unit")),
                                                         ("domain", (o.attributes or {}).get("domain")),
                                                         ("plane", (o.attributes or {}).get("plane"))) if v}}
                   for q, o in sorted(observed.items())]
    datasets = []
    for d in sorted(of_type("Model Dataset"), key=lambda a: a.key):
        attrs = d.attributes or {}
        target = next((t for t in bm_targets(db, "models", d.uid) if t.uid in path_id), None)
        if target is None:
            continue
        values = {}
        for v in db.scalars(select(BeamModelValue).where(BeamModelValue.dataset_uid == d.uid)):
            el = g.asset(v.subject_uid)
            if not _live(el):
                continue
            view = _value_view(v)
            values[(el.attributes or {}).get("model_name")] = {
                k: x for k, x in (("s", view["s"]), ("geometry", view["geometry"]), ("physics", view["physics"]),
                                  ("optics", view["optics"]), ("native", view["native"])) if x not in (None, {}, [])}
        did = _local(db, d, ws, mid, "dataset/")
        datasets.append({"id": did, **({"name": d.name} if d.name != did else {}),
                         "kind": attrs.get("dataset_kind") or "other", "path": path_id[target.uid],
                         **{k: attrs[k] for k in ("source", "version", "git_commit", "simulator", "simulator_version",
                                                  "generated_at", "valid_from", "valid_until") if attrs.get(k)},
                         "values": values})
    model = {k: v for k, v in (("id", mid), ("name", head.get("model_name")), ("source", head.get("model_source")),
                               ("version", head.get("model_version")), ("git_commit", head.get("model_git_commit")),
                               ("simulator", head.get("model_simulator"))) if v}
    return {"format": FORMAT, "model": model, "systems": out_systems, "paths": out_paths, "elements": elements,
            "observables": observables, "datasets": datasets}


def bm_sources(db: Session, rel: str, target: str) -> list[Asset]:
    return [a for a in _sources(db, rel, [target]) if _live(a)]


def bm_targets(db: Session, rel: str, source: str) -> list[Asset]:
    return [a for a in _targets(db, rel, [source]) if _live(a)]


def export_bundle(db: Session, workspace_id: str, model_ids: Optional[list[str]] = None,
                  fmt: Optional[str] = None) -> dict:
    """Several models in one bundle: v1 when every model is v1 (and no format is asked for), else v2."""
    from app.beam_model_core.upgrade import V2_BUNDLE
    from app.services import beam_model_v2 as v2
    ids = model_ids or [m["model_id"] for m in list_models(db, workspace_id)]
    fmt = fmt or ("2" if any(v2.native_format(db, workspace_id, i) == "2" for i in ids) else "1")
    models = [m for m in (export_canonical(db, workspace_id, i, fmt) for i in ids) if m is not None]
    if fmt == "2":
        return {"schema_version": V2_BUNDLE, "models": models}
    return {"format": BUNDLE_FORMAT, "models": models}


def json_schema() -> dict:
    """The canonical representation's JSON Schema, from the same model the importer validates with."""
    out = CanonicalModel.model_json_schema()
    out["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    out["$id"] = "https://argus.infn.it/schemas/argus.beam-model-1.json"
    out["title"] = "ARGUS canonical beam model (argus.beam-model/1)"
    return out


def canonical_json(model: CanonicalModel) -> str:
    return json.dumps(model.model_dump(exclude_none=True), indent=2, sort_keys=False)


__all__ = ["import_canonical", "validate", "propose_bindings", "bindings", "path_graph", "ordered_elements",
           "neighbours", "between", "diagnostics", "correctors_upstream", "observables_of", "signals_for",
           "equipment", "controls", "context", "dataset_view", "ensure_signal", "BeamModelError", "ELEMENT_TYPES"]


def rekey_records(db: Session, workspace_id: str, actor: str) -> list[tuple[str, str]]:
    """Give the records the beam models of a workspace made before Record keys applied to them a key from the
    workspace's pattern, keeping the old one (btf:accumulator_pa/DHSA11) as a `former_key` alias, so a link, a
    note or a bookmark that names it still finds the record. Retired ones too: importing the model again brings
    them back. (old key, new key) of each, by model then type then name; the caller commits."""
    from app.ledger.identity import add_label
    from app.models.ledger import IdentityBinding, RecordEvent
    from app.models.schema import Schema
    from app.services.asset_keys import allocate
    bound = select(IdentityBinding.uid).where(IdentityBinding.source_ref.like(f"beam-model:{workspace_id}:%"))
    rows = [a for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.uid.in_(bound),
                                                      Asset.deleted_at.is_(None)))
            if re.match(rf"^{re.escape(workspace_id)}:[^/]+/", a.key or "")]
    rows.sort(key=lambda a: (a.key.split("/", 1)[0], a.type or "", a.name or "", a.key))
    done = []
    for a in rows:
        new = allocate(db, workspace_id, db.get(Schema, a.schema_uid))
        add_label(db, a.uid, "former_key", a.key, "beam-model")
        db.add(RecordEvent(uid=a.uid, kind="rekeyed", before={"key": a.key}, after={"key": new},
                           cause=f"Record keys applied to beam model records by {actor}", at=engine.now()))
        done.append((a.key, new))
        a.key = new
    db.flush()
    return done
