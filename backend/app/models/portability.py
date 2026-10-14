"""Portable exports and imports (docs/export-import-design.md).

* `PortabilityExport` and `PortabilityImport` are the two lifecycles. Their `state` moves only
  through `app.portability.lifecycle`, which checks the transition, who may make it, and writes
  a `PortabilityEvent` for it.
* `PortabilityEvent` is the audit of both: append-only (the same database guard as the ledger's
  audit tables) and sealed in the daily digest chain. No second audit system.
* `PortabilityRowMap` is what makes an import idempotent and undoable while it is staged: every
  row an import wrote, by its key in the archive and its key here.
* `PortabilityTagSeen` remembers which commit each export tag named when it was imported, so a
  tag that has since moved is refused.
* `PortabilityOriginRecord` is the origin chain of imported ledger rows (append-only).
* `PortabilityDownloadToken` holds single-use download capabilities, as hashes.
"""
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Sequence, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class PortabilityExport(Base):
    __tablename__ = "portability_exports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)        # full | incremental | workspace | evidence-only | backup-reference
    workspaces: Mapped[list] = mapped_column(JSONB, default=list)
    base_export_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classifications: Mapped[list] = mapped_column(JSONB, default=list)   # restricted classes included
    decisions: Mapped[dict] = mapped_column(JSONB, default=dict)         # dependency outcomes, by dependency id
    destination: Mapped[dict] = mapped_column(JSONB, default=dict)       # {"repository": ..., "artifact_store": ...}
    state: Mapped[str] = mapped_column(String, default="requested", index=True)
    risk: Mapped[str] = mapped_column(String, default="normal")          # normal | high
    requested_by: Mapped[str] = mapped_column(String)
    approved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)          # closure, estimate, warnings
    watermark: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    manifest: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    manifest_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    out_dir: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    git: Mapped[dict] = mapped_column(JSONB, default=dict)               # repository, commit, tag, parent
    # Retention (default 90 days for archives, quarantine, staging and evidence copies): a legal hold
    # suspends deletion; `purged_at` records when the files went (the record and its audit stay).
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    legal_hold_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    purged_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PortabilityImport(Base):
    __tablename__ = "portability_imports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)        # restore | clone | merge | selective | evidence
    source: Mapped[dict] = mapped_column(JSONB, default=dict)   # {"repository", "ref", "expected_commit"} or {"upload"}
    state: Mapped[str] = mapped_column(String, default="created", index=True)
    requested_by: Mapped[str] = mapped_column(String)
    approved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quarantine_dir: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    commit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    manifest: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    verification: Mapped[dict] = mapped_column(JSONB, default=dict)
    dry_run: Mapped[dict] = mapped_column(JSONB, default=dict)
    decisions: Mapped[dict] = mapped_column(JSONB, default=dict)      # workspace map, conflict outcomes
    checkpoints: Mapped[dict] = mapped_column(JSONB, default=dict)    # {"done": ["family:chunk", ...]}
    reconciliation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reconciliation_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    staging: Mapped[dict] = mapped_column(JSONB, default=dict)     # the isolated staging database
    # Retention (default 90 days for archives, quarantine, staging and evidence copies): a legal hold
    # suspends deletion; `purged_at` records when the files went (the record and its audit stay).
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    legal_hold_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    purged_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PortabilityEvent(Base):
    """One transition or audited action of an export or import. Append-only."""
    __tablename__ = "portability_events"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_kind: Mapped[str] = mapped_column(String)          # export | import
    subject_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)                  # the action: approve, generate, download …
    from_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class PortabilityRowMap(Base):
    __tablename__ = "portability_row_map"
    __table_args__ = (UniqueConstraint("origin", "family", "source_key", name="uq_portability_row"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    origin: Mapped[str] = mapped_column(String)                # the exporting instance's identity
    family: Mapped[str] = mapped_column(String)
    source_key: Mapped[str] = mapped_column(String)
    local_key: Mapped[str] = mapped_column(String)
    import_id: Mapped[str] = mapped_column(String, index=True)
    created: Mapped[bool] = mapped_column(Boolean, default=True)   # False: an identical row was already here
    # The row as this import left it: a later increment may update it only if nobody here changed it since.
    content_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class PortabilityTagSeen(Base):
    __tablename__ = "portability_tags_seen"

    repository_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)
    commit: Mapped[str] = mapped_column(String)
    tag_object: Mapped[str] = mapped_column(String)
    first_seen: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    import_id: Mapped[str] = mapped_column(String)


class PortabilityChainLink(Base):
    """An export applied here, per origin: the order increments must follow, by exact watermark."""
    __tablename__ = "portability_chain"

    origin: Mapped[str] = mapped_column(String, primary_key=True)
    export_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    watermark_label: Mapped[int] = mapped_column(BigInteger)        # the origin's checkpoint sequence
    vector_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    manifest_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    import_id: Mapped[str] = mapped_column(String)
    applied_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


# Export checkpoints are numbered from a sequence that nothing purges: a discard, a rollback or a
# purge never makes a checkpoint number repeat or move backwards.
CHECKPOINT_SEQUENCE = Sequence("portability_checkpoint_seq", metadata=Base.metadata)


class PortabilityOriginRecord(Base):
    """One imported ledger row, as the origin chain recorded it. Append-only.

    The imported row itself lives in its ordinary table with a new local sequence and a local
    `recorded_at`; this record keeps where it came from — origin instance, family, original sequence
    or key, original record time, the hash of its archive line and of the checkpoint — and which
    local ingestion event brought it. `portability.origin.verify_chain` recomputes the hashes."""
    __tablename__ = "portability_origin_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_id: Mapped[str] = mapped_column(String, index=True)
    origin_instance_id: Mapped[str] = mapped_column(String, index=True)
    origin_family: Mapped[str] = mapped_column(String)
    origin_sequence: Mapped[str] = mapped_column(String)            # the origin's seq, or key for id-keyed rows
    origin_recorded_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    origin_event_hash: Mapped[str] = mapped_column(String)
    origin_checkpoint_hash: Mapped[str] = mapped_column(String)
    local_table: Mapped[str] = mapped_column(String)
    local_key: Mapped[str] = mapped_column(String)
    local_ingested_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    local_ingestion_event_id: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(BigInteger)               # order in the origin chain


class PortabilityDownloadToken(Base):
    """A single-use, short-lived download capability, stored as a hash, bound to an export, an actor
    and the exact archive version (manifest hash)."""
    __tablename__ = "portability_download_tokens"

    token_sha256: Mapped[str] = mapped_column(String, primary_key=True)
    export_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    manifest_sha256: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)


class PortabilityJob(Base):
    """A long step (generate, publish, fetch, verify, execute, finalize) run in the background:
    queued → running → completed | failed. Polled by the web pages; the step's own audit is in
    portability_events as always."""
    __tablename__ = "portability_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String)            # export | import
    subject_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="queued", index=True)
    requested_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)   # duration, peak memory



class PortabilitySchedule(Base):
    """A published Git export, repeated at an interval (app.portability.schedules).

    Each run makes a new export with the same scope and destination — an increment on the last one published,
    or a complete one — and takes it through analysis, approval, generation and publication. Setting the schedule
    is the standing approval of its runs, given by an administrator; a run whose analysis needs a person's
    decision stops there and waits for one. Only normal-risk exports can be scheduled."""
    __tablename__ = "portability_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_export_id: Mapped[str] = mapped_column(String, index=True)
    chain: Mapped[str] = mapped_column(String, default="incremental")      # incremental | complete
    every_minutes: Mapped[int] = mapped_column(Integer)
    skip_unchanged: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # The export each run repeats: scope, destination, outcomes and identity profile, as approved.
    mode: Mapped[str] = mapped_column(String)
    workspaces: Mapped[list] = mapped_column(JSONB, default=list)
    destination: Mapped[dict] = mapped_column(JSONB, default=dict)
    decisions: Mapped[dict] = mapped_column(JSONB, default=dict)
    next_run_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    running_since: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outcome: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # published | unchanged | waiting | failed
    last_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_export_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_published_export_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String)
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
