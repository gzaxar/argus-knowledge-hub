"""Generate a checkpoint: one consistent ledger watermark, the chosen families as immutable chunks,
blobs as content-addressed artifacts, a manifest, checksums and a signature.

**The watermark.** A short transaction takes SHARE locks on the ledger's sequenced tables (which waits
for every transaction already writing to them, and holds new writers back for milliseconds), reads
each table's highest `seq`, allocates the next checkpoint number, and exports its snapshot. The
export then reads everything — ledger and records alike — in a read-only transaction that imports
that snapshot, and the lock is released. So every row with `seq <= W[table]` is committed and
visible, no later transaction can take a `seq <= W[table]`, and records are read at the same instant.

The watermark is the **vector** of per-table high-water marks. Its identity is the SHA-256 of its
canonical serialization, never a sum; the checkpoint number comes from a sequence nothing purges.

**What leaves, and in what order.** Rows are selected, restricted (§6), transformed by the identity
profile (`identity_policy`), and scanned for secrets. Blobs are read and inspected (`blob_scan`)
before they are stored anywhere, into a local staging area. Chunks are written; data chunks are
destined for the artifact store, small catalogue and governance chunks may stay in Git. An export
that includes restricted classes is encrypted (`envelope`). Only when every check has passed are
chunks and blobs copied to the destination artifact store; on any failure the staging area and the
checkpoint directory are securely removed, and nothing is published.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.portability import FORMAT, FORMAT_MAJOR, blob_scan, chunks, closure, secret_scan
from app.portability.artifacts import DirectoryStore
from app.portability.envelope import Envelope
from app.portability.families import FAMILIES, GROUP_ORDER, SEQUENCED_TABLES, Family, Scope, to_json
from app.portability.identity_policy import IdentityPolicy
from app.portability.policy import Policy
from app.portability.signing import Signer, sign_checkpoint

MODES = ("full", "incremental", "workspace", "evidence-only", "backup-reference")
INSTANCE_KEY = "portability.instance"
WATERMARK_CAPABILITY = "watermark-vector/1"
# Chunks small enough, of reviewable groups, may live in Git; every other chunk is an artifact.
GIT_CHUNK_LIMIT = 256 * 1024
GIT_CHUNK_GROUPS = ("catalogue", "governance", "access")
REQUIRES = ["argus-archive/1", "zstd", "ed25519", "ledger-replay/1", WATERMARK_CAPABILITY, "external-chunks/1"]


class ExportError(ValueError):
    def __init__(self, message: str, code: str = "export_refused", detail: Optional[dict] = None):
        super().__init__(message)
        self.code, self.detail = code, detail or {}


def now() -> datetime:
    return datetime.now(timezone.utc)


def instance(db: Session) -> dict:
    """This deployment's identity: made once, kept in the application settings."""
    from app.models.app_setting import AppSetting
    row = db.get(AppSetting, INSTANCE_KEY)
    if row is None:
        row = AppSetting(key=INSTANCE_KEY, value={"id": str(uuid.uuid4()),
                                                  "name": os.environ.get("ARGUS_INSTANCE_NAME", "argus"),
                                                  "created_at": now().isoformat()})
        db.add(row)
        db.flush()
    return dict(row.value)


def schema_head(db: Session) -> Optional[str]:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 — a database built by create_all has no alembic table
        db.rollback()
        return None


def secure_delete(path: Path) -> None:
    """Overwrite and remove a file or a directory tree (best effort: copy-on-write and flash storage
    may keep old blocks; the institution's volume encryption is the real protection)."""
    if not path.exists():
        return
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    for f in files:
        try:
            size = f.stat().st_size
            os.chmod(f, 0o600)
            with open(f, "r+b") as fh:
                fh.write(b"\0" * min(size, 64 << 20))
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass
    if path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------------- the watermark

def vector_sha256(vector: dict) -> str:
    """The identity of a watermark: SHA-256 of the canonical serialization of its full vector."""
    return hashlib.sha256(json.dumps({k: int(v) for k, v in sorted(vector.items())}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@contextmanager
def at_watermark(engine: Engine, lock_timeout: str = "30s") -> Iterator[tuple[Session, dict]]:
    """A read-only session at a consistent ledger watermark, and the watermark."""
    locker = engine.connect()
    reader = None
    try:
        lt = locker.begin()
        locker.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        locker.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
        try:
            locker.execute(text(f"LOCK TABLE {', '.join(SEQUENCED_TABLES)} IN SHARE MODE"))
        except Exception as e:
            raise ExportError("the ledger is busy: its writers did not finish within the lock timeout",
                              code="ledger_busy") from e
        snapshot = locker.execute(text("SELECT pg_export_snapshot()")).scalar()
        if not re.fullmatch(r"[0-9A-F-]+", snapshot or ""):
            raise ExportError("unexpected snapshot identifier")
        vector = {t: int(locker.execute(text(f"SELECT coalesce(max(seq), 0) FROM {t}")).scalar())
                  for t in SEQUENCED_TABLES}
        checkpoint = int(locker.execute(text("SELECT nextval('portability_checkpoint_seq')")).scalar())
        at = locker.execute(text("SELECT clock_timestamp()")).scalar()
        reader = engine.connect()
        reader.begin()
        reader.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        reader.execute(text(f"SET TRANSACTION SNAPSHOT '{snapshot}'"))
        lt.commit()                       # the lock is held only until the snapshot is shared
        watermark = {"checkpoint_sequence": checkpoint, "vector": vector, "vector_sha256": vector_sha256(vector),
                     "snapshot_time": at.isoformat()}
        with Session(bind=reader) as session:
            yield session, watermark
    finally:
        if reader is not None:
            reader.rollback()
            reader.close()
        locker.close()


# --------------------------------------------------------------------------- restriction

def restrict(db: Session, sc: Scope, classifications: list[str]) -> dict:
    """Leave out restricted records whose class is not included, and hide restricted fields."""
    from app.models.asset import Asset
    from app.models.issue import Issue
    from app.models.ledger import Claim, IdentityBinding
    from app.services.visibility import Grants, hidden_fields, restricted_class
    grants = Grants(classifications)
    excluded_classes: set = set()
    for model in (Asset, Issue):
        for rec in db.scalars(select(model).where(model.workspace_id.in_(sc.workspaces))):
            cls = restricted_class(rec)
            if cls is not None and not grants.allows(cls):
                sc.excluded_uids.add(rec.uid)
                excluded_classes.add(cls)
                continue
            hidden = hidden_fields(db, rec, grants)
            if hidden:
                sc.hidden[rec.uid] = sorted(hidden)
    refs = {ref: uid for ref, uid in db.execute(select(IdentityBinding.source_ref, IdentityBinding.uid))
            if uid in sc.excluded_uids or uid in sc.hidden}
    if refs:
        for c in db.scalars(select(Claim).where(Claim.source_ref.in_(list(refs)))):
            uid = refs[c.source_ref]
            if uid in sc.excluded_uids or (c.predicate.startswith("attr:") and c.predicate[5:] in sc.hidden.get(uid, ())):
                sc.excluded_claims.add(c.claim_id)
    return {"included": sorted(classifications), "excluded_classes": sorted(excluded_classes),
            "fields_hidden": bool(sc.hidden)}


def _withheld(fam: Family, row: dict, sc: Scope) -> bool:
    """A row left out because it is, names, or reveals a restricted record or field."""
    for col in fam.subjects:
        if row.get(col) in sc.excluded_uids:
            return True
    if fam.name in ("claims", "claim_events") and row.get("claim_id") in sc.excluded_claims:
        return True
    pred = row.get("predicate")
    subject = row.get("subject_uid")
    if pred and subject and pred.startswith("attr:") and pred[5:] in sc.hidden.get(subject, ()):
        return True
    if fam.name == "p_fact_state" and row.get("contributor", "").startswith("claim:") and \
            row["contributor"][6:] in sc.excluded_claims:
        return True
    return False


# --------------------------------------------------------------------------- rows

def rows_of(db: Session, fam: Family, sc: Scope, blobs: Optional["Blobs"], grants_classes: list[str],
            ident: Optional[IdentityPolicy] = None) -> Iterator[tuple[str, dict]]:
    """The exported rows of a family: restricted, redacted, blobs replaced by their digest, people
    transformed by the identity profile. A blob a decision excludes leaves its column null."""
    from app.services.visibility import Grants, redacted_attributes
    grants = Grants(grants_classes)
    for obj in db.scalars(fam.select(db, sc)):
        row = {c: to_json(getattr(obj, _attr(fam, c))) for c in fam.columns}
        if _withheld(fam, row, sc):
            continue
        if fam.redact and getattr(obj, "attributes", None) is not None:
            row["attributes"] = redacted_attributes(db, obj, grants)
        for col, kind in fam.blobs.items():
            row[col] = blobs.add(obj, fam, col, kind, row) if blobs is not None else None
        if ident is not None:
            row = ident.row(fam.name, row)
        key = str(getattr(obj, "seq")) if fam.sequenced else fam.key_of(row)
        yield key, row


def _attr(fam: Family, column: str) -> str:
    """The mapped attribute for a column (most share the name)."""
    for prop in fam.model.__mapper__.column_attrs:
        if prop.columns[0].name == column:
            return prop.key
    return column


class Blobs:
    """Every blob of an export: read, inspected, decided on, staged locally — never stored at the
    destination until the whole export has passed (`publish_to`)."""

    def __init__(self, staging: Optional[Path], decisions: dict, encrypted: bool,
                 limits: blob_scan.ScanLimits = blob_scan.LIMITS, policy: Optional[Policy] = None):
        self.policy = policy or Policy.strict()
        self.uninspected: list = []
        self.staging = DirectoryStore("staging", staging) if staging is not None else None
        self.decisions = decisions
        self.encrypted = encrypted
        self.limits = limits
        self.entries: dict[str, dict] = {}
        self.missing: list = []
        self.reports: dict[str, dict] = {}
        self.needs_decision: list = []
        self.secrets: list = []
        self.excluded: list = []

    def decision(self, digest: str, status: str) -> Optional[str]:
        explicit = self.decisions.get(f"blob:{digest}") or (
            self.decisions.get("opaque_blobs") if status in ("opaque", "uninspectable") else
            self.decisions.get("classified_blobs") if status == "finding" else None)
        return explicit or self.by_policy(status)

    def by_policy(self, status: str) -> Optional[str]:
        """The policy's default outcome, when nobody decided: shown as such in the manifest."""
        p = self.policy
        if status == "opaque" and p.opaque_blobs == "allow_with_warning":
            return "approve_opaque"
        if status == "uninspectable" and p.uninspectable_blobs == "allow_with_warning":
            return "approve_opaque"
        if status == "finding" and p.classified_blobs == "allow_with_warning":
            return "accept_classified"
        return None

    def add(self, obj, fam: Family, col: str, kind: str, row: dict) -> Optional[str]:
        value = getattr(obj, _attr(fam, col))
        if value is None:
            return None
        where = f"{fam.name}[{fam.key_of(row)}].{col}"
        if kind == "file":
            path = Path(value)
            if not path.is_file():
                self.missing.append({"family": fam.name, "key": fam.key_of(row), "file": path.name})
                return None
            data = path.read_bytes() if path.stat().st_size <= self.limits.max_bytes else None
            name, mime = row.get("filename") or path.name, row.get("mime_type")
        else:
            data, name, mime = bytes(value), "", None
        if data is None:
            digest = _file_sha(Path(value))
            report = blob_scan.BlobReport(digest, "uninspectable", reason="over the inspection size limit")
        else:
            digest = hashlib.sha256(data).hexdigest()
            report = self.reports.get(digest) and blob_scan.BlobReport(digest, self.reports[digest]["status"],
                                                                       findings=self.reports[digest]["findings"])
            if report is None:
                report = blob_scan.scan(digest, data, mime, name, where, self.limits,
                                        readers=tuple(self.policy.blob_readers))
        self.reports[digest] = report.summary()
        secrets = [f for f in report.findings if f.get("category") == "secret"]
        if secrets:
            self.secrets += secrets
            return None
        if report.status != "ok":
            outcome = self.decision(digest, report.status)
            options = ["approve_opaque", "exclude", "block"] if report.status in ("opaque", "uninspectable") \
                else ["accept_classified", "exclude", "block"]
            if self.encrypted:
                options.append("classify_encrypt")
            if outcome not in options or outcome == "block":
                self.needs_decision.append({"id": f"blob:{digest}", "where": where, "status": report.status,
                                            "reason": report.reason, "findings": report.findings[:5],
                                            "options": options, "outcome": outcome})
                return None
            if outcome == "exclude":
                self.excluded.append({"where": where, "sha256": digest, "status": report.status})
                return None
            if report.status in ("opaque", "uninspectable") and digest not in {u["sha256"] for u in self.uninspected}:
                self.uninspected.append({"where": where, "sha256": digest, "status": report.status,
                                         "reason": report.reason,
                                         "by": "policy" if outcome == self.by_policy(report.status) and not
                                         self.decisions.get(f"blob:{digest}") else "decision"})
        cls = (getattr(obj, "attributes", None) or {}).get("classification") if hasattr(obj, "attributes") else None
        if self.staging is not None and digest not in self.entries:
            if data is None:
                self.staging.put_file(Path(value))
            else:
                self.staging.put_bytes(data)
        e = self.entries.setdefault(digest, {
            "sha256": digest, "size": len(data) if data is not None else Path(value).stat().st_size,
            "mime_type": mime or "application/octet-stream", "classification": cls or "unrestricted",
            "content_inspection": report.status if report.status == "ok" else
            f"{report.status}: {self.decision(digest, report.status)}"
            + (" (uninspected)" if report.status in ("opaque", "uninspectable") else ""),
            "retention_class": row.get("retention_class") or "archive", "referenced_by": []})
        e["referenced_by"].append(f"{fam.name}:{fam.key_of(row)}:{col}")
        return f"sha256:{digest}"

    def publish_to(self, store: DirectoryStore, envelope: Optional[Envelope]) -> None:
        """Copy the staged blobs to the destination, encrypted when the export is."""
        for digest, e in self.entries.items():
            data = (self.staging.root / "sha256" / digest[:2] / digest).read_bytes()
            stored = envelope.encrypt(data, f"blob:{digest}") if envelope is not None else data
            sdigest, ssize = store.put_bytes(stored)
            e.update({"stored_sha256": sdigest, "stored_size": ssize, "locator": store.locator(sdigest),
                      "encryption": {"algorithm": "AES-256-GCM", "aad": f"blob:{digest}"} if envelope else None})


def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def prescan(db: Session, sc: Scope, classifications: list[str], decisions: dict, encrypted: bool,
            policy: Optional[Policy] = None) -> dict:
    """The blob inspection an approver sees before approving: what is blocked, what needs a decision,
    what will travel uninspected. Nothing is stored."""
    blobs = Blobs(None, decisions, encrypted, policy=policy)
    sc = Scope(workspaces=sc.workspaces, watermark={t: 2 ** 62 for t in SEQUENCED_TABLES},
               excluded_uids=sc.excluded_uids, hidden=sc.hidden, excluded_claims=sc.excluded_claims)
    for fam in FAMILIES:
        if fam.blobs:
            for _ in rows_of(db, fam, sc, blobs, classifications):
                pass
    return {"inspected": len(blobs.reports), "secrets": blobs.secrets[:50], "needs_decision": blobs.needs_decision,
            "excluded": blobs.excluded, "missing": blobs.missing[:50], "missing_count": len(blobs.missing),
            "uninspected": blobs.uninspected[:200],
            "ready": not blobs.secrets and not blobs.needs_decision and not blobs.missing}


# --------------------------------------------------------------------------- generate

def generate(engine: Engine, *, export_id: str, mode: str, workspaces: list[str], out_dir: Path,
             store: Optional[DirectoryStore], signer: Optional[Signer], requested_by: str,
             approved_by: Optional[str] = None, classifications: Optional[list[str]] = None,
             decisions: Optional[dict] = None, base_manifest: Optional[dict] = None,
             repository: Optional[dict] = None, include_projections: bool = True,
             identity_profile: Optional[str] = None, envelope: Optional[Envelope] = None,
             policy: Optional[Policy] = None, purpose: Optional[str] = None) -> dict:
    """Write a checkpoint into `out_dir`, copy its artifacts to `store`, and return its manifest.
    Nothing is published to Git here. On any failure nothing is left at the destination."""
    if mode not in MODES:
        raise ExportError(f"unknown export mode {mode!r}")
    if mode == "backup-reference":
        raise ExportError("a backup-reference export names a disaster-recovery backup; it is recorded, "
                          "not generated (docs/export-import-design.md §3)", code="not_generated")
    if mode == "incremental" and base_manifest is None:
        raise ExportError("an incremental export needs its base export", code="no_base")
    classifications = sorted(classifications or [])
    if classifications and envelope is None:
        raise ExportError("restricted classes travel only encrypted, to an approved destination",
                          code="restricted_destination_required")
    if store is None:
        raise ExportError("an artifact store is needed: data chunks and blobs are artifacts", code="no_store")
    decisions = dict(decisions or {})
    out_dir.mkdir(parents=True, exist_ok=False)
    staging = out_dir.parent / f".{out_dir.name}.staging"
    try:
        return _generate(engine, export_id, mode, workspaces, out_dir, staging, store, signer, requested_by,
                         approved_by, classifications, decisions, base_manifest, repository, include_projections,
                         identity_profile, envelope, policy or Policy.strict(), purpose)
    except BaseException:
        secure_delete(out_dir)
        raise
    finally:
        secure_delete(staging)


def _generate(engine, export_id, mode, workspaces, out_dir, staging, store, signer, requested_by, approved_by,
              classifications, decisions, base_manifest, repository, include_projections, identity_profile,
              envelope, policy, purpose) -> dict:
    from app.models.user import User
    with Session(engine) as w:
        inst = instance(w)
        w.commit()
        head = schema_head(w)
    with at_watermark(engine) as (db, watermark):
        from app.models.workspace import Workspace
        if mode in ("full",) or (mode == "incremental" and base_manifest.get("mode") == "full"):
            workspaces = sorted(db.scalars(select(Workspace.id).where(Workspace.import_state.is_(None))))
        elif mode == "incremental":
            workspaces = list(base_manifest["workspaces"])
        if not workspaces:
            raise ExportError("nothing to export: no workspace selected")
        missing_ws = [w_ for w_ in workspaces if db.get(Workspace, w_) is None]
        if missing_ws:
            raise ExportError(f"unknown workspaces {missing_ws}", code="not_found")
        previous = dict(base_manifest["watermark"]["vector"]) if mode == "incremental" else {}
        if previous and set(previous) != set(SEQUENCED_TABLES):
            raise ExportError("the base export's watermark has other sequenced families: a new full "
                              "checkpoint is needed", code="incompatible_base")
        if previous and any(watermark["vector"].get(t, 0) < v for t, v in previous.items()):
            raise ExportError("the base export is ahead of this instance's ledger", code="out_of_order")
        sc = Scope(workspaces=sorted(workspaces), watermark=watermark["vector"], previous=previous)
        restriction = restrict(db, sc, classifications)
        analysis = closure.resolve(db, sc, decisions)
        site_dependencies = _site_dependencies(db, sc)
        if analysis["unresolved"] or analysis["blocked"]:
            raise ExportError("dependencies need an outcome before this export can run", code="closure",
                              detail={"closure": analysis})
        if sc.excluded_uids:            # computed again for workspaces the closure added
            restriction = restrict(db, sc, classifications)
        ident = IdentityPolicy.make(identity_profile, [(u.id, u.email, u.username if u.username and
                                                        len(u.username) >= 3 else None)
                                                       for u in db.scalars(select(User))])
        blobs = Blobs(staging, decisions, envelope is not None, policy=policy)
        findings: list = []
        families: dict = {}
        for group in GROUP_ORDER:
            for fam in [f for f in FAMILIES if f.group == group]:
                if fam.group == "projection" and not include_projections:
                    continue
                items = list(rows_of(db, fam, sc, blobs, classifications, ident))
                findings += secret_scan.scan_rows(fam.name, items)
                written = chunks.write_chunks(out_dir, f"{group}-{fam.name}", fam.name, items)
                families[fam.name] = {
                    "group": group, "authoritative": fam.authoritative, "sequenced": fam.sequenced,
                    "replace_set": fam.replace_set, "rows": sum(c["rows"] for c in written),
                    "sha256": hashlib.sha256("".join(c["content_sha256"] for c in written).encode()).hexdigest(),
                    "chunks": written, "schema": f"format/families/{fam.name}.schema.json"}
        if findings or blobs.secrets:
            raise ExportError("the export holds what looks like a secret; nothing was stored or published",
                              code="secret_found", detail={"findings": (findings + blobs.secrets)[:50]})
        if blobs.needs_decision:
            raise ExportError(f"{len(blobs.needs_decision)} blob(s) could not be inspected or carry restricted "
                              "markers, and need a decision", code="blob_review",
                              detail={"blobs": blobs.needs_decision[:100]})
        if blobs.missing:
            raise ExportError(f"{len(blobs.missing)} attachment file(s) are missing; the archive would not be "
                              "artifact-complete", code="blob_missing", detail={"missing": blobs.missing[:50]})
        versions = _versions(db)
        from app.ledger import invariants
        try:
            inv = invariants.report(db, sc.workspaces)
            inv_summary = {"ok": inv.get("ok"), "codes": sorted(k for k, v in (inv.get("invariants") or {}).items()
                                                                if isinstance(v, dict) and not v.get("ok", True))}
        except Exception as e:  # noqa: BLE001 — the report is evidence, not a gate, at export time
            db.rollback()
            inv_summary = {"ok": None, "error": str(e)[:200]}

    # Everything passed: chunks are placed (Git or artifact, encrypted when the export is), blobs copied.
    for fam in families.values():
        for c in fam["chunks"]:
            _place_chunk(out_dir, c, fam["group"], store, envelope)
    blobs.publish_to(store, envelope)
    blob_lines = [json.dumps(b, sort_keys=True) for b in sorted(blobs.entries.values(), key=lambda b: b["sha256"])]
    blob_manifest = "".join(x + "\n" for x in blob_lines).encode()
    if envelope is not None:
        blob_manifest = envelope.encrypt(blob_manifest, "blobs.manifest.ndjson")
    (out_dir / "blobs.manifest.ndjson").write_bytes(blob_manifest)
    (out_dir / "relation-registry.json").write_text(json.dumps(registry_view(), indent=1, sort_keys=True) + "\n")
    (out_dir / "workspaces.ndjson").write_text("".join(
        json.dumps({"id": w_}, sort_keys=True) + "\n" for w_ in sc.workspaces))
    complete = mode in ("full",) and not restriction["excluded_classes"] and not restriction["fields_hidden"] \
        and not blobs.excluded
    selective = mode in ("workspace", "evidence-only") or (mode == "incremental" and base_manifest.get("selective"))
    stored = sorted(blobs.entries.values(), key=lambda b: b["sha256"])
    manifest = {
        "format": FORMAT, "format_major": FORMAT_MAJOR, "export_id": export_id, "mode": mode,
        "labels": {"complete": complete and not selective, "selective": bool(selective),
                   "incremental": mode == "incremental", "evidence_only": mode == "evidence-only",
                   "signed": signer is not None, "encrypted": envelope is not None, "artifact_complete": True,
                   "uninspected_content": bool(blobs.uninspected)},
        "purpose": purpose,
        "policy": policy.describe(),
        "selective": bool(selective),
        "argus": {"application_version": os.environ.get("ARGUS_VERSION", "1.0.0"), "database_schema": head,
                  "instance_id": inst["id"], "instance_name": inst.get("name")},
        "repository": repository or {},
        "workspaces": sc.workspaces,
        "watermark": watermark,
        "base": ({"export_id": base_manifest["export_id"], "watermark": base_manifest["watermark"],
                  "manifest_sha256": base_manifest.get("_sha256")} if mode == "incremental" else None),
        "versions": versions,
        "created_at": now().isoformat(), "requested_by": ident.value(requested_by),
        "approved_by": ident.value(approved_by),
        "identity": ident.describe(),
        "families": families,
        "blobs": {"count": len(stored), "bytes": sum(b["size"] for b in stored),
                  "manifest": "blobs.manifest.ndjson", "stores": [store.name] if stored else [],
                  "stored": [{"stored_sha256": b["stored_sha256"], "size": b["stored_size"], "locator": b["locator"]}
                             for b in stored],
                  "excluded": len(blobs.excluded),
                  "inspection": {"ok": sum(1 for b in stored if b["content_inspection"] == "ok"),
                                 "by_decision": sum(1 for b in stored if b["content_inspection"] != "ok"),
                                 "uninspected": len(blobs.uninspected),
                                 "readers": list(policy.blob_readers)},
                  "uninspected": [{k: u[k] for k in ("sha256", "status", "reason", "by")}
                                  for u in blobs.uninspected[:1000]]},
        "classifications": restriction,
        # A facility exported without its site keeps what it inherits from the site only as a dependency: an import
        # never makes a site-wide grant or a second copy of the site's group from it (issue #26).
        "site_dependencies": site_dependencies,
        "closure": {"dependencies": [_public(d) for d in analysis["dependencies"]],
                    "automatic": analysis["automatic"],
                    "decisions": {k: v for k, v in decisions.items() if not k.startswith("blob:")}},
        "invariants": inv_summary,
        "encryption": ({**envelope.metadata(), "covers": ["data chunks", "blobs", "blobs.manifest.ndjson"]}
                       if envelope is not None else None),
        "importer": {"requires": REQUIRES + (["envelope/1"] if envelope is not None else []),
                     "database_schema": head, "sequenced_families": sorted(SEQUENCED_TABLES)},
    }
    (out_dir / "reconciliation.json").write_text(json.dumps({
        "export_id": export_id, "watermark": watermark,
        "families": {k: {"rows": v["rows"], "sha256": v["sha256"]} for k, v in families.items()},
        "invariants": inv_summary}, indent=1, sort_keys=True))
    return finish(out_dir, manifest, signer)


def _place_chunk(out_dir: Path, c: dict, group: str, store: DirectoryStore, envelope: Optional[Envelope]) -> None:
    """Decide where a chunk lives: Git for small reviewable groups, the artifact store otherwise; an
    encrypted export keeps every chunk encrypted, as an artifact."""
    path = out_dir / c["file"]
    if envelope is None and group in GIT_CHUNK_GROUPS and c["bytes"] <= GIT_CHUNK_LIMIT:
        c.update({"storage": "git", "path": c["file"]})
        return
    if envelope is not None:
        path.write_bytes(envelope.encrypt(path.read_bytes(), c["file"]))
    data = path.read_bytes()
    digest, size = store.put_bytes(data)
    c.update({"storage": "artifact", "locator": store.locator(digest), "sha256": digest, "bytes": size,
              "encrypted": envelope is not None})


def _site_dependencies(db, sc) -> list[dict]:
    from app.models.workspace import Workspace
    from app.services.site_group_grants import of_site
    out = []
    for wid in sc.workspaces:
        ws = db.get(Workspace, wid)
        if ws is None or not ws.site_id or ws.site_id in sc.workspaces:
            continue
        out.append({"workspace": wid, "site": ws.site_id,
                    "inherited": [{"group": g["group_name"], "group_uid": g["group_uid"], "role": g["role_id"]}
                                  for g in of_site(db, ws.site_id)]})
    return out


def _public(dep: dict) -> dict:
    """A dependency as the manifest (and so every repository reader) sees it: a restricted one by its
    outcome only — no count, no example, nothing that says how many or which."""
    if dep["rule"] == "restricted_reference":
        return {k: dep[k] for k in ("id", "rule", "outcome", "options")}
    return dep


def finish(out_dir: Path, manifest: dict, signer: Optional[Signer]) -> dict:
    """Write the manifest, the checksums of every file, and the signature over both."""
    if signer is not None:
        manifest["signature"] = {"algorithm": "ed25519", "key_id": signer.key_id, "principal": signer.principal}
    body = json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    (out_dir / "manifest.json").write_text(body)
    manifest_sha = hashlib.sha256(body.encode()).hexdigest()
    names = sorted(p.name for p in out_dir.iterdir() if p.name not in ("checksums.sha256", "signature.json"))
    sums = "".join(f"{chunks.sha256_file(out_dir / n)}  {n}\n" for n in names)
    (out_dir / "checksums.sha256").write_text(sums)
    if signer is not None:
        sig = sign_checkpoint(signer, hashlib.sha256(sums.encode()).hexdigest(), manifest_sha)
        (out_dir / "signature.json").write_text(json.dumps(sig, indent=1, sort_keys=True) + "\n")
    manifest["_sha256"] = manifest_sha
    return manifest


def _stable(v):
    if isinstance(v, (set, frozenset)):
        return sorted(_stable(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_stable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _stable(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if hasattr(v, "__dataclass_fields__"):
        return {k: _stable(getattr(v, k)) for k in sorted(v.__dataclass_fields__)}
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)


def registry_view() -> dict:
    """The relation registry and the relation semantics, in a stable form (hashed and published)."""
    from app.ledger import registry
    from app.services import causal_model
    return {"endpoints": _stable(registry.ENDPOINTS), "cardinality": _stable(registry.CARDINALITY),
            "semantics": _stable(causal_model.SEMANTICS)}


def _versions(db: Session) -> dict:
    from app.models.ledger import LedgerPolicy
    from app.models.workflow import Workflow
    lock = Path(__file__).resolve().parents[1] / "ledger" / "rules.lock.json"
    policy = db.scalar(select(LedgerPolicy).order_by(LedgerPolicy.activated_at.desc()).limit(1))
    reg = json.dumps(registry_view(), sort_keys=True)
    wf = json.dumps(sorted((w.uid, str(w.updated_at) if hasattr(w, "updated_at") else "")
                           for w in db.scalars(select(Workflow))), default=str)
    return {"policy": policy.version if policy else None,
            "rules_lock_sha256": chunks.sha256_file(lock) if lock.exists() else None,
            "relation_registry_sha256": hashlib.sha256(reg.encode()).hexdigest(),
            "workflows_sha256": hashlib.sha256(wf.encode()).hexdigest()}


# --------------------------------------------------------------------------- schemas

def json_schemas() -> dict[str, dict]:
    """The JSON Schemas of the format: the manifest, the record envelope, the blob manifest, and one
    per family, generated from the same table definitions the exporter reads."""
    from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, Integer, LargeBinary
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    def col_schema(col) -> dict:
        t = col.type
        if isinstance(t, (Integer, BigInteger)):
            s = {"type": "integer"}
        elif isinstance(t, Float):
            s = {"type": "number"}
        elif isinstance(t, Boolean):
            s = {"type": "boolean"}
        elif isinstance(t, DateTime):
            s = {"type": "string", "format": "date-time"}
        elif isinstance(t, Date):
            s = {"type": "string", "format": "date"}
        elif isinstance(t, LargeBinary):
            s = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
        elif isinstance(t, (JSONB, JSON)):
            s = {}
        elif isinstance(t, ARRAY):
            s = {"type": "array"}
        else:
            s = {"type": "string"}
        if col.nullable and s:
            s = {"anyOf": [s, {"type": "null"}]}
        return s

    base = "https://argus.infn.it/schemas/argus-archive/1"
    out = {}
    for fam in FAMILIES:
        props = {c.name: col_schema(c) for c in fam.model.__table__.columns if c.name not in fam.exclude}
        for col in fam.blobs:
            props[col] = {"anyOf": [{"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}, {"type": "null"}]}
        if fam.name == "identities":     # which columns travel depends on the identity profile
            props = {k: v for k, v in props.items() if k in ("id", "oidc_sub", "dn", "email", "name", "username",
                                                             "source", "active", "created_at")}
            props["actor_type"] = {"type": "string"}
            props["issuer_hash"] = {"type": "string"}
        out[f"families/{fam.name}.schema.json"] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{base}/families/{fam.name}.json",
            "title": f"{fam.name} ({fam.group}{'' if fam.authoritative else ', not authoritative'})",
            "type": "object", "properties": props, "additionalProperties": False}
    out["record.schema.json"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{base}/record.json",
        "title": "One line of a chunk", "type": "object", "required": ["f", "k", "d"], "additionalProperties": False,
        "properties": {"f": {"type": "string", "enum": [f.name for f in FAMILIES]},
                       "k": {"type": "string"}, "d": {"type": "object"}}}
    out["ledger.schema.json"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{base}/ledger.json",
        "title": "A ledger line: a record envelope of a ledger family; `k` is the source seq for sequenced ones",
        "allOf": [{"$ref": "record.json"}],
        "properties": {"f": {"enum": [f.name for f in FAMILIES if f.group == "ledger"]}}}
    out["blob-manifest.schema.json"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{base}/blob-manifest.json",
        "title": "One line of blobs.manifest.ndjson", "type": "object",
        "required": ["sha256", "size", "locator", "classification"],
        "properties": {"sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "size": {"type": "integer"},
                       "stored_sha256": {"type": "string"}, "stored_size": {"type": "integer"},
                       "content_inspection": {"type": "string"},
                       "mime_type": {"type": ["string", "null"]}, "locator": {"type": "string"},
                       "classification": {"type": "string"}, "encryption": {"type": ["object", "null"]},
                       "recipients": {"type": "array", "items": {"type": "string"}},
                       "retention_class": {"type": "string"},
                       "referenced_by": {"type": "array", "items": {"type": "string"}}}}
    out["manifest.schema.json"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{base}/manifest.json",
        "title": "argus-archive/1 manifest", "type": "object",
        "required": ["format", "format_major", "export_id", "mode", "labels", "argus", "workspaces", "watermark",
                     "identity", "families", "blobs", "classifications", "closure", "importer"],
        "properties": {
            "format": {"const": FORMAT}, "format_major": {"const": FORMAT_MAJOR},
            "export_id": {"type": "string"}, "mode": {"enum": list(MODES)},
            "labels": {"type": "object", "required": ["complete", "selective", "incremental", "evidence_only",
                                                      "signed", "encrypted", "artifact_complete"]},
            "argus": {"type": "object", "required": ["application_version", "database_schema", "instance_id"]},
            "repository": {"type": "object"}, "workspaces": {"type": "array", "items": {"type": "string"}},
            "watermark": {"type": "object", "required": ["checkpoint_sequence", "vector", "vector_sha256",
                                                         "snapshot_time"],
                          "properties": {"checkpoint_sequence": {"type": "integer"},
                                         "vector": {"type": "object", "additionalProperties": {"type": "integer"}},
                                         "vector_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                                         "snapshot_time": {"type": "string", "format": "date-time"}}},
            "identity": {"type": "object", "required": ["profile"]},
            "base": {"type": ["object", "null"]}, "versions": {"type": "object"},
            "families": {"type": "object", "additionalProperties": {
                "type": "object", "required": ["group", "authoritative", "rows", "sha256", "chunks"],
                "properties": {"chunks": {"type": "array", "items": {
                    "type": "object", "required": ["file", "storage", "sha256", "bytes", "rows", "content_sha256"],
                    "properties": {"storage": {"enum": ["git", "artifact"]}, "path": {"type": "string"},
                                   "locator": {"type": "string"}, "sha256": {"type": "string"},
                                   "bytes": {"type": "integer"}, "encrypted": {"type": "boolean"}}}}}}},
            "blobs": {"type": "object", "required": ["count", "bytes", "manifest"]},
            "classifications": {"type": "object"}, "closure": {"type": "object"},
            "encryption": {"type": "object"}, "signature": {"type": "object"},
            "importer": {"type": "object", "required": ["requires"]}}}
    return out
