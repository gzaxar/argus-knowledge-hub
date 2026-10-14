"""GLPI connections of a workspace (docs/glpi.md): set up with protected credentials, discovered, mapped
(entities, GLPI's own schema), previewed and imported; and the decisions on records GLPI stopped listing.

Every step that reads GLPI reads it live, through the interfaces it exposes; nothing reads its database. A
run may be pinned to the snapshot its preview was made from (`expect_digest`): if GLPI changed in between,
the run stops and returns the new plan instead.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.auth import OidcIdentity, get_grants, get_identity, require_permission
from app.db import get_db
from app.integrations.glpi import discovery, importer, mapping, schema, source
from app.models.import_config import ImportConfig
from app.models.import_job import ImportJob
from app.services.crypto import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/v1/glpi", tags=["glpi"])


class GlpiConnectionIn(BaseModel):
    name: str
    base_url: str
    user_token: Optional[str] = None      # omit on update to keep the stored one
    app_token: Optional[str] = None
    verify_tls: bool = True
    key_prefix: str = "GLPI"
    documents: bool = True
    tickets: bool = True


class GlpiEntityMapIn(BaseModel):
    entity_map: list[dict]


class GlpiAuthorityIn(BaseModel):
    records: str = "argus"
    tickets: str = "argus"


class GlpiSchemaApproveIn(BaseModel):
    digest: str


class GlpiRunIn(BaseModel):
    expect_digest: Optional[str] = None


class RetirementDecisionIn(BaseModel):
    ref: str
    decision: str              # retire | keep
    reason: Optional[str] = None


def _actor(identity) -> str:
    return identity.user.id if isinstance(identity, OidcIdentity) else "api-token"


def _owner(db: Session, identity, workspace_id: str) -> None:
    from app.routers.workspaces import _require_owner_or_admin
    _require_owner_or_admin(workspace_id, identity, db)


def _config(db: Session, uid: str, workspace_id: str) -> ImportConfig:
    c = db.get(ImportConfig, uid)
    if c is None or c.workspace_id != workspace_id or c.source != "glpi":
        raise HTTPException(status_code=404, detail="No such GLPI connection")
    return c


def _out(c: ImportConfig) -> dict:
    p = dict(c.params or {})
    return {"uid": c.uid, "name": c.name, "workspace_id": c.workspace_id, "base_url": p.get("base_url"),
            "verify_tls": p.get("verify_tls", True), "key_prefix": p.get("key_prefix", "GLPI"),
            "documents": p.get("documents", True), "tickets": p.get("tickets", True),
            "has_credentials": bool(c.encrypted_secret), "entity_map": p.get("entity_map") or [],
            "authority": {"records": "argus", "tickets": "argus", **(p.get("authority") or {})},
            "discovery": p.get("discovery"), "schema_status": (p.get("schema") or {}).get("status"),
            "last_digest": p.get("last_digest"), "last_run_at": c.last_run_at,
            "last_import_job_uid": c.last_import_job_uid}


def _set(c: ImportConfig, **values) -> None:
    c.params = {**(c.params or {}), **values}
    flag_modified(c, "params")


def read_live(c: ImportConfig) -> dict:
    """A snapshot of the connection's GLPI, read now (replaced in tests)."""
    secret = json.loads(decrypt_secret(c.encrypted_secret)) if c.encrypted_secret else {}
    if not secret.get("user_token"):
        raise HTTPException(status_code=422, detail="This connection has no user token")
    p = c.params or {}
    try:
        with source.LegacyClient(p["base_url"], secret["user_token"], secret.get("app_token"),
                                 verify=p.get("verify_tls", True)) as client:
            return source.read(client)
    except source.GlpiError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "code": "glpi"})


def document_reader(c: ImportConfig):
    secret = json.loads(decrypt_secret(c.encrypted_secret)) if c.encrypted_secret else {}
    p = c.params or {}

    def read(document_id):
        with source.LegacyClient(p["base_url"], secret["user_token"], secret.get("app_token"),
                                 verify=p.get("verify_tls", True)) as client:
            return client.document(document_id)
    return read


def snapshot_digest(snapshot: dict) -> str:
    body = {k: v for k, v in snapshot.items() if k not in ("read_at", "files")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _settings(c: ImportConfig) -> importer.Settings:
    try:
        return importer.Settings.of(c.params or {}, c.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# --------------------------------------------------------------------------- connections

@router.get("/connections")
def list_connections(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    return [_out(c) for c in db.scalars(select(ImportConfig).where(ImportConfig.workspace_id == workspace_id,
                                                                 ImportConfig.source == "glpi"))]


@router.post("/connections", status_code=201)
def create_connection(body: GlpiConnectionIn, identity=Depends(get_identity),
                      workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """A GLPI connection, its tokens encrypted (never returned). Give it a GLPI API client and a user whose
    profile can only read what is imported, in the entities imported (docs/glpi.md)."""
    _owner(db, identity, workspace_id)
    if not body.user_token:
        raise HTTPException(status_code=422, detail="A GLPI user token is needed")
    c = ImportConfig(uid=str(uuid.uuid4()), workspace_id=workspace_id, name=body.name, source="glpi",
                     merge_strategy="ledger",
                     params={"base_url": body.base_url.rstrip("/"), "verify_tls": body.verify_tls,
                             "key_prefix": body.key_prefix, "documents": body.documents, "tickets": body.tickets},
                     encrypted_secret=encrypt_secret(json.dumps({"user_token": body.user_token,
                                                                 "app_token": body.app_token})))
    db.add(c)
    db.commit()
    return _out(c)


@router.put("/connections/{uid}")
def update_connection(uid: str, body: GlpiConnectionIn, identity=Depends(get_identity),
                      workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    c.name = body.name
    _set(c, base_url=body.base_url.rstrip("/"), verify_tls=body.verify_tls, key_prefix=body.key_prefix,
         documents=body.documents, tickets=body.tickets)
    if body.user_token:
        c.encrypted_secret = encrypt_secret(json.dumps({"user_token": body.user_token, "app_token": body.app_token}))
    db.commit()
    return _out(c)


@router.delete("/connections/{uid}", status_code=204)
def delete_connection(uid: str, identity=Depends(get_identity),
                      workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """Forget the connection and its credentials. The records it imported stay (their GLPI identities too)."""
    _owner(db, identity, workspace_id)
    db.delete(_config(db, uid, workspace_id))
    db.commit()


# --------------------------------------------------------------------------- discovery and mapping

@router.post("/connections/{uid}/discover")
def discover(uid: str, identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
             db: Session = Depends(get_db)):
    """Read GLPI now and record what it is: version, APIs, entities, item types, custom assets and fields,
    plugins. Proposes an entity mapping (if there is none) and GLPI's schema as ARGUS types and fields."""
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    snap = read_live(c)
    return _discovered(db, c, snap)


def _discovered(db: Session, c: ImportConfig, snap: dict) -> dict:
    found = discovery.discover(snap)
    proposal = schema.propose(db, c.workspace_id, snap)
    state = dict((c.params or {}).get("schema") or {})
    state["proposal"] = proposal
    state["status"] = schema.status(state, snap)
    values = {"discovery": found, "schema": state}
    if not (c.params or {}).get("entity_map"):
        values["entity_map"] = mapping.default_entity_map(snap, c.workspace_id)
    _set(c, **values)
    db.commit()
    return {"discovery": found, "entity_map": (c.params or {}).get("entity_map"), "schema": state}


@router.get("/connections/{uid}")
def get_connection(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    c = _config(db, uid, workspace_id)
    return {**_out(c), "schema": (c.params or {}).get("schema")}


@router.put("/connections/{uid}/entity-map")
def set_entity_map(uid: str, body: GlpiEntityMapIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """Which GLPI entities go to which workspaces (each entry: entity_id, workspace_id, recursive). The
    person setting it must be able to create records and tickets in every workspace it names."""
    from app.services.permissions import resolve_permission
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    for e in body.entity_map:
        target = e.get("workspace_id")
        if e.get("entity_id") is None or not target:
            raise HTTPException(status_code=422, detail="each entry names an entity_id and a workspace_id")
        if isinstance(identity, OidcIdentity) and not identity.user.is_admin and not all(
                resolve_permission(db, identity.user, target, "create", r) for r in ("objects", "tickets")):
            raise HTTPException(status_code=403, detail=f"You may not create records and tickets in {target}")
    _set(c, entity_map=body.entity_map)
    db.commit()
    return _out(c)


@router.put("/connections/{uid}/authority")
def set_authority(uid: str, body: GlpiAuthorityIn, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """Who wins when a field was edited here and GLPI changes it: argus (the local value stays, the
    difference is reported) or glpi (GLPI's applies; a field edited here goes to review in the ledger)."""
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    for v in (body.records, body.tickets):
        if v not in importer.AUTHORITIES:
            raise HTTPException(status_code=422, detail=f"authority is one of {', '.join(importer.AUTHORITIES)}")
    _set(c, authority={"records": body.records, "tickets": body.tickets})
    db.commit()
    return _out(c)


@router.post("/connections/{uid}/schema/approve")
def approve_schema(uid: str, body: GlpiSchemaApproveIn, identity=Depends(get_identity),
                   workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """Approve the proposal that was reviewed (named by its digest): create the workspace types and fields it
    proposes. A proposal made since — GLPI's schema changed — is not approved by an older digest."""
    from app.services.permissions import resolve_permission
    _owner(db, identity, workspace_id)
    if isinstance(identity, OidcIdentity) and not identity.user.is_admin and not \
            resolve_permission(db, identity.user, workspace_id, "approve", "objects"):
        raise HTTPException(status_code=403, detail="Approving a schema change needs approve on objects")
    c = _config(db, uid, workspace_id)
    state = dict((c.params or {}).get("schema") or {})
    proposal = state.get("proposal")
    if not proposal:
        raise HTTPException(status_code=409, detail="Discover first: there is no proposal")
    if proposal["digest"] != body.digest:
        raise HTTPException(status_code=409, detail={"error": "GLPI's schema changed since this proposal was made",
                                                     "digest": proposal["digest"]})
    state["approved"] = schema.approve(db, workspace_id, proposal, _actor(identity))
    state["status"] = "approved"
    state.setdefault("history", []).append({"digest": proposal["digest"], "at": state["approved"]["at"],
                                            "by": _actor(identity), "changes": proposal.get("changes", 0)})
    _set(c, schema=state)
    db.commit()
    return state


# --------------------------------------------------------------------------- preview and import

@router.post("/connections/{uid}/preview")
def preview(uid: str, identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
            grants=Depends(get_grants), db: Session = Depends(get_db)):
    """What importing now would do in each workspace: records created, updated (which fields), unchanged;
    conflicts with local edits and how the authority policy settles them; records GLPI no longer lists
    (retirement candidates); tickets; documents; custom types awaiting schema review; entities outside the map."""
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    snap = read_live(c)
    _discovered(db, c, snap)
    report = importer.redact(importer.plan(db, _settings(c), snap), grants)
    db.rollback()
    return {**report, "digest": snapshot_digest(snap)}


@router.post("/connections/{uid}/run")
def run(uid: str, body: GlpiRunIn, identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
        grants=Depends(get_grants), db: Session = Depends(get_db)):
    """Import now. With `expect_digest` (from the preview), only if GLPI still holds what was previewed."""
    _owner(db, identity, workspace_id)
    c = _config(db, uid, workspace_id)
    snap = read_live(c)
    digest = snapshot_digest(snap)
    if body.expect_digest and body.expect_digest != digest:
        report = importer.redact(importer.plan(db, _settings(c), snap), grants)
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": "GLPI changed since the preview", "digest": digest,
                                                     "plan": report})
    return importer.redact(_run(db, c, snap, _actor(identity), digest), grants)


def _run(db: Session, c: ImportConfig, snap: dict, actor: str, digest: str) -> dict:
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=c.workspace_id, source="glpi", status="running",
                    started_at=datetime.now(timezone.utc))
    db.add(job)
    db.flush()
    try:
        report = importer.run(db, _settings(c), snap, actor, document_reader=document_reader(c) if c.encrypted_secret else None)
    except Exception as e:
        db.rollback()
        job = ImportJob(uid=job.uid, workspace_id=c.workspace_id, source="glpi", status="failed", error=str(e)[:2000],
                        completed_at=datetime.now(timezone.utc))
        db.merge(job)
        db.commit()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "glpi_import"})
    job.status, job.completed_at = "done", datetime.now(timezone.utc)
    job.counts = {ws: {"created": len(r["creates"]), "updated": len(r["updates"]), "unchanged": r["unchanged"],
                       "conflicts": len(r["conflicts"]), "retirement_candidates": len(r["retirement_candidates"]),
                       "tickets": r.get("tickets_result"), "documents": r.get("documents_result")}
                  for ws, r in report["workspaces"].items()}
    job.warnings = [f"{x['records']} {x['itemtype']} awaiting schema review" for x in report["awaiting_schema_review"]]
    c.last_run_at, c.last_import_job_uid = job.completed_at, job.uid
    _set(c, last_digest=digest)
    db.commit()
    return {**report, "digest": digest, "job_uid": job.uid}


# --------------------------------------------------------------------------- retirement candidates

@router.get("/connections/{uid}/retirement-candidates")
def retirement_candidates(uid: str, workspace_id: str = Depends(require_permission("read")),
                          db: Session = Depends(get_db)):
    """Records GLPI no longer lists (or has in its trash) that nobody has decided on yet."""
    from app.models.asset import Asset
    from app.models.ledger import Conflict
    from app.services.visibility import can_see
    c = _config(db, uid, workspace_id)
    inst = mapping.instance_id((c.params or {})["base_url"])
    out = []
    for row in db.scalars(select(Conflict).where(Conflict.workspace_id == workspace_id,
                                                 Conflict.conflict_type == importer.RETIREMENT,
                                                 Conflict.detail["instance"].astext == inst)):
        asset = db.get(Asset, row.subject_uid)
        if asset is None or not can_see(asset):
            continue
        out.append({"ref": row.detail.get("source"), "uid": asset.uid, "key": asset.key, "name": asset.name,
                    "type": asset.type, "reason": row.detail.get("reason")})
    return out


@router.post("/connections/{uid}/retirement-candidates")
def decide(uid: str, body: RetirementDecisionIn, identity=Depends(get_identity),
           workspace_id: str = Depends(require_permission("modify")), db: Session = Depends(get_db)):
    """Retire a record GLPI no longer lists, or keep it as an ARGUS record. The import stops stating it."""
    c = _config(db, uid, workspace_id)
    try:
        done = importer.decide_retirement(db, workspace_id, _settings(c), body.ref, body.decision, _actor(identity),
                                          body.reason)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    key = "retired_refs" if body.decision == "retire" else "kept_refs"
    _set(c, **{key: sorted(set((c.params or {}).get(key) or []) | {body.ref})})
    db.commit()
    return done
