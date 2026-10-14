"""Portable exports and imports (docs/export-import-design.md §14, §20).

Mounted under /v1/portability/: /v1/imports already belongs to the Jira, Insight and Git import jobs.

People only: an API token cannot request, approve, generate, publish or import an archive. What else
is needed follows the portability policy (`app.portability.policy`, shown by `GET /config`):

* requesting a workspace export needs the policy's right on each workspace (`read` under the trusted
  policy, `approve` under the strict one); a full export, restricted classes and `full_identity` need
  an instance administrator;
* approving needs an instance administrator, and for high-risk work step-up (`auth_time`, or under the
  trusted policy a recent session plus `confirm: true`) and, if the policy requires it, a second person;
* generating and publishing need an instance administrator or, once approved, the requester;
* imports into existing workspaces need their administration rights (trusted policy) — new workspaces
  and the instance need an instance administrator; approving an archive with uninspected content needs
  `acknowledge_uninspected: true`.

Every step is a state transition, audited in `portability_events`, and idempotent. Long steps take
`?background=true` and return a job to poll (`GET /v1/portability/jobs/{id}`).
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.db import engine as db_engine
from app.db import get_db
from app.models.portability import PortabilityExport, PortabilityImport
from app.portability import jobs, service
from app.portability.lifecycle import TransitionError
from app.routers.ledger import actor_of
from app.services.permissions import has_permission, resolve_permission

exports_router = APIRouter(prefix="/v1/portability/exports", tags=["portability"])
imports_router = APIRouter(prefix="/v1/portability/imports", tags=["portability"])
config_router = APIRouter(prefix="/v1/portability", tags=["portability"])

from app.portability import signing, ui_config  # noqa: E402


def _person(identity) -> OidcIdentity:
    if not isinstance(identity, OidcIdentity):
        raise HTTPException(status_code=403, detail={"error": "portable exports and imports are for people, not API "
                                                              "tokens", "code": "forbidden"})
    return identity


def _admin(identity) -> OidcIdentity:
    person = _person(identity)
    if not person.user.is_admin:
        raise HTTPException(status_code=403, detail={"error": "this needs an instance administrator",
                                                      "code": "forbidden"})
    return person


def _guard(fn):
    try:
        return fn()
    except service.ServiceError as e:
        raise HTTPException(status_code=e.status, detail={"error": str(e), "code": e.code, **e.detail}) from e
    except TransitionError as e:
        raise HTTPException(status_code=e.status, detail={"error": str(e), "code": e.code}) from e


def _export(db: Session, export_id: str, identity) -> PortabilityExport:
    exp = db.get(PortabilityExport, export_id)
    person = _person(identity)
    if exp is None or not (person.user.is_admin or exp.requested_by == actor_of(person)):
        raise HTTPException(status_code=404, detail="Export not found")
    return exp


def _import(db: Session, import_id: str, identity) -> PortabilityImport:
    imp = db.get(PortabilityImport, import_id)
    person = _person(identity)
    if imp is None or not (person.user.is_admin or imp.requested_by == actor_of(person)):
        raise HTTPException(status_code=404, detail="Import not found")
    return imp


def _may_import(db: Session, imp: PortabilityImport, identity, cfg: service.Config) -> None:
    """Approving, executing and finalizing an import: an instance administrator, or — under the trusted
    policy — someone who administers every (existing) workspace the import writes into."""
    from app.models.workspace import Workspace
    person = _person(identity)
    if person.user.is_admin:
        return
    if cfg.policy.import_permission != "workspace_admin" or not imp.manifest:
        raise HTTPException(status_code=403, detail={"error": "this import needs an instance administrator",
                                                      "code": "forbidden"})
    plan = service._plan(imp, cfg, staged=False)
    missing = [w for w in plan.workspaces if db.get(Workspace, w) is None]
    if missing:
        raise HTTPException(status_code=403, detail={"error": f"new workspaces ({', '.join(missing)}) need an instance "
                                                              "administrator", "code": "forbidden"})
    lacking = [w for w in plan.workspaces if not has_permission(db, person.user, w, "manage_members", "workspace")]
    if lacking:
        raise HTTPException(status_code=403, detail={"error": f"you do not administer {', '.join(lacking)}",
                                                      "code": "forbidden"})


def _commit(db: Session, view: dict) -> dict:
    db.commit()
    return view


def _step_up(identity, confirm: bool) -> tuple[bool, str]:
    if not isinstance(identity, OidcIdentity):
        return False, "not a person"
    return service.step_up(identity.claims, service.config(), confirm)


def _background(kind: str, subject_id: str, action: str, actor: str, fn) -> JSONResponse:
    job = jobs.start(SessionLocal, kind, subject_id, action, actor, fn)
    return JSONResponse(status_code=202, content={"job": job})


# --------------------------------------------------------------------------- configuration, jobs

@config_router.get("/config")
def portability_config(identity=Depends(get_identity)):
    """What a person can choose from, and the policy in force: registered repositories and artifact
    stores (names only, never URLs or paths), signing and verification set-up, restricted classes,
    modes, outcomes — and every relaxed choice of the policy."""
    _person(identity)
    from app.portability import closure, envelope, exporter, identity_policy
    from app.portability import policy as policy_mod
    from app.portability.blob_scan import DECISIONS as BLOB_OUTCOMES
    from app.services.visibility import restricted_classes
    cfg = service.config()
    return {"repositories": sorted(cfg.repositories), "artifact_stores": sorted(cfg.stores),
            # Chosen as the artifact store: the data is committed with the checkpoint in its repository.
            "repository_store": service.REPOSITORY_STORE,
            "signing": {"configured": cfg.signer is not None and cfg.signer.key_path.exists(),
                        "key_id": cfg.signer.key_id if cfg.signer is not None and cfg.signer.key_path.exists() else None,
                        "principal": cfg.signer.principal if cfg.signer is not None else None,
                        # Public: what another installation pastes into its trusted keys to accept these exports.
                        "public_line": (signing.allowed_signers_line(cfg.signer).strip()
                                        if cfg.signer is not None and cfg.signer.key_path.exists() else None)},
            "trusted_keys": cfg.trusted is not None and cfg.trusted.exists(),
            "restricted_classes": list(restricted_classes()),
            "restricted_destinations": {k: sorted(v) for k, v in cfg.restricted_destinations.items()
                                        if k in cfg.repositories},
            "encryption_recipients": sorted(k for k, v in cfg.recipients.items() if v.exists()),
            "recipients": ({k: [r.name for r in envelope.load_recipients(v)] for k, v in cfg.recipients.items()
                            if v.exists()} if identity.user.is_admin else {}),
            "identity_profiles": list(identity_policy.PROFILES), "default_identity_profile": identity_policy.DEFAULT,
            "purposes": list(policy_mod.PURPOSES), "purpose_profiles": policy_mod.PURPOSE_PROFILE,
            "blob_outcomes": list(BLOB_OUTCOMES), "step_up_seconds": cfg.step_up_seconds,
            "policy": cfg.policy.describe(),
            "export_modes": [m for m in exporter.MODES if m != "backup-reference"],
            "import_modes": list(service.IMPORT_MODES), "outcomes": sorted(closure.OUTCOMES),
            "is_admin": bool(identity.user.is_admin),
            "ui_config": {"enabled": ui_config.enabled(),
                          "sources": {"repositories": (cfg.sources or {}).get("repositories", {}),
                                      "signing_key": "web" if (cfg.sources or {}).get("signing_key") == "web"
                                      else ("deployment" if cfg.signer is not None else None),
                                      "trusted_keys": (cfg.sources or {}).get("trusted_keys")
                                      or ("deployment" if cfg.trusted is not None else None)}}}


# --------------------------------------------------------------------------- set-up from the web app

class RepositoryIn(BaseModel):
    name: str
    url: str
    provider: Optional[str] = None
    token: Optional[str] = None
    confirm: bool = False


class FingerprintsIn(BaseModel):
    fingerprints: list[str] = Field(default_factory=list)
    confirm: bool = False


class TokenIn(BaseModel):
    token: str
    confirm: bool = False


class TestIn(BaseModel):
    write: bool = False


class TrustedKeyIn(BaseModel):
    line: str
    note: Optional[str] = None
    confirm: bool = False


class SigningKeyIn(BaseModel):
    principal: Optional[str] = None
    confirm: bool = False


class RepositoryUpdateIn(BaseModel):
    url: Optional[str] = None
    provider: Optional[str] = None
    confirm: bool = False


class NoteIn(BaseModel):
    note: Optional[str] = None
    confirm: bool = False


class StoreIn(BaseModel):
    name: str
    note: Optional[str] = None
    confirm: bool = False


class SetupConfirmIn(BaseModel):
    confirm: bool = False


class ApproveIn(BaseModel):
    kind: str
    id: str
    confirm: bool = False


def _setup(identity, confirm: Optional[bool]) -> tuple[str, "service.Config"]:
    """An administrator, signed in recently or confirming it (the step-up exports use), for any change to
    where archives go and which keys are trusted."""
    person = _admin(identity)
    if confirm is not None:
        ok, how = _step_up(person, confirm)
        if not ok:
            raise HTTPException(status_code=401, detail={"error": f"confirm it is you before changing the set-up "
                                                                  f"({how})", "code": "step_up_required"})
    return actor_of(person), service.config()


def _ui(fn):
    try:
        return fn()
    except ui_config.ConfigError as e:
        raise HTTPException(status_code=e.status, detail={"error": str(e), "code": e.code}) from e


@config_router.get("/setup")
def portability_setup(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The set-up administrators manage here: repositories, trusted keys, signing keys (no secrets), next to
    what the deployment configures (names only), and whether this is switched on."""
    _admin(identity)
    return ui_config.view(db, service.config())


@config_router.post("/setup/repositories", status_code=201)
def add_repository(body: RepositoryIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Register a repository. For SSH, ARGUS makes the deploy key and returns only its public half, with the
    server's host-key fingerprints to confirm; for https, the token is kept encrypted and never shown."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.add_repository(db, cfg, actor, name=body.name, url=body.url,
                                                            provider=body.provider, token=body.token)))


@config_router.post("/setup/repositories/{name}")
def update_repository(name: str, body: RepositoryUpdateIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Change a registered repository's address or provider."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.update_repository(db, cfg, actor, name, url=body.url,
                                                               provider=body.provider)))


@config_router.post("/setup/stores", status_code=201)
def add_store(body: StoreIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Register an artifact store: a directory in the portability area."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.add_store(db, cfg, actor, body.name, body.note)))


@config_router.post("/setup/stores/{name}/remove", status_code=204)
def remove_store(name: str, body: Optional[SetupConfirmIn] = None, identity=Depends(get_identity),
                 db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, bool(body and body.confirm))
    _ui(lambda: ui_config.remove_store(db, cfg, actor, name))
    db.commit()


@config_router.post("/setup/trusted-keys/{key_id}/note")
def note_trusted_key(key_id: str, body: NoteIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.update_trusted_key(db, cfg, actor, key_id, body.note)))


@config_router.post("/setup/repositories/{name}/host-keys/read")
def read_host_keys(name: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, None)
    return _commit(db, _ui(lambda: ui_config.rescan_host_keys(db, cfg, actor, name)))


@config_router.post("/setup/repositories/{name}/host-keys/confirm")
def confirm_host_keys(name: str, body: FingerprintsIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.confirm_host_keys(db, cfg, actor, name, body.fingerprints)))


@config_router.post("/setup/repositories/{name}/token")
def replace_token(name: str, body: TokenIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.set_token(db, cfg, actor, name, body.token)))


@config_router.post("/setup/repositories/{name}/test")
def test_repository(name: str, body: Optional[TestIn] = None, identity=Depends(get_identity),
                    db: Session = Depends(get_db)):
    """Read the repository (and, with `write`, push and delete a test branch): before using it."""
    actor, cfg = _setup(identity, None)
    return _commit(db, _ui(lambda: ui_config.test_repository(db, cfg, actor, name, write=bool(body and body.write))))


@config_router.post("/setup/repositories/{name}/remove", status_code=204)
def remove_repository(name: str, body: Optional[SetupConfirmIn] = None, identity=Depends(get_identity),
                      db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, bool(body and body.confirm))
    _ui(lambda: ui_config.remove_repository(db, cfg, actor, name))
    db.commit()


@config_router.post("/setup/trusted-keys", status_code=201)
def add_trusted_key(body: TrustedKeyIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Trust another installation's exports: paste its allowed-signers line."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.add_trusted_key(db, cfg, actor, body.line, body.note)))


@config_router.post("/setup/trusted-keys/{key_id}/remove", status_code=204)
def remove_trusted_key(key_id: str, body: Optional[SetupConfirmIn] = None, identity=Depends(get_identity),
                       db: Session = Depends(get_db)):
    actor, cfg = _setup(identity, bool(body and body.confirm))
    _ui(lambda: ui_config.remove_trusted_key(db, cfg, actor, key_id))
    db.commit()


@config_router.post("/setup/signing-key", status_code=201)
def generate_signing_key(body: SigningKeyIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Make this installation's signing key (when the deployment configures none); returns the public line to
    give to the installations that import from this one."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.generate_signing_key(db, cfg, actor, body.principal)))


@config_router.post("/setup/approve")
def approve_setup(body: ApproveIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Another administrator activates a registration (policies with separation of duties)."""
    actor, cfg = _setup(identity, body.confirm)
    return _commit(db, _ui(lambda: ui_config.approve(db, cfg, actor, body.kind, body.id)))


@config_router.get("/jobs/{job_id}")
def get_job(job_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _person(identity)
    out = jobs.get(db, job_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return out


@config_router.get("/jobs")
def list_jobs(subject: str = Query(...), identity=Depends(get_identity), db: Session = Depends(get_db)):
    _person(identity)
    return jobs.for_subject(db, subject)


class HoldIn(BaseModel):
    on: bool = True
    reason: str = ""


# --------------------------------------------------------------------------- exports

class ExportIn(BaseModel):
    mode: str = "workspace"
    workspaces: list[str] = Field(default_factory=list)
    classifications: list[str] = Field(default_factory=list)
    repository: Optional[str] = None
    artifact_store: Optional[str] = None
    recipients: list[str] = Field(default_factory=list)
    decisions: dict = Field(default_factory=dict)
    base_export_id: Optional[str] = None
    identity_profile: Optional[str] = None
    purpose: Optional[str] = None


NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff"}


@exports_router.post("", status_code=201)
def create_export(body: ExportIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    cfg = service.config()
    if body.mode in ("full",) or body.classifications or body.identity_profile == "full_identity" or body.recipients:
        _admin(identity)
    right = "read" if cfg.policy.export_permission == "read" else "approve"
    for ws in body.workspaces:
        if not resolve_permission(db, person.user, ws, right, "objects"):
            raise HTTPException(status_code=403, detail={"error": f"exporting {ws} needs its {right} right",
                                                          "code": "forbidden"})
    exp = _guard(lambda: service.create_export(
        db, actor_of(person), mode=body.mode, workspaces=body.workspaces, classifications=body.classifications,
        destination={"repository": body.repository, "artifact_store": body.artifact_store,
                     **({"recipients": body.recipients} if body.recipients else {})},
        decisions=body.decisions, base_export_id=body.base_export_id, identity_profile=body.identity_profile,
        purpose=body.purpose, cfg=cfg))
    _guard(lambda: service.analyse_export(db, exp, actor_of(person), cfg))
    return _commit(db, service.export_view(exp))


@exports_router.get("")
def list_exports(identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    q = select(PortabilityExport).order_by(PortabilityExport.created_at.desc()).limit(200)
    if not person.user.is_admin:
        q = q.where(PortabilityExport.requested_by == actor_of(person))
    return [service.export_view(e) for e in db.scalars(q)]


@exports_router.get("/{export_id}")
def get_export(export_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    return service.export_view(_export(db, export_id, identity))


class DecisionsIn(BaseModel):
    decisions: dict


@exports_router.post("/{export_id}/decisions")
def decide_export(export_id: str, body: DecisionsIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    exp = _export(db, export_id, identity)
    _guard(lambda: service.set_export_decisions(db, exp, body.decisions, actor_of(identity), service.config()))
    return _commit(db, service.export_view(exp))


class ConfirmIn(BaseModel):
    confirm: bool = False


@exports_router.post("/{export_id}/approve")
def approve_export(export_id: str, body: Optional[ConfirmIn] = None, identity=Depends(get_identity),
                   db: Session = Depends(get_db)):
    exp = _export(db, export_id, identity)
    ok, how = _step_up(identity, bool(body and body.confirm))
    _guard(lambda: service.approve_export(db, exp, actor_of(identity), admin=_person(identity).user.is_admin,
                                          fresh_auth=ok, cfg=service.config(), step_up_how=how))
    return _commit(db, service.export_view(exp))


def _may_run(exp: PortabilityExport, identity) -> None:
    person = _person(identity)
    if not (person.user.is_admin or (exp.requested_by == actor_of(person) and exp.approved_by)):
        raise HTTPException(status_code=403, detail={"error": "this needs an instance administrator or, once approved, "
                                                              "the requester", "code": "forbidden"})


@exports_router.post("/{export_id}/generate")
def generate_export(export_id: str, body: Optional[ConfirmIn] = None, background: bool = False,
                    identity=Depends(get_identity), db: Session = Depends(get_db)):
    exp = _export(db, export_id, identity)
    _may_run(exp, identity)
    ok, _how = _step_up(identity, bool(body and body.confirm))
    actor = actor_of(identity)

    def run(s: Session):
        return service.generate_export(db_engine, s, s.get(PortabilityExport, export_id), actor, service.config(),
                                       fresh_auth=ok)
    if background:
        return _background("export", export_id, "generate", actor, run)
    exp = _guard(lambda: run(db))
    return _commit(db, service.export_view(exp))


@exports_router.post("/{export_id}/publish-git")
def publish_export(export_id: str, background: bool = False, identity=Depends(get_identity),
                   db: Session = Depends(get_db)):
    exp = _export(db, export_id, identity)
    _may_run(exp, identity)
    actor = actor_of(identity)

    def run(s: Session):
        return service.publish_export(s, s.get(PortabilityExport, export_id), actor, service.config())
    if background:
        return _background("export", export_id, "publish-git", actor, run)
    exp = _guard(lambda: run(db))
    return _commit(db, service.export_view(exp))


@exports_router.get("/{export_id}/manifest")
def export_manifest(export_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    exp = _export(db, export_id, identity)
    if exp.manifest is None:
        raise HTTPException(status_code=409, detail={"error": "not generated yet", "code": "not_ready"})
    return {"manifest": exp.manifest, "sha256": exp.manifest_sha256}


@exports_router.post("/{export_id}/download-token")
def download_token(export_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """A single-use, five-minute token for an out-of-band download (an operator's tool), sent as the
    `X-Download-Token` header. Prefer `GET /archive` with your own credentials."""
    _admin(identity)
    exp = _export(db, export_id, identity)
    return _commit(db, _guard(lambda: service.download_token(db, exp, actor_of(identity))))


@exports_router.get("/{export_id}/archive")
def archive(export_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The checkpoint's files as a tar, with the caller's own credentials: no capability in a URL."""
    from app.portability.lifecycle import audit
    exp = _export(db, export_id, identity)
    _may_run(exp, identity)
    if not exp.out_dir or exp.purged_at or exp.state not in ("ready_to_publish", "publishing", "published"):
        raise HTTPException(status_code=409, detail={"error": "no local archive (not generated, or past retention)",
                                                      "code": "not_ready"})
    audit(db, exp, "download", actor_of(identity), {"via": "session"})
    db.commit()
    return Response(service.archive_tar(exp), media_type="application/x-tar",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{exp.id}.tar"'})


@exports_router.get("/{export_id}/download")
def download(export_id: str, token: Optional[str] = Query(None), x_download_token: Optional[str] = Header(None),
             db: Session = Depends(get_db)):
    """The checkpoint as a tar, for a single-use token in the `X-Download-Token` header. A token in the
    query string is refused unless the policy enables it and the operator confirmed proxy redaction."""
    exp = db.get(PortabilityExport, export_id)
    if exp is None or not exp.out_dir or exp.purged_at:
        raise HTTPException(status_code=404, detail="Export not found")
    if token and not x_download_token and not service.config().policy.query_tokens_allowed():
        raise HTTPException(status_code=400, detail={"error": "send the token in the X-Download-Token header; query-string "
                                                              "tokens are disabled", "code": "query_token_disabled"})
    _guard(lambda: service.consume_download_token(db, exp, x_download_token or token or ""))
    return Response(service.archive_tar(exp), media_type="application/x-tar",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{exp.id}.tar"'})


@exports_router.post("/{export_id}/download-tokens/revoke")
def revoke_tokens(export_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    exp = _export(db, export_id, identity)
    n = service.revoke_download_tokens(db, exp, actor_of(identity))
    return _commit(db, {"revoked": n})


class RevokeIn(BaseModel):
    reason: str


@exports_router.post("/{export_id}/revoke")
def revoke_export(export_id: str, body: RevokeIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    exp = _export(db, export_id, identity)
    _guard(lambda: service.revoke_export(db, exp, actor_of(identity), body.reason))
    return _commit(db, service.export_view(exp))


@exports_router.post("/{export_id}/legal-hold")
def export_legal_hold(export_id: str, body: HoldIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    exp = _export(db, export_id, identity)
    _guard(lambda: service.set_legal_hold(db, exp, body.on, body.reason, actor_of(identity)))
    return _commit(db, service.export_view(exp))


# --------------------------------------------------------------------------- imports

class ImportIn(BaseModel):
    mode: str = "clone"
    repository: Optional[str] = None
    ref: Optional[str] = None
    expected_commit: Optional[str] = None
    repository_id: Optional[str] = None
    decisions: dict = Field(default_factory=dict)


@imports_router.post("", status_code=201)
def create_import(body: ImportIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    cfg = service.config()
    if cfg.policy.import_permission == "instance_admin" or body.mode == "restore":
        _admin(identity)
    source = {k: v for k, v in {"repository": body.repository, "ref": body.ref, "expected_commit": body.expected_commit,
                                "repository_id": body.repository_id}.items() if v}
    imp = _guard(lambda: service.create_import(db, actor_of(person), mode=body.mode, source=source,
                                               decisions=body.decisions, cfg=cfg))
    return _commit(db, service.import_view(imp))


@imports_router.get("")
def list_imports(identity=Depends(get_identity), db: Session = Depends(get_db)):
    person = _person(identity)
    q = select(PortabilityImport).order_by(PortabilityImport.created_at.desc()).limit(200)
    if not person.user.is_admin:
        q = q.where(PortabilityImport.requested_by == actor_of(person))
    return [service.import_view(i) for i in db.scalars(q)]


@imports_router.get("/{import_id}")
def get_import(import_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    return service.import_view(_import(db, import_id, identity))


LONG = ("fetch-git", "verify", "execute", "resume", "finalize")


def _step(name: str):
    def endpoint(import_id: str, background: bool = False, identity=Depends(get_identity),
                 db: Session = Depends(get_db)):
        imp = _import(db, import_id, identity)
        cfg = service.config()
        actor = actor_of(identity)
        if name in ("execute", "resume", "finalize"):
            _may_import(db, imp, identity, cfg)

        def run(s: Session):
            row = s.get(PortabilityImport, import_id)
            return {"fetch-git": lambda: service.fetch_git(s, row, actor, cfg),
                    "verify": lambda: service.verify_import(s, row, actor, cfg),
                    "execute": lambda: service.execute(s, row, actor, cfg),
                    "resume": lambda: service.execute(s, row, actor, cfg),
                    "finalize": lambda: service.finalize(s, row, actor, cfg)}[name]()
        if background:
            return _background("import", import_id, name, actor, run)
        out = _guard(lambda: run(db))
        return _commit(db, service.import_view(out))
    endpoint.__name__ = f"import_{name.replace('-', '_')}"
    return endpoint


for _name in LONG:
    imports_router.add_api_route(f"/{{import_id}}/{_name}", _step(_name), methods=["POST"])


class ApproveImportIn(BaseModel):
    acknowledge_uninspected: bool = False


@imports_router.post("/{import_id}/approve")
def approve_import(import_id: str, body: Optional[ApproveImportIn] = None, identity=Depends(get_identity),
                   db: Session = Depends(get_db)):
    imp = _import(db, import_id, identity)
    cfg = service.config()
    _may_import(db, imp, identity, cfg)
    out = _guard(lambda: service.approve_import(db, imp, actor_of(identity),
                                                acknowledge_uninspected=bool(body and body.acknowledge_uninspected),
                                                cfg=cfg))
    return _commit(db, service.import_view(out))


class DiscardIn(BaseModel):
    reason: str = ""


@imports_router.post("/{import_id}/discard")
def discard(import_id: str, body: Optional[DiscardIn] = None, identity=Depends(get_identity),
            db: Session = Depends(get_db)):
    """Abandon an import: its staging database and quarantine go; its audit trail stays."""
    imp = _import(db, import_id, identity)
    out = _guard(lambda: service.discard(db, imp, actor_of(identity), service.config(), body.reason if body else ""))
    return _commit(db, service.import_view(out))


@imports_router.post("/{import_id}/legal-hold")
def import_legal_hold(import_id: str, body: HoldIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    _admin(identity)
    imp = _import(db, import_id, identity)
    _guard(lambda: service.set_legal_hold(db, imp, body.on, body.reason, actor_of(identity)))
    return _commit(db, service.import_view(imp))


@imports_router.get("/{import_id}/origin-chain")
def origin_chain(import_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Recompute the origin chain of a finalized import from the rows here."""
    from app.portability import importer
    _import(db, import_id, identity)
    return importer.verify_chain(db, import_id)


class DryRunIn(BaseModel):
    decisions: dict = Field(default_factory=dict)


@imports_router.post("/{import_id}/dry-run")
def dry_run(import_id: str, body: Optional[DryRunIn] = None, background: bool = False,
            identity=Depends(get_identity), db: Session = Depends(get_db)):
    """What executing would do, row by row. With `background`, a job the page follows, reporting the family it
    is checking and how many rows of the archive it has gone through."""
    imp = _import(db, import_id, identity)
    actor, decisions = actor_of(identity), (body.decisions if body else None)
    if background:
        from app.models.portability import PortabilityImport as _Imp

        def run(s):
            return service.dry_run(s, s.get(_Imp, import_id), actor, service.config(), decisions)
        return _background("import", import_id, "dry-run", actor, run)
    out = _guard(lambda: service.dry_run(db, imp, actor, service.config(), decisions))
    return _commit(db, {**service.import_view(out), "dry_run": out.dry_run})


@imports_router.post("/{import_id}/upload")
async def upload(import_id: str, file: UploadFile = File(...), identity=Depends(get_identity),
                 db: Session = Depends(get_db)):
    imp = _import(db, import_id, identity)
    cfg = service.config()
    data = await file.read(cfg.limits.max_chunk_bytes * 8 + 1)
    out = _guard(lambda: service.upload(db, imp, actor_of(identity), data, cfg))
    return _commit(db, service.import_view(out))


@imports_router.get("/{import_id}/reconciliation")
def reconciliation(import_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    imp = _import(db, import_id, identity)
    if imp.reconciliation is None:
        raise HTTPException(status_code=409, detail={"error": "not reconciled yet", "code": "not_ready"})
    return {"report": imp.reconciliation, "sha256": imp.reconciliation_sha256}


@imports_router.get("/{import_id}/provenance")
def provenance(import_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    return service.provenance(db, _import(db, import_id, identity))


@imports_router.get("/{import_id}/evidence")
def evidence_families(import_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    imp = _import(db, import_id, identity)
    out = _guard(lambda: service.evidence_families(db, imp, service.config(), identity.user, actor_of(identity)))
    return _commit(db, out)


@imports_router.get("/{import_id}/evidence/{family}")
def evidence(import_id: str, family: str, offset: int = 0, limit: int = Query(50, le=500),
             identity=Depends(get_identity), db: Session = Depends(get_db)):
    imp = _import(db, import_id, identity)
    out = _guard(lambda: service.evidence_rows(db, imp, service.config(), family, offset, limit,
                                               viewer=identity.user, actor=actor_of(identity)))
    return _commit(db, out)



# --------------------------------------------------------------------------- periodic exports

class ScheduleIn(BaseModel):
    export_id: str
    every_minutes: int = Field(1440, description="at least 60, at most 31 days")
    chain: str = Field("incremental", description="incremental: an increment on the last publication; "
                                                  "complete: a complete export each time")
    skip_unchanged: bool = True
    confirm: bool = False


class ScheduleChangeIn(BaseModel):
    enabled: Optional[bool] = None
    every_minutes: Optional[int] = None
    chain: Optional[str] = None
    skip_unchanged: Optional[bool] = None


def _schedule(db: Session, schedule_id: str):
    from app.models.portability import PortabilitySchedule
    sched = db.get(PortabilitySchedule, schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return sched


@config_router.get("/schedules")
def list_schedules(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Exports repeated at an interval (app/portability/schedules.py). Administrators."""
    from app.models.portability import PortabilitySchedule
    from app.portability import schedules
    _admin(identity)
    return [schedules.view(s) for s in db.scalars(select(PortabilitySchedule).order_by(PortabilitySchedule.created_at))]


@config_router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Repeat a published Git export every `every_minutes`. Setting it is the standing approval of its runs: an
    administrator; for a high-risk export, a recent sign-in and (with separation of duties) not its requester."""
    from app.portability import schedules
    person = _admin(identity)
    exp = _export(db, body.export_id, identity)
    ok, how = _step_up(identity, body.confirm)
    sched = _guard(lambda: schedules.create(db, exp, actor_of(person), every_minutes=body.every_minutes,
                                            chain=body.chain, skip_unchanged=body.skip_unchanged, admin=True,
                                            fresh_auth=ok, step_up_how=how, cfg=service.config()))
    return _commit(db, schedules.view(sched))


@config_router.put("/schedules/{schedule_id}")
def change_schedule(schedule_id: str, body: ScheduleChangeIn, identity=Depends(get_identity),
                    db: Session = Depends(get_db)):
    """Switch a schedule off or on, or change how often and how it runs."""
    from app.portability import schedules
    person = _admin(identity)
    sched = _schedule(db, schedule_id)
    _guard(lambda: schedules.change(db, sched, actor_of(person), enabled=body.enabled,
                                    every_minutes=body.every_minutes, skip_unchanged=body.skip_unchanged,
                                    chain=body.chain))
    return _commit(db, schedules.view(sched))


@config_router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Stop repeating the export. What it published stays published."""
    from app.portability import schedules
    person = _admin(identity)
    schedules.remove(db, _schedule(db, schedule_id), actor_of(person))
    db.commit()
    return Response(status_code=204)


@config_router.post("/schedules/{schedule_id}/run", status_code=202)
def run_schedule(schedule_id: str, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Run it now, in the background, as its next run would."""
    from app.portability import schedules
    person = _admin(identity)
    _schedule(db, schedule_id)

    def run(s: Session):
        from app.models.portability import PortabilitySchedule
        out = schedules.run_now(db_engine, s, s.get(PortabilitySchedule, schedule_id), service.config())
        if out["outcome"] == "failed":
            raise service.ServiceError(out["message"], "schedule_run_failed", 409)
        return out
    return _background("schedule", schedule_id, "run-schedule", actor_of(person), run)

ROUTERS = (config_router, exports_router, imports_router)
