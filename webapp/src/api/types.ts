export interface SchemaAttribute {
  id?: string;
  name: string;
  key?: string;
  type: string;
  required?: boolean;
  unique?: boolean;
  indexed?: boolean;
  default?: unknown;
  description?: string;
  options?: { id: string; value: string }[];
  referenceType?: string;
  referenceSchemaUid?: string;
  includeChildren?: boolean;
  multiValue?: boolean;
  minCardinality?: number;
  maxCardinality?: number;
  regex?: string;
  readOnly?: boolean;
  visible?: boolean;
  order?: number;
  global?: boolean;
}

export const ATTRIBUTE_TYPES = [
  "string",
  "text",
  "integer",
  "float",
  "boolean",
  "date",
  "datetime",
  "enumeration",
  "reference",
  "attachment",
  "user",
  "current_user",
  "group",
] as const;

export interface AppSchema {
  uid: string;
  workspace_id: string;
  name: string;
  description: string | null;
  is_concrete: boolean;
  parent_schema_uid: string | null;
  attributes: SchemaAttribute[];
  metadata: Record<string, unknown>;
  version: number;
  icon_uid: string | null;
  is_global: boolean;
  applies_to: "objects" | "tickets" | "documents";
  created_at: string;
  updated_at: string;
}

export interface SchemaInput {
  uid?: string;
  name: string;
  description?: string | null;
  is_concrete: boolean;
  parent_schema_uid?: string | null;
  attributes: SchemaAttribute[];
  metadata?: Record<string, unknown>;
  is_global?: boolean;
  applies_to?: "objects" | "tickets" | "documents";
}

export interface Asset {
  uid: string;
  workspace_id: string;
  schema_uid: string;
  key: string;
  name: string;
  type: string;
  avatar_icon_uid: string | null;
  attributes: Record<string, unknown>;
  inbound_relations: string[];
  outbound_relations: string[];
  is_global: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface AssetInput {
  uid?: string;
  schema_uid: string;
  /** Blank: the workspace's key pattern makes one. */
  key?: string;
  name: string;
  /** Always the schema's name; the server sets it. */
  type?: string;
  avatar_icon_uid?: string | null;
  attributes: Record<string, unknown>;
  inbound_relations?: string[];
  outbound_relations?: string[];
  is_global?: boolean;
}

export interface Relation {
  id: number;
  workspace_id: string;
  from_asset_uid: string;
  to_asset_uid: string;
  relation_type: string;
  created_at: string;
  /** Set on edges the fact ledger maintains ("ledger" from claims, "derived"
   * from other records); those are never edited directly. */
  derivation?: string | null;
}

export interface Issue {
  uid: string;
  workspace_id: string;
  asset_uid: string | null;
  schema_uid: string | null;
  attributes: Record<string, unknown>;
  title: string;
  description: string | null;
  state: string;
  priority: string | null;
  assignee: string | null;
  labels: string[];
  due_date: string | null;
  closed_at: string | null;
  created_by: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface IssueInput {
  uid?: string;
  asset_uid?: string | null;
  schema_uid?: string | null;
  attributes?: Record<string, unknown>;
  title: string;
  description?: string | null;
  state?: string;
  priority?: string | null;
  assignee?: string | null;
  labels?: string[];
  due_date?: string | null;
  created_by?: string | null;
}

export interface IssueComment {
  uid: string;
  issue_uid: string;
  author: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface AssetComment {
  uid: string;
  asset_uid: string;
  author: string;
  text: string;
  created: string;
  updated: string;
  backend_id: string | null;
  backend_url: string | null;
}

export interface AssetHistory {
  uid: string;
  asset_uid: string;
  type: string;
  author: string;
  details: string;
  timestamp: string;
  backend_id: string | null;
}

export interface AssetTicket {
  /** The ticket in this application, when this row corresponds to one. */
  issue_uid?: string | null;
  uid: string;
  asset_uid: string;
  ticket_key: string;
  summary: string;
  type: string;
  status: string;
  created: string;
  updated: string;
  backend_id: string | null;
  backend_url: string | null;
}

export const LABEL_TYPES = ["qrcode", "barcode", "serial", "rfid"] as const;
export const LABEL_ISSUERS = ["user", "vendor", "system"] as const;

export interface AssetLabel {
  uid: string;
  asset_uid: string;
  type: string;
  value: string;
  namespace: string | null;
  issuer: string;
  verified: boolean;
  confidence: number | null;
  created_at: string;
  updated_at: string;
}

export interface AssetLabelInput {
  uid?: string;
  type: string;
  value: string;
  namespace?: string | null;
  issuer: string;
  verified?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AssetLabelSearchResult {
  uid: string;
  type: string;
  value: string;
  namespace: string | null;
  issuer: string;
  verified: boolean;
  asset_uid: string;
  asset_name: string;
  asset_key: string;
}

export interface Attachment {
  uid: string;
  workspace_id: string;
  asset_uid: string | null;
  document_revision_uid?: string | null;
  /** "dxf-of:<uid>" on a converted drawing; identifies what it came from. */
  backend_id?: string | null;
  /** Carries "preview-failed: …" when a drawing could not be converted. */
  backend_url?: string | null;
  filename: string;
  mime_type: string | null;
  file_size: number | null;
  author: string | null;
  created_at: string;
}

export interface GlobalValueOption {
  id: string;
  value: string;
  responsible?: string;
  meaning?: string;
}

export interface GlobalValue {
  uid: string;
  workspace_id: string;
  name: string;
  key: string;
  type: string;
  applies_to: "objects" | "tickets" | "documents";
  options: GlobalValueOption[] | null;
  default_value: string | null;
  constraints: Record<string, unknown> | null;
  required: boolean;
  unique: boolean;
  indexed: boolean;
  multi_value: boolean;
  min_cardinality: number | null;
  max_cardinality: number | null;
  reference_type: string | null;
  egu: string | null;
  allowed_egu_list: string[] | null;
  read_only: boolean;
  visible: boolean;
  enabled: boolean;
  is_system_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface GlobalValueInput {
  uid?: string;
  name: string;
  key: string;
  type: string;
  applies_to?: "objects" | "tickets" | "documents";
  options?: GlobalValueOption[] | null;
  default_value?: string | null;
  required?: boolean;
  unique?: boolean;
  indexed?: boolean;
  multi_value?: boolean;
  read_only?: boolean;
  visible?: boolean;
  enabled?: boolean;
}

/** The sources an import can run against. Kept in one place: the job type
 * used to list only two of them, so any code branching on a Confluence or
 * ticket job read as unreachable. */
export type ImportSource = "jira" | "jira-issues" | "confluence" | "git";

export interface ImportJob {
  uid: string;
  workspace_id: string;
  source: ImportSource | "spreadsheet";
  status: "pending" | "running" | "succeeded" | "failed";
  progress: string | null;
  counts: Record<string, number>;
  warnings: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** "remove_all_before" is retired: imports never delete what people attached to
 * a record. A stored configuration that still names it runs as "override". */
export type MergeStrategy = "override" | "no_override" | "update_if_newer";

export type TransferMode = "copy" | "move";

export interface TransferRequest {
  target_workspace_id: string;
  mode: TransferMode;
  type_uids?: string[];
  include_instances?: boolean;
  include_descendant_types?: boolean;
  asset_uids?: string[];
  document_uids?: string[];
  issue_uids?: string[];
  /** Copy only: merge into a same-named type/object at the target instead
   * of refusing. Move never merges, regardless of this flag. */
  force?: boolean;
}

export interface TransferJob {
  uid: string;
  workspace_id: string;
  target_workspace_id: string;
  mode: TransferMode;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: string | null;
  counts: Record<string, number>;
  warnings: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export const MERGE_STRATEGIES: { value: MergeStrategy; label: string; description: string }[] = [
  {
    value: "override",
    label: "Override",
    description: "Always overwrite matched objects with the source's current values.",
  },
  {
    value: "no_override",
    label: "Don't override",
    description: "Only create new objects; leave already-imported ones untouched.",
  },
  {
    value: "update_if_newer",
    label: "Update if source is more recent",
    description: "Overwrite a matched object only if the source's version is newer.",
  },
];

export interface JiraImportInput {
  source: "jira";
  base_url: string;
  pat: string;
  jira_schema_id: string;
  merge_strategy?: MergeStrategy;
}

export interface GitImportInput {
  source: "git";
  provider: "github" | "gitlab";
  repo_url: string;
  pat: string;
  branch: string;
  merge_strategy?: MergeStrategy;
}

export interface JiraIssueImportInput {
  source: "jira-issues";
  base_url: string;
  pat: string;
  jql: string;
  schema_uid?: string | null;
  link_assets?: boolean;
  merge_strategy?: MergeStrategy;
}

export type ImportInput = JiraImportInput | JiraIssueImportInput | GitImportInput;

export interface ImportConfig {
  uid: string;
  workspace_id: string;
  name: string;
  source: ImportSource;
  merge_strategy: MergeStrategy;
  params: Record<string, string | boolean | null>;
  last_run_at: string | null;
  last_import_job_uid: string | null;
  created_at: string;
  updated_at: string;
}

export interface JiraIssueImportConfigParams {
  source: "jira-issues";
  base_url: string;
  jql: string;
  schema_uid?: string | null;
  link_assets?: boolean;
  pat?: string;
}

export interface JiraImportConfigParams {
  source: "jira";
  base_url: string;
  jira_schema_id: string;
  pat?: string;
}

export interface GitImportConfigParams {
  source: "git";
  provider: "github" | "gitlab";
  repo_url: string;
  branch: string;
  /** Omitted for a public repository: no token is sent at all, rather than
   * an empty one, which these APIs reject. */
  pat?: string;
}

export interface ConfluenceImportConfigParams {
  source: "confluence";
  base_url: string;
  space_key?: string | null;
  cql?: string | null;
  link_assets?: boolean;
  pat?: string;
}

/** EPIK8s control configuration: one beamline's values.yaml. Read only —
 * the file in git deploys the accelerator. */
export interface Epik8sImportConfigParams {
  source: "epik8s";
  provider: "github" | "gitlab";
  repo_url: string;
  branch: string;
  path: string;
  /** Make an Access Point for an address no object in the inventory carries,
   * marked as needing confirmation; otherwise only report it. */
  create_missing_nodes?: boolean;
  infer_elements?: boolean;
  infer_controllers?: boolean;
  it_workspace?: string | null;
  link_inventory?: boolean;
  ai_unrecognised?: boolean;
  pat?: string;
}

export type ImportConfigParams =
  | JiraImportConfigParams
  | ConfluenceImportConfigParams
  | JiraIssueImportConfigParams
  | GitImportConfigParams
  | Epik8sImportConfigParams;

export interface ImportConfigInput {
  name: string;
  merge_strategy: MergeStrategy;
  config: ImportConfigParams;
}

export interface ImportConfigUpdateInput {
  name?: string;
  merge_strategy?: MergeStrategy;
  config?: ImportConfigParams;
}

export interface Me {
  auth_type: "pat" | "oidc";
  workspace_id: string | null;
  user_id: string | null;
  email: string | null;
  name: string | null;
  is_admin: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  is_global: boolean;
  created_at: string;
}

export interface WorkspaceUpdateInput {
  name?: string;
  is_global?: boolean;
}

export interface MyWorkspace {
  id: string;
  name: string;
  is_global: boolean;
  created_at: string;
  can_read: boolean;
  can_create: boolean;
  can_modify: boolean;
  can_delete: boolean;
  can_read_tickets: boolean;
  can_create_tickets: boolean;
  can_modify_tickets: boolean;
  can_delete_tickets: boolean;
  can_read_documents: boolean;
  can_create_documents: boolean;
  can_modify_documents: boolean;
  can_delete_documents: boolean;
  can_approve_documents: boolean;
}

export interface MissingReferenceIssue {
  asset_uid: string;
  asset_name: string;
  asset_key: string;
  attribute_key: string;
  attribute_name: string;
  attribute_type: string;
  value: string;
}

export interface DanglingObjectIssue {
  relation_id: number;
  from_asset_uid: string;
  to_asset_uid: string;
  relation_type: string;
  reason: string;
}

export interface OrphanedObjectIssue {
  asset_uid: string;
  name: string;
  key: string;
}

export interface IntegrityReport {
  missing_references: MissingReferenceIssue[];
  dangling_objects: DanglingObjectIssue[];
  orphaned_objects: OrphanedObjectIssue[];
  counts: {
    assets_scanned: number;
    missing_references: number;
    dangling_objects: number;
    orphaned_objects: number;
  };
}

export interface RelinkResult {
  assets_scanned: number;
  assets_updated: number;
  values_relinked: number;
}

export interface CleanupOptions {
  clear_missing_references?: boolean;
  delete_orphaned_objects?: boolean;
  remove_dangling_relations?: boolean;
}

export interface CleanupResult {
  cleared_references: number;
  deleted_orphaned_objects: number;
  removed_dangling_relations: number;
}

export interface MemberDirectoryEntry {
  user_id: string;
  email: string;
  name: string | null;
}

export interface Member {
  user_id: string;
  email: string;
  name: string | null;
  can_read: boolean;
  can_create: boolean;
  can_modify: boolean;
  can_delete: boolean;
  can_read_tickets: boolean;
  can_create_tickets: boolean;
  can_modify_tickets: boolean;
  can_delete_tickets: boolean;
  can_read_documents: boolean;
  can_create_documents: boolean;
  can_modify_documents: boolean;
  can_delete_documents: boolean;
  can_approve_documents: boolean;
}

export interface MemberInput {
  email: string;
  can_read: boolean;
  can_create: boolean;
  can_modify: boolean;
  can_delete: boolean;
  can_read_tickets: boolean;
  can_create_tickets: boolean;
  can_modify_tickets: boolean;
  can_delete_tickets: boolean;
  can_read_documents: boolean;
  can_create_documents: boolean;
  can_modify_documents: boolean;
  can_delete_documents: boolean;
  can_approve_documents: boolean;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface DefaultAccess {
  default_can_read: boolean;
  default_can_create: boolean;
  default_can_modify: boolean;
  default_can_delete: boolean;
  default_can_read_tickets: boolean;
  default_can_create_tickets: boolean;
  default_can_modify_tickets: boolean;
  default_can_delete_tickets: boolean;
  default_can_read_documents: boolean;
  default_can_create_documents: boolean;
  default_can_modify_documents: boolean;
  default_can_delete_documents: boolean;
  default_can_approve_documents: boolean;
}

export interface WorkspaceDetail extends DefaultAccess {
  id: string;
  name: string;
  created_at: string;
}

export type DocumentState = "draft" | "in_review" | "approved" | "published" | "superseded" | "retired";
export type AuthorityLevel = "ufficiale" | "informativo" | "bozza_interna";
export type Confidentiality = "pubblico" | "interno" | "riservato";

export interface DocumentStep {
  ordine?: number;
  testo: string;
  checklist?: boolean;
  voce_critica?: boolean;
}

export interface AppDocument {
  uid: string;
  workspace_id: string;
  code: string;
  title: string;
  document_type_uid: string | null;
  owner_user_id: string | null;
  responsible_service_asset_uid: string | null;
  authority_level: AuthorityLevel;
  confidentiality: Confidentiality;
  source: string;
  /** Readable from every workspace. Never true for a riservato document. */
  is_global: boolean;
  current_revision_uid: string | null;
  retention_class?: "permanent" | "10y" | "5y" | "2y" | "none";
  retired_at?: string | null;
  superseded_by_uid?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentInput {
  uid?: string;
  /** Null lets the system assign one from the document's type. */
  code: string | null;
  title: string;
  document_type_uid?: string | null;
  owner_user_id?: string | null;
  responsible_service_asset_uid?: string | null;
  authority_level?: AuthorityLevel;
  confidentiality?: Confidentiality;
  source?: string;
  body_markdown?: string | null;
  steps?: DocumentStep[];
  attributes?: Record<string, unknown>;
  valid_from?: string | null;
  valid_until?: string | null;
  next_review_due?: string | null;
}

export interface DocumentUpdateInput {
  title?: string;
  document_type_uid?: string | null;
  owner_user_id?: string | null;
  responsible_service_asset_uid?: string | null;
  authority_level?: AuthorityLevel;
  confidentiality?: Confidentiality;
  is_global?: boolean;
}

export interface DocumentRevision {
  uid: string;
  document_uid: string;
  revision_number: number;
  state: DocumentState;
  body_markdown: string | null;
  steps: DocumentStep[];
  attributes: Record<string, unknown>;
  valid_from: string | null;
  valid_until: string | null;
  next_review_due: string | null;
  authored_by: string | null;
  approved_by: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  published_at: string | null;
  review_comment: string | null;
  superseded_by_uid: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentRevisionInput {
  body_markdown?: string | null;
  steps?: DocumentStep[];
  attributes?: Record<string, unknown>;
  valid_from?: string | null;
  valid_until?: string | null;
  next_review_due?: string | null;
}

export interface DocumentRelation {
  id: number;
  from_document_uid: string;
  to_type: "asset" | "schema" | "document" | "issue";
  to_uid: string;
  relation_type: string;
  created_at: string;
}

export interface IssueHistoryEntry {
  uid: string;
  issue_uid: string;
  type: string;
  author: string;
  field: string | null;
  from_value: string | null;
  to_value: string | null;
  details: string | null;
  timestamp: string;
}

export interface IssueAssetLink {
  asset_uid: string;
  name: string;
  key: string;
  type: string | null;
  relation: string;
}

export interface IssueDocumentLink {
  document_uid: string;
  code: string;
  title: string;
  relation: string;
  relation_id: number;
}

export interface IssueTicketLink {
  link_id: number;
  issue_uid: string;
  title: string;
  state: string;
  source_key: string | null;
  relation: string;
  outgoing: boolean;
}

export interface IssueLinks {
  assets: IssueAssetLink[];
  documents: IssueDocumentLink[];
  tickets: IssueTicketLink[];
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: Record<string, string[]>;
  is_system: boolean;
  rank: number;
}

export interface RoleBinding {
  id: number;
  workspace_id: string;
  subject_type: "user" | "group";
  subject_id: string;
  subject_label: string;
  subject_active: boolean;
  role_id: string;
  role_name: string;
  created_at: string | null;
}

export interface RoleBindingInput {
  subject_type: "user" | "group";
  subject_id: string;
  role_id: string;
}

export interface DirectoryGroup {
  uid: string;
  dn: string | null;
  name: string;
  description: string | null;
  email: string | null;
  source: string;
  active: boolean;
  member_count: number;
}

export interface DirectoryGroupMember {
  user_id: string;
  email: string;
  name: string | null;
  username: string | null;
  active: boolean;
  source: string;
}

export interface DirectoryStatus {
  provider: string;
  is_test_data: boolean;
  groups: number;
  active_groups: number;
  users: number;
  last_synced_at: string | null;
}

export interface EffectivePermissions {
  workspace_id: string;
  is_admin: boolean;
  objects: string[];
  tickets: string[];
  documents: string[];
  workspace: string[];
}

export interface LLMConfig {
  workspace_id: string;
  base_url: string;
  model: string;
  embedding_model: string | null;
  vision_model: string | null;
  asr_model: string | null;
  tts_model: string | null;
  rerank_model?: string | null;
  /** The key itself is never sent back — only whether one is stored. */
  has_api_key: boolean;
  enabled: boolean;
  allow_confidential: boolean;
  /** The most a single reply may use; null: no limit. */
  max_output_tokens: number | null;
  /** Index a document for Ask ARGUS as soon as it is published or retired. */
  index_on_publish?: boolean;
  /** Hours between refreshes of the whole index; 0: no timer. */
  index_interval_hours?: number;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_error: string | null;
}

export interface LLMConfigInput {
  base_url: string;
  model: string;
  embedding_model?: string | null;
  vision_model?: string | null;
  asr_model?: string | null;
  tts_model?: string | null;
  rerank_model?: string | null;
  /** Omitted keeps the stored key; "" clears it. */
  api_key?: string;
  enabled: boolean;
  allow_confidential: boolean;
  /** Null or omitted: no limit. */
  max_output_tokens?: number | null;
  /** Omitted keeps the stored setting. */
  index_on_publish?: boolean;
  index_interval_hours?: number;
}

export interface LLMCheckResult {
  ok: boolean;
  error: string | null;
  models: string[];
}

export interface AIStatus {
  configured: boolean;
  enabled: boolean;
  validated: boolean;
  model: string | null;
  has_embeddings: boolean;
  has_rerank?: boolean;
  has_vision: boolean;
  has_asr: boolean;
  has_tts: boolean;
  /** Set when these settings belong to another workspace — the shared
   * default — rather than to this one. */
  inherited_from: string | null;
  reason: string | null;
}

export interface MentionedObject {
  uid: string;
  key: string | null;
  name: string | null;
  /** "key" is something somebody wrote down; "name" could be a coincidence. */
  matched_on: string;
}

export interface DraftDocumentResult {
  body_markdown: string;
  mentioned_objects: MentionedObject[];
}

export interface ReviewFinding {
  severity: "high" | "medium" | "low";
  message: string;
}

export interface ReviewDocumentResult {
  findings: ReviewFinding[];
  mentioned_objects: MentionedObject[];
}

export interface DraftTicketResult {
  category: string | null;
  impact: string | null;
  detected_by: string | null;
  system: string | null;
  subsystem: string | null;
  root_cause: string | null;
  corrective_action: string | null;
  mentioned_objects: MentionedObject[];
}

export interface PhotoIdentification {
  type_uid: string | null;
  type_name: string | null;
  name: string | null;
  manufacturer: string | null;
  model: string | null;
  serial: string | null;
  description: string | null;
  visible_text: string[];
  confidence: "high" | "medium" | "low";
  matches: { uid: string; key: string; name: string }[];
  unmatched_keys: string[];
  error: string | null;
}

export interface AISuggestion {
  id: number;
  target_type: string;
  target_uid: string;
  field: string;
  suggested_value: string;
  suggested_label: string | null;
  previous_value: string | null;
  previous_label: string | null;
  target_label: string | null;
  model: string;
  status: string;
  created_at: string;
}

export interface SuggestRunResult {
  considered: number;
  proposed: number;
  unchanged: number;
  failed_batches: number;
}

export interface MarkdownImportResult {
  documents: number;
  attachments: number;
  relations: number;
  skipped: string[];
}

export interface RetypeResult {
  moved: number;
  not_found: string[];
}

export interface BulkDeleteResult {
  deleted: number;
  not_found: string[];
}

export interface Icon {
  uid: string;
  workspace_id: string;
  name: string;
  filename: string;
  mime_type: string | null;
  file_size: number | null;
  is_global: boolean;
  created_at: string;
  updated_at: string;
}

export interface IconUpdate {
  name?: string;
  is_global?: boolean;
}

/** A node in the knowledge graph. `kind` is what the thing *is*, which is
 * also what decides where clicking it goes. */
export interface GraphNode {
  kind: "asset" | "ticket" | "document" | "group" | "person";
  uid: string;
  label: string;
  sublabel: string | null;
  type_name: string | null;
  state: string | null;
  /** Hops from the node the walk started at. */
  depth: number;
  /** A restricted record the viewer may not see: drawn, never named. */
  restricted?: boolean;
}

export interface GraphEdge {
  from_kind: string;
  from_uid: string;
  to_kind: string;
  to_uid: string;
  relation: string;
  /** structure | work | documentation | people */
  via: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** The node cap stopped the walk: what you see is a subset. */
  truncated: boolean;
}

export interface GraphSummary {
  nodes: Record<string, number>;
  edges: Record<string, number>;
}

/** Import sources read almost alike; spell them out so a ticket import
 * isn't mistaken for an object import when reading a list of runs. */
export function importSourceLabel(source: string): string {
  if (source === "jira") return "Jira objects";
  if (source === "jira-issues") return "Jira tickets";
  if (source === "confluence") return "Confluence";
  if (source === "git") return "Git";
  if (source === "spreadsheet") return "Spreadsheet";
  return source;
}

export interface AskStep {
  tool: string;
  arguments: Record<string, unknown>;
  /** The tool's raw JSON result. Shown, not summarised: the point of the
   * Ask page is seeing which records an answer came from. */
  result: string;
  error: string | null;
  seconds: number;
}

export interface AskResult {
  answer: string;
  steps: AskStep[];
  /** "answered" or "exhausted" — an answer given after the lookup limit
   * was cut short and should be read as such. */
  stopped: string;
  error: string | null;
  seconds: number;
}

/** How a workspace's identifier is derived from its name, installation-wide. */
export interface WorkspaceIdRule {
  prefix: string;
  separator: string;
  case: "lower" | "upper" | "keep";
  max_length: number;
}

export interface WorkspaceIdSuggestion {
  id: string;
  /** What the rule produced before a number was added to make it free. */
  base: string;
  taken: boolean;
}

export interface AssetKeyRule {
  pattern: string;
  is_default?: boolean;
  example?: string;
}

export interface MappingSourceType {
  uid: string;
  name: string;
  total: number;
  mapped: number;
  open: number;
  suggested: boolean;
}

export interface MappingField {
  value: string;
  source: "rule" | "ai" | "person";
  confidence: number;
  evidence: string | null;
}

export interface MappingVendor {
  name: string;
  existing_uid: string | null;
  company_key: string | null;
  source: "rule" | "ai" | "person";
  confidence: number;
}

export type MappingAction = "create_model" | "merge" | "create_vendor";
export type MappingStatus = "proposed" | "accepted" | "skipped" | "applied";

export interface MappingItem {
  id: string;
  source_uid: string;
  source_key: string;
  source_name: string;
  source_type: string;
  source: Record<string, unknown> & {
    producer?: string | null;
    reseller?: string | null;
    description?: string;
    /** What applying the row brings along from the imported record. */
    carry?: { avatar: boolean; attachments: number; history: number; comments: number; tickets: number };
  };
  /** What applying it actually copied or linked. */
  carried?: Record<string, number | boolean>;
  proposal: {
    action: MappingAction;
    fields: Partial<Record<"name" | "model_code" | "device_class" | "datasheet_url" | "description", MappingField>>;
    vendor: MappingVendor | null;
    merge_into: { uid: string; key: string; name: string } | null;
    duplicate_of: string | null;
    warnings: string[];
    ai: { kind: string | null } | null;
  };
  confidence: number | null;
  status: MappingStatus;
  result_uid: string | null;
}

export interface CatalogueMapping {
  id: string;
  source_workspace_id: string;
  target_workspace_id: string;
  actor: string;
  state: "analysing" | "ready" | "failed";
  use_ai: boolean;
  total: number;
  analysed: number;
  ai: { used?: boolean; model?: string; workspace?: string; reason?: string; error?: string; runs?: string[] };
  error: string | null;
  created_at: string;
  counts: Partial<Record<MappingStatus, number>>;
  /** Applied rows that have not yet brought their attachments, history and tickets along. */
  pending_carry?: number;
  kind?: "catalogue" | "records";
  /** Catalogue mappings: created records not yet shared with every workspace. */
  unshared?: number;
  /** Record mappings: the plan per source type uid. */
  plan?: Record<string, PlanEntry> | null;
  /** Record mappings: records open rows name but cannot point at, because they are not shared with the target. */
  hidden_references?: HiddenReference[];
  items?: MappingItem[];
}

export type PlanSource = "rule" | "ai" | "person";

export interface PlanCompanion {
  label: string;
  type: { uid: string; name: string };
  verb: string;
  /** true: the linked record points at the main one (a port is `port of` the camera). */
  from_companion: boolean;
  fixed: Record<string, string>;
  suffix: string;
  share: boolean;
  source: PlanSource;
}

export interface PlanField {
  kind: "copy" | "enum" | "reference" | "description" | "drop" | "link" | "companion" | "group";
  /** kind companion: which linked record the value goes to. */
  companion?: string;
  /** kind group: make a local group for a name no group has. */
  create_missing?: boolean;
  target?: string | null;
  values?: Record<string, string>;
  ref_type?: string | null;
  text_to?: string;
  /** When no record matches, create one of this type (a missing Location as an Area). */
  create_type?: { uid: string; name: string } | null;
  verb?: string | null;
  reverse?: boolean;
  source: PlanSource;
  confidence: number;
}

export interface PlanEntry {
  source_type: string;
  count: number;
  target_type: { uid: string; name: string; source: PlanSource; confidence: number; reason?: string; alias?: string } | null;
  /** Create its records shared with every workspace; defaults to whether the target type is shared. */
  share?: boolean | null;
  /** Values every row of this type gets (Kind = Pipe for "Pipes" → Vacuum Component). */
  fixed?: Record<string, string>;
  fields: Record<string, PlanField>;
  /** Linked records each row brings: an Ethernet port, a network address… */
  companions?: Record<string, PlanCompanion>;
  relations: Record<string, { verb: string | null; reverse: boolean; source: PlanSource; confidence: number }>;
  profile: {
    fields: Record<string, { count: number; distinct?: number; samples?: string[]; link_to?: Record<string, number> }>;
    relations: Record<string, { count: number; to: Record<string, number> }>;
    examples: string[];
  };
}

export interface HiddenReference {
  uid: string;
  name: string;
  key: string;
  workspace_id: string;
  type: string | null;
  rows: number;
}

export interface MappingVocabulary {
  types: { uid: string; name: string; path: string; shared: boolean }[];
  attributes: Record<
    string,
    {
      key: string;
      name: string;
      type: string;
      options: { id: string; value: string }[];
      ref_type: string | null;
      create_types: { uid: string; name: string }[];
    }[]
  >;
  verbs: Record<string, string>;
}

export interface RecordProposal {
  action: "create" | "merge";
  merge_into: { uid: string; key: string; name: string } | null;
  type: { uid: string; name: string } | null;
  fields: { name: { value: string } };
  attributes: Record<
    string,
    {
      value: unknown;
      label?: string | null;
      from: string | null;
      source: string;
      /** A referenced record that does not exist yet and is created on apply. */
      create?: { type_uid: string; type: string; name: string };
      /** An owning group that does not exist yet and is made on apply. */
      create_group?: { name: string };
      /** Found, but not shared with the target: the row can only keep its text. */
      hidden?: { uid: string; name: string; key: string; workspace_id: string; type: string | null };
    }
  >;
  links: { to_source: string; verb: string | null; reverse: boolean; via: string }[];
  companions?: {
    id: string;
    label: string;
    type: { uid: string; name: string };
    name: string;
    attributes: Record<string, { value: unknown; from: string | null; source: string }>;
    verb: string;
    from_companion: boolean;
    share: boolean;
  }[];
  warnings: string[];
  confidence: number;
  share?: boolean;
  person?: boolean;
}

export interface AskConversation {
  id: string;
  title: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface AskMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  steps: AskStep[] | null;
  stopped: string | null;
  error: string | null;
  seconds: number | null;
  created_at: string | null;
}

export interface AskConversationDetail extends AskConversation {
  messages: AskMessage[];
}

/** One server-sent event of a chat turn (POST /v1/ai/chat). */
/** The user guide. */
export interface HelpTopicSummary {
  slug: string;
  title: string;
  summary: string;
  keywords: string[];
  sections: { heading: string; anchor: string }[];
}
export interface HelpTopic {
  slug: string;
  title: string;
  summary: string;
  keywords: string[];
  body: string;
}
export interface HelpHit {
  topic: string;
  title: string;
  section: string;
  anchor: string;
  text: string;
}

/** A change the assistant proposed: nothing is changed until the person applies it. */
export interface AskAction {
  id: string;
  number: number;
  /** The question it answered (its message seq); the answer that proposed it is the next message. */
  turn_seq: number;
  kind: "create" | "update" | "relate" | "unrelate";
  summary: string;
  status: "proposed" | "applied" | "failed" | "discarded";
  result: { uid?: string; key?: string; name?: string; relation_id?: number } | null;
  error: string | null;
  reason: string | null;
}

export type ChatEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "thinking"; text: string }
  | { type: "text"; text: string }
  | { type: "text_reset" }
  | { type: "step_start"; index: number; tool: string; arguments: Record<string, unknown> }
  | ({ type: "step"; index: number; summary: string } & AskStep)
  | { type: "proposal"; action: AskAction }
  | { type: "done"; answer: string; steps: AskStep[]; stopped: string; error: string | null; seconds: number | null };

export interface KnowledgeStatus {
  ready: boolean;
  pgvector: boolean;
  embedding_model: string | null;
  /** Indexed sources and passages, by kind (document, ticket, ticket_comment, attachment, asset_comment). */
  sources: Record<string, number>;
  passages: Record<string, number>;
  run: {
    state: "running" | "done" | "failed";
    started_at: string | null;
    finished_at: string | null;
    result: {
      indexed?: number; unchanged?: number; removed?: number; unreadable?: number; chunks?: number;
      seconds?: number; failed?: string[];
    } | null;
  } | null;
  /** When the index is brought up to date without anyone asking (the AI settings above). */
  schedule?: { on_publish: boolean; interval_hours: number; active: boolean; next_at: string | null };
}

/** One hop of a failure's path: the provider stops, so the dependent loses what the relation carries. */
export interface FailureStep {
  provider: string;   // key
  dependent: string;  // key
  relation: string;
  layer: string;
  carries: string;
}

export interface FailureNode {
  uid: string;
  key: string;
  name: string;
  type: string;
  inferred?: boolean;
}

export interface ImpactAffected extends FailureNode {
  depth: number;
  losses: Record<string, number>;
  path: FailureStep[];
  layers: string[];
  weak: boolean;
}

export interface ImpactResult {
  origin: FailureNode;
  affected: ImpactAffected[];
  count: number;
  by_type: Record<string, number>;
  by_loss: Record<string, number>;
  truncated: boolean;
}

export interface RootCauseCandidate extends FailureNode {
  fit: number;
  coverage: number;
  explains: (FailureNode & { loss: string; depth: number; path: FailureStep[] })[];
  would_also_affect: number;
  contradicted_by: FailureNode[];
  history: { tickets: number; recent: { uid?: string; title?: string }[] };
}

export interface RootCauseResult {
  symptoms: FailureNode[];
  candidates: RootCauseCandidate[];
  hypotheses: { causes: (FailureNode & { explains: string[] })[]; unexplained: string[] }[];
  not_found: string[];
}

/* The beam model (docs/beam-model.md). */
export interface BeamRecord {
  uid: string;
  key: string;
  name: string;
  type: string;
  model_name?: string;
  element_kind?: string;
  capabilities?: string[];
  topology?: string;
  system_kind?: string;
  dataset_kind?: string;
  model_id?: string;
  serial?: string;
  manufacturer?: string;
  model?: string;
  address?: string;
  role?: string;
  quantity?: string;
  signal_system?: string;
  attributes?: Record<string, unknown>;
}

export interface BeamSystem extends BeamRecord {
  beams: BeamRecord[];
  paths: BeamRecord[];
}

export interface BeamNode extends BeamRecord {
  index: number;
  s?: number | null;
  length?: number | null;
  angle?: number | null;
  optics?: { beta_x?: number; beta_y?: number; dx?: number } | null;
  geometry?: { x?: number; y?: number; z?: number; yaw?: number; pitch?: number; roll?: number } | null;
}

export interface BeamPathGraph {
  path: BeamRecord;
  topology: "open" | "closed" | null;
  length: number | null;
  reference: string | null;
  dataset_uid: string | null;
  nodes: BeamNode[];
  edges: { from: string; to: string; relation: string }[];
  branches_out: { from: string; to: string; to_path: BeamRecord | null }[];
  branches_in: { from: string; to: string; from_path: BeamRecord | null }[];
}

export interface BeamConversionReport {
  converter: string;
  file: string;
  elements: number;
  total_bend: number;
  ring: boolean;
  survey_closure_m: number | null;
  not_executed?: string[];
  tunes?: Record<string, string>;
}

export interface BeamValues {
  dataset_uid: string;
  path_uid: string | null;
  s: number | null;
  geometry: Record<string, number> | null;
  physics: Record<string, unknown>;
  optics: Record<string, unknown>;
  native: { source?: string; type?: string; parameters?: Record<string, unknown> };
}

export interface BeamSignal extends BeamRecord {
  measures: string[];
  device: BeamRecord | null;
}

export interface BeamElementContext {
  element: BeamRecord;
  path: BeamRecord | null;
  physics: (BeamRecord & BeamValues) | null;
  datasets: (BeamRecord & BeamValues)[];
  equipment: {
    installed: { asset: BeamRecord | null; certainty: string; valid_from: unknown; valid_until: unknown }[];
    history: { asset: BeamRecord | null; status: string; valid_from: unknown; valid_until: unknown }[];
  };
  power: BeamRecord[];
  controls: {
    control_devices: BeamRecord[];
    iocs: BeamRecord[];
    signals: BeamSignal[];
    connected_electronics: BeamRecord[];
  };
  observables: (BeamRecord & { measured_by: BeamSignal[] })[];
  documentation: { uid: string; code: string | null; title: string; via: string; for: string }[];
  tickets: { uid: string; title: string; state: string; for: string }[];
  upstream: (BeamRecord & { via: string; distance: number })[];
  downstream: (BeamRecord & { via: string; distance: number })[];
  asset_bindings?: AssetBinding[];
}

// ------------------------------------------------------------------- beamline asset synchronization

export type BindingStatus = "unmatched" | "proposed" | "confirmed" | "ambiguous" | "rejected";
export type BindingAuthority = "authoritative" | "human_confirmed" | "auto_accepted" | "suggestion";

export interface AssetRefView { id: string; name?: string; type?: string }

export interface SyncCandidate {
  asset: AssetRefView;
  confidence: number;
  evidence: { kind: string; weight: number | null; detail?: string }[];
}

export interface SyncProposal {
  component: string;
  component_uid?: string;
  name: string;
  type: string;
  family: string;
  relation: string;
  paths: string[];
  s: number | null;
  status: BindingStatus;
  expects_asset: boolean;
  asset: AssetRefView | null;
  confidence: number | null;
  evidence: string[];
  delta_s: number | null;
  candidates: SyncCandidate[];
  auto_acceptable: boolean;
  authority: BindingAuthority | null;
  diff: string;
  notes: string[];
}

export interface AssetSyncSummary {
  model_components: number;
  virtual_components: number;
  physical_candidates: number;
  confirmed: number;
  proposed: number;
  auto_acceptable: number;
  ambiguous: number;
  unmatched: number;
  rejected: number;
  diff: Record<string, number>;
}

export interface AssetSyncStatus {
  model: string;
  summary: AssetSyncSummary;
  groups: Record<string, number>;
  proposals: SyncProposal[];
  unmodelled_assets: AssetRefView[];
  stale_bindings: { component: string; asset: string; relation: string; note: string }[];
  matcher: string;
  matcher_version: string;
  generated_at: string;
}

export interface AssetSyncDecision { component: string; asset: string; relation?: string; reason?: string }

export interface AssetSyncApply {
  accept?: AssetSyncDecision[];
  reject?: AssetSyncDecision[];
  accept_high_confidence?: boolean;
  keep_proposals?: boolean;
}

export interface AssetSyncApplied {
  confirmed: { component: string; asset: string; relation: string; authority: string }[];
  rejected: { component: string; asset: string }[];
  kept: number;
  problems: string[];
  summary: AssetSyncSummary;
}

export interface AssetBinding {
  component: string;
  relation: string;
  target: { namespace: string; id: string; name?: string };
  status: string;
  authority?: BindingAuthority;
  confidence?: number;
  evidence?: string[];
  source?: { method: string; matcher?: string; matcher_version?: string };
  confirmed_by?: { type: string; id: string };
  timestamp?: string;
  asset?: BeamRecord | { uid: string; name: string | null; type: string | null } | null;
  note?: string | null;
}

export interface BeamModelSummary {
  model_id: string;
  name: string | null;
  source: string | null;
  version: string | null;
  systems: BeamRecord[];
  paths: number;
  elements: number;
  datasets: number;
}

export interface BeamModelCheck {
  index: number;
  model: string | null;
  ok: boolean;
  problems: string[];
  format?: "1" | "2";
  levels?: string[];
  warnings?: string[];
  gaps?: Record<string, string[]>;
  summary: { systems: number; paths: number; elements: number; datasets: number; observables: number;
             components?: number; definitions?: number; placements?: number; connections?: number;
             boundaries?: number; shared_components?: string[] } | null;
}

export interface BeamImportReport {
  model: string;
  state: string;
  systems: number;
  paths: number;
  elements: number;
  datasets: number;
  values: number;
  awaiting_policy: boolean;
  format?: "1" | "2";
  levels?: string[];
  warnings?: string[];
}

/** The canonical representation (argus.beam-model/1, docs/beam-model.md §8). */
export interface CanonicalValues {
  s?: number | null;
  geometry?: Record<string, number> | null;
  physics?: Record<string, unknown>;
  optics?: Record<string, unknown>;
  native?: { source?: string; type?: string; parameters?: Record<string, unknown> };
}
export interface CanonicalElement {
  id: string;
  name?: string;
  type: string;
  capabilities?: string[];
  observes?: string[];
  native?: { source?: string; type?: string; parameters?: Record<string, unknown> };
}
export interface CanonicalPath {
  id: string;
  name?: string;
  system: string;
  topology: "open" | "closed";
  elements: string[];
  reference?: string;
  length?: number;
  direction?: string;
  branches?: { at: string; to_path: string }[];
}
export interface CanonicalBeam {
  id: string;
  name?: string;
  kind: "particle" | "photon";
  parameters: Record<string, unknown>;
}
export interface CanonicalSystem {
  id: string;
  name?: string;
  kind: string;
  beams: CanonicalBeam[];
}
export interface CanonicalDataset {
  id: string;
  name?: string;
  kind: string;
  path: string;
  values: Record<string, CanonicalValues>;
  [k: string]: unknown;
}
export interface CanonicalBeamModel {
  format: string;
  model: { id: string; name?: string; source?: string; version?: string; git_commit?: string; simulator?: string };
  systems: CanonicalSystem[];
  paths: CanonicalPath[];
  elements: CanonicalElement[];
  observables?: { quantity: string; unit?: string; domain?: string; plane?: string }[];
  datasets?: CanonicalDataset[];
}


// ------------------------------------------------------------------- argus.beam-model/2 (docs/beam-model-format.md)
// Loose on purpose: the editor changes what it shows and passes everything else through untouched.

export interface V2Profile {
  shape: "circle" | "ellipse" | "rectangle" | "racetrack" | "polygon" | "custom";
  radius?: number; semi_axis_x?: number; semi_axis_y?: number; half_width_x?: number; half_height_y?: number;
  corner_radius?: number; points?: number[][]; offset_x?: number; offset_y?: number; [k: string]: unknown;
}
export interface V2Boundary {
  id?: string; component?: string; path?: string; s_start?: number; s_end?: number; profile: V2Profile;
  when_state?: string; kind?: "physical" | "model"; note?: string; [k: string]: unknown;
}
export interface V2Provenance {
  source?: string; file?: string; symbol?: string; expression?: string; line?: number; note?: string; [k: string]: unknown;
}
export interface V2StateModel {
  states: { name: string; meaning?: Record<string, unknown>; description?: string }[];
  default?: string; mappings?: { signal?: string; value: unknown; state: string }[];
}
export interface V2Native { format?: string; type?: string; name?: string; file?: string; parameters?: Record<string, unknown>; [k: string]: unknown }
export interface V2Component {
  id: string; name?: string; type?: string; definition?: string; family?: string; aliases?: string[];
  capabilities?: string[]; parameters?: Record<string, unknown>;
  geometry?: { length?: number; [k: string]: unknown };
  boundaries?: V2Boundary[];
  material?: { material: string; thickness?: number; density?: number; radiation_length?: number; [k: string]: unknown };
  states?: V2StateModel;
  measurement_model?: { type: string; observables?: string[]; [k: string]: unknown };
  observes?: string[]; mounted_on?: string; contained_in?: string; fiducials?: string[];
  native?: V2Native; description?: string; provenance?: Record<string, V2Provenance>; [k: string]: unknown;
}
export interface V2Placement { component: string; id?: string; s?: number; length?: number; reversed?: boolean }
export interface V2Path {
  id: string; name?: string; system?: string; beams?: string[]; topology: "open" | "closed";
  placements: (string | V2Placement)[]; reference?: string; length?: number; direction?: string; [k: string]: unknown;
}
export interface V2Connection {
  kind: "branch" | "merge" | "continue"; from: { path: string; component?: string }; to: { path: string; component?: string };
  note?: string;
}
export interface V2Beam {
  id: string; name?: string; kind?: "particle" | "photon"; species?: string; charge?: number; rest_mass?: number;
  reference_energy?: number; reference_momentum?: number; wavelength?: number; systems?: string[];
  parameters?: Record<string, unknown>; [k: string]: unknown;
}
export interface V2System { id: string; name?: string; kind?: string; beams?: string[]; [k: string]: unknown }
export interface V2Values {
  s?: number | null; geometry?: Record<string, number> | null; physics?: Record<string, unknown>;
  optics?: Record<string, unknown>; native?: V2Native; provenance?: Record<string, V2Provenance>; [k: string]: unknown;
}
export interface V2Field {
  quantity: string; path: string; unit?: string; samples: number[][]; interpolation?: "linear" | "step" | "none";
  description?: string; [k: string]: unknown;
}
export interface V2Dataset {
  id: string; name?: string; kind?: string; category?: string; path?: string; values?: Record<string, V2Values>;
  source?: string; version?: string; git_commit?: string; simulator?: string; simulator_version?: string;
  generated_at?: string; valid_from?: string; valid_until?: string; fields?: V2Field[]; boundaries?: V2Boundary[];
  [k: string]: unknown;
}
export interface V2Definition {
  id: string; type: string; name?: string; capabilities?: string[]; parameters?: Record<string, unknown>;
  geometry?: { length?: number; [k: string]: unknown }; boundaries?: V2Boundary[];
  material?: V2Component["material"]; states?: V2StateModel; native?: V2Native;
  provenance?: Record<string, V2Provenance>; [k: string]: unknown;
}
export interface BeamModelV2 {
  schema_version: "argus.beam-model/2";
  model: { id: string; name?: string; source?: string; version?: string; git_commit?: string; simulator?: string; [k: string]: unknown };
  facility?: { id: string; name?: string; namespace?: string; site?: string; [k: string]: unknown };
  systems: V2System[]; beams: V2Beam[]; paths: V2Path[]; connections: V2Connection[];
  definitions?: V2Definition[];
  components: V2Component[]; boundaries?: V2Boundary[]; observables?: { quantity: string; unit?: string; [k: string]: unknown }[];
  datasets?: V2Dataset[]; external_bindings?: unknown[]; provenance?: Record<string, unknown>; [k: string]: unknown;
}

export interface BeamVocabulary {
  families: Record<string, Record<string, string[]>>;
  capabilities: Record<string, string>;
  observables: Record<string, { unit: string; domain: string; plane: string }>;
  measurement_models: string[];
  states: Record<string, Record<string, Record<string, unknown>>>;
  binding_relations: Record<string, string>;
  shapes: string[];
  virtual_families: string[];
}

/** The semantic graph around a record: what is about the same thing, by the knowledge index. */
export interface SemanticGraph {
  nodes: { kind: string; uid: string; label: string; sublabel: string | null; depth: number }[];
  edges: { from_kind: string; from_uid: string; to_kind: string; to_uid: string; relation: string; score: number;
           excerpt: string; matched: string }[];
  available: boolean;
  reason: string | null;
  basis: string | null;
}
