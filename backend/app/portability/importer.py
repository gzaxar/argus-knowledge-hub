"""Load a verified checkpoint: dry run, isolated load, rebuild, reconciliation, atomic promotion.

The same deterministic functions run twice (`staging.py`): first in the import's own staging
database, with durable per-chunk checkpoints (`execute`, `rebuild`, `reconcile`); then, at
finalization, in the active database inside one transaction (`promote`), which commits only when
its result equals the staged one. Every row an import writes is recorded in the row map by its key
in the archive (sequenced rows: the exporting instance's `seq`) and its key here, so that

* the same commit imported again changes nothing (identical rows are skipped and mapped);
* an interrupted import resumes from its last finished chunk, in staging;
* a discarded or failed import never touched the active database: staging is dropped, nothing purged;
* an increment updates only rows the same origin wrote and nobody here has changed since.

Imported ledger rows keep their original `at`; their local `recorded_at` is the ingestion time, so a
local audit day sealed before the import never changes (I-PORT-8). The origin chain — origin
instance, family, original sequence, original time, the hash of each archive line and of the
checkpoint — is kept in `portability_origin_records`, tied to one local ingestion event.

Outcomes per row:

  identical            skip
  new                  create
  same key, same origin, unchanged here     update (an increment of the same chain)
  same key, divergent  block — never overwritten
  identity / types     a person already known is kept as is; a type that differs is a catalogue
                       conflict to review, never overwritten
  missing reference    block, or by decision `unresolved_references: defer` left unresolved and
                       listed in the reconciliation

Projections are never loaded: the importer replays bindings and stream heads from events, rebuilds
fact state, derived relations and conflicts with the ledger engine, and then compares the result
with the projections the export carried (`reconcile`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.db import Base
from app.ledger.writer import writing
from app.models.attachment import file_sha256
from app.models.ledger import (ClaimEvent, Conflict, ConflictEvent, Decision, IdentityBinding, IdentityEvent,
                               RecordEvent, RevisionEvent, SourceRevision, StatusEvent, StreamHead)
from app.models.portability import PortabilityChainLink, PortabilityEvent, PortabilityOriginRecord, PortabilityRowMap
from app.models.workspace import Workspace
from app.portability import chunks
from app.portability.families import BY_NAME, FAMILIES, ORIGIN_CHAIN, Family, Scope, from_json, to_json

LOAD_GROUPS = ("catalogue", "identity", "access", "governance", "records", "ledger")
GOVERNANCE = ("policies", "rulesets")
REFERENCE_ONLY = ("identities",)              # never updated, never compared as a failure
# A divergent row here may be resolved as part of the import instead of only ever blocking it: pure
# vocabulary, no access control or ledger history riding on it (unlike, say, roles or group members,
# where letting an archive silently overwrite a local decision would be a real privilege question, or
# assets/tickets/documents, which go through the fact ledger, not a plain column overwrite). "types"
# is catalogue too but already has its own admission flow (catalogue_conflicts), not this one.
CATALOGUE_RESOLVABLE = ("icons", "equipment_classes", "equipment_class_reviews")
EVENT_TABLES = (ClaimEvent, RevisionEvent, Decision, StatusEvent, IdentityEvent, RecordEvent, ConflictEvent)


class ImportBlocked(ValueError):
    def __init__(self, message: str, code: str = "blocked", detail: Optional[dict] = None):
        super().__init__(message)
        self.code, self.detail = code, detail or {}


@dataclass
class Plan:
    import_id: str
    origin: str
    mode: str                                  # restore | clone | merge | selective | evidence
    checkpoint: Path
    manifest: dict
    blob_dir: Path
    attachments_dir: Path
    decisions: dict = field(default_factory=dict)
    ingested_at: Optional[datetime] = None          # the local record time of every row loaded
    manifest_sha256: str = ""                        # the origin checkpoint hash
    created_files: list = field(default_factory=list)  # files this run added (removed if it rolls back)
    _index: Optional[dict] = None

    @property
    def selected(self) -> Optional[set]:
        """For a selective import: the archive's workspaces chosen (None: all of them)."""
        chosen = self.decisions.get("select_workspaces")
        return set(chosen) if chosen else None

    @property
    def ws_map(self) -> dict:
        return dict(self.decisions.get("workspace_map") or {})

    def map_ws(self, ws):
        return self.ws_map.get(ws, ws) if isinstance(ws, str) else ws

    def unmap_ws(self, ws):
        rev = {v: k for k, v in self.ws_map.items()}
        return rev.get(ws, ws) if isinstance(ws, str) else ws

    def families(self, groups=LOAD_GROUPS) -> list[Family]:
        out = [f for g in groups for f in FAMILIES if f.group == g and f.name in self.manifest["families"]]
        # Workspaces first: types, records and streams all belong to one.
        out.sort(key=lambda f: f.name != "workspaces")
        if self.mode in ("merge", "selective") and self.decisions.get("governance") != "load":
            out = [f for f in out if f.name not in GOVERNANCE]
        return out

    @property
    def workspaces(self) -> list[str]:
        return [self.map_ws(w) for w in self.manifest["workspaces"] if self.selected is None or w in self.selected]


_MODELS = {m.class_.__table__.name: m.class_ for m in Base.registry.mappers if hasattr(m.class_, "__table__")}


def archive_rows(plan: Plan, fam: Family) -> Iterator[tuple[str, str, dict]]:
    """The archive's rows of a family — for a selective import, only those of the chosen workspaces."""
    for c in plan.manifest["families"][fam.name]["chunks"]:
        for key, row in chunks.read_chunk(plan.checkpoint / c["file"], fam.name):
            if plan.selected is None or _kept(plan, fam, row):
                yield c["file"], key, row


def _index(plan: Plan) -> dict:
    """Which workspace each record, stream, claim and domain of the archive belongs to."""
    if plan._index is None:
        idx: dict = {}

        def read(name):
            fam = BY_NAME[name]
            for c in plan.manifest["families"].get(name, {}).get("chunks", []):
                yield from chunks.read_chunk(plan.checkpoint / c["file"], fam.name)
        for name, key in (("assets", "uid"), ("tickets", "uid"), ("documents", "uid"), ("streams", "id"),
                          ("migration_domains", "id")):
            for _, r in read(name):
                idx[r[key]] = r["workspace_id"]
        for _, r in read("claims"):
            idx[r["claim_id"]] = idx.get(r["stream_id"])
        plan._index = idx
    return plan._index


_CONTEXT = ("types", "icons", "identities", "policies", "rulesets", "roles")


def _kept(plan: Plan, fam: Family, row: dict) -> bool:
    """Whether a row belongs to the chosen workspaces of a selective import."""
    if fam.name in _CONTEXT:
        return True
    chosen, idx = plan.selected, _index(plan)
    if fam.name == "workspaces":
        return row["id"] in chosen
    if "workspace_id" in row and fam.name != "decisions":
        return row["workspace_id"] in chosen
    for col in ("stream_id", "issue_uid", "from_issue_uid", "asset_uid", "document_uid", "subject_uid", "uid",
                "new_uid", "domain_id", "claim_id"):
        if row.get(col) is not None and row[col] in idx:
            return idx[row[col]] in chosen
    if fam.name == "decisions":
        return row.get("workspace_id") in chosen
    return False


def _attr(fam: Family, column: str) -> str:
    for prop in fam.model.__mapper__.column_attrs:
        if prop.columns[0].name == column:
            return prop.key
    return column


# Columns that name a workspace: mapped to this instance's ids on the way in, back on the way out.
WORKSPACE_COLUMNS = ("workspace_id", "site_id", "home_site_id")


def _mapped_row(plan: Plan, fam: Family, row: dict) -> dict:
    """An archive row with this instance's workspace ids."""
    out = dict(row)
    for col in WORKSPACE_COLUMNS:
        if col in out:
            out[col] = plan.map_ws(out[col])
    if fam.name == "workspaces":
        out["id"] = plan.map_ws(out["id"])
    if fam.name == "rulesets" and out.get("scope") != "*":
        out["scope"] = plan.map_ws(out.get("scope"))
    return out


def archive_form(plan: Plan, fam: Family, obj, key: str) -> dict:
    """A local row as the exporter would have written it, in the archive's workspace ids."""
    row = {c: to_json(getattr(obj, _attr(fam, c))) for c in fam.columns}
    for col, kind in fam.blobs.items():
        v = getattr(obj, _attr(fam, col))
        if v is None:
            row[col] = None
        elif kind == "file":
            digest = file_sha256(v)
            row[col] = f"sha256:{digest}" if digest else None
        else:
            row[col] = f"sha256:{hashlib.sha256(bytes(v)).hexdigest()}"
    if fam.sequenced:
        row["seq"] = int(key)
    for col in WORKSPACE_COLUMNS:
        if col in row:
            row[col] = plan.unmap_ws(row[col])
    if fam.name == "workspaces":
        row["id"] = plan.unmap_ws(row["id"])
    if fam.name == "rulesets" and row.get("scope") != "*":
        row["scope"] = plan.unmap_ws(row.get("scope"))
    return row


def _digest(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def find_local(db: Session, plan: Plan, fam: Family, key: str, row: dict):
    """The local row that holds this archive row, if any."""
    rm = db.scalar(select(PortabilityRowMap).where(PortabilityRowMap.origin == plan.origin,
                                                   PortabilityRowMap.family == fam.name,
                                                   PortabilityRowMap.source_key == key))
    if fam.sequenced:
        if rm is not None:
            return db.get(fam.model, int(rm.local_key)), rm
        if fam.name == "decisions":            # a decision is globally unique by its id
            return db.scalar(select(Decision).where(Decision.decision_id == row["decision_id"])), None
        return None, None
    mapped = _mapped_row(plan, fam, row)
    pk = [c.name for c in fam.model.__table__.primary_key.columns]
    if set(pk) <= set(fam.key):
        ident = tuple(from_json(fam.model, c, mapped[c]) for c in pk)
        return db.get(fam.model, ident[0] if len(ident) == 1 else ident), rm
    conds = []
    for c in fam.key:
        col = fam.model.__table__.columns[c]
        v = from_json(fam.model, c, mapped.get(c))
        conds.append(col.is_(None) if v is None else col == v)
    return db.scalar(select(fam.model).where(and_(*conds)).limit(1)), rm


def _blob_value(plan: Plan, kind: str, value):
    if value is None:
        return None
    if not (isinstance(value, str) and value.startswith("sha256:")):
        raise ImportBlocked(f"a blob reference is malformed: {str(value)[:40]}", "malformed")
    digest = value[len("sha256:"):]
    src = plan.blob_dir / digest
    if not src.is_file():
        raise ImportBlocked(f"blob sha256:{digest} was not fetched into quarantine", "missing_artifact")
    if kind == "bytes":
        return src.read_bytes()
    dest = plan.attachments_dir / "portable" / digest[:2] / digest
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        plan.created_files.append(dest)
    return str(dest)


def _values(plan: Plan, fam: Family, row: dict, *, with_deferred: bool) -> dict:
    mapped = _mapped_row(plan, fam, row)
    out = {}
    for c in fam.columns:
        if c in fam.deferred and not with_deferred:
            continue
        if fam.sequenced and c == "seq":
            continue
        v = mapped.get(c)
        if fam.name == "identities" and c not in row:
            continue                            # a column the identity profile did not export
        out[_attr(fam, c)] = (_blob_value(plan, fam.blobs[c], v) if c in fam.blobs else from_json(fam.model, c, v))
    if fam.name == "identities":
        # A historical actor reference: no contact or directory data unless the profile exported it.
        out.setdefault("email", f"{row['id']}@historical.invalid")
        out["active"] = bool(row.get("active", False))
        out.setdefault("source", "archive")
    if "recorded_at" in fam.model.__table__.columns:
        out["recorded_at"] = plan.ingested_at or datetime.now(timezone.utc)   # local ingestion time (I-PORT-8)
    return out


def _missing_refs(db: Session, fam: Family, values: dict, pending: dict) -> list[tuple[str, str]]:
    """Foreign keys whose target is neither here nor in this import."""
    out = []
    for col in fam.model.__table__.columns:
        attr = _attr(fam, col.name)
        v = values.get(attr)
        if v is None or not col.foreign_keys:
            continue
        if fam.name == "types" and col.name == "workspace_id":
            continue                            # a shared type's owner comes as a stub (_ensure_owner)
        for fk in col.foreign_keys:
            target = _MODELS.get(fk.column.table.name)
            if target is None or v in pending.get(fk.column.table.name, ()):
                continue
            if db.get(target, v) is None:
                out.append((col.name, f"{fk.column.table.name}:{v}"))
    return out


# Fields a reconciliation does not hold against a row: a relation is its ends and its type, and the same relation
# stored twice by an older import (two rows, created microseconds apart) is loaded once and cannot match both stamps.
# A policy is its body and vocabulary; when it was activated is this instance's own history — an import that
# activates one of the archive's policies again here (_activate_archive_sources) moves only that.
# The decision that accepts this release's rebuilt projections over the archive's (reconcile).
PROJECTIONS_ACCEPT = "accept_rebuilt"

RECONCILE_IGNORES = {"relations": {"created_at"}, "policies": {"activated_at"}}


def _normalize_legacy_multi(attrs: object) -> object:
    """A multi-value attribute (engine.MULTI_ATTRS: zones, networks, argus_keywords) read from an
    export taken before the claim-per-member fix may still carry the shape a claim holding the whole
    list, instead of one per member, used to project as — ["beam"] stored as [["beam"]] — exactly what
    project_subject itself now unwraps on sight (engine.py). Reconciling an archive against a freshly
    rebuilt local copy needs the same tolerance, or every asset so affected looks like a genuine
    mismatch on every import of an archive taken before the fix, forever (the archive is immutable)."""
    if not isinstance(attrs, dict):
        return attrs
    from app.ledger.engine import MULTI_ATTRS
    keys = {p[5:] for p in MULTI_ATTRS if p.startswith("attr:")}
    out = dict(attrs)
    for key in keys & set(out):
        v = out[key]
        if not isinstance(v, list):
            continue
        flat = []
        for item in v:
            flat.extend(item) if isinstance(item, list) else flat.append(item)
        out[key] = list(dict.fromkeys(flat))
    return out


def as_archived(form: dict, row: dict) -> dict:
    """A local row in the shape of an archive row: a column this release added and an older archive does not
    carry (groups.email_domains) is left out when it holds nothing — the archive could not have said it."""
    return {k: v for k, v in form.items() if k in row or v is not None}


def _reconciles(fam: Family, local, row: dict, form: dict) -> bool:
    form = as_archived(form, row)
    if form == row or (local is not None and _installation_defined(fam, local, row)):
        return True
    if isinstance(form.get("attributes"), dict) and isinstance(row.get("attributes"), dict):
        nform = {**form, "attributes": _normalize_legacy_multi(form["attributes"])}
        nrow = {**row, "attributes": _normalize_legacy_multi(row["attributes"])}
        if nform == nrow:
            return True
    ignore = RECONCILE_IGNORES.get(fam.name)
    return bool(ignore) and local is not None and \
        {k: v for k, v in form.items() if k not in ignore} == {k: v for k, v in row.items() if k not in ignore}


def _installation_defined(fam: Family, local, row: dict) -> bool:
    """A built-in role (viewer, owner…) is made by every installation and kept current by each release: the same
    role on both sides, whatever its timestamps say. The local one stands; it is never divergent."""
    return fam.name == "roles" and bool(getattr(local, "is_system", False)) and bool(row.get("is_system"))


# --------------------------------------------------------------------------- dry run

def dry_run(db: Session, plan: Plan) -> dict:
    """What executing would do, row by row, without writing anything."""
    counts: dict = defaultdict(lambda: defaultdict(int))
    blocking: list = []
    catalogue: list = []
    candidates: list = []
    refs: list = []
    identity_notes: list = []
    pending = _pending_keys(plan)
    from app.portability import jobs
    total = sum((plan.manifest["families"].get(f.name) or {}).get("rows") or 0 for f in plan.families()) or None
    seen = 0
    for fam in plan.families():
        jobs.report(f"checking {fam.name}", seen, total, force=True)
        for _, key, row in archive_rows(plan, fam):
            seen += 1
            if seen % 200 == 0:
                jobs.report(f"checking {fam.name}", seen, total)
            local, rm = find_local(db, plan, fam, key, row)
            if local is None:
                missing = _missing_refs(db, fam, _values_for_check(plan, fam, row), pending)
                if missing:
                    refs.append({"family": fam.name, "key": key, "missing": missing})
                    counts[fam.name]["unresolved_reference"] += 1
                else:
                    counts[fam.name]["create"] += 1
                if fam.name == "assets":
                    candidates += _candidates(db, row)
                continue
            form = as_archived(archive_form(plan, fam, local, key), row)
            if form == row or _installation_defined(fam, local, row) or \
                    (fam.name in RECONCILE_IGNORES and _reconciles(fam, local, row, form)):
                counts[fam.name]["identical"] += 1
                continue
            if fam.name in REFERENCE_ONLY:
                counts[fam.name]["known_identity"] += 1
                identity_notes.append({"user": key, "note": "known here with other details; kept as is"})
                continue
            if rm is not None and rm.content_sha256 == _digest(form):
                counts[fam.name]["update_same_origin"] += 1
                continue
            counts[fam.name]["divergent"] += 1
            if fam.name in CATALOGUE_RESOLVABLE:
                resolution = (plan.decisions.get("catalogue_conflicts") or {}).get(f"{fam.name}:{key}")
                if resolution in ("keep_local", "use_archive"):
                    counts[fam.name][f"resolved_{resolution}"] += 1
                    continue
                fields = _differs(row, form)[:20]
                item = {"family": fam.name, "key": key, "reason": "same key, different content, not from this chain",
                        "resolvable": True, "fields": fields,
                        "local": {f: form.get(f) for f in fields}, "archive": {f: row.get(f) for f in fields}}
            else:
                item = {"family": fam.name, "key": key, "reason": "same key, different content, not from this chain"}
            (catalogue if fam.name == "types" else blocking).append(item)
    unresolved = refs if (plan.decisions.get("unresolved_references") or "block") == "block" else []
    governance = [f for f in GOVERNANCE if f in plan.manifest["families"] and f not in [x.name for x in plan.families()]]
    workspaces = []
    for w in plan.manifest["workspaces"]:
        if plan.selected is not None and w not in plan.selected:
            continue
        local_ws = plan.map_ws(w)
        here = db.get(Workspace, local_ws)
        # An import never mixes into a workspace with independent local history: a workspace is new
        # here, or it is the same origin's (an increment), or it is mapped to another id.
        if here is not None and not _ours(db, plan, "workspaces", w):
            blocking.append({"family": "workspaces", "key": w,
                             "reason": f"workspace {local_ws} already exists here with its own history; map it "
                                       "to another id"})
        workspaces.append({"archive": w, "local": local_ws, "exists": here is not None})
    if plan.selected is not None:
        unknown = sorted(plan.selected - set(plan.manifest["workspaces"]))
        if unknown:
            blocking.append({"family": "workspaces", "key": ",".join(unknown), "reason": "not in this archive"})
    chain = chain_status(db, plan)
    if chain.get("problem"):
        blocking.append({"family": "chain", "key": plan.manifest["export_id"], "reason": chain["problem"]})
    return {
        "mode": plan.mode, "export_id": plan.manifest["export_id"], "origin": plan.origin,
        "labels": plan.manifest["labels"], "workspaces": workspaces,
        "families": {k: dict(v) for k, v in counts.items()},
        "blocking": blocking[:200], "blocking_count": len(blocking),
        "catalogue_conflicts": catalogue[:200], "identity_candidates": candidates[:200],
        "unresolved_references": refs[:200], "unresolved_reference_count": len(refs),
        "unresolved_references_outcome": plan.decisions.get("unresolved_references") or "block",
        "identities": identity_notes[:50], "governance_not_loaded": governance, "chain": chain,
        "ready": not blocking and not catalogue and not unresolved,
    }


def _values_for_check(plan: Plan, fam: Family, row: dict) -> dict:
    mapped = _mapped_row(plan, fam, row)
    return {_attr(fam, c): (None if c in fam.blobs else from_json(fam.model, c, mapped.get(c)))
            for c in fam.columns if not (fam.sequenced and c == "seq")}


def _pending_keys(plan: Plan) -> dict:
    """Primary keys this import will bring, by table: references to them are not missing."""
    out: dict = defaultdict(set)
    for fam in plan.families():
        pk = [c.name for c in fam.model.__table__.primary_key.columns]
        if len(pk) != 1 or pk[0] not in fam.key:
            continue
        for _, key, row in archive_rows(plan, fam):
            out[fam.table].add(_mapped_row(plan, fam, row).get(pk[0]))
    return out


def _candidates(db: Session, row: dict) -> list:
    """Records here holding the same immutable external identifier: candidates, never merges."""
    from app.models.asset import Asset
    out = []
    attrs = row.get("attributes") or {}
    for name in ("argus_source_key", "insight_object_id", "serial_number", "serial", "mac"):
        v = attrs.get(name)
        if not v:
            continue
        other = db.scalar(select(Asset.uid).where(Asset.attributes[name].astext == str(v), Asset.uid != row["uid"])
                          .limit(1))
        if other:
            out.append({"archive": row["uid"], "here": other, "identifier": name, "value": str(v)})
    return out


def _ours(db: Session, plan: Plan, family: str, key: str) -> bool:
    return db.scalar(select(func.count()).select_from(PortabilityRowMap).where(
        PortabilityRowMap.origin == plan.origin, PortabilityRowMap.family == family,
        PortabilityRowMap.source_key == key)) > 0


def chain_status(db: Session, plan: Plan) -> dict:
    """Where this export sits in the chain of exports applied here from the same origin. Increments
    match their base by the exact watermark vector and manifest hash, never by a number."""
    m = plan.manifest
    links = list(db.scalars(select(PortabilityChainLink).where(PortabilityChainLink.origin == plan.origin)
                            .order_by(PortabilityChainLink.position)))
    applied = {l.export_id for l in links}
    if m["export_id"] in applied:
        return {"status": "already_applied", "applied": len(links)}
    if m["mode"] == "incremental":
        base = m.get("base") or {}
        if not links:
            return {"status": "out_of_order",
                    "problem": f"increment of {base.get('export_id')}, which was never imported here"}
        last = links[-1]
        if last.export_id != base.get("export_id"):
            return {"status": "out_of_order",
                    "problem": f"increment of {base.get('export_id')}, but the last export applied here from this "
                               f"origin is {last.export_id}: an increment is missing or out of order"}
        if last.vector_sha256 != base["watermark"].get("vector_sha256"):
            return {"status": "out_of_order", "problem": "the base watermark vector differs from the one applied here"}
        if last.manifest_sha256 and base.get("manifest_sha256") and last.manifest_sha256 != base["manifest_sha256"]:
            return {"status": "out_of_order", "problem": "the base manifest differs from the one applied here"}
        return {"status": "next", "applied": len(links)}
    return {"status": "first" if not links else "new_checkpoint", "applied": len(links)}


def references(db_unused, plan: Plan) -> dict:
    """Primary keys the archive's rows refer to and do not bring themselves, by table: what staging
    must be seeded with from the active instance."""
    pending = _pending_keys(plan)
    out: dict = defaultdict(set)
    for fam in plan.families():
        fks = [(c, fk) for c in fam.model.__table__.columns if c.name in fam.columns for fk in c.foreign_keys]
        if not fks:
            continue
        for _, key, row in archive_rows(plan, fam):
            mapped = _mapped_row(plan, fam, row)
            for c, fk in fks:
                v = mapped.get(c.name)
                if v is None or (isinstance(v, str) and v.startswith("sha256:")):
                    continue
                if v not in pending.get(fk.column.table.name, ()):
                    out[fk.column.table.name].add(v)
    return {k: sorted(v) for k, v in out.items()}


# --------------------------------------------------------------------------- execute

def execute(db: Session, plan: Plan, done: set, save: Callable[[set], None],
            stop_after: Optional[int] = None) -> dict:
    """Load the checkpoint chunk by chunk. `done` holds the finished steps; `save` persists them and
    commits. `stop_after` stops after that many steps (tests use it to prove resumption)."""
    report = {"created": 0, "updated": 0, "identical": 0, "deferred": [], "steps": 0}
    pending = _pending_keys(plan)
    steps = 0

    from app.portability import jobs
    from app.services.sites import LOADING_ARCHIVE
    planned = sum(len(plan.manifest["families"][f.name]["chunks"]) + (1 if f.deferred else 0) for f in plan.families())

    def step(name: str, fn):
        nonlocal steps
        if name in done:
            return
        jobs.report(f"loading {name.split(':')[0]}", len(done), planned, force=True)
        if stop_after is not None and steps >= stop_after:
            raise InterruptedError(f"stopped before {name}")
        with writing(db):
            fn()
        done.add(name)
        save(done)
        steps += 1
        report["steps"] += 1

    # The archive's rows are what it says, derived columns included: a flush guard that would derive one
    # (sites: site_shared) stands aside while they load.
    was = db.info.get(LOADING_ARCHIVE)
    db.info[LOADING_ARCHIVE] = True
    try:
        for fam in plan.families():
            for c in plan.manifest["families"][fam.name]["chunks"]:
                step(f"{fam.name}:{c['file']}", lambda fam=fam, c=c: _load_chunk(db, plan, fam, c, pending, report))
            if fam.replace_set and plan.manifest["mode"] == "incremental":
                step(f"{fam.name}:replace", lambda fam=fam: _replace(db, plan, fam))
        # References inside and across families (a document's current revision, a merge survivor, a parent
        # type) once everything they can name is loaded.
        for fam in plan.families():
            if fam.deferred:
                step(f"{fam.name}:deferred", lambda fam=fam: _deferred(db, plan, fam, pending, report))
    finally:
        if was is None:
            db.info.pop(LOADING_ARCHIVE, None)
        else:
            db.info[LOADING_ARCHIVE] = was
    if "policies" in {f.name for f in plan.families()}:
        step("policies:activate", lambda: _activate_archive_sources(db, plan))
    return report


def _activate_archive_sources(db: Session, plan: Plan) -> None:
    """Loading the archive's policies alone changes nothing: the active one is the most recently activated,
    and a policy this instance activated after the archive's stays so. The sources the archive's latest
    policy had admitted would then stay pending here, and their records project empty. When the import
    loads governance (approved as part of it), activate the active policy again with those streams added:
    the union of what is in effect here and what was in effect there — never a stream that was still
    pending at the source, and never one dropped from here."""
    from app.ledger import engine
    latest = None
    for _, _key, row in archive_rows(plan, BY_NAME["policies"]):
        if latest is None or str(row.get("activated_at") or "") > str(latest.get("activated_at") or ""):
            latest = row
    archived = set(((latest or {}).get("vocabulary") or {}).get("streams") or [])
    _policy, active = engine.active_policy(db)
    here = set((active.vocabulary or {}).get("streams") or [])
    if archived <= here:
        return
    engine.activate_policy(db, active.body, actor=f"import:{plan.import_id}", streams=here | archived)


def _remember(db: Session, plan: Plan, fam: Family, key: str, local_key: str, created: bool, form: dict) -> None:
    rm = db.scalar(select(PortabilityRowMap).where(PortabilityRowMap.origin == plan.origin,
                                                   PortabilityRowMap.family == fam.name,
                                                   PortabilityRowMap.source_key == key))
    if rm is None:
        db.add(PortabilityRowMap(origin=plan.origin, family=fam.name, source_key=key, local_key=local_key,
                                 import_id=plan.import_id, created=created, content_sha256=_digest(form)))
    else:
        rm.content_sha256 = _digest(form)


def _local_key(fam: Family, obj) -> str:
    pk = [c.name for c in fam.model.__table__.primary_key.columns]
    return "|".join(str(getattr(obj, _attr(fam, c))) for c in pk)


def _load_chunk(db: Session, plan: Plan, fam: Family, chunk: dict, pending: dict, report: dict) -> None:
    for key, row in chunks.read_chunk(plan.checkpoint / chunk["file"], fam.name):
        if plan.selected is not None and not _kept(plan, fam, row):
            continue
        local, rm = find_local(db, plan, fam, key, row)
        if local is not None:
            form = as_archived(archive_form(plan, fam, local, key), row)
            if form == row or fam.name in REFERENCE_ONLY or _installation_defined(fam, local, row) or \
                    (fam.name in RECONCILE_IGNORES and _reconciles(fam, local, row, form)):
                if rm is None:
                    _remember(db, plan, fam, key, _local_key(fam, local), False, form)
                report["identical"] += 1
                continue
            if rm is None or rm.content_sha256 != _digest(form):
                resolution = (plan.decisions.get("catalogue_conflicts") or {}).get(f"{fam.name}:{key}") \
                    if fam.name in CATALOGUE_RESOLVABLE else None
                if resolution == "keep_local":
                    # No row-map entry: this archive's content was not adopted here, so a future
                    # import (a new job, possibly a newer export) must ask again rather than treat
                    # this origin as trusted to auto-update it from here on.
                    report["identical"] += 1
                    continue
                if resolution != "use_archive":
                    raise ImportBlocked(f"{fam.name} {key} exists here with different content", "divergent",
                                        {"family": fam.name, "key": key, "fields": _differs(row, form)[:10],
                                         "same_origin": rm is not None})
            for attr, v in _values(plan, fam, row, with_deferred=True).items():
                setattr(local, attr, v)
            db.flush()
            _remember(db, plan, fam, key, _local_key(fam, local), False, archive_form(plan, fam, local, key))
            report["updated"] += 1
            continue
        values = _values(plan, fam, row, with_deferred=False)
        missing = _missing_refs(db, fam, values, pending)
        if missing:
            if (plan.decisions.get("unresolved_references") or "block") != "defer":
                raise ImportBlocked(f"{fam.name} {key} refers to what is neither here nor in the archive",
                                    "unresolved_reference", {"family": fam.name, "key": key, "missing": missing})
            nullable = {c.name: c.nullable for c in fam.model.__table__.columns}
            if not all(nullable[c] for c, _ in missing):
                report["deferred"].append({"family": fam.name, "key": key, "missing": missing, "row": "left out"})
                continue
            for c, _ in missing:
                values[_attr(fam, c)] = None
            report["deferred"].append({"family": fam.name, "key": key, "missing": missing, "row": "loaded"})
        if fam.name == "types":
            _ensure_owner(db, plan, values.get("workspace_id"))
        obj = fam.model(**values)
        db.add(obj)
        db.flush()
        _remember(db, plan, fam, key, _local_key(fam, obj), True, archive_form(plan, fam, obj, key))
        report["created"] += 1


def _ensure_owner(db: Session, plan: Plan, ws: Optional[str]) -> None:
    """A shared type's owner workspace, when this instance does not have it: a stub, so the type
    keeps its identity. It appears with the rest of the import, at promotion."""
    if not ws or db.get(Workspace, ws) is not None:
        return
    db.add(Workspace(id=ws, name=ws, is_global=True))
    db.flush()
    db.add(PortabilityRowMap(origin=plan.origin, family="workspaces", source_key=plan.unmap_ws(ws), local_key=ws,
                             import_id=plan.import_id, created=True, content_sha256=None))


def _deferred(db: Session, plan: Plan, fam: Family, pending: dict, report: dict) -> None:
    for _, key, row in archive_rows(plan, fam):
        values = {k: v for k, v in _values(plan, fam, row, with_deferred=True).items()
                  if k in {_attr(fam, c) for c in fam.deferred}}
        if not any(v is not None for v in values.values()):
            continue
        local, _ = find_local(db, plan, fam, key, row)
        if local is None:
            continue
        for attr, v in values.items():
            setattr(local, attr, v)
        db.flush()
        _remember(db, plan, fam, key, _local_key(fam, local), False, archive_form(plan, fam, local, key))


def _replace(db: Session, plan: Plan, fam: Family) -> None:
    """An increment states a set-valued family whole: what this origin wrote earlier and the set no
    longer holds goes. Nothing another origin or a person here wrote is touched."""
    keys = {key for _, key, _ in archive_rows(plan, fam)}
    for rm in list(db.scalars(select(PortabilityRowMap).where(PortabilityRowMap.origin == plan.origin,
                                                               PortabilityRowMap.family == fam.name,
                                                               PortabilityRowMap.created.is_(True)))):
        if rm.source_key in keys:
            continue
        local = _by_local_key(db, fam, rm.local_key)
        if local is not None:
            db.delete(local)
        db.delete(rm)
    db.flush()


def _by_local_key(db: Session, fam: Family, local_key: str):
    pk = [c for c in fam.model.__table__.primary_key.columns]
    parts = local_key.split("|")
    vals = [int(p) if str(c.type) in ("INTEGER", "BIGINT") else p for c, p in zip(pk, parts)]
    return db.get(fam.model, vals[0] if len(vals) == 1 else tuple(vals))


# --------------------------------------------------------------------------- rebuild

def _imported(db: Session, plan: Plan, family: str) -> list[PortabilityRowMap]:
    return list(db.scalars(select(PortabilityRowMap).where(PortabilityRowMap.origin == plan.origin,
                                                           PortabilityRowMap.family == family)))


def rebuild(db: Session, plan: Plan) -> dict:
    """Projections from the ledger alone: bindings and heads replayed from events, then the engine's
    own rebuild (fact state, attributes, status, derived relations, conflicts), then the conflicts
    the engine keeps only as events. Returns what the rebuild itself wrote to the audit."""
    from app.ledger import engine
    from app.ledger.engine import DERIVED_CONFLICTS
    from app.models.asset import Asset
    from app.portability import jobs
    jobs.report("rebuilding what the ledger derives (identities, heads, facts, relations)", force=True)
    before = {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in EVENT_TABLES}
    with writing(db):
        adopted = _adopt_unbacked_relations(db, plan)
        refs = {db.get(IdentityEvent, int(rm.local_key)).source_ref for rm in _imported(db, plan, "identity_events")}
        for ref in sorted(refs):
            state = None
            for ev in db.scalars(select(IdentityEvent).where(IdentityEvent.source_ref == ref).order_by(IdentityEvent.seq)):
                state = None if ev.kind == "unbound" else ev.uid
            b = db.get(IdentityBinding, ref)
            if state is None and b is not None:
                db.delete(b)
            elif state is not None and b is None:
                db.add(IdentityBinding(source_ref=ref, uid=state))
            elif state is not None:
                b.uid = state
        db.flush()
        for rm in _imported(db, plan, "streams"):
            sid = rm.local_key
            revs = list(db.scalars(select(SourceRevision).where(SourceRevision.stream_id == sid,
                                                                SourceRevision.ordering == "head")
                                   .order_by(SourceRevision.number)))
            pub = db.scalar(select(RevisionEvent).where(RevisionEvent.stream_id == sid,
                                                        RevisionEvent.kind.in_(("published", "rewound_to")))
                            .order_by(RevisionEvent.seq.desc()).limit(1))
            head = db.get(StreamHead, sid) or StreamHead(stream_id=sid)
            head.parsed_head = revs[-1].id if revs else None
            head.parsed_number = revs[-1].number if revs else 0
            published = db.get(SourceRevision, pub.revision_id) if pub else None
            head.published_head = published.id if published else None
            head.published_number = published.number if published else 0
            db.add(head)
        db.flush()
        for ws in plan.workspaces:
            if db.get(Workspace, ws) is not None:
                engine.rebuild(db, ws)
        uids = set(db.scalars(select(Asset.uid).where(Asset.workspace_id.in_(plan.workspaces))))
        last: dict = {}
        for ev in db.scalars(select(ConflictEvent).where(ConflictEvent.subject_uid.in_(uids),
                                                         ConflictEvent.conflict_type.in_(DERIVED_CONFLICTS))
                             .order_by(ConflictEvent.seq)):
            last[ev.conflict_id] = ev
        for cid, ev in last.items():
            here = db.get(Conflict, cid)
            if ev.kind == "opened" and here is None:
                rec = db.get(Asset, ev.subject_uid)
                db.add(Conflict(conflict_id=cid, conflict_type=ev.conflict_type,
                                severity="blocking" if ev.conflict_type == "merge_installation_overlap" else "non-blocking",
                                workspace_id=rec.workspace_id, subject_uid=ev.subject_uid, predicate=ev.predicate,
                                member=ev.member, detail=ev.detail or {}, opened_seq=ev.seq))
            elif ev.kind != "opened" and here is not None:
                db.delete(here)
        db.flush()
        # A record's timestamps are not ledger state: loading references and rebuilding touched them,
        # the archive has them.
        for fam in plan.families():
            if "updated_at" not in fam.columns or "uid" not in fam.key:
                continue
            for _, key, row in archive_rows(plan, fam):
                if row.get("updated_at"):
                    db.execute(update(fam.model).where(fam.model.uid == row["uid"])
                               .values(updated_at=from_json(fam.model, "updated_at", row["updated_at"]))
                               .execution_options(synchronize_session=False))
        db.flush()
    db.expire_all()
    _refresh_row_map(db, plan)
    after = {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in EVENT_TABLES}
    return {"events_written_by_rebuild": {k: after[k] - before[k] for k in after if after[k] != before[k]},
            "relations_kept_without_ledger_facts": adopted}


def _ledger_managed(db: Session, uid: str) -> bool:
    """What engine.rebuild re-projects: a record with an identity binding or a decision."""
    return bool(db.scalar(select(IdentityBinding.uid).where(IdentityBinding.uid == uid).limit(1))
                or db.scalar(select(Decision.decision_id).where(Decision.subject_uid == uid).limit(1)))


def _adopt_unbacked_relations(db: Session, plan: Plan) -> int:
    """A `ledger` relation is a projection and travels as one; a rebuild makes it again from the record's facts.
    A record with no ledger facts at all (no binding, no decision) is not re-projected, and its ledger relations
    were exported with nothing to make them from: INFN Cloud's medium-linac had 208 (its Installations' `installed
    at` and `installation of` among them), and every import dropped them. They are kept as the source had them —
    the record's facts, whatever made them — and the derive stage builds on them (realized by)."""
    from app.models.asset import Asset, Relation
    fam = BY_NAME["p_derived_relations"]
    if fam.name not in plan.manifest["families"]:
        return 0
    managed: dict = {}
    n = 0
    for _, _, row in archive_rows(plan, fam):
        if row.get("derivation") != "ledger":
            continue
        if plan.selected is not None and _names_unselected(plan, fam, row):
            continue
        m = _mapped_row(plan, fam, row)
        frm, to = m.get("from_asset_uid"), m.get("to_asset_uid")
        if frm not in managed:
            managed[frm] = _ledger_managed(db, frm)
        if managed[frm] or db.get(Asset, frm) is None or db.get(Asset, to) is None:
            continue
        here = db.scalar(select(Relation.id).where(
            Relation.from_asset_uid == frm, Relation.to_asset_uid == to, Relation.relation_type == m["relation_type"],
            Relation.derivation == "ledger").limit(1))
        if here is None:
            db.add(Relation(workspace_id=m["workspace_id"], from_asset_uid=frm, to_asset_uid=to,
                            relation_type=m["relation_type"], derivation="ledger", rule=m.get("rule")))
        n += 1
    db.flush()
    return n


def _refresh_row_map(db: Session, plan: Plan) -> None:
    """Record each row as this import leaves it — after the rebuild and the timestamp restore — so a
    later increment can tell a row nobody here changed from one a person changed."""
    for rm in db.scalars(select(PortabilityRowMap).where(PortabilityRowMap.origin == plan.origin,
                                                         PortabilityRowMap.import_id == plan.import_id)):
        fam = BY_NAME.get(rm.family)
        if fam is None or fam.sequenced or fam.name in REFERENCE_ONLY:
            continue
        obj = _by_local_key(db, fam, rm.local_key)
        if obj is not None:
            rm.content_sha256 = _digest(archive_form(plan, fam, obj, rm.source_key))
    db.flush()


# --------------------------------------------------------------------------- reconcile

def reconcile(db: Session, plan: Plan, deferred: Optional[list] = None) -> dict:
    """Authoritative families row by row against the archive (and so against the manifest's hashes),
    projections rebuilt here against the projections the export carried, invariants."""
    explained = {(d["family"], d["key"]) for d in (deferred or [])}
    fams: dict = {}
    from app.portability import jobs
    total = sum((plan.manifest["families"].get(f.name) or {}).get("rows") or 0 for f in plan.families()) or None
    seen = 0
    for fam in plan.families():
        jobs.report(f"reconciling {fam.name}", seen, total, force=True)
        h = hashlib.sha256()
        mismatches = []
        rows = 0
        for c in plan.manifest["families"][fam.name]["chunks"]:
            ch = hashlib.sha256()
            for key, row in chunks.read_chunk(plan.checkpoint / c["file"], fam.name):
                seen += 1
                if seen % 200 == 0:
                    jobs.report(f"reconciling {fam.name}", seen, total)
                if plan.selected is not None and not _kept(plan, fam, row):
                    continue
                local, _ = find_local(db, plan, fam, key, row)
                form = archive_form(plan, fam, local, key) if local is not None else {}
                same = _reconciles(fam, local, row, form)
                # A "keep what's here" catalogue resolution (importer.CATALOGUE_RESOLVABLE) is exactly
                # as deliberate as identities (REFERENCE_ONLY) staying local: this row's own divergence
                # was already decided at execute time, not left for reconciliation to flag again.
                kept_local = (fam.name in CATALOGUE_RESOLVABLE and local is not None and
                             (plan.decisions.get("catalogue_conflicts") or {}).get(f"{fam.name}:{key}") == "keep_local")
                if not same and (fam.name, key) not in explained and fam.name not in REFERENCE_ONLY and not kept_local:
                    mismatches.append({"key": key, "missing": local is None,
                                       "fields": sorted(_differs(row, as_archived(form, row)))[:10]})
                # A row accepted as the archive's (a built-in role, a relation's stamp) is hashed as the archive has
                # it, so staging and promotion, each with its own local stamps, agree.
                ch.update(chunks.line(fam.name, key, row if same else form))
                rows += 1
            h.update(ch.hexdigest().encode())
        expected = plan.manifest["families"][fam.name]
        fams[fam.name] = {"rows": rows, "expected_rows": expected["rows"], "sha256": h.hexdigest(),
                          "expected_sha256": expected["sha256"], "mismatches": mismatches[:20],
                          "mismatch_count": len(mismatches),
                          "ok": not mismatches and (rows == expected["rows"] or plan.selected is not None),
                          "selective": plan.selected is not None}
    projections = _compare_projections(db, plan)
    from app.ledger import invariants
    local_inv = invariants.report(db, [w for w in plan.workspaces if db.get(Workspace, w) is not None])
    exported_ok = (plan.manifest.get("invariants") or {}).get("ok")
    inv_ok = bool(local_inv.get("ok")) or exported_ok is False
    authoritative_ok = all(f["ok"] for f in fams.values())
    projections_ok = all(p["ok"] for p in projections.values())
    # Decision `projections: accept_rebuilt`: the projections are what this release rebuilds from the archive's
    # ledger, not what the source had (an archive from an older release, whose projections were stale or derived
    # by older rules). Only when every authoritative row is the archive's: then an invariant failing here fails on
    # the source's own data, and is listed, not hidden.
    accepting = plan.decisions.get("projections") == PROJECTIONS_ACCEPT and authoritative_ok
    accepted = None
    if accepting and not (projections_ok and inv_ok):
        accepted = {"decision": PROJECTIONS_ACCEPT,
                    "archive_release": (plan.manifest.get("argus") or {}).get("application_version"),
                    "this_release": os.environ.get("ARGUS_VERSION", "1.0.0"),
                    "projections": sorted(k for k, p in projections.items() if not p["ok"]),
                    "invariants": [] if inv_ok else list(local_inv.get("failing") or [])}
    passed = authoritative_ok and ((projections_ok and inv_ok) or accepted is not None)
    failing = list(local_inv.get("failing") or [])
    return {"import_id": plan.import_id, "export_id": plan.manifest["export_id"], "origin": plan.origin,
            "watermark": plan.manifest["watermark"], "families": fams, "projections": projections,
            "invariants": {"ok": local_inv.get("ok"), "exported_ok": exported_ok, "acceptable": inv_ok,
                           "failing": failing,
                           "examples": {k: ((local_inv.get("invariants") or {}).get(k) or {}).get("examples", [])[:5]
                                        for k in failing}},
            "accepted": accepted, "deferred_references": deferred or [], "passed": passed}


def _differs(expected: dict, got: dict) -> list[str]:
    """Which fields differ, naming keys inside JSON objects too — never their values."""
    out = []
    for k in set(expected) | set(got):
        a, b = expected.get(k), got.get(k)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            out += [f"{k}.{sub}" for sub in sorted(set(a) | set(b)) if a.get(sub) != b.get(sub)]
        else:
            out.append(k)
    return out


PROJECTION_TIMESTAMPS = ("created_at", "updated_at")   # when a projection row was derived, not what it says


def _proj_key(fam: Family, row: dict) -> str:
    row = {k: v for k, v in row.items() if k not in PROJECTION_TIMESTAMPS}
    detail = row.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("values"), list):
        # A conflict's values are a set (engine: sorted since 1.35.132; an older archive has them in arrival order).
        row["detail"] = {**detail, "values": sorted(detail["values"],
                                                   key=lambda v: json.dumps(v, sort_keys=True, default=str))}
    return json.dumps(row, sort_keys=True, default=str)


def _names_unselected(plan: Plan, fam: Family, row: dict) -> bool:
    idx = _index(plan)
    return any(row.get(c) in idx and idx[row[c]] not in plan.selected for c in fam.subjects)


def _compare_projections(db: Session, plan: Plan) -> dict:
    out = {}
    sc = Scope(workspaces=plan.workspaces, watermark={})
    for fam in [f for f in FAMILIES if f.group == "projection" and f.name in plan.manifest["families"]]:
        outside = 0
        exported = set()
        for _, _, row in archive_rows(plan, fam):
            if plan.selected is not None and _names_unselected(plan, fam, row):
                outside += 1              # derived from records this selective import did not take
                continue
            exported.add(_proj_key(fam, _mapped_row(plan, fam, row)))
        local = set()
        for obj in db.scalars(fam.select(db, sc)):
            row = {c: to_json(getattr(obj, _attr(fam, c))) for c in fam.columns}
            local.add(_proj_key(fam, row))
        only_exported, only_local = sorted(exported - local), sorted(local - exported)
        out[fam.name] = {"exported": len(exported), "rebuilt": len(local), "ok": not only_exported and not only_local,
                         "outside_selection": outside,
                         "only_in_export": [json.loads(x) for x in only_exported[:5]],
                         "only_rebuilt": [json.loads(x) for x in only_local[:5]]}
    return out


# --------------------------------------------------------------------------- finalize, discard

def origin_chain(plan: Plan) -> tuple[list[dict], str]:
    """The origin chain of an archive: every row of its append-only ledger families (for a selective
    import, of the chosen workspaces), in family and archive order, with the hash of its archive line.
    Returns the rows and the hash of the whole chain."""
    out, h = [], hashlib.sha256()
    for name in ORIGIN_CHAIN:
        fam = BY_NAME[name]
        if name not in plan.manifest["families"]:
            continue
        for _, key, row in archive_rows(plan, fam):
            line_hash = hashlib.sha256(chunks.line(name, key, row)).hexdigest()
            when = row.get("at") or row.get("retrieved_at") or row.get("created_at")
            out.append({"family": name, "key": key, "hash": line_hash, "at": when})
            h.update(f"{name}:{key}:{line_hash}\n".encode())
    return out, h.hexdigest()


def promote(db: Session, plan: Plan, staged: dict, actor: str, probe: Optional[Callable] = None) -> dict:
    """Finalization: load the verified archive into the ACTIVE database, rebuild and reconcile there,
    write the origin chain and its local ingestion event, and record the chain position — all in the
    caller's single transaction. Raises (and the caller rolls back) unless the result equals the
    staged reconciliation. `probe` lets a test look at the instance from outside before commit."""
    plan.ingested_at = datetime.now(timezone.utc)
    report = execute(db, plan, set(), lambda _s: None)
    rebuilt = rebuild(db, plan)
    rec = reconcile(db, plan, report["deferred"])
    if not rec["passed"]:
        raise ImportBlocked("the import reconciled in staging but not on promotion", "promotion_mismatch",
                            {"families": {k: v for k, v in rec["families"].items() if not v["ok"]},
                             "projections": {k: v for k, v in rec["projections"].items() if not v["ok"]}})
    for name, fam in rec["families"].items():
        if name in REFERENCE_ONLY:
            continue                         # people are references, kept as known here; not compared
        if staged.get("families", {}).get(name, {}).get("sha256") not in (None, fam["sha256"]):
            raise ImportBlocked(f"{name} differs between staging and promotion", "promotion_mismatch")
    chain, chain_sha = origin_chain(plan)
    manifest_sha = plan.manifest_sha256
    by_family: dict = defaultdict(int)
    for r in chain:
        by_family[r["family"]] += 1
    ingestion = PortabilityEvent(subject_kind="import", subject_id=plan.import_id, kind="ingested", actor=actor,
                                 detail={"origin_instance_id": plan.origin, "export_id": plan.manifest["export_id"],
                                         "origin_checkpoint_hash": manifest_sha, "origin_chain_sha256": chain_sha,
                                         "origin_rows": dict(by_family),
                                         "watermark_vector_sha256": plan.manifest["watermark"]["vector_sha256"]},
                                 at=plan.ingested_at)
    db.add(ingestion)
    db.flush()
    maps = {(m.family, m.source_key): m.local_key for m in db.scalars(select(PortabilityRowMap).where(
        PortabilityRowMap.origin == plan.origin, PortabilityRowMap.import_id == plan.import_id))}
    for pos, r in enumerate(chain):
        local = maps.get((r["family"], r["key"]))
        if local is None:
            continue                         # already here from an earlier import of this origin
        db.add(PortabilityOriginRecord(
            import_id=plan.import_id, origin_instance_id=plan.origin, origin_family=r["family"],
            origin_sequence=r["key"], origin_recorded_at=from_json(BY_NAME["decisions"].model, "at", r["at"])
            if isinstance(r["at"], str) else None, origin_event_hash=r["hash"], origin_checkpoint_hash=manifest_sha,
            local_table=BY_NAME[r["family"]].table, local_key=local, local_ingested_at=plan.ingested_at,
            local_ingestion_event_id=ingestion.seq, position=pos))
    position = db.scalar(select(func.coalesce(func.max(PortabilityChainLink.position), 0)).where(
        PortabilityChainLink.origin == plan.origin)) + 1
    db.add(PortabilityChainLink(origin=plan.origin, export_id=plan.manifest["export_id"], position=position,
                                watermark_label=plan.manifest["watermark"]["checkpoint_sequence"],
                                vector_sha256=plan.manifest["watermark"]["vector_sha256"],
                                manifest_sha256=manifest_sha, import_id=plan.import_id))
    db.flush()
    if probe is not None:
        probe()
    rec["rebuild"] = rebuilt
    rec["origin_chain"] = {"sha256": chain_sha, "rows": len(chain), "ingestion_event": ingestion.seq}
    return rec


def verify_chain(db: Session, import_id: str) -> dict:
    """Recompute the origin chain of a finalized import from the rows here: every imported ledger row
    must still serialize to the archive line it came from, and the chain to its recorded hash."""
    from app.models.portability import PortabilityImport
    imp = db.get(PortabilityImport, import_id)
    ingestion = db.scalar(select(PortabilityEvent).where(PortabilityEvent.subject_id == import_id,
                                                         PortabilityEvent.kind == "ingested"))
    if imp is None or ingestion is None:
        return {"ok": False, "reason": "no ingestion recorded for this import"}
    plan = Plan(import_id=import_id, origin=ingestion.detail["origin_instance_id"], mode=imp.mode,
                checkpoint=Path("."), manifest=imp.manifest, blob_dir=Path("."), attachments_dir=Path("."),
                decisions=imp.decisions or {})
    bad = []
    for rec in db.scalars(select(PortabilityOriginRecord).where(PortabilityOriginRecord.import_id == import_id)
                          .order_by(PortabilityOriginRecord.position)):
        fam = BY_NAME[rec.origin_family]
        obj = _by_local_key(db, fam, rec.local_key)
        if obj is None:
            bad.append({"family": rec.origin_family, "key": rec.origin_sequence, "problem": "missing"})
            continue
        form = archive_form(plan, fam, obj, rec.origin_sequence)
        if hashlib.sha256(chunks.line(fam.name, rec.origin_sequence, form)).hexdigest() != rec.origin_event_hash:
            bad.append({"family": rec.origin_family, "key": rec.origin_sequence, "problem": "changed"})
    return {"ok": not bad, "problems": bad[:50], "origin_chain_sha256": ingestion.detail["origin_chain_sha256"],
            "ingestion_event": ingestion.seq}
