/** Portable exports and imports (docs/export-import-design.md). */

/** Portability set-up made in the web app (app/portability/ui_config.py); secrets are never sent. */
export interface SetupRepository {
  name: string;
  url: string;
  provider: "github" | "gitlab" | "other" | "local";
  auth: "ssh" | "https" | "none" | "local";
  source: "web";
  public_key: string | null;
  has_token: boolean;
  host_keys: { type: string; fingerprint: string }[];
  host_keys_confirmed: boolean;
  status: "pending" | "active";
  usable: boolean;
  created_by: string;
  created_at: string | null;
  approved_by: string | null;
  last_test: { at: string; read: boolean; write: boolean | null; error: string | null } | null;
}

export interface PortabilitySetup {
  enabled: boolean;
  separation_of_duties: boolean;
  deployment: { repositories: string[]; stores: string[]; signing_key: boolean; trusted_keys: boolean };
  stores: { name: string; note: string | null; status: "pending" | "active"; path: string; created_by: string;
            created_at: string | null; approved_by: string | null }[];
  repositories: SetupRepository[];
  trusted_keys: { id: string; principal: string; key_id: string; note: string | null; line: string;
                  status: "pending" | "active"; created_by: string; created_at: string | null; approved_by: string | null }[];
  signing_keys: { id: string; principal: string; key_id: string; public_line: string; status: "pending" | "active";
                  created_by: string; created_at: string | null; approved_by: string | null }[];
}

export interface PortabilityConfig {
  repositories: string[];
  artifact_stores: string[];
  /** The value that keeps an export's data in its repository, with the archive. */
  repository_store?: string;
  signing: { configured: boolean; key_id: string | null; principal: string | null; public_line?: string | null };
  trusted_keys: boolean;
  ui_config?: { enabled: boolean; sources: { repositories: Record<string, "deployment" | "web">;
                signing_key: "deployment" | "web" | null; trusted_keys: "deployment" | "web" | "both" | null } };
  restricted_classes: string[];
  export_modes: string[];
  import_modes: string[];
  outcomes: string[];
  is_admin: boolean;
  restricted_destinations: Record<string, string[]>;
  encryption_recipients: string[];
  identity_profiles: string[];
  default_identity_profile: string;
  blob_outcomes: string[];
  step_up_seconds: number;
  /** Approved recipients per restricted repository (administrators only). */
  recipients: Record<string, string[]>;
  purposes: string[];
  purpose_profiles: Record<string, string>;
  policy: PortabilityPolicy;
}

/** The policy in force (docs/export-import-design.md §20): every relaxed choice is named. */
export interface PortabilityPolicy {
  profile: "trusted" | "strict";
  separation_of_duties: boolean;
  step_up: "strict" | "session_confirmation";
  step_up_seconds: number;
  session_seconds: number;
  full_identity_high_risk: boolean;
  opaque_blobs: string;
  uninspectable_blobs: string;
  classified_blobs: string;
  blob_readers: string[];
  export_permission: string;
  import_permission: string;
  evidence_workspace_admins: boolean;
  query_tokens: boolean;
  retention_days: number;
  relaxations: string[];
}

export interface PortabilityJob {
  id: string;
  subject_kind: "export" | "import";
  subject_id: string;
  action: string;
  state: "queued" | "running" | "completed" | "failed";
  requested_by: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: { error: string; code: string } | null;
  metrics: { seconds?: number; process_peak_memory_mb?: number;
             /** What a running step is doing and how far it has got. */
             progress?: { stage: string; done: number | null; total: number | null; percent: number | null; at: string } | null };
}

export interface LegalHold {
  legal_hold: boolean;
  legal_hold_reason: string | null;
  purged_at: string | null;
}

export interface BlobDecision {
  id: string;
  where: string;
  status: "opaque" | "uninspectable" | "finding";
  reason?: string | null;
  findings: { where: string; kind: string; category?: string }[];
  options: string[];
  outcome: string | null;
}

export interface ArchiveLabels {
  complete: boolean;
  selective: boolean;
  full: boolean;
  incremental: boolean;
  signed: boolean;
  encrypted: boolean;
  artifact_complete: boolean;
  evidence_only: boolean;
  git_published: boolean;
  verified: boolean;
  restorable: boolean;
  /** Files that travelled without content inspection (opaque or unreadable), under policy or decision. */
  uninspected_content?: boolean;
}

export interface UninspectedBlob {
  where: string;
  sha256: string;
  status: "opaque" | "uninspectable";
  reason: string | null;
  by: "policy" | "decision";
}

export interface Dependency {
  id: string;
  rule: string;
  workspace: string | null;
  count?: number;
  examples?: { from: string; to: string }[];
  options: string[];
  outcome: string | null;
  problem?: string;
}

export interface ExportAnalysis {
  closure?: {
    dependencies: Dependency[];
    automatic: { rule: string; outcome: string; detail: string }[];
    unresolved: string[];
    blocked: string[];
    workspaces?: string[];
  };
  restriction?: { included: string[]; excluded_classes: string[]; fields_hidden: boolean };
  estimate?: { records: number; tickets: number; claim_events: number; attachments: number; attachment_bytes: number };
  blobs?: { inspected: number; secrets: { where: string; kind: string }[]; needs_decision: BlobDecision[];
            excluded: { where: string; sha256: string; status: string }[]; missing: unknown[]; ready: boolean;
            uninspected?: UninspectedBlob[] };
  identity_profile?: string;
  policy?: PortabilityPolicy;
  metrics?: { seconds: number; peak_memory_mb: number; rows: number; artifact_bytes: number };
  ready?: boolean;
  warnings?: string[];
}

export interface Watermark {
  checkpoint_sequence: number;
  vector: Record<string, number>;
  vector_sha256: string;
  snapshot_time: string;
}

export interface PortabilityError {
  error: string;
  code: string;
  [k: string]: unknown;
}

export interface ExportView {
  id: string;
  mode: string;
  state: string;
  risk: "normal" | "high";
  workspaces: string[];
  classifications: string[];
  base_export_id: string | null;
  destination: { repository?: string | null; artifact_store?: string | null };
  decisions: Record<string, string>;
  requested_by: string;
  approved_by: string | null;
  analysis: ExportAnalysis;
  watermark: Watermark | null;
  manifest_sha256: string | null;
  git: { repository?: string; repository_id?: string; commit?: string; tag?: string; parent?: string | null;
         previous_tag?: string | null; root_commit?: string; repository_bytes?: number; files_in_git?: number };
  identity_profile?: string;
  error: PortabilityError | null;
  labels: ArchiveLabels;
  created_at: string | null;
  legal_hold: boolean;
  legal_hold_reason: string | null;
  purged_at: string | null;
}

export interface FamilyManifest {
  group: string;
  authoritative: boolean;
  rows: number;
  sha256: string;
  chunks: { file: string; rows: number; first: string | null; last: string | null; bytes: number;
            storage?: "git" | "artifact"; locator?: string; encrypted?: boolean }[];
}

export interface ArchiveManifest {
  format: string;
  export_id: string;
  mode: string;
  /** The portability policy the archive was made under (informative: never needed to read it). */
  policy?: PortabilityPolicy;
  purpose?: string | null;
  labels: Record<string, boolean>;
  argus: { application_version: string; database_schema: string | null; instance_id: string; instance_name?: string };
  workspaces: string[];
  watermark: Watermark;
  base: { export_id: string; watermark: Watermark } | null;
  versions: Record<string, string | null>;
  families: Record<string, FamilyManifest>;
  blobs: { count: number; bytes: number; manifest: string; stores: string[]; excluded?: number;
           inspection?: { ok: number; by_decision: number; uninspected?: number; readers?: string[] };
           uninspected?: UninspectedBlob[] };
  identity?: { profile: string; identity_columns: string[]; actors_transformed: boolean; salt_key_id?: string };
  encryption?: { algorithm: string; key_wrapping: string; recipients: { recipient: string; key_id: string }[] } | null;
  classifications: { included: string[]; excluded_classes: string[]; fields_hidden: boolean };
  closure: { dependencies: Dependency[]; automatic: { rule: string; outcome: string; detail: string }[];
             decisions: Record<string, string> };
  invariants?: { ok: boolean | null; codes?: string[] };
  signature?: { algorithm: string; key_id: string; principal: string };
  created_at: string;
  requested_by: string;
  approved_by: string | null;
}

export interface DryRunReport {
  mode: string;
  export_id: string;
  ready: boolean;
  note?: string;
  workspaces?: { archive: string; local: string; exists: boolean }[];
  families?: Record<string, Record<string, number>>;
  blocking?: { family: string; key: string; reason: string; resolvable?: boolean; fields?: string[];
    local?: Record<string, unknown>; archive?: Record<string, unknown> }[];
  blocking_count?: number;
  catalogue_conflicts?: { family: string; key: string; reason: string }[];
  identity_candidates?: { archive: string; here: string; identifier: string; value: string }[];
  unresolved_references?: { family: string; key: string; missing: [string, string][] }[];
  unresolved_reference_count?: number;
  unresolved_references_outcome?: string;
  identities?: { user: string; note: string }[];
  governance_not_loaded?: string[];
  chain?: { status: string; problem?: string; applied?: number };
  uninspected_content?: { count: number; warning: string; items: UninspectedBlob[] };
}

export interface ImportView {
  id: string;
  mode: string;
  state: string;
  source: { repository?: string; ref?: string; expected_commit?: string };
  commit: string | null;
  requested_by: string;
  approved_by: string | null;
  decisions: Record<string, unknown>;
  manifest: (Pick<ArchiveManifest, "export_id" | "mode" | "workspaces" | "watermark" | "argus" | "labels" |
    "classifications" | "base" | "blobs" | "identity"> & { policy?: PortabilityPolicy; purpose?: string | null }) | null;
  staging?: { database?: string; created_at?: string };
  verification: {
    git?: { repository_id: string; root_commit: string; commit: string; tag: string | null; tag_object: string | null;
            signed_by: string; export_id: string; previous_tag: string | null; lfs_pointers: unknown[] };
    upload?: { bytes: number; sha256: string };
    checkpoint?: { files: number; chunks: number; rows: number; blobs: number; blob_bytes: number;
                   signed_by: string | null; artifact_complete: boolean; manifest_sha256: string;
                   external_chunks?: number; content_verified?: boolean; encrypted?: boolean };
  };
  dry_run: DryRunReport | Record<string, never>;
  checkpoints: { done: number };
  reconciliation_passed: boolean | null;
  reconciliation_sha256: string | null;
  error: PortabilityError | null;
  labels: ArchiveLabels;
  created_at: string | null;
  legal_hold: boolean;
  legal_hold_reason: string | null;
  purged_at: string | null;
}

export interface FamilyReconciliation {
  rows: number;
  expected_rows: number;
  sha256: string;
  expected_sha256: string;
  ok: boolean;
  mismatch_count: number;
  mismatches: { key: string; missing: boolean; fields: string[] }[];
}

export interface ReconciliationReport {
  passed: boolean;
  evidence_only?: boolean;
  already_applied?: boolean;
  export_id: string;
  families?: Record<string, FamilyReconciliation>;
  projections?: Record<string, { exported: number; rebuilt: number; ok: boolean }>;
  invariants?: { ok: boolean | null; exported_ok: boolean | null; acceptable: boolean };
  deferred_references?: { family: string; key: string; missing: [string, string][]; row: string }[];
  rebuild?: { events_written_by_rebuild: Record<string, number> };
  staged?: boolean;
  origin_chain?: { sha256: string; rows?: number; ingestion_event?: number };
  promotion?: { origin_chain: { sha256: string; rows: number; ingestion_event: number }; passed: boolean };
  signature?: { algorithm: string; key_id: string; principal: string };
}

export interface OriginChainCheck {
  ok: boolean;
  problems?: { family: string; key: string; problem: string }[];
  origin_chain_sha256?: string;
  ingestion_event?: number;
  reason?: string;
}

export interface ProvenanceView {
  origin_chain?: OriginChainCheck;
  git: ImportView["verification"]["git"] | null;
  origin: ArchiveManifest["argus"] | null;
  watermark: Watermark | null;
  reconciliation_sha256: string | null;
  events: { seq: number; kind: string; from: string | null; to: string | null; actor: string; at: string;
            detail: Record<string, unknown> | null }[];
}

/** A published Git export repeated at an interval (backend app/portability/schedules.py). */
export interface PortabilitySchedule {
  id: string;
  source_export_id: string;
  chain: "incremental" | "complete";
  every_minutes: number;
  skip_unchanged: boolean;
  enabled: boolean;
  mode: string;
  workspaces: string[];
  repository: string | null;
  next_run_at: string | null;
  running: boolean;
  last_run_at: string | null;
  last_outcome: "published" | "unchanged" | "waiting" | "failed" | null;
  last_message: string | null;
  last_export_id: string | null;
  last_published_export_id: string | null;
  failures: number;
  runs: number;
  created_by: string;
  updated_by: string | null;
  created_at: string | null;
}
