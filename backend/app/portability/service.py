"""Exports and imports as lifecycles: what the API and the CLI call.

Configuration (environment; docs/operations.md):

  ARGUS_PORTABILITY_ROOT                  working area: checkpoints, quarantine, evidence, clones, staging files
  ARGUS_PORTABILITY_REPOSITORIES          name=url,…  the only repositories ARGUS publishes to or fetches
                                          from (an API caller names one; it never passes a URL)
  ARGUS_PORTABILITY_ARTIFACT_STORES       name=/path,…  content-addressed artifact stores
  ARGUS_PORTABILITY_SIGNING_KEY           the Ed25519 signing key (a mounted secret, never in a repository)
  ARGUS_PORTABILITY_TRUSTED_KEYS          allowed-signers file of the keys an import trusts
  ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS  repository=class|class,…  repositories approved for restricted
                                          classes; an export with restricted classes goes nowhere else
  ARGUS_PORTABILITY_RECIPIENTS            repository=/path,…  recipient public keys (X25519) per destination
  ARGUS_PORTABILITY_DECRYPTION_KEYS       a directory of recipient private keys, mounted for an import session only
  ARGUS_PORTABILITY_EVIDENCE_READERS      user ids or e-mails allowed to read restricted rows of evidence archives
  ARGUS_PORTABILITY_STEP_UP_SECONDS       how recent a sign-in must be for high-risk steps (default 300)
  ARGUS_PORTABILITY_STAGING_URL           the server for staging databases (default: the active one)
  ATTACHMENTS_DIR                         where imported files land
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import shutil
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.portability import (PortabilityDownloadToken, PortabilityEvent, PortabilityExport, PortabilityImport,
                                    PortabilityTagSeen)
from app.portability import (artifacts, chunks, closure, envelope, exporter, gitrepo, identity_policy, importer,
                             signing, staging)
from app.portability import policy as policy_mod
from app.portability.policy import Policy
from app.portability import verify as verifier
from app.portability.blob_scan import DECISIONS as BLOB_OUTCOMES
from app.portability.families import Scope
from app.portability.lifecycle import TransitionError, audit, expect, labels, move

HIGH_RISK_MODES = ("full", "evidence-only")
# The artifact store "in the repository": the export's data files are committed with its checkpoint, in the
# destination repository, instead of a separate store (gitrepo.publish; artifacts.GitTreeStore on import).
REPOSITORY_STORE = "@repository"
DOWNLOAD_TTL = timedelta(minutes=5)


@dataclass
class Config:
    root: Path
    attachments_dir: Path
    stores: dict = field(default_factory=dict)
    signer: Optional[signing.Signer] = None
    trusted: Optional[Path] = None
    repositories: dict = field(default_factory=dict)
    limits: chunks.Limits = chunks.LIMITS
    publish_reconciliation: bool = False
    restricted_destinations: dict = field(default_factory=dict)   # repository -> set of classes
    recipients: dict = field(default_factory=dict)                # repository -> recipients file
    decryption_keys: Optional[Path] = None
    evidence_readers: set = field(default_factory=set)
    step_up_seconds: int = 300
    policy: Policy = field(default_factory=Policy.trusted)
    repository_keys: dict = field(default_factory=dict)      # repository -> SSH deploy key file
    repository_tokens: dict = field(default_factory=dict)    # repository -> token file
    repository_known_hosts: dict = field(default_factory=dict)  # repository -> known_hosts (web app set-up)
    # Where each repository, signing key and trusted key came from: "deployment" or "web".
    sources: dict = field(default_factory=dict)

    def git_env(self, repository: Optional[str]) -> Optional[dict]:
        key, token = self.repository_keys.get(repository or ""), self.repository_tokens.get(repository or "")
        if key is None and token is None:
            return None
        return gitrepo.credentials_env(key, token, self.root / "git-askpass",
                                       known_hosts=self.repository_known_hosts.get(repository or ""))

    def export_dir(self, export_id: str) -> Path:
        return self.root / "exports" / export_id

    def repository_store(self, export_id: str, repository: str) -> artifacts.DirectoryStore:
        """Where an export's data files wait to be committed with it: named after its repository."""
        return artifacts.DirectoryStore(repository, self.root / "repository-stores" / export_id)

    def quarantine(self, import_id: str) -> Path:
        return self.root / "quarantine" / import_id

    def evidence(self, import_id: str) -> Path:
        return self.root / "evidence" / import_id

    def staged_files(self, import_id: str) -> Path:
        return self.root / "staging" / import_id

    def work(self, repository: str) -> Path:
        return self.root / "work" / hashlib.sha256(repository.encode()).hexdigest()[:16]

    def private_keys(self) -> list:
        return envelope.load_private_keys(self.decryption_keys)


def _pairs(name: str) -> dict:
    out = {}
    for item in filter(None, (os.environ.get(name) or "").split(",")):
        k, _, v = item.partition("=")
        out[k.strip()] = v.strip()
    return out


def config() -> Config:
    """The deployment's set-up, with what administrators registered in the web app added to it (when that is
    switched on: app/portability/ui_config.py)."""
    from app.portability import ui_config
    return ui_config.merged(_deployment_config())


def _deployment_config() -> Config:
    trusted = os.environ.get("ARGUS_PORTABILITY_TRUSTED_KEYS")
    keys = os.environ.get("ARGUS_PORTABILITY_DECRYPTION_KEYS")
    return Config(root=Path(os.environ.get("ARGUS_PORTABILITY_ROOT", "/data/portability")),
                  attachments_dir=Path(os.environ.get("ATTACHMENTS_DIR", "/data/attachments")),
                  stores=artifacts.configured_stores(), signer=signing.configured_signer(),
                  trusted=Path(trusted) if trusted else None, repositories=_pairs("ARGUS_PORTABILITY_REPOSITORIES"),
                  publish_reconciliation=os.environ.get("ARGUS_PORTABILITY_PUBLISH_RECONCILIATION") == "1",
                  restricted_destinations={k: set(filter(None, v.split("|"))) for k, v in
                                           _pairs("ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS").items()},
                  recipients={k: Path(v) for k, v in _pairs("ARGUS_PORTABILITY_RECIPIENTS").items()},
                  decryption_keys=Path(keys) if keys else None,
                  evidence_readers=set(filter(None, (os.environ.get("ARGUS_PORTABILITY_EVIDENCE_READERS") or "")
                                              .replace(" ", "").split(","))),
                  step_up_seconds=int(os.environ.get("ARGUS_PORTABILITY_STEP_UP_SECONDS", "300")),
                  policy=policy_mod.from_env(),
                  repository_keys={k: Path(v) for k, v in _pairs("ARGUS_PORTABILITY_REPOSITORY_KEYS").items()},
                  repository_tokens={k: Path(v) for k, v in _pairs("ARGUS_PORTABILITY_REPOSITORY_TOKENS").items()})


class ServiceError(ValueError):
    def __init__(self, message: str, code: str = "refused", status: int = 409, detail: Optional[dict] = None):
        super().__init__(message)
        self.code, self.status, self.detail = code, status, detail or {}


def _fail(db: Session, subject, actor: str, exc: Exception, to: str = "failed") -> None:
    db.rollback()
    subject = db.get(type(subject), subject.id)
    detail = {"error": str(exc), "code": getattr(exc, "code", "error"), **(getattr(exc, "detail", None) or {})}
    subject.error = detail
    try:
        move(db, subject, to, actor, "fail", {"code": detail["code"]})
    except TransitionError:
        audit(db, subject, "error", actor, {"code": detail["code"]})
    db.commit()


def fresh(claims: Optional[dict], cfg: Config, confirmed: bool = False) -> bool:
    return step_up(claims, cfg, confirmed)[0]


def step_up(claims: Optional[dict], cfg: Config, confirmed: bool = False) -> tuple[bool, str]:
    """Step-up authentication, and how it was satisfied (recorded in the audit):

    * `auth_time`, when the identity provider sends it, within `step_up_seconds`;
    * otherwise, under the `session_confirmation` policy, a session issued (`iat`) within
      `session_seconds` plus the person's explicit confirmation of the step;
    * nothing else. Under the `strict` policy only `auth_time` counts."""
    p = cfg.policy
    claims = claims or {}
    if claims.get("auth_time"):
        ok = time.time() - float(claims["auth_time"]) <= min(p.step_up_seconds, cfg.step_up_seconds)
        return ok, "auth_time" if ok else "auth_time too old"
    if p.step_up == "session_confirmation":
        if not confirmed:
            return False, "confirmation required (the identity provider sends no auth_time)"
        if claims.get("iat") and time.time() - float(claims["iat"]) <= p.session_seconds:
            return True, "recent session + confirmation"
        return False, "session too old: sign in again"
    return False, "auth_time required by policy"


def _peak_memory_mb() -> float:
    import resource
    import sys
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


# =========================================================================== exports

def _check_destination(mode: str, classifications: list[str], destination: dict, cfg: Config) -> None:
    """Restricted classes go only to a destination approved for each of them, and only encrypted."""
    if not classifications:
        return
    repo = destination.get("repository")
    approved = cfg.restricted_destinations.get(repo or "", set())
    missing = sorted(set(classifications) - approved)
    if not repo or missing:
        raise ServiceError(f"restricted classes {', '.join(missing or classifications)} may go only to a destination "
                           "approved for them (ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS)",
                           "restricted_destination_required", 422)
    if repo not in cfg.recipients or not cfg.recipients[repo].exists():
        raise ServiceError(f"{repo} has no encryption recipients: an unencrypted restricted export is not available",
                           "encryption_unavailable", 422)
    chosen = destination.get("recipients") or []
    known = {r.name for r in envelope.load_recipients(cfg.recipients[repo])}
    if not chosen:
        raise ServiceError("a restricted export needs an administrator to choose its approved recipient(s)",
                           "recipient_required", 422, {"recipients": sorted(known)})
    if set(chosen) - known:
        raise ServiceError(f"not approved recipients of {repo}: {sorted(set(chosen) - known)}", "invalid", 422)


def create_export(db: Session, actor: str, *, mode: str, workspaces: list[str], classifications: list[str],
                  destination: dict, decisions: Optional[dict] = None, base_export_id: Optional[str] = None,
                  identity_profile: Optional[str] = None, purpose: Optional[str] = None,
                  cfg: Config) -> PortabilityExport:
    if mode not in exporter.MODES:
        raise ServiceError(f"unknown mode {mode!r}", "invalid", 422)
    if destination.get("repository") and destination["repository"] not in cfg.repositories:
        raise ServiceError(f"repository {destination['repository']!r} is not registered", "invalid", 422)
    if destination.get("artifact_store") == REPOSITORY_STORE:
        if not destination.get("repository"):
            raise ServiceError("data kept in the repository needs a destination repository", "invalid", 422)
    elif destination.get("artifact_store") and destination["artifact_store"] not in cfg.stores:
        raise ServiceError(f"artifact store {destination['artifact_store']!r} is not configured", "invalid", 422)
    if purpose is not None and purpose not in policy_mod.PURPOSES:
        raise ServiceError(f"unknown purpose {purpose!r}; one of {', '.join(policy_mod.PURPOSES)}", "invalid", 422)
    profile = identity_profile or policy_mod.PURPOSE_PROFILE.get(purpose or "", identity_policy.DEFAULT)
    if profile not in identity_policy.PROFILES:
        raise ServiceError(f"unknown identity profile {profile!r}", "invalid", 422)
    if mode == "incremental":
        base = db.get(PortabilityExport, base_export_id or "")
        if not was_published(base):
            raise ServiceError("an incremental export needs a base export published to Git (expired since is fine: "
                               "its publication stays)", "invalid", 422)
        workspaces = list(base.workspaces)
        classifications = list(base.classifications)
        profile = (base.manifest or {}).get("identity", {}).get("profile", profile)
        destination = {**base.destination, **{k: v for k, v in destination.items() if v}}
    if mode not in ("full", "incremental") and not workspaces:
        raise ServiceError("choose at least one workspace", "invalid", 422)
    _check_destination(mode, classifications, destination, cfg)
    risk = "high" if mode in HIGH_RISK_MODES or classifications or \
        (profile in identity_policy.HIGH_RISK and cfg.policy.full_identity_high_risk) else "normal"
    exp = PortabilityExport(id=f"exp-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}", mode=mode,
                            workspaces=sorted(workspaces), classifications=sorted(classifications),
                            decisions={**(decisions or {}), "identity_profile": profile,
                                       **({"purpose": purpose} if purpose else {})}, destination=destination,
                            state="requested", risk=risk, requested_by=actor, base_export_id=base_export_id)
    db.add(exp)
    db.flush()
    audit(db, exp, "request", actor, {"mode": mode, "workspaces": exp.workspaces, "risk": risk,
                                      "classifications": exp.classifications, "identity_profile": profile,
                                      "purpose": purpose, "policy": cfg.policy.profile,
                                      "relaxations": cfg.policy.relaxations()}, None, "requested")
    return exp


def analyse_export(db: Session, exp: PortabilityExport, actor: str, cfg: Optional[Config] = None) -> PortabilityExport:
    cfg = cfg or config()
    from app.models.workspace import Workspace
    move(db, exp, "analysing", actor, "analyse")
    ws = exp.workspaces
    if exp.mode == "full" or (exp.mode == "incremental" and db.get(PortabilityExport, exp.base_export_id).mode == "full"):
        ws = sorted(db.scalars(select(Workspace.id).where(Workspace.import_state.is_(None))))
    sc = Scope(workspaces=list(ws), watermark={})
    restriction = exporter.restrict(db, sc, exp.classifications)
    analysis = closure.resolve(db, sc, exp.decisions or {})
    blobs = exporter.prescan(db, sc, exp.classifications, exp.decisions or {}, bool(exp.classifications),
                             policy=cfg.policy)
    estimate = _estimate(db, sc)
    ready = not analysis["unresolved"] and not analysis["blocked"] and blobs["ready"]
    exp.analysis = {"closure": analysis, "restriction": restriction, "estimate": estimate, "blobs": blobs,
                    "identity_profile": (exp.decisions or {}).get("identity_profile"), "ready": ready,
                    "policy": cfg.policy.describe(),
                    "warnings": _warnings(exp, restriction, analysis, blobs)}
    move(db, exp, "awaiting_approval", actor, "analysed", {"ready": ready})
    return exp


def _estimate(db: Session, sc: Scope) -> dict:
    from sqlalchemy import func

    from app.models.asset import Asset
    from app.models.attachment import Attachment
    from app.models.issue import Issue
    from app.models.ledger import ClaimEvent
    return {"records": db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id.in_(sc.workspaces))),
            "tickets": db.scalar(select(func.count()).select_from(Issue).where(Issue.workspace_id.in_(sc.workspaces))),
            "claim_events": db.scalar(select(func.count()).select_from(ClaimEvent).where(
                ClaimEvent.stream_id.in_(sc.streams()))),
            "attachments": db.scalar(select(func.count()).select_from(Attachment).where(
                Attachment.workspace_id.in_(sc.workspaces))),
            "attachment_bytes": int(db.scalar(select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
                Attachment.workspace_id.in_(sc.workspaces))) or 0)}


def _warnings(exp: PortabilityExport, restriction: dict, analysis: dict, blobs: dict) -> list[str]:
    out = []
    if restriction["excluded_classes"]:
        out.append(f"restricted classes left out: {', '.join(restriction['excluded_classes'])} — the archive is "
                   "not complete")
    if restriction["fields_hidden"]:
        out.append("restricted fields are hidden on some records — the archive is not complete")
    if exp.classifications:
        out.append(f"restricted classes included: {', '.join(exp.classifications)} — encrypted for the destination's "
                   "recipients; every reader of the destination repository must hold them")
    if (exp.decisions or {}).get("identity_profile") == "full_identity":
        out.append("full identity: e-mail addresses, names and directory DNs leave ARGUS")
    if analysis["unresolved"]:
        out.append(f"{len(analysis['unresolved'])} dependencies need an outcome")
    if blobs["secrets"]:
        out.append(f"{len(blobs['secrets'])} secret(s) found inside attachments or source contents: the export is "
                   "refused until the content is corrected")
    if blobs["needs_decision"]:
        out.append(f"{len(blobs['needs_decision'])} blob(s) could not be inspected or carry restricted markers")
    if blobs.get("missing"):
        count = blobs.get("missing_count") or len(blobs["missing"])
        families = sorted({m["family"] for m in blobs["missing"]})
        out.append(f"{count} attachment file(s) are missing from storage ({', '.join(families)}…): the export cannot "
                   "be ready until they are back. When every file reads as missing, the process that analysed it "
                   "does not see the attachments volume.")
    if blobs.get("uninspected"):
        out.append(f"{len(blobs['uninspected'])} file(s) will travel UNINSPECTED (opaque or unreadable), labelled as "
                   "such; an importer must accept the warning")
    if analysis.get("workspaces") and sorted(analysis["workspaces"]) != sorted(exp.workspaces) and exp.mode != "full":
        out.append(f"the closure adds workspaces: {', '.join(sorted(set(analysis['workspaces']) - set(exp.workspaces)))}")
    return out


def set_export_decisions(db: Session, exp: PortabilityExport, decisions: dict, actor: str,
                         cfg: Optional[Config] = None) -> PortabilityExport:
    expect(exp, "awaiting_approval", "failed")
    bad = {}
    for k, v in decisions.items():
        if k == "identity_profile":
            if v not in identity_policy.PROFILES:
                bad[k] = v
        elif k.startswith("blob:") or k in ("opaque_blobs", "classified_blobs"):
            if v not in BLOB_OUTCOMES or (v == "classify_encrypt" and not exp.classifications):
                bad[k] = v
        elif v not in closure.OUTCOMES:
            bad[k] = v
    if bad:
        raise ServiceError(f"unknown or unavailable outcomes {bad}", "invalid", 422)
    cfg = cfg or config()
    if decisions.get("identity_profile") in identity_policy.HIGH_RISK and cfg.policy.full_identity_high_risk:
        exp.risk = "high"
    exp.decisions = {**(exp.decisions or {}), **decisions}
    audit(db, exp, "decide", actor, {"decisions": decisions})
    return analyse_export(db, exp, actor, cfg)


def approve_export(db: Session, exp: PortabilityExport, actor: str, *, admin: bool,
                   fresh_auth: bool = False, cfg: Optional[Config] = None,
                   step_up_how: str = "") -> PortabilityExport:
    if exp.state == "approved":
        return exp
    expect(exp, "awaiting_approval")
    if not admin:
        raise ServiceError("approving an export needs an instance administrator", "forbidden", 403)
    pol = (cfg or config()).policy
    if exp.risk == "high" and actor == exp.requested_by and pol.separation_of_duties:
        raise ServiceError("a high-risk export needs an approver other than its requester", "separation", 403)
    if exp.risk == "high" and not fresh_auth:
        raise ServiceError("approving a high-risk export needs a recent sign-in"
                           + (" or, with a recent session, an explicit confirmation" if pol.step_up ==
                              "session_confirmation" else ""), "step_up_required", 401,
                           {"step_up": step_up_how or "missing"})
    if not (exp.analysis or {}).get("ready"):
        raise ServiceError("dependencies or blobs still need an outcome", "closure", 409,
                           {"unresolved": exp.analysis.get("closure", {}).get("unresolved"),
                            "blobs": exp.analysis.get("blobs", {}).get("needs_decision")})
    if cfg is not None:
        _check_destination(exp.mode, exp.classifications, exp.destination or {}, cfg)
    exp.approved_by = actor
    move(db, exp, "approved", actor, "approve", {"risk": exp.risk, "step_up": step_up_how or fresh_auth,
                                                 "self_approved": actor == exp.requested_by,
                                                 "policy": pol.profile, "relaxations": pol.relaxations()})
    return exp


def generate_export(engine: Engine, db: Session, exp: PortabilityExport, actor: str, cfg: Config,
                    fresh_auth: bool = False) -> PortabilityExport:
    started = time.monotonic()
    if exp.state in ("ready_to_publish", "published"):
        return exp
    expect(exp, "approved")
    if cfg.signer is None:
        raise ServiceError("no signing key is configured (ARGUS_PORTABILITY_SIGNING_KEY)", "no_signing_key", 409)
    if exp.classifications and not fresh_auth:
        raise ServiceError("generating a restricted export needs a recent sign-in: sign in again",
                           "step_up_required", 401)
    _check_destination(exp.mode, exp.classifications, exp.destination or {}, cfg)
    env = None
    if exp.classifications:
        chosen = set(exp.destination.get("recipients") or [])
        env = envelope.Envelope.new([r for r in envelope.load_recipients(cfg.recipients[exp.destination["repository"]])
                                     if r.name in chosen])
    move(db, exp, "generating", actor, "generate")
    db.commit()
    out = cfg.export_dir(exp.id)
    chosen = (exp.destination or {}).get("artifact_store") or ""
    store = (cfg.repository_store(exp.id, exp.destination["repository"]) if chosen == REPOSITORY_STORE
             else cfg.stores.get(chosen))
    base = None
    if exp.mode == "incremental":
        b = db.get(PortabilityExport, exp.base_export_id)
        base = {**b.manifest, "_sha256": b.manifest_sha256}
    try:
        if out.exists():
            exporter.secure_delete(out)
        manifest = exporter.generate(engine, export_id=exp.id, mode=exp.mode, workspaces=exp.workspaces, out_dir=out,
                                     store=store, signer=cfg.signer, requested_by=exp.requested_by,
                                     approved_by=exp.approved_by, classifications=exp.classifications,
                                     decisions=exp.decisions, base_manifest=base,
                                     repository={"name": (exp.destination or {}).get("repository")},
                                     identity_profile=(exp.decisions or {}).get("identity_profile"), envelope=env,
                                     policy=cfg.policy, purpose=(exp.decisions or {}).get("purpose"))
        exp = db.get(PortabilityExport, exp.id)
        move(db, exp, "verifying", actor, "generated", {"checkpoint": manifest["watermark"]["checkpoint_sequence"],
                                                        "vector_sha256": manifest["watermark"]["vector_sha256"]})
        work = cfg.root / "verify" / exp.id
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(out, work / "checkpoint")
        for c in [c for f in manifest["families"].values() for c in f["chunks"] if c.get("storage") == "artifact"]:
            (work / "checkpoint" / c["file"]).unlink()           # verified as a reader will: fetched by locator
        stores = {**cfg.stores, store.name: store} if chosen == REPOSITORY_STORE else cfg.stores
        checked = verifier.verify(work / "checkpoint", trusted=cfg.trusted, stores=stores, blob_dir=work / "blobs",
                                  limits=cfg.limits, private_keys=None, plain_dir=work / "plain")
        exporter.secure_delete(work)
        exp.manifest = {k: v for k, v in manifest.items() if k != "_sha256"}
        exp.manifest_sha256 = manifest["_sha256"]
        exp.watermark = manifest["watermark"]
        exp.out_dir = str(out)
        metrics = {"seconds": round(time.monotonic() - started, 2), "peak_memory_mb": _peak_memory_mb(),
                   "rows": checked["report"]["rows"], "artifact_bytes": sum(
                       c["bytes"] for f in manifest["families"].values() for c in f["chunks"]) + manifest["blobs"]["bytes"]}
        exp.analysis = {**(exp.analysis or {}), "metrics": metrics}
        move(db, exp, "ready_to_publish", actor, "verified", {"report": checked["report"], "metrics": metrics})
        db.commit()
    except Exception as e:  # noqa: BLE001 — every failure is recorded on the export
        exporter.secure_delete(out)
        _fail(db, exp, actor, e)
        raise ServiceError(str(e), getattr(e, "code", "export_failed"), 409, getattr(e, "detail", None)) from e
    return exp


def publish_export(db: Session, exp: PortabilityExport, actor: str, cfg: Config) -> PortabilityExport:
    if exp.state == "published":
        return exp
    expect(exp, "ready_to_publish")
    repo = (exp.destination or {}).get("repository")
    if repo not in cfg.repositories:
        raise ServiceError("this export has no registered destination repository", "invalid", 422)
    if exp.classifications:
        _check_destination(exp.mode, exp.classifications, exp.destination, cfg)
    move(db, exp, "publishing", actor, "publish", {"repository": repo})
    db.commit()
    previous = None
    if exp.mode == "incremental":
        previous = (db.get(PortabilityExport, exp.base_export_id).git or {}).get("tag")
    manifest = {**exp.manifest, "_sha256": exp.manifest_sha256}
    try:
        in_repository = (exp.destination or {}).get("artifact_store") == REPOSITORY_STORE
        pub = gitrepo.publish(Path(exp.out_dir), manifest, remote=cfg.repositories[repo], work=cfg.work(repo),
                              signer=cfg.signer, schemas=exporter.json_schemas(), previous_tag=previous,
                              credentials=cfg.git_env(repo),
                              artifacts=cfg.repository_store(exp.id, repo).root if in_repository else None)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        exp = db.get(PortabilityExport, exp.id)
        exp.error = {"error": str(e), "code": getattr(e, "code", "publish_failed"), **(getattr(e, "detail", None) or {})}
        move(db, exp, "ready_to_publish", actor, "publish_failed", {"code": exp.error["code"]})
        db.commit()
        raise ServiceError(str(e), getattr(e, "code", "publish_failed"), 409, getattr(e, "detail", None)) from e
    exp = db.get(PortabilityExport, exp.id)
    exp.git = {"repository": repo, "repository_id": pub.repository_id, "root_commit": pub.root_commit,
               "commit": pub.commit, "parent": pub.parent, "tag": pub.tag, "tag_object": pub.tag_object,
               "previous_tag": pub.previous_tag, "repository_bytes": pub.repository_bytes,
               "files_in_git": len(pub.files)}
    move(db, exp, "published", actor, "published", exp.git)
    return exp


# --------------------------------------------------------------------------- downloads

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def download_token(db: Session, exp: PortabilityExport, actor: str) -> dict:
    """A single-use token, valid for minutes, bound to this export, this actor and this exact archive
    version. Only its hash is stored."""
    expect(exp, "ready_to_publish", "published")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + DOWNLOAD_TTL
    db.add(PortabilityDownloadToken(token_sha256=_token_hash(token), export_id=exp.id, actor=actor,
                                    manifest_sha256=exp.manifest_sha256, expires_at=expires))
    audit(db, exp, "download_token", actor, {"expires": expires.isoformat(), "token": _token_hash(token)[:12]})
    return {"token": token, "expires": int(expires.timestamp())}


def consume_download_token(db: Session, exp: PortabilityExport, token: str) -> str:
    """Use a token: once, before it expires, for the archive version it was issued for. The token is
    consumed when the download starts; a broken transfer needs a new one."""
    row = db.get(PortabilityDownloadToken, _token_hash(token or ""))
    now = datetime.now(timezone.utc)
    reason = None
    if row is None or row.export_id != exp.id:
        reason = "unknown"
    elif row.revoked_at is not None:
        reason = "revoked"
    elif row.consumed_at is not None:
        reason = "already used"
    elif row.expires_at < now:
        reason = "expired"
    elif row.manifest_sha256 != exp.manifest_sha256:
        reason = "issued for another archive version"
    if reason:
        audit(db, exp, "download_refused", row.actor if row else "unknown",
              {"reason": reason, "token": _token_hash(token or "")[:12]})
        db.commit()
        raise ServiceError(f"the download token is not valid: {reason}", "forbidden", 403)
    row.consumed_at = now
    audit(db, exp, "download", row.actor, {"token": row.token_sha256[:12], "via": "token"})
    db.commit()
    return row.actor


def revoke_download_tokens(db: Session, exp: PortabilityExport, actor: str) -> int:
    n = 0
    for row in db.scalars(select(PortabilityDownloadToken).where(PortabilityDownloadToken.export_id == exp.id,
                                                                 PortabilityDownloadToken.consumed_at.is_(None),
                                                                 PortabilityDownloadToken.revoked_at.is_(None))):
        row.revoked_at = datetime.now(timezone.utc)
        n += 1
    audit(db, exp, "download_tokens_revoked", actor, {"count": n})
    return n


def archive_tar(exp: PortabilityExport) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(Path(exp.out_dir).iterdir()):
            tar.add(p, arcname=p.name, recursive=False)
    return buf.getvalue()


def revoke_export(db: Session, exp: PortabilityExport, actor: str, reason: str) -> PortabilityExport:
    move(db, exp, "revoked", actor, "revoke", {"reason": reason})
    revoke_download_tokens(db, exp, actor)
    return exp


def export_view(exp: PortabilityExport) -> dict:
    return {"id": exp.id, "mode": exp.mode, "state": exp.state, "risk": exp.risk, "workspaces": exp.workspaces,
            "classifications": exp.classifications, "base_export_id": exp.base_export_id,
            "destination": exp.destination, "decisions": exp.decisions, "requested_by": exp.requested_by,
            "approved_by": exp.approved_by, "analysis": exp.analysis, "watermark": exp.watermark,
            "manifest_sha256": exp.manifest_sha256, "git": exp.git, "error": exp.error,
            "identity_profile": (exp.decisions or {}).get("identity_profile"),
            "labels": labels(exp.manifest, {"git_published": exp.state == "published",
                                            "verified": exp.state in ("ready_to_publish", "publishing", "published")}),
            "legal_hold": bool(exp.legal_hold), "legal_hold_reason": exp.legal_hold_reason,
            "purged_at": exp.purged_at.isoformat() if exp.purged_at else None,
            "created_at": exp.created_at.isoformat() if exp.created_at else None}


# =========================================================================== imports

IMPORT_MODES = ("restore", "clone", "merge", "selective", "evidence")


def _holds_records(db: Session, workspace_id: str) -> bool:
    """Whether anybody has put anything in this workspace: equipment, tickets, documents or ledger sources."""
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    from app.models.ledger import LedgerStream
    return any(db.scalar(select(m.workspace_id).where(m.workspace_id == workspace_id).limit(1)) is not None
               for m in (Asset, Issue, Document, LedgerStream))


def create_import(db: Session, actor: str, *, mode: str, source: dict, decisions: Optional[dict],
                  cfg: Config) -> PortabilityImport:
    if mode not in IMPORT_MODES:
        raise ServiceError(f"unknown mode {mode!r}", "invalid", 422)
    if source.get("repository") and source["repository"] not in cfg.repositories:
        raise ServiceError(f"repository {source['repository']!r} is not registered", "invalid", 422)
    imp = PortabilityImport(id=f"imp-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}", mode=mode,
                            source=source, state="created", requested_by=actor, decisions=decisions or {})
    db.add(imp)
    db.flush()
    imp.quarantine_dir = str(cfg.quarantine(imp.id))
    audit(db, imp, "request", actor, {"mode": mode, "source": source}, None, "created")
    return imp


def fetch_git(db: Session, imp: PortabilityImport, actor: str, cfg: Config) -> PortabilityImport:
    if imp.state == "quarantined":
        return imp
    expect(imp, "created")
    src = imp.source or {}
    url = cfg.repositories.get(src.get("repository") or "")
    if not url or not src.get("ref"):
        raise ServiceError("name a registered repository and a signed tag or commit", "invalid", 422)
    move(db, imp, "fetching", actor, "fetch", {"repository": src["repository"], "ref": src["ref"]})
    db.commit()
    try:
        if cfg.trusted is None:
            raise ServiceError("no trusted keys are configured (ARGUS_PORTABILITY_TRUSTED_KEYS)", "no_trusted_keys")
        got = gitrepo.fetch_into_quarantine(url, src["ref"], Path(imp.quarantine_dir), cfg.trusted, limits=cfg.limits,
                                            credentials_env=cfg.git_env(src["repository"]))
        if src.get("expected_commit") and src["expected_commit"] != got.commit:
            raise ServiceError(f"{src['ref']} names {got.commit[:12]}, not the expected {src['expected_commit'][:12]}",
                               "unexpected_commit")
        if src.get("repository_id") and src["repository_id"] != got.repository_id:
            raise ServiceError("this is not the registered repository (its identity differs)", "repository_identity")
        if got.tag:
            seen = db.get(PortabilityTagSeen, (got.repository_id, got.tag))
            if seen is not None and (seen.commit != got.commit or seen.tag_object != got.tag_object):
                raise ServiceError(f"tag {got.tag} has moved since it was first imported here "
                                   f"(it named {seen.commit[:12]})", "moved_tag")
        if got.previous_tag and not gitrepo.has_commit(Path(imp.quarantine_dir), url, _tag_commit(
                Path(imp.quarantine_dir), url, got.previous_tag, cfg.git_env(src["repository"])), got.commit,
                cfg.git_env(src["repository"])):
            raise ServiceError(f"the previous export {got.previous_tag} is not in this repository's history",
                               "missing_commit")
    except Exception as e:  # noqa: BLE001
        _fail(db, imp, actor, e, to="invalid")
        raise ServiceError(str(e), getattr(e, "code", "fetch_failed"), 409, getattr(e, "detail", None)) from e
    imp = db.get(PortabilityImport, imp.id)
    imp.commit = got.commit
    imp.verification = {"git": {"repository_id": got.repository_id, "root_commit": got.root_commit,
                                "commit": got.commit, "tag": got.tag, "tag_object": got.tag_object,
                                "signed_by": got.signer, "export_id": got.export_id,
                                "previous_tag": got.previous_tag, "lfs_pointers": got.lfs,
                                # Data files committed with the checkpoint (the "in the repository" store).
                                "artifacts_in_repository": any(e["path"].startswith(artifacts.REPOSITORY_ARTIFACTS + "/")
                                                               for e in got.tree)}}
    move(db, imp, "quarantined", actor, "fetched", imp.verification["git"])
    return imp


def _tag_commit(qdir: Path, url: str, tag: str, credentials: Optional[dict] = None) -> str:
    repo = qdir / "repo.git"
    gitrepo.git(["fetch", "-q", "--no-tags", "--no-recurse-submodules", url, f"+refs/tags/{tag}:refs/tags/{tag}"],
                cwd=repo, check=False, env=credentials)
    r = gitrepo.git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd=repo, check=False)
    return r.stdout.strip() or "0" * 40


def upload(db: Session, imp: PortabilityImport, actor: str, data: bytes, cfg: Config) -> PortabilityImport:
    """A checkpoint as a tar of its files (no directories, no links): for archives that do not come
    from Git — an escrow copy. Signature verification still applies."""
    expect(imp, "created")
    out = Path(imp.quarantine_dir) / "checkpoint"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for m in tar.getmembers():
            if not m.isfile() or "/" in m.name or not gitrepo.SAFE_NAME.match(m.name):
                raise ServiceError(f"the upload holds {m.name!r}, which is not a plain checkpoint file", "unsafe_upload")
            total += m.size
            if m.size > cfg.limits.max_file_bytes or total > cfg.limits.max_chunk_bytes * 8:
                raise ServiceError("the upload is too large", "too_large", 413)
            (out / m.name).write_bytes(tar.extractfile(m).read())
    imp.verification = {"upload": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
    move(db, imp, "quarantined", actor, "uploaded", imp.verification["upload"])
    return imp


def verify_import(db: Session, imp: PortabilityImport, actor: str, cfg: Config) -> PortabilityImport:
    if imp.state in ("dry_run_ready", "awaiting_mapping"):
        return imp
    expect(imp, "quarantined")
    move(db, imp, "verifying", actor, "verify")
    db.commit()
    q = Path(imp.quarantine_dir)
    try:
        git_info = imp.verification.get("git") or {}
        lfs = git_info.get("lfs_pointers") or []
        stores = (artifacts.StoresWithRepository(cfg.stores, q / "repo.git", git_info["commit"])
                  if git_info.get("artifacts_in_repository") else cfg.stores)
        checked = verifier.verify(q / "checkpoint", trusted=cfg.trusted, stores=stores, blob_dir=q / "blobs",
                                  lfs=lfs, limits=cfg.limits, private_keys=cfg.private_keys(), plain_dir=q / "plain")
        if not checked["report"]["content_verified"]:
            raise ServiceError("the archive is encrypted and no recipient key for it is available to this import "
                               "session (ARGUS_PORTABILITY_DECRYPTION_KEYS)", "decryption_key_required")
        _columns_known(checked["plain"], checked["manifest"], cfg.limits)
        git = imp.verification.get("git") or {}
        if git and git.get("export_id") != checked["manifest"]["export_id"]:
            raise ServiceError("the tag names another export than the manifest", "mismatch")
    except Exception as e:  # noqa: BLE001
        _fail(db, imp, actor, e, to="invalid")
        raise ServiceError(str(e), getattr(e, "code", "invalid"), 409, getattr(e, "detail", None)) from e
    imp = db.get(PortabilityImport, imp.id)
    imp.manifest = checked["manifest"]
    imp.verification = {**imp.verification, "checkpoint": checked["report"], "plain": str(checked["plain"])}
    move(db, imp, "dry_run_ready", actor, "verified", {"report": checked["report"]})
    return imp


IDENTITY_EXTRA = {"actor_type", "issuer_hash"}


def _columns_known(checkpoint: Path, manifest: dict, limits: chunks.Limits) -> None:
    """Every column in the archive is one this importer knows: nothing is dropped silently."""
    from app.portability.families import BY_NAME
    for name, fam in manifest["families"].items():
        known = set(BY_NAME[name].columns) | (IDENTITY_EXTRA if name == "identities" else set())
        for c in fam["chunks"][:1]:
            for _, row in chunks.read_chunk(checkpoint / c["file"], name, limits):
                extra = set(row) - known
                if extra:
                    raise ServiceError(f"{name} carries columns this importer does not know: {sorted(extra)}",
                                       "incompatible")
                break


def _plan(imp: PortabilityImport, cfg: Config, *, staged: bool) -> importer.Plan:
    q = Path(imp.quarantine_dir)
    plain = Path((imp.verification or {}).get("plain") or (q / "checkpoint"))
    return importer.Plan(import_id=imp.id, origin=imp.manifest["argus"]["instance_id"], mode=imp.mode,
                         checkpoint=plain, manifest=imp.manifest, blob_dir=q / "blobs",
                         attachments_dir=(cfg.staged_files(imp.id) / "attachments") if staged else cfg.attachments_dir,
                         decisions=imp.decisions or {},
                         manifest_sha256=((imp.verification or {}).get("checkpoint") or {}).get("manifest_sha256", ""))


def dry_run(db: Session, imp: PortabilityImport, actor: str, cfg: Config,
            decisions: Optional[dict] = None) -> PortabilityImport:
    expect(imp, "dry_run_ready", "awaiting_approval")
    if decisions:
        imp.decisions = {**(imp.decisions or {}), **decisions}
    plan = _plan(imp, cfg, staged=False)
    report = {"mode": imp.mode, "export_id": imp.manifest["export_id"], "labels": imp.manifest["labels"]} \
        if imp.mode == "evidence" else importer.dry_run(db, plan)
    if imp.mode == "evidence":
        report["ready"] = True
        report["note"] = "evidence-only: kept read-only, nothing loaded into active state"
    uninspected = (imp.manifest.get("blobs") or {}).get("inspection", {}).get("uninspected", 0)
    if uninspected:
        report["uninspected_content"] = {"count": uninspected, "warning": f"{uninspected} file(s) in this archive "
                                         "were not inspected at export (opaque or unreadable); approving the import "
                                         "accepts them", "items": (imp.manifest.get("blobs") or {}).get("uninspected", [])[:50]}
    if imp.mode == "selective" and not plan.selected:
        report.setdefault("blocking", []).append({"family": "workspaces", "key": "-",
                                                  "reason": "a selective import names the workspaces it takes "
                                                            "(decision select_workspaces)"})
        report["ready"] = False
    if imp.mode == "restore" and imp.manifest.get("identity", {}).get("profile") != "full_identity":
        report.setdefault("blocking", []).append({"family": "identities", "key": "-", "reason":
                                                  "restore rebuilds the same instance and needs a full_identity "
                                                  "archive; this one transformed its actors — use clone or merge"})
        report["ready"] = False
    if imp.mode == "restore":
        from app.models.workspace import Workspace
        # A workspace nobody has put anything in (the default one a new installation makes) does not make
        # the instance any less empty.
        others = [w for w in db.scalars(select(Workspace.id).where(Workspace.import_state.is_(None)))
                  if w not in plan.workspaces and _holds_records(db, w)]
        if others:
            report.setdefault("blocking", []).append({"family": "instance", "key": "-", "reason":
                                                      "restore needs an empty instance; use clone or merge"})
            report["ready"] = False
    imp.dry_run = report
    imp.state = "dry_run_ready" if imp.state == "awaiting_approval" else imp.state
    audit(db, imp, "dry_run", actor, {"ready": report.get("ready"), "blocking": len(report.get("blocking", []))})
    if report.get("ready"):
        move(db, imp, "awaiting_approval", actor, "dry_run_ready")
    return imp


def approve_import(db: Session, imp: PortabilityImport, actor: str, *, acknowledge_uninspected: bool = False,
                   cfg: Optional[Config] = None) -> PortabilityImport:
    if imp.state == "approved":
        return imp
    expect(imp, "awaiting_approval")
    pol = (cfg or config()).policy
    restricted = bool((imp.manifest.get("classifications") or {}).get("included"))
    if (imp.mode in ("merge", "restore") or restricted) and actor == imp.requested_by and pol.separation_of_duties:
        raise ServiceError("this import needs an approver other than its requester", "separation", 403)
    uninspected = (imp.manifest.get("blobs") or {}).get("inspection", {}).get("uninspected", 0)
    if uninspected and not acknowledge_uninspected:
        raise ServiceError(f"the archive carries {uninspected} uninspected file(s): accept the warning to approve",
                           "acknowledgement_required", 409, {"uninspected": uninspected})
    imp.approved_by = actor
    move(db, imp, "approved", actor, "approve", {"accepted_uninspected": uninspected or None,
                                                 "self_approved": actor == imp.requested_by,
                                                 "policy": pol.profile, "relaxations": pol.relaxations()})
    return imp


def execute(db: Session, imp: PortabilityImport, actor: str, cfg: Config,
            stop_after: Optional[int] = None) -> PortabilityImport:
    """Load, rebuild and reconcile the import in its own staging database. Nothing reaches the active
    database here; `finalize` promotes it."""
    if imp.state in ("ready_to_finalize", "finalized"):
        return imp
    expect(imp, "approved", "importing", "failed")
    if imp.state != "importing":
        move(db, imp, "importing", actor, "execute" if imp.state == "approved" else "resume")
        db.commit()
    if imp.mode == "evidence":
        return _store_evidence(db, imp, actor, cfg)
    plan = _plan(imp, cfg, staged=True)
    if importer.chain_status(db, plan).get("status") == "already_applied":
        imp.reconciliation = {"passed": True, "already_applied": True, "export_id": imp.manifest["export_id"]}
        _sign_report(imp, cfg)
        move(db, imp, "rebuilding", actor, "already_applied")
        move(db, imp, "reconciling", actor, "already_applied")
        move(db, imp, "ready_to_finalize", actor, "reconciled", {"passed": True, "identical_history": True})
        db.commit()
        return imp
    active_url = db.get_bind().url
    try:
        name = (imp.staging or {}).get("database") or staging.create(active_url, imp.id)
        if not (imp.staging or {}).get("database"):
            row = db.get(PortabilityImport, imp.id)
            row.staging = {"database": name, "created_at": datetime.now(timezone.utc).isoformat()}
            audit(db, row, "staging_created", actor, {"database": name})
            db.commit()
    except Exception as e:  # noqa: BLE001
        _fail(db, imp, actor, e)
        raise ServiceError(str(e), "staging_failed", 409) from e
    stage_engine = staging.engine_for(active_url, name)
    done = set((imp.checkpoints or {}).get("done") or [])
    deferred = list((imp.checkpoints or {}).get("deferred") or [])
    try:
        with Session(stage_engine) as sdb:
            if "seeded" not in done:
                seeded = staging.seed(db, sdb, plan, importer.references(None, plan))
                sdb.commit()
                done.add("seeded")
                _save(db, imp, done, deferred, {"seeded": seeded})

            def save(steps: set):
                sdb.commit()
                _save(db, imp, steps, deferred)

            plan.ingested_at = datetime.now(timezone.utc)
            report = importer.execute(sdb, plan, done, save, stop_after=stop_after)
            deferred += report["deferred"]
            _save(db, imp, done, deferred)
            imp = db.get(PortabilityImport, imp.id)
            move(db, imp, "rebuilding", actor, "loaded", {"steps": len(done), "where": "staging"})
            db.commit()
            rebuilt = importer.rebuild(sdb, plan)
            sdb.commit()
            imp = db.get(PortabilityImport, imp.id)
            move(db, imp, "reconciling", actor, "rebuilt", rebuilt)
            db.commit()             # seen as reconciling while it runs, not only when it ends
            imp = db.get(PortabilityImport, imp.id)
            rec = importer.reconcile(sdb, plan, deferred)
            rec["rebuild"] = rebuilt
            rec["git"] = (imp.verification or {}).get("git")
            rec["staged"] = True
            imp.reconciliation = rec
            _sign_report(imp, cfg)
            move(db, imp, "ready_to_finalize" if rec["passed"] else "failed", actor, "reconciled",
                 {"passed": rec["passed"], "sha256": imp.reconciliation_sha256, "where": "staging"})
            db.commit()
    except InterruptedError as e:
        db.rollback()
        row = db.get(PortabilityImport, imp.id)
        row.error = {"error": str(e), "code": "interrupted"}
        audit(db, row, "interrupted", actor, {"done": len(done)})
        db.commit()
        raise ServiceError(str(e), "interrupted", 409) from e
    except Exception as e:  # noqa: BLE001
        _fail(db, imp, actor, e)
        raise ServiceError(str(e), getattr(e, "code", "import_failed"), 409, getattr(e, "detail", None)) from e
    finally:
        stage_engine.dispose()
    return imp


def _save(db: Session, imp: PortabilityImport, steps: set, deferred: list, extra: Optional[dict] = None) -> None:
    row = db.get(PortabilityImport, imp.id)
    row.checkpoints = {**(row.checkpoints or {}), "done": sorted(steps), "deferred": deferred, **(extra or {})}
    db.commit()


def _store_evidence(db: Session, imp: PortabilityImport, actor: str, cfg: Config) -> PortabilityImport:
    """Keep the verified (decrypted) checkpoint read-only in the evidence store, with its origin chain
    hash. Nothing is loaded into active state."""
    dest = cfg.evidence(imp.id)
    plan = _plan(imp, cfg, staged=True)
    if not dest.exists():
        (dest / "checkpoint").mkdir(parents=True)
        for f in plan.checkpoint.iterdir():
            if f.is_file():
                shutil.copyfile(f, dest / "checkpoint" / f.name)
    _, chain_sha = importer.origin_chain(plan)
    move(db, imp, "rebuilding", actor, "evidence_stored", {"path": dest.name, "origin_chain_sha256": chain_sha})
    move(db, imp, "reconciling", actor, "no_projection")
    imp.reconciliation = {"passed": True, "evidence_only": True, "export_id": imp.manifest["export_id"],
                          "origin_chain": {"sha256": chain_sha}}
    _sign_report(imp, cfg)
    move(db, imp, "ready_to_finalize", actor, "reconciled", {"passed": True})
    db.commit()
    return imp


def _sign_report(imp: PortabilityImport, cfg: Config) -> None:
    body = json.dumps({k: v for k, v in imp.reconciliation.items() if k != "signature"}, sort_keys=True, default=str)
    imp.reconciliation_sha256 = hashlib.sha256(body.encode()).hexdigest()
    if cfg.signer is not None:
        manifest_sha = ((imp.verification or {}).get("checkpoint") or {}).get("manifest_sha256", "")
        imp.reconciliation = {**imp.reconciliation, "signature": signing.sign_checkpoint(
            cfg.signer, imp.reconciliation_sha256, manifest_sha)}


def finalize(db: Session, imp: PortabilityImport, actor: str, cfg: Config,
             probe: Optional[Callable] = None) -> PortabilityImport:
    """Promote the staged import into the active database in one transaction: all of it becomes
    visible at once, or — on any difference from the staged result — none of it."""
    if imp.state == "finalized":
        return imp
    expect(imp, "ready_to_finalize")
    if not (imp.reconciliation or {}).get("passed"):
        raise ServiceError("the reconciliation did not pass", "reconciliation_failed")
    plan = None
    started = time.monotonic()
    try:
        promoted = None
        if imp.mode != "evidence" and not imp.reconciliation.get("already_applied"):
            plan = _plan(imp, cfg, staged=False)
            promoted = importer.promote(db, plan, imp.reconciliation, actor, probe=probe)
            if imp.mode == "restore":
                from app.models.app_setting import AppSetting
                row = db.get(AppSetting, exporter.INSTANCE_KEY)
                value = {"id": imp.manifest["argus"]["instance_id"], "name": imp.manifest["argus"].get("instance_name"),
                         "restored_from": imp.manifest["export_id"]}
                if row is None:
                    db.add(AppSetting(key=exporter.INSTANCE_KEY, value=value))
                else:
                    row.value = value
        git = (imp.verification or {}).get("git") or {}
        if git.get("tag") and db.get(PortabilityTagSeen, (git["repository_id"], git["tag"])) is None:
            db.add(PortabilityTagSeen(repository_id=git["repository_id"], tag=git["tag"], commit=git["commit"],
                                      tag_object=git["tag_object"], import_id=imp.id))
        detail = {"reconciliation_sha256": imp.reconciliation_sha256,
                  "metrics": {"promotion_seconds": round(time.monotonic() - started, 2),
                              "peak_memory_mb": _peak_memory_mb()}}
        if promoted is not None:
            imp.reconciliation = {**imp.reconciliation, "promotion": {
                k: promoted[k] for k in ("origin_chain", "rebuild", "passed")}}
            detail["origin_chain_sha256"] = promoted["origin_chain"]["sha256"]
        move(db, imp, "finalized", actor, "finalize", detail)
        db.commit()
    except Exception as e:  # noqa: BLE001 — nothing of the promotion was committed
        db.rollback()
        for f in (plan.created_files if plan is not None else []):
            exporter.secure_delete(Path(f))
        imp = db.get(PortabilityImport, imp.id)
        imp.error = {"error": str(e), "code": getattr(e, "code", "promotion_failed"),
                     **(getattr(e, "detail", None) or {})}
        audit(db, imp, "promotion_failed", actor, {"code": imp.error["code"]})
        db.commit()
        raise ServiceError(str(e), getattr(e, "code", "promotion_failed"), 409, getattr(e, "detail", None)) from e
    _cleanup(db, imp, cfg, keep_evidence=imp.mode == "evidence")
    return imp


def _cleanup(db: Session, imp: PortabilityImport, cfg: Config, keep_evidence: bool) -> None:
    """Remove what never became authoritative: the staging database, staged files, quarantine."""
    staging.drop(db.get_bind().url, (imp.staging or {}).get("database"))
    exporter.secure_delete(cfg.staged_files(imp.id))
    if not keep_evidence:
        exporter.secure_delete(Path(imp.quarantine_dir))


def discard(db: Session, imp: PortabilityImport, actor: str, cfg: Config, reason: str = "") -> PortabilityImport:
    """Abandon an import. The active database was never written to, so nothing there is deleted: the
    staging database and the quarantine go; the import's audit trail stays, append-only."""
    if imp.state == "discarded":
        return imp
    if imp.state == "finalized":
        raise ServiceError("a finalized import is history: correct it with ledger decisions", "finalized")
    db_name = (imp.staging or {}).get("database")
    _cleanup(db, imp, cfg, keep_evidence=False)
    exporter.secure_delete(cfg.evidence(imp.id))
    move(db, imp, "discarded", actor, "discard", {"reason": reason or None, "staging_dropped": db_name,
                                                  "checkpoints_done": len((imp.checkpoints or {}).get("done") or [])})
    return imp


def import_view(imp: PortabilityImport) -> dict:
    m = imp.manifest or {}
    git = (imp.verification or {}).get("git") or {}
    return {"id": imp.id, "mode": imp.mode, "state": imp.state, "source": imp.source, "commit": imp.commit,
            "requested_by": imp.requested_by, "approved_by": imp.approved_by, "decisions": imp.decisions,
            "manifest": {k: m.get(k) for k in ("export_id", "mode", "workspaces", "watermark", "argus", "labels",
                                               "policy", "purpose", "classifications", "base", "blobs",
                                               "identity")} if m else None,
            "verification": {k: v for k, v in (imp.verification or {}).items() if k != "plain"},
            "dry_run": imp.dry_run,
            "checkpoints": {"done": len((imp.checkpoints or {}).get("done") or [])},
            "staging": imp.staging,
            "reconciliation_passed": (imp.reconciliation or {}).get("passed"),
            "reconciliation_sha256": imp.reconciliation_sha256, "error": imp.error,
            "labels": labels(m, {"git_published": bool(git.get("tag")),
                                 "verified": imp.state not in ("created", "fetching", "quarantined", "verifying",
                                                               "invalid")}),
            "legal_hold": bool(imp.legal_hold), "legal_hold_reason": imp.legal_hold_reason,
            "purged_at": imp.purged_at.isoformat() if imp.purged_at else None,
            "created_at": imp.created_at.isoformat() if imp.created_at else None}


def provenance(db: Session, imp: PortabilityImport) -> dict:
    events = db.scalars(select(PortabilityEvent).where(PortabilityEvent.subject_kind == "import",
                                                       PortabilityEvent.subject_id == imp.id)
                        .order_by(PortabilityEvent.seq))
    out = {"import": import_view(imp), "git": (imp.verification or {}).get("git"),
           "origin": (imp.manifest or {}).get("argus"), "watermark": (imp.manifest or {}).get("watermark"),
           "reconciliation_sha256": imp.reconciliation_sha256,
           "events": [{"seq": e.seq, "kind": e.kind, "from": e.from_state, "to": e.to_state, "actor": e.actor,
                       "at": e.at.isoformat(), "detail": e.detail} for e in events]}
    if imp.state == "finalized" and imp.mode != "evidence":
        out["origin_chain"] = importer.verify_chain(db, imp.id)
    return out


# --------------------------------------------------------------------------- evidence

def _reader(cfg: Config, viewer) -> bool:
    """Whether a viewer may read every restricted row of evidence: an explicit institutional list,
    never implied by being an administrator."""
    return bool(cfg.evidence_readers & {getattr(viewer, "id", None), getattr(viewer, "email", None)})


def _administered(db: Session, cfg: Config, imp: PortabilityImport, viewer) -> set:
    """The archive's workspaces whose local namesake this viewer administers: under the trusted policy,
    a workspace administrator reads the evidence of their own workspace."""
    if viewer is None or not cfg.policy.evidence_workspace_admins:
        return set()
    from app.services.permissions import has_permission
    out = set()
    for w in imp.manifest.get("workspaces", []):
        try:
            if not getattr(viewer, "is_admin", False) and has_permission(db, viewer, w, "manage_members", "workspace"):
                out.add(w)
        except Exception:  # noqa: BLE001 — a workspace that does not exist here
            continue
    return out


def _evidence_filter(imp: PortabilityImport, cfg: Config, full: bool, administered: set = frozenset()):
    """A predicate for rows a viewer may see: restricted records, rows naming them, and personal identity
    data only for evidence readers — or, for a workspace administrator, those of their own workspace."""
    from app.portability.families import BY_NAME
    base = cfg.evidence(imp.id) / "checkpoint"
    restricted: dict = {}
    for name in ("assets", "tickets"):
        for c in (imp.manifest["families"].get(name) or {}).get("chunks", []):
            for _, r in chunks.read_chunk(base / c["file"], name, cfg.limits):
                cls = ((r.get("attributes") or {}).get("classification") or "")
                if isinstance(cls, str) and cls.startswith("restricted:"):
                    restricted[r["uid"]] = r.get("workspace_id")

    def visible(family: str, row: dict) -> bool:
        if full:
            return True
        if family == "identities" and imp.manifest.get("identity", {}).get("profile") == "full_identity":
            return False
        fam = BY_NAME.get(family)
        named = [row.get(col) for col in (fam.subjects if fam else ())] + [row.get("uid")]
        for uid in named:
            if uid in restricted and restricted[uid] not in administered:
                return False
        return True
    return visible


def evidence_families(db: Session, imp: PortabilityImport, cfg: Config, viewer, actor: str) -> list[dict]:
    expect(imp, "finalized")
    if imp.mode != "evidence":
        raise ServiceError("only an evidence import is browsed from its archive", "invalid", 422)
    full = _reader(cfg, viewer)
    administered = _administered(db, cfg, imp, viewer)
    visible = _evidence_filter(imp, cfg, full, administered)
    out = []
    for name, fam in imp.manifest["families"].items():
        n = 0
        for c in fam["chunks"]:
            n += sum(1 for _, r in chunks.read_chunk(cfg.evidence(imp.id) / "checkpoint" / c["file"], name, cfg.limits)
                     if visible(name, r))
        if n or full:
            out.append({"family": name, "visible_rows": n})
    audit(db, imp, "evidence_list", actor, {"restricted_reader": full, "workspace_admin_of": sorted(administered)})
    return out


def evidence_rows(db: Session, imp: PortabilityImport, cfg: Config, family: str, offset: int, limit: int,
                  viewer=None, actor: str = "system") -> dict:
    """Browse an evidence archive. Restricted rows (and personal identity data under a full-identity
    profile) are shown only to the institution's evidence readers and, under the trusted policy, to a
    workspace's administrators for that workspace; counts are of visible rows only. Every read is
    audited. Evidence is browsed only: not searched, not indexed, not downloadable."""
    expect(imp, "finalized")
    if imp.mode != "evidence":
        raise ServiceError("only an evidence import is browsed from its archive", "invalid", 422)
    fam = (imp.manifest or {}).get("families", {}).get(family)
    full = _reader(cfg, viewer)
    administered = _administered(db, cfg, imp, viewer)
    visible = _evidence_filter(imp, cfg, full, administered)
    if fam is None:
        raise ServiceError(f"no family {family!r}", "not_found", 404)
    rows, i = [], 0
    for c in fam["chunks"]:
        for key, row in chunks.read_chunk(cfg.evidence(imp.id) / "checkpoint" / c["file"], family, cfg.limits):
            if not visible(family, row):
                continue
            if i >= offset and len(rows) < limit:
                rows.append({"key": key, "row": row})
            i += 1
    if i == 0 and not full:
        raise ServiceError(f"no family {family!r}", "not_found", 404)     # not even its existence
    audit(db, imp, "evidence_read", actor, {"family": family, "offset": offset, "returned": len(rows),
                                            "restricted_reader": full, "workspace_admin_of": sorted(administered)})
    return {"family": family, "total": i, "offset": offset, "rows": rows}


# --------------------------------------------------------------------------- retention, legal holds

def set_legal_hold(db: Session, subject, on: bool, reason: str, actor: str):
    """Suspend (or resume) automatic deletion of an export's or import's files. Audited."""
    if on and not reason.strip():
        raise ServiceError("a legal hold needs a reason", "invalid", 422)
    subject.legal_hold = on
    subject.legal_hold_reason = reason.strip() if on else None
    audit(db, subject, "legal_hold" if on else "legal_hold_released", actor, {"reason": reason.strip() or None})
    return subject


EXPORT_DONE = ("published", "ready_to_publish", "failed", "revoked", "expired")


def was_published(exp: Optional[PortabilityExport]) -> bool:
    """Published to Git — still, or expired since: retention deletes an export's local files, not its publication
    (its record, manifest and tag stay), so an increment can still be built on it. Not one revoked."""
    return exp is not None and exp.state in ("published", "expired") and bool((exp.git or {}).get("tag"))
IMPORT_DONE = ("finalized", "discarded", "failed", "invalid")


def cleanup(db: Session, cfg: Config, actor: str = "retention", now: Optional[datetime] = None) -> dict:
    """Delete the files of exports and imports older than the retention period (archives, quarantine,
    staging databases and files, evidence copies), unless a legal hold suspends it. The records, their
    audit, Git history and artifacts already published are kept. Every deletion is audited."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg.policy.retention_days)
    report = {"exports": [], "imports": [], "held": 0}
    for exp in db.scalars(select(PortabilityExport).where(PortabilityExport.created_at < cutoff,
                                                          PortabilityExport.purged_at.is_(None),
                                                          PortabilityExport.state.in_(EXPORT_DONE))):
        if exp.legal_hold:
            report["held"] += 1
            continue
        if exp.out_dir:
            exporter.secure_delete(Path(exp.out_dir))
        staged = cfg.root / "repository-stores" / exp.id      # data waiting to be committed with it
        if staged.exists():
            exporter.secure_delete(staged)
        if exp.state in ("published", "ready_to_publish"):
            move(db, exp, "expired", actor, "expire", {"retention_days": cfg.policy.retention_days})
        exp.purged_at = now
        audit(db, exp, "purged", actor, {"what": "local archive files", "retention_days": cfg.policy.retention_days})
        report["exports"].append(exp.id)
    for imp in db.scalars(select(PortabilityImport).where(PortabilityImport.created_at < cutoff,
                                                          PortabilityImport.purged_at.is_(None),
                                                          PortabilityImport.state.in_(IMPORT_DONE))):
        if imp.legal_hold:
            report["held"] += 1
            continue
        staging.drop(db.get_bind().url, (imp.staging or {}).get("database"))
        for p in (Path(imp.quarantine_dir) if imp.quarantine_dir else None, cfg.staged_files(imp.id),
                  cfg.evidence(imp.id)):
            if p is not None:
                exporter.secure_delete(p)
        imp.purged_at = now
        audit(db, imp, "purged", actor, {"what": "quarantine, staging and evidence files",
                                         "retention_days": cfg.policy.retention_days})
        report["imports"].append(imp.id)
    db.flush()
    return report
