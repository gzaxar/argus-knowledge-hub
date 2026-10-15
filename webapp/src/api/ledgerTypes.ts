/** Types of the fact ledger API (`/v1/ledger`, `/v1/installations`, `/v1/access-points`). */

export interface TemporalValue {
  kind: "date" | "before_records" | "unscheduled" | "open" | "unknown_past" | "range";
  nominal?: string;
  precision?: "instant" | "day" | "month" | "year";
  bound?: string;
  /** kind "range": an inferred instant somewhere between these two observations. */
  earliest?: string;
  latest?: string;
}

export interface RecordBrief {
  uid: string;
  key: string;
  name: string;
  type: string;
  record_status: string;
}

export interface InstallationView {
  uid: string;
  key: string;
  status: "Proposed" | "Confirmed" | "Rejected" | "Withdrawn";
  valid_from: TemporalValue | null;
  valid_until: TemporalValue | null;
  removal_reason: string | null;
  temporal_state: "Planned" | "Future" | "Current" | "Ended";
  temporal_certainty: "definite" | "possible";
  position: RecordBrief | null;
  asset: RecordBrief | null;
}

export interface FactContributor {
  status: string;
  rank: string | null;
  effective: boolean;
  kind: "claim" | "decision";
  claim_id?: string;
  value?: unknown;
  polarity?: string;
  method?: string;
  rule_id?: string | null;
  stream?: string;
  source_kind?: string | null;
  revision?: string | null;
  observed_at?: string | null;
  evidence?: Record<string, unknown> | null;
  decision_id?: string;
  decision?: string;
  actor?: string;
  at?: string;
  reason?: string | null;
}

export interface RecordFacts {
  record: RecordBrief;
  source_refs: string[];
  facts: { predicate: string; member: string | null; contributors: FactContributor[] }[];
}

export interface ReviewQueue {
  conflicts: {
    conflict_id: string;
    type: string;
    severity: "blocking" | "non-blocking";
    predicate: string | null;
    member: string | null;
    detail: Record<string, unknown>;
    record: RecordBrief | null;
  }[];
  proposals: LedgerReviewProposal[];
  held_revisions: { revision_id: string; stream_id: string; revision: string; observed_at: string; reasons: string[] }[];
  provisional_records: RecordBrief[];
  installation_proposals: (Omit<InstallationView, "temporal_state" | "temporal_certainty"> & {
    position: RecordBrief | null;
    asset: RecordBrief | null;
  })[];
  counts: {
    conflicts: number;
    blocking: number;
    proposals: number;
    held_revisions: number;
    installation_proposals: number;
  };
}

export interface Decision {
  kind: "accept" | "reject" | "confirm" | "supersede" | "retract" | "revoke" | "resolve_conflict";
  subject_uid?: string;
  predicate?: string;
  member?: string | null;
  value?: unknown;
  supersedes?: string[];
  target?: Record<string, unknown>;
  reason?: string;
}

export interface AccessPointView {
  uid: string;
  key: string;
  address: string | null;
  record_status: string;
  position_uid: string | null;
  position: RecordBrief | null;
  in_service_from: TemporalValue | null;
  in_service_until: TemporalValue | null;
  successor: string | null;
  successor_record: RecordBrief | null;
}

export interface AddressUse {
  access_point_uid: string;
  position: RecordBrief | null;
  asset: RecordBrief | null;
  certainty: "definite" | "possible";
}

export interface PortCandidate {
  port_uid: string;
  label: string;
}

export interface SegmentPort {
  status: "attached" | "unresolved" | "confirmation_required" | "invalid" | "not_applicable";
  position_uid?: string | null;
  installation_uid?: string;
  unit_uid?: string;
  unit?: RecordBrief | null;
  port_uid?: string;
  port?: RecordBrief | null;
  required?: Record<string, unknown>;
  reason?: string;
  failed?: string;
  candidates?: PortCandidate[];
  ports?: (PortCandidate & { failed: string | null })[];
  evidence?: Record<string, unknown>;
}

export interface TicketLinkView {
  asset_uid: string;
  name: string | null;
  key: string | null;
  type: string | null;
  role: "subject" | "related" | "involved_equipment" | "involved_position";
  certainty: "definite" | "possible";
  origin: "ticket" | "derived" | "migration-split";
  detail: { incident?: [string, string]; source?: string } | null;
}

export interface RecordTickets {
  counts: { subject: number; involved: number };
  involved: {
    ticket_uid: string;
    key: string;
    title: string;
    state: string;
    role: string;
    certainty: "definite" | "possible";
    origin: string;
  }[];
}

export interface RuleEntry {
  rule_id: string;
  family: string;
  meaning: string;
  supersedes: string | null;
  carries_rejections: boolean;
  implementations: string[];
  signature: string;
  active: boolean;
  active_impl: string | null;
}

export interface ExitCriterion {
  id: string;
  text: string;
  ok: boolean;
  attested?: boolean;
  detail?: Record<string, unknown>;
}

export interface ReconciliationDifference {
  id: string;
  section: string;
  item: string;
  message: string;
  explained_by: string | null;
  sha256?: string;
  size?: number;
}

export interface ReconciliationBody {
  domain: string;
  manifest_hash: string;
  watermark: Record<string, unknown> | null;
  sections: Record<string, { source: number; argus: number }>;
  differences: ReconciliationDifference[];
  unexplained: number;
  passed: boolean;
  at: string;
}

export interface DomainView {
  id: string;
  workspace_id: string;
  name: string;
  resource: string;
  stage: "T0" | "T1" | "T2" | "T3" | "T4" | "T5";
  stage_name: string;
  stream_ids: string[];
  pilot: boolean;
  archive_url: string | null;
  steward: string | null;
  backup_steward: string | null;
  watermark: Record<string, unknown> | null;
  manifest_hash: string | null;
  frozen_at: string | null;
  exited_at: string | null;
  authoritative: boolean;
  latest_report: { id: string; passed: boolean; created_at: string; unexplained: number; body_hash: string } | null;
  streams: { id: string; kind: string; frozen_at: string | null }[];
}

export interface EntryCriterion {
  id: string;
  criterion: string;
  text: string;
  ok: boolean;
  met: boolean;
  waived: boolean;
  waiver: string | null;
  waivable: boolean;
  attested: boolean;
  detail: Record<string, unknown> | null;
}

export interface DomainDetail extends DomainView {
  exit_criteria: ExitCriterion[];
  entry_criteria: EntryCriterion[] | null;
  entry_attestations: Record<string, string>;
  report: ReconciliationBody | null;
  stages: Record<string, string>;
}

export interface LookupHit {
  status: "migrated";
  kind: "asset" | "ticket";
  uid: string;
  key: string;
  name: string;
  workspace_id: string;
  path: string;
  via: string;
}

export interface ValueHistory {
  current: unknown;
  history: { at: string; until: string | null; value: unknown; by: string | null; via: string; kind: string; reason?: string | null }[];
}

export interface EquipmentState {
  lifecycle: { state: string | null; recorded: string | null; allowed: string[]; installation: Record<string, unknown> | null };
  states: string[];
  custody: ValueHistory;
  location: ValueHistory;
  lifecycle_history: ValueHistory;
  designated_spare: boolean;
}

export interface SpareView {
  uid: string;
  key: string;
  name: string;
  type: string;
  product_model: string | null;
  location: string | null;
  custodian: string | null;
  lifecycle: string | null;
  available: boolean;
  why_not: string | null;
}

export interface AuditEntry {
  at: string;
  type: "record" | "decision" | "fact" | "identity" | "conflict";
  kind: string;
  actor?: string;
  predicate?: string | null;
  value?: unknown;
  before?: unknown;
  after?: unknown;
  cause?: string;
  reason?: string | null;
  decision_id?: string;
  source_ref?: string;
  conflict_type?: string;
}

export interface BulkChangeView {
  id: string;
  actor: string;
  description: string | null;
  spec: Record<string, unknown>;
  count: number;
  state: "previewed" | "awaiting_approval" | "applied" | "undone";
  approved_by: string | null;
  needs_approval: boolean;
  threshold: number;
  batch_id: string | null;
  created_at: string;
  applied_at: string | null;
  preview: { uid: string; key: string; name: string; type: string; changes: { predicate: string; before: unknown; after: unknown }[] }[];
}

export interface AuditDigestView {
  day: string;
  digest: string;
  prev_digest: string | null;
  counts: Record<string, number>;
  sealed_at: string;
}

export interface WorkflowState {
  key: string;
  name: string;
  category: "open" | "active" | "waiting" | "done";
  sla_hours?: number;
  escalate_to?: string;
}

export interface WorkflowTransition {
  to: string;
  name: string;
  to_name: string;
  category: string;
  requires: ("assignee" | "resolution" | "comment")[];
}

export interface TicketTransitions {
  workflow: { uid: string | null; name: string };
  state: string;
  state_name: string;
  transitions: WorkflowTransition[];
  states: WorkflowState[];
}

export interface WorkflowDef {
  uid: string | null;
  name: string;
  initial: string;
  is_default: boolean;
  states: WorkflowState[];
  transitions: { from: string; to: string; name?: string; requires?: string[] }[];
  source?: Record<string, unknown> | null;
  version?: number;
}

export interface Rehearsal {
  workflow: string;
  tickets: number;
  transitions_checked: number;
  unmapped_statuses: Record<string, number>;
  disallowed: { from: string; to: string; count: number; example: string | null }[];
  ok: boolean;
}

export interface NotificationView {
  id: number;
  kind: string;
  title: string;
  issue_uid: string | null;
  detail: Record<string, unknown>;
  actor: string | null;
  created_at: string;
  read: boolean;
  workspace_id?: string;
  workspace_name?: string;
}

export interface FollowState {
  subject: "asset" | "document";
  uid: string;
  following: boolean;
  followers: number;
}

export type RetentionClass = "permanent" | "10y" | "5y" | "2y" | "none";

export interface RetentionView {
  class: RetentionClass;
  released_at: string | null;
  retain_until: string | null;
  permanent: boolean;
  deletable: boolean;
  retired_at: string | null;
  superseded_by: string | null;
}

export interface AttachmentCheck {
  uid: string;
  recorded: string | null;
  actual: string | null;
  ok: boolean;
  missing: boolean;
}

export interface RoleTemplate {
  id: string;
  name: string;
  description: string;
  permissions: Record<string, string[]>;
}

export interface AccessSnapshot {
  workspace: string;
  people: { user: string; email: string | null; name: string | null; active: boolean; roles: string[];
            permissions: Record<string, string[]> }[];
  groups: { group: string; name: string; roles: string[] }[];
  tokens: { token: number; label: string | null; restricted_grants: string[]; created_at: string | null;
            last_used_at: string | null; revoked: boolean }[];
  open_defaults: string[];
  administrators: string[];
}

export interface AccessReviewView {
  id: string;
  workspace_id: string;
  created_by: string;
  created_at: string;
  snapshot_hash: string;
  changes: { added: string[]; removed: string[]; changed: string[] };
  signatures: { signer: string; at: string; comment: string | null }[];
  required_signers: number;
  completed_at: string | null;
  summary: { people: number; groups: number; tokens: number; open_defaults: number };
  snapshot?: AccessSnapshot;
}

export interface RetirementCondition {
  id: string;
  item: string;
  text: string;
  ok: boolean;
  attested?: boolean;
  detail?: unknown;
}

export interface RetirementStatus {
  retired: boolean;
  retired_at: string | null;
  signed_by: string | null;
  conditions: RetirementCondition[];
  attestations: Record<string, string>;
}

export type MigrationOutcome = "M-BLOCK" | "M-FUNC" | "M-POS" | "M-PHYS" | "M-MIXED" | "M-RETIRE" | "M-EDGE" | "M-EDGE-HOLD";

export interface MigrationAction {
  do: "keep" | "retire" | "retype" | "equipment" | "installation" | "move_labels" | "move_attachments" | "edge_to_attribute" | "hold_edge";
  set?: Record<string, unknown>;
  label?: string;
  note?: string;
  key?: string;
  match?: string | null;
  workspace?: string;
  status?: string;
  labels?: string[];
  attachments?: string[];
}

export interface MigrationRow {
  item: number;
  legacy_uid: string;
  legacy_key: string;
  legacy_type: string;
  outcome: MigrationOutcome;
  confidence: number;
  evidence: Record<string, unknown>;
  actions: MigrationAction[];
  warnings: string[];
  reviewer_required: boolean;
  override: { outcome: string; by: string; reason: string } | null;
  status: "planned" | "applied" | "failed" | "stale" | "rolled_back";
  reason: string | null;
  applied: Record<string, unknown> | null;
}

export interface MigrationPlanView {
  id: string;
  workspace_id: string;
  inventory_workspace_id: string;
  status: string;
  created_by: string;
  created_at: string;
  applied_at: string | null;
  finalized_at: string | null;
  invariants: {
    ok: boolean;
    checks: Record<string, boolean>;
    summary: Record<string, number>;
    not_automated: string[];
    deep_verification?: {
      at: string;
      ok: boolean;
      "I-MIG-4"?: { ok: boolean; failing: string[] };
      "I-MIG-5": { ok: boolean; before?: number; after?: number; grew?: Record<string, number[]>; reason?: string };
      "I-MIG-6": { ok: boolean; records: number; differences: { uid: string; fields: string[] }[] };
      "I-MIG-7"?: { ok: boolean | null; reason?: string; before?: number; after?: number; lost?: { incident: string; cause: string }[]; more_precise?: number };
    };
  } | null;
  outcomes: Record<string, number>;
  statuses: Record<string, number>;
  rows?: MigrationRow[];
}

export interface QueueAgeing {
  queue: string;
  label: string;
  targets: { due: number; backup: number; governance: number };
  size: number;
  overdue: number;
  at_backup: number;
  at_governance: number;
  oldest: number | null;
  buckets: { label: string; count: number }[];
}

export interface QueueDashboard {
  workspace_id: string;
  queues: QueueAgeing[];
  total: number;
  steward: string | null;
  backup_steward: string | null;
  domain: string | null;
  governance: string[];
}

export interface GoldenIncident {
  id: string;
  name: string;
  symptoms: string[];
  expected_causes: string[];
  symptom_kind: Record<string, string>;
  healthy: string[];
  ticket_uid: string | null;
  created_by: string;
  created_at: string;
}

export interface GoldenRun {
  incidents: number;
  found: number;
  expected: number;
  results: { incident: string; name: string; found: number; expected: number;
             causes: Record<string, { found: boolean; as: string | null; rank: number | null; more_precise: boolean }> }[];
}

export interface EquipmentClassView {
  name: string;
  status: "active" | "promoted" | "deprecated";
  promoted_type: string | null;
  added_by: string;
  added_at: string;
  note: string | null;
}

export interface ClassTrigger {
  kind: string;
  text: string;
}

export interface EquipmentClassReport {
  at: string;
  equipment: number;
  other_equipment: number;
  unclassified: { count: number; share: number; alert: boolean; rule: string };
  classes: {
    class: string;
    status: string;
    promoted_type: string | null;
    objects: number;
    workspaces: Record<string, number>;
    sources: Record<string, number>;
    in_tickets: number;
    causal: number;
    requested_attributes: string[];
    description_keys: { key: string; count: number }[];
    triggers: ClassTrigger[];
  }[];
}

export interface ClassReview {
  id: number;
  class: string;
  triggers: ClassTrigger[];
  status: "open" | "promoted" | "declined";
  opened_at: string;
  decided_by: string | null;
  decided_at: string | null;
  reason: string | null;
}

/** A fact waiting for confirmation; `ai` is set on an AI proposal (asset-model-revision §23.11). */
export type LedgerReviewProposal = {
  claim_id: string;
  predicate: string;
  member: string | null;
  value: unknown;
  method: string;
  rule_id: string | null;
  stream_id: string;
  record: RecordBrief | null;
  ai?: {
    confidence: number | null;
    quote: string | null;
    grounded: boolean | null;
    current: unknown;
    model: string | null;
    requested_by: string | null;
    profile_id: string | null;
  };
};

/** How a person gets their notifications by e-mail (GET /v1/notifications/preferences). */
export interface EmailPreferences {
  email: "instant" | "digest" | "off";
  /** Categories never sent by e-mail; the app still has them. */
  muted: string[];
  address: string | null;
  email_configured: boolean;
  digest_hour: number;
  categories: { key: string; label: string }[];
}

/** What a person hears about in one workspace beyond what they watch or follow. */
export interface WorkspaceSubscription {
  workspace_id: string;
  workspace_name: string;
  tickets: boolean;
  documents: boolean;
  assets: boolean;
}
