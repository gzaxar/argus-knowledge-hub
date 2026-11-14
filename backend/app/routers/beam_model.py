"""The beam model's API (docs/beam-model.md): read the physics positions, their topology and datasets, and
everything the facility knows behind each one; import a canonical model; bind positions to hardware.

Binding decisions are the Installations' own: confirm, reject and swap are `/v1/installations/...`."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.ledger.engine import LedgerError
from app.models.asset import Asset
from app.routers.hub import scope as hub_scope
from app.services import beam_model as bm

systems_router = APIRouter(prefix="/v1/beam-systems", tags=["beam-model"])
paths_router = APIRouter(prefix="/v1/beam-paths", tags=["beam-model"])
elements_router = APIRouter(prefix="/v1/beam-elements", tags=["beam-model"])
diagnostics_router = APIRouter(prefix="/v1/diagnostics", tags=["beam-model"])
observables_router = APIRouter(prefix="/v1/observables", tags=["beam-model"])
datasets_router = APIRouter(prefix="/v1/model-datasets", tags=["beam-model"])
bindings_router = APIRouter(prefix="/v1/model-bindings", tags=["beam-model"])
model_router = APIRouter(prefix="/v1/beam-model", tags=["beam-model"])
models_router = APIRouter(prefix="/v1/beam-models", tags=["beam-model"])
ROUTERS = [systems_router, paths_router, elements_router, diagnostics_router, observables_router,
           datasets_router, bindings_router, model_router, models_router]


def _actor(identity) -> str:
    from app.routers.ledger import actor_of
    return actor_of(identity)


def _record(db: Session, workspace_id: str, uid: str, types: Optional[set] = None, what: str = "record") -> Asset:
    a = db.get(Asset, uid)
    if a is None or a.workspace_id != workspace_id or a.deleted_at is not None or (types and a.type not in types):
        raise HTTPException(status_code=404, detail=f"No such {what} in this workspace")
    return a


def _element(db: Session, workspace_id: str, uid: str) -> Asset:
    from app.ledger.registry import BEAM_ELEMENTS
    return _record(db, workspace_id, uid, BEAM_ELEMENTS, "beam element")


def _of_type(db: Session, workspace_id: str, types: set) -> list[Asset]:
    return list(db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.type.in_(types),
                                               Asset.deleted_at.is_(None),
                                               Asset.record_status.notin_(("Retired", "Merged")))
                           .order_by(Asset.name)))


# --------------------------------------------------------------------------- systems and paths

@systems_router.get("")
def list_systems(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The beam systems here, each with its beams and paths."""
    out = []
    for s in _of_type(db, workspace_id, {"Beam System"}):
        beams = [bm._summary(b) | {"attributes": _attrs(b)} for b in bm._sources(db, "beam of", [s.uid])]
        paths = [bm._summary(p) for p in bm._sources(db, "part of", [s.uid]) if p.type == "Beam Path"]
        out.append({**bm._summary(s), "beams": beams, "paths": paths})
    return out


@systems_router.get("/{uid}")
def get_system(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    s = _record(db, workspace_id, uid, {"Beam System"}, "beam system")
    return {**bm._summary(s), "attributes": _attrs(s),
            "beams": [bm._summary(b) | {"attributes": _attrs(b)} for b in bm._sources(db, "beam of", [uid])],
            "paths": [bm._summary(p) for p in bm._sources(db, "part of", [uid]) if p.type == "Beam Path"]}


@paths_router.get("")
def list_paths(system: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
               db: Session = Depends(get_db)):
    paths = _of_type(db, workspace_id, {"Beam Path"})
    if system:
        paths = [p for p in paths if any(t.uid == system for t in bm._targets(db, "part of", [p.uid]))]
    return [bm._summary(p) | {"attributes": _attrs(p)} for p in paths]


@paths_router.get("/{uid}/graph")
def path_graph(uid: str, dataset: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
               db: Session = Depends(get_db)):
    """The path for a viewer: ordered nodes with `s` and geometry from a dataset (its design optics when none
    is named), the edges between them, and the branches that leave and join it."""
    _record(db, workspace_id, uid, {"Beam Path"}, "beam path")
    return bm.path_graph(db, workspace_id, uid, dataset)


@paths_router.get("/{uid}/tunnel")
def path_tunnel(uid: str, dataset: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
                identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The tunnel along the path: elements by `s`, the hardware installed at each with its room, plan point, rack,
    supplies and open tickets, and the rooms crossed as bands along `s` (services/tunnel.py)."""
    from app.routers.activities import _may_cached
    from app.routers.indoor import _viewer
    from app.services import tunnel
    _record(db, workspace_id, uid, {"Beam Path"}, "beam path")
    allowed = _may_cached(db, identity)
    return tunnel.tunnel(db, workspace_id, uid, _viewer(db, identity, workspace_id),
                         may_read_tickets=lambda ws: allowed(ws, "read", "tickets"), dataset_uid=dataset)


@paths_router.get("/{uid}/elements")
def path_elements(uid: str, dataset: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
                  db: Session = Depends(get_db)):
    _record(db, workspace_id, uid, {"Beam Path"}, "beam path")
    return bm.path_graph(db, workspace_id, uid, dataset)["nodes"]


@paths_router.get("/{uid}")
def get_path(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    p = _record(db, workspace_id, uid, {"Beam Path"}, "beam path")
    return {**bm._summary(p), "attributes": _attrs(p),
            "system": [bm._summary(s) for s in bm._targets(db, "part of", [uid])],
            "datasets": [bm._summary(d) for d in bm._sources(db, "models", [uid])]}


# --------------------------------------------------------------------------- elements

@elements_router.get("")
def list_elements(path: Optional[str] = None, kind: Optional[str] = None, q: Optional[str] = None,
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Beam elements, in beam order when a path is given."""
    from app.ledger.registry import BEAM_ELEMENTS
    if path:
        _record(db, workspace_id, path, {"Beam Path"}, "beam path")
        rows = [db.get(Asset, u) for u in bm.ordered_elements(bm._Graph(db, workspace_id), path)]
    else:
        rows = _of_type(db, workspace_id, BEAM_ELEMENTS)
    out = [bm._summary(a) for a in rows if a is not None]
    if kind:
        out = [a for a in out if a.get("element_kind") == kind or a["type"] == kind]
    if q:
        needle = q.lower()
        out = [a for a in out if needle in (a["name"] or "").lower() or needle in (a.get("model_name") or "").lower()]
    return out


@elements_router.get("/{uid}")
def get_element(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    a = _element(db, workspace_id, uid)
    path = bm.path_of(db, uid)
    return {**bm._summary(a), "attributes": _attrs(a), "path": bm._summary(db.get(Asset, path)) if path else None}


@elements_router.get("/{uid}/context")
def element_context(uid: str, dataset: Optional[str] = None, db: Session = Depends(get_db),
                    s=Depends(hub_scope)):
    """Everything a viewer shows for a selected position: physics and optics from the datasets, the hardware
    installed and its history, power, controls (signal identities, never values), documentation and tickets
    of the installed unit, and what it observes. Documents and tickets follow the reader's own rights."""
    if not s.access.assets:
        raise HTTPException(status_code=403, detail="Not permitted")
    _element(db, s.workspace_id, uid)
    return bm.context(db, s.workspace_id, uid, dataset, access=s.access)


@elements_router.get("/{uid}/upstream")
def upstream(uid: str, n: int = Query(1, ge=1, le=1000), workspace_id: str = Depends(require_permission("read")),
             db: Session = Depends(get_db)):
    _element(db, workspace_id, uid)
    return bm.neighbours(db, workspace_id, uid, "upstream", n)


@elements_router.get("/{uid}/downstream")
def downstream(uid: str, n: int = Query(1, ge=1, le=1000), workspace_id: str = Depends(require_permission("read")),
               db: Session = Depends(get_db)):
    _element(db, workspace_id, uid)
    return bm.neighbours(db, workspace_id, uid, "downstream", n)


@elements_router.get("/{uid}/between/{other}")
def between(uid: str, other: str, workspace_id: str = Depends(require_permission("read")),
            db: Session = Depends(get_db)):
    _element(db, workspace_id, uid)
    _element(db, workspace_id, other)
    found = bm.between(db, workspace_id, uid, other)
    if found is None:
        raise HTTPException(status_code=404, detail="The beam does not go from one to the other")
    return found


@elements_router.get("/{uid}/equipment")
def element_equipment(uid: str, at: Optional[datetime] = None,
                      workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The hardware installed at the position now, or at `at`, and its whole installation history."""
    _element(db, workspace_id, uid)
    return bm.equipment(db, workspace_id, uid, at.isoformat() if at else None)


@elements_router.get("/{uid}/controls")
def element_controls(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    _element(db, workspace_id, uid)
    return bm.controls(db, workspace_id, uid)


@elements_router.get("/{uid}/observables")
def element_observables(uid: str, workspace_id: str = Depends(require_permission("read")),
                        db: Session = Depends(get_db)):
    _element(db, workspace_id, uid)
    return bm.observables_of(db, workspace_id, uid)


@elements_router.get("/{uid}/diagnostics")
def element_diagnostics(uid: str, n: int = Query(20, ge=1, le=1000),
                        workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The diagnostics nearest the position, up- and downstream within n steps."""
    _element(db, workspace_id, uid)
    out = {}
    for direction in ("upstream", "downstream"):
        out[direction] = [x for x in bm.neighbours(db, workspace_id, uid, direction, n)
                          if bm._is_diagnostic(db.get(Asset, x["uid"]))]
    return out


@elements_router.get("/{uid}/correctors")
def element_correctors(uid: str, plane: str = Query("x", pattern="^(x|y)$"),
                       workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The steering elements upstream of the position that act in a plane, nearest first."""
    _element(db, workspace_id, uid)
    return bm.correctors_upstream(db, workspace_id, uid, plane)


# --------------------------------------------------------------------------- diagnostics and observables

@diagnostics_router.get("")
def list_diagnostics(path: Optional[str] = None, observable: Optional[str] = None,
                     workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Diagnostic positions, of a path or all; only those observing `observable` when given."""
    return bm.diagnostics(db, workspace_id, path, observable)


@observables_router.get("")
def list_observables(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    return [bm._summary(o) | {"attributes": _attrs(o)} for o in _of_type(db, workspace_id, {"Observable"})]


@observables_router.get("/{quantity}")
def get_observable(quantity: str, workspace_id: str = Depends(require_permission("read")),
                   db: Session = Depends(get_db)):
    """An observable: the diagnostics that observe it and the control signals that measure it."""
    obs = next((o for o in _of_type(db, workspace_id, {"Observable"}) if (o.attributes or {}).get("quantity") == quantity), None)
    if obs is None:
        raise HTTPException(status_code=404, detail="No such observable in this workspace")
    signals = [bm._summary(s) for s in bm._sources(db, "measures", [obs.uid]) if s.type == "Control Signal"]
    return {**bm._summary(obs), "attributes": _attrs(obs), "diagnostics": bm.diagnostics(db, workspace_id, None, quantity),
            "signals": signals}


# --------------------------------------------------------------------------- datasets and bindings

@datasets_router.get("")
def list_datasets(path: Optional[str] = None, workspace_id: str = Depends(require_permission("read")),
                  db: Session = Depends(get_db)):
    rows = _of_type(db, workspace_id, {"Model Dataset"})
    if path:
        rows = [d for d in rows if any(t.uid == path for t in bm._targets(db, "models", [d.uid]))]
    return [bm._summary(d) | {"attributes": _attrs(d)} for d in rows]


@datasets_router.get("/{uid}")
def get_dataset(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """A dataset, its provenance, and its values per element in `s` order."""
    view = bm.dataset_view(db, workspace_id, uid)
    if view is None:
        raise HTTPException(status_code=404, detail="No such model dataset in this workspace")
    return view


@bindings_router.get("")
def list_bindings(state: Optional[str] = Query(None, pattern="^(confirmed|historical|proposed|rejected|withdrawn)$"),
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Every position's bindings to hardware: confirmed (current), historical (ended), proposed (waiting for a
    person in the review queue), rejected or withdrawn. Confirm or reject one at /v1/installations/{uid}."""
    rows = bm.bindings(db, workspace_id)
    return [r for r in rows if not state or r["state"] == state]


@bindings_router.post("/propose")
def propose_bindings(identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
                     db: Session = Depends(get_db)):
    """Propose bindings by name: each unbound position whose model name names exactly one physical asset here
    gets a proposed Installation in the review queue. Nothing becomes a binding until a person confirms it."""
    try:
        report = bm.propose_bindings(db, workspace_id)
    except LedgerError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    return report


class BindingIn(BaseModel):
    position_uid: str
    asset_uid: str
    valid_from: datetime


@bindings_router.post("", status_code=201)
def create_binding(body: BindingIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    """A person binds a position to the hardware installed there from a date: a confirmed Installation."""
    from app.ledger import service
    actor = _actor(identity)
    try:
        uid = service.new_installation_claims(db, workspace_id, actor, body.position_uid, body.asset_uid,
                                              {"kind": "date", "nominal": body.valid_from.isoformat(),
                                               "precision": "instant"})
        service.confirm_installation(db, workspace_id, actor, uid)
    except LedgerError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    return {"installation_uid": uid}


# --------------------------------------------------------------------------- import and signals

@model_router.get("/formats")
def formats():
    """What can be read: the canonical JSON, and every simulator converter installed (app/beam_converters)."""
    from app import beam_converters as bc
    return [{"name": "argus", "label": "ARGUS canonical JSON (argus.beam-model/2, /1)",
             "extensions": [".beam.json", ".json"]}] + [
        {"name": c.name, "label": c.label, "extensions": list(c.extensions)} for c in bc.converters()]


@model_router.get("/schema")
def schema(version: str = Query("2", pattern="^(1|2)$")):
    """The JSON Schema of the canonical representation (docs/beam-model-format.md): v2 (`*.beam.json`), or v1."""
    if version == "1":
        return bm.json_schema()
    from app.beam_model_core.schema import json_schema
    return json_schema()


@model_router.get("/vocabulary")
def vocabulary():
    """The canonical vocabularies (docs/beam-model-format.md §4–§9): component types by family with their default
    capabilities, capabilities, built-in observables, measurement models, default state sets, binding relations
    and profile shapes — what an editor offers."""
    from app.beam_model_core import vocabulary as V
    return {"families": V.FAMILIES, "capabilities": V.CAPABILITIES,
            "observables": {q: {"unit": u, "domain": d, "plane": p} for q, (u, d, p) in V.OBSERVABLES.items()},
            "measurement_models": sorted(V.MEASUREMENT_MODELS), "states": V.DEFAULT_STATES,
            "binding_relations": V.BINDING_RELATIONS, "shapes": sorted(V.SHAPES),
            "virtual_families": sorted(set(V.FAMILIES) - V.PHYSICAL_FAMILIES)}


@model_router.post("/upgrade")
def upgrade_model(doc=Body(..., description="A model of any supported version"),
                  workspace_id: str = Depends(require_permission("read"))):
    """A v1 document as argus.beam-model/2 (a v2 one is returned as it is). Nothing is written."""
    from app.beam_model_core.upgrade import upgrade
    try:
        return upgrade(doc)
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail={"problems": [str(e)]}) from e


class ConvertIn(BaseModel):
    filename: str
    content: str
    converter: Optional[str] = None
    options: dict = {}


@model_router.post("/convert")
def convert(body: ConvertIn, workspace_id: str = Depends(require_permission("read"))):
    """A simulator file (MAD-X sequence or TFS table, Elegant lattice …) turned into a canonical model, checked,
    and returned for a person to look at. Nothing is written: importing is a separate step."""
    from app import beam_converters as bc
    try:
        options = bc.Options(**{k: v for k, v in body.options.items() if k in bc.Options.__dataclass_fields__})
        doc = bc.convert(body.filename, body.content, options, body.converter)
    except (bc.ConversionError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail={"problems": [str(e)]}) from e
    report = doc.pop("conversion", {})
    return {"model": doc, "report": report, "check": bm.check_all([doc])[0]}


@model_router.get("/models")
def list_models(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The beam models in this workspace, by model id, with what each holds."""
    return bm.list_models(db, workspace_id)


@model_router.delete("/models/{model_id}")
def remove_model(model_id: str, workspace_id: str = Depends(require_permission("delete")),
                 identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Remove a whole model: its records retire (their history, tickets and installations stay), its values,
    stored documents and bindings go. Importing it again brings it back."""
    try:
        report = bm.remove_model(db, workspace_id, model_id, actor=_actor(identity))
    except bm.BeamModelError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="; ".join(e.problems)) from e
    if report is None:
        raise HTTPException(status_code=404, detail="No such beam model in this workspace")
    db.commit()
    return report


@model_router.get("/models/{model_id}/export")
def export_model(model_id: str, format: Optional[str] = Query(None, pattern="^(1|2)$"),
                 workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """One model as canonical JSON — in the format it was imported in, or `format` 1 or 2. v2 gives back the
    document whole with the hub's current bindings; v1 is rebuilt from what the hub holds now. Either imports
    again, here or in another hub, as the same model."""
    doc = bm.export_canonical(db, workspace_id, model_id, format)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such beam model in this workspace")
    return doc


@model_router.get("/export")
def export_models(model: Optional[list[str]] = Query(None, description="Model ids; all when omitted"),
                  format: Optional[str] = Query(None, pattern="^(1|2)$"),
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Several models (or all) in one bundle: argus.beam-model-bundle/2, or /1 when every model is v1."""
    return bm.export_bundle(db, workspace_id, model, format)


@model_router.post("/validate")
def validate_models(doc=Body(..., description="A model, a bundle, or a list of models"),
                    workspace_id: str = Depends(require_permission("read"))):
    """Check models without importing them: each one's problems, or what it holds."""
    return {"models": bm.check_all(bm.models_of(doc))}


@model_router.post("/import")
def import_model(doc=Body(..., description="A canonical beam model (argus.beam-model/2 or /1), a bundle "
                                           "(argus.beam-model-bundle/2 or /1) or a list of models"),
                 identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
                 db: Session = Depends(get_db)):
    """Import (or update) one or several canonical beam models, all or none: if any is invalid nothing is written.
    Records and topology become ledger claims with their provenance; each dataset's values are replaced. A model
    a signed-in person brings takes effect at once; one an API token pushes (the Accelerator Model Toolbox) is
    external, and waits for the authority policy to cover its source. A revision that would retire too much is
    held for approval."""
    from app.auth import PatIdentity
    docs = bm.models_of(doc)
    checks = bm.check_all(docs)
    if not docs or any(not c["ok"] for c in checks):
        if len(docs) == 1 and checks:
            raise HTTPException(status_code=422, detail={"problems": checks[0]["problems"]})
        raise HTTPException(status_code=422, detail={"models": checks})
    trusted = not isinstance(identity, PatIdentity)
    reports = []
    try:
        from app.services import beam_asset_sync as sync
        for d in docs:
            report = bm.import_canonical(db, workspace_id, d, _actor(identity), trusted=trusted)
            if report.get("state") == "published":
                auto = sync.auto_after_import(db, workspace_id, report["model"])
                if auto is not None:
                    report["asset_sync"] = {k: auto[k] for k in ("summary", "kept", "problems")} | {
                        "confirmed": len(auto["confirmed"])}
            reports.append(report)
    except bm.BeamModelError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"problems": e.problems}) from e
    except LedgerError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    from app.beam_model_core.upgrade import V1_BUNDLE, V2_BUNDLE, version_of
    bundle = isinstance(doc, list) or version_of(doc) in (V1_BUNDLE, V2_BUNDLE)
    return reports[0] if len(docs) == 1 and not bundle else {"models": reports}


class SignalIn(BaseModel):
    name: str
    address: str
    role: str
    device_uid: Optional[str] = None
    for_uid: Optional[str] = None
    measures: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None
    system: str = "EPICS"


@model_router.post("/signals", status_code=201)
def create_signal(body: SignalIn, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """A control signal's identity: which PV carries which quantity, for which position, from which device."""
    try:
        uid = bm.ensure_signal(db, workspace_id, _actor(identity), **body.model_dump())
    except (bm.BeamModelError, LedgerError) as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()
    return {"uid": uid}


def _attrs(a: Asset) -> dict:
    return {k: v for k, v in (a.attributes or {}).items() if not k.startswith("argus_")}


# --------------------------------------------------------------------------- argus.beam-model/2: one model

def _document(db: Session, workspace_id: str, model_id: str):
    from app.services import beam_model_v2 as v2
    doc = v2.document(db, workspace_id, model_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such beam model in this workspace")
    return doc


@models_router.get("/{model_id}/document")
def model_document(model_id: str, workspace_id: str = Depends(require_permission("read")),
                   db: Session = Depends(get_db)):
    """The model as stored (argus.beam-model/2), with its validation: completeness levels, warnings, gaps."""
    from app.services import beam_model_v2 as v2
    row = v2.current(db, workspace_id, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such beam model in this workspace")
    return {"model": model_id, "revision": row.revision, "imported_by": row.imported_by,
            "imported_at": row.imported_at.isoformat() if row.imported_at else None, "validation": row.report,
            "document": v2.export(db, workspace_id, model_id)}


@models_router.get("/{model_id}/aperture")
def limiting_aperture(model_id: str, path: str, start: Optional[str] = Query(None, alias="from"),
                      end: Optional[str] = Query(None, alias="to"), dataset: Optional[str] = None,
                      state: list[str] = Query([], description="component:STATE, e.g. SCP1:IN"),
                      workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The tightest restriction of the beam between two components of a path, whatever produces it (a magnet
    bore, a chamber, a bellows, a valve, a collimator, an iris), in the states the model assumes unless given."""
    from app.beam_model_core import queries
    doc = _document(db, workspace_id, model_id)
    try:
        return queries.limiting_aperture(doc, path, start, end, dataset,
                                         dict(s.split(":", 1) for s in state if ":" in s))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@models_router.get("/{model_id}/components/{component}/alignment")
def alignment(model_id: str, component: str, workspace_id: str = Depends(require_permission("read")),
              db: Session = Depends(get_db)):
    """What a component is mounted on, what moves with it, and which fiducials define its alignment."""
    from app.beam_model_core import queries
    doc = _document(db, workspace_id, model_id)
    c = next((x for x in doc.components if x.id == component), None)
    if c is None:
        raise HTTPException(status_code=404, detail="No such component in this model")
    return {"component": component, "mounted_on": queries.support_chain(doc, component),
            "moves_with_it": queries.moves_with(doc, component), "fiducials": queries.fiducials_of(doc, component),
            "alignment": c.geometry.alignment.model_dump(exclude_none=True) if c.geometry and c.geometry.alignment
            else None}


class SyncOptions(BaseModel):
    dataset: Optional[str] = None
    propose_threshold: Optional[float] = None
    auto_threshold: Optional[float] = None
    margin: Optional[float] = None
    s_tolerance: Optional[float] = None
    xyz_tolerance: Optional[float] = None
    naming_rules: list[dict] = []


@models_router.post("/{model_id}/asset-sync/preview")
def asset_sync_preview(model_id: str, body: Optional[SyncOptions] = None,
                       workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Proposed bindings between the model's components and this workspace's physical assets, with confidence,
    evidence and how each differs from what is bound now. Nothing is written."""
    from app.services import beam_asset_sync as sync
    try:
        return sync.preview(db, workspace_id, model_id, body.model_dump() if body else None)
    except sync.SyncError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class Decision(BaseModel):
    component: str
    asset: str
    relation: str = "implemented_by"
    note: Optional[str] = None
    reason: Optional[str] = None


class ApplyIn(BaseModel):
    accept: list[Decision] = []
    reject: list[Decision] = []
    accept_high_confidence: bool = False
    keep_proposals: bool = True
    options: Optional[SyncOptions] = None


@models_router.post("/{model_id}/asset-sync/apply")
def asset_sync_apply(model_id: str, body: ApplyIn, identity=Depends(get_identity),
                     workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    """Record a person's decisions: accept chosen proposals (or every auto-acceptable one), reject others, keep
    the rest for review. An accepted `implemented_by` binding becomes a confirmed Installation (a swap when
    another unit is installed there). Confirmed bindings are never changed by a later sync."""
    from app.services import beam_asset_sync as sync
    try:
        out = sync.apply(db, workspace_id, model_id, _actor(identity), {
            "accept": [d.model_dump() for d in body.accept], "reject": [d.model_dump() for d in body.reject],
            "accept_high_confidence": body.accept_high_confidence, "keep_proposals": body.keep_proposals,
            "options": body.options.model_dump() if body.options else None})
    except sync.SyncError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    db.commit()
    return out


@models_router.get("/{model_id}/asset-sync/status")
def asset_sync_status(model_id: str, filter: Optional[str] = Query(
        None, description="magnets, diagnostics, vacuum, rf, optics, mechanical, interception, sources, or a status: "
                          "confirmed, proposed, ambiguous, unmatched"),
                      workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The synchronization summary and the entries, filtered by family or status."""
    from app.services import beam_asset_sync as sync
    try:
        return sync.status(db, workspace_id, model_id, filter)
    except sync.SyncError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@models_router.get("/{model_id}/asset-bindings")
def asset_bindings(model_id: str, status: Optional[str] = Query(
        None, pattern="^(confirmed|proposed|ambiguous|rejected|superseded)$"),
                   workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Every recorded binding of the model: status, authority, confidence, evidence, matcher and decision."""
    from app.services import beam_asset_sync as sync
    return sync.bindings(db, workspace_id, model_id, status)
