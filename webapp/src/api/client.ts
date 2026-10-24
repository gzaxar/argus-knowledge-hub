import { loadSession } from "./session";
import type {
  ArchiveManifest,
  ExportView,
  ImportView,
  OriginChainCheck,
  PortabilityConfig, PortabilityJob, PortabilitySchedule, PortabilitySetup, SetupRepository,
  ProvenanceView,
  ReconciliationReport,
} from "./portabilityTypes";
import type {
  AppSchema,
  Asset,
  AssetComment,
  AssetHistory,
  AssetInput,
  AssetLabel,
  AssetLabelInput,
  AssetLabelSearchResult,
  AssetTicket,
  Attachment,
  AppDocument,
  BulkDeleteResult,
  DocumentInput,
  DocumentUpdateInput,
  DocumentRevision,
  DocumentRevisionInput,
  DocumentRelation,
  GlobalValue,
  GlobalValueInput,
  Icon,
  IconUpdate,
  ImportConfig,
  ImportConfigInput,
  ImportConfigUpdateInput,
  ImportInput,
  ImportJob,
  Issue,
  IssueComment,
  IssueInput,
  AdminUser,
  CleanupOptions,
  CleanupResult,
  DefaultAccess,
  IntegrityReport,
  Me,
  Member,
  MemberCandidate,
  MemberDirectoryEntry,
  MemberInput,
  MyWorkspace,
  RelinkResult,
  AISuggestion,
  AIStatus,
  DraftDocumentResult,
  DraftTicketResult,
  PhotoIdentification,
  ReviewDocumentResult,
  SuggestRunResult,
  LLMCheckResult,
  LLMConfig,
  LLMConfigInput,
  MarkdownImportResult,
  Relation,
  RetypeResult,
  TransferJob,
  TransferRequest,
  Workspace,
  WorkspaceUpdateInput,
  SchemaInput,
  WorkspaceDetail,
  IssueHistoryEntry,
  IssueLinks,
  IssueAssetLink,
  IssueDocumentLink,
  IssueTicketLink,
  Role,
  RoleBinding,
  RoleBindingInput,
  DirectoryGroup,
  DirectoryGroupMember,
  DirectoryStatus,
  EffectivePermissions,
  Graph,
  GraphSummary,
  AskResult,
  AskConversation,
  AskAction,
  HelpHit,
  HelpTopic,
  HelpTopicSummary,
  AskConversationDetail,
  AskFeedbackResult,
  Statistics,
  Activity,
  ActivityPage,
  TemplateListing,
  TemplateChoice,
  TemplateVariant,
  OfficialTemplate,
  TemplateComparison,
  TemplateProblem,
  TemplateDescription,
  ReshapeSource,
  ReshapeResult,
  ReshapeSaved,
  ReshapeGeneration,
  ChatEvent,
  KnowledgeStatus,
  SemanticGraph,
  ImpactResult,
  RootCauseResult,
  BeamSystem,
  BeamPathGraph,
  BeamElementContext, BeamModelV2, BeamVocabulary, AssetSyncStatus, AssetSyncApply, AssetSyncApplied, AssetBinding,
  BeamRecord,
  BeamModelSummary,
  BeamModelCheck,
  BeamConversionReport,
  BeamImportReport,
  CanonicalBeamModel,
  WorkspaceIdRule,
  AssetKeyRule,
  CatalogueMapping,
  MappingItem,
  MappingVocabulary,
  PlanEntry,
  MappingSourceType,
  WorkspaceIdSuggestion,
} from "./types";
import type {
  AssetContext,
  DocumentContext,
  HubOverview,
  HubSearchResult,
  TicketContext,
} from "./hubTypes";
import type {
  AccessPointView,
  AddressUse,
  NotificationView,
  EmailPreferences,
  WorkspaceSubscription,
  AccessReviewView,
  AttachmentCheck,
  RetentionClass,
  RetentionView,
  RetirementStatus,
  MigrationPlanView,
  QueueDashboard,
  GoldenIncident,
  GoldenRun,
  EquipmentClassView,
  EquipmentClassReport,
  ClassReview,
  MigrationRow,
  RoleTemplate,
  Rehearsal,
  TicketTransitions,
  WorkflowDef,
  AuditDigestView,
  AuditEntry,
  BulkChangeView,
  EquipmentState,
  SpareView,
  ValueHistory,
  Decision as LedgerDecision,
  DomainDetail,
  DomainView,
  InstallationView,
  LookupHit,
  ReconciliationBody,
  RecordFacts,
  RecordTickets,
  ReviewQueue,
  RuleEntry,
  SegmentPort,
  TemporalValue,
  TicketLinkView,
  FollowState,
} from "./ledgerTypes";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(`API error ${status}: ${JSON.stringify(body)}`);
    this.status = status;
    this.body = body;
  }

  /** The message the API meant for a person — FastAPI puts it in `detail`.
   * Null when the body carries no readable message, so callers can fall back
   * to their own wording rather than showing a JSON dump. */
  get detail(): string | null {
    const detail = (this.body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : null;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const session = await loadSession();
  if (!session) throw new Error("Not signed in");

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${session.token}`);
  // A call about a named workspace (a page under /workspaces/:id) says so itself; the rest act in the current one.
  if (session.workspaceId && !headers.has("X-Workspace-Id")) headers.set("X-Workspace-Id", session.workspaceId);
  if (!(init.body instanceof FormData) && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(`${session.baseUrl}${path}`, { ...init, headers });
  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data as T;
}

export async function checkHealth(baseUrl: string): Promise<boolean> {
  try {
    const resp = await fetch(`${baseUrl}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}

export async function checkToken(): Promise<boolean> {
  try {
    await request("/v1/schemas");
    return true;
  } catch {
    return false;
  }
}

const json = (body: unknown) => JSON.stringify(body);

function authHeaders(session: { token: string; workspaceId?: string }): HeadersInit {
  const headers: Record<string, string> = { Authorization: `Bearer ${session.token}` };
  if (session.workspaceId) headers["X-Workspace-Id"] = session.workspaceId;
  return headers;
}

export const schemasApi = {
  list: () => request<AppSchema[]>("/v1/schemas"),
  get: (uid: string) => request<AppSchema>(`/v1/schemas/${uid}`),
  create: (input: SchemaInput) =>
    request<AppSchema>("/v1/schemas", { method: "POST", body: json(input) }),
  update: (uid: string, input: Partial<SchemaInput>) =>
    request<AppSchema>(`/v1/schemas/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/schemas/${uid}`, { method: "DELETE" }),
  uploadIcon: async (uid: string, file: File): Promise<AppSchema> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${session.baseUrl}/v1/schemas/${uid}/icon`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as AppSchema;
  },
  setIconFromLibrary: (uid: string, iconUid: string) =>
    request<AppSchema>(`/v1/schemas/${uid}/icon/${iconUid}`, { method: "PUT" }),
  clearIcon: (uid: string) => request<AppSchema>(`/v1/schemas/${uid}/icon`, { method: "DELETE" }),
};

export const assetsApi = {
  list: (schemaUid?: string) =>
    request<Asset[]>(`/v1/assets${schemaUid ? `?schema_uid=${schemaUid}` : ""}`),
  /** The uids of the records whose key, name, a label (QR code, barcode, former key, alias), serial,
   *  inventory number or MAC contains this. */
  matching: (q: string) =>
    request<{ uid: string }[]>(`/v1/assets?q=${encodeURIComponent(q)}&sort=key&limit=500`).then(
      (rows) => new Set(rows.map((r) => r.uid)),
    ),
  get: (uid: string) => request<Asset>(`/v1/assets/${uid}`),
  create: (input: AssetInput) =>
    request<Asset>("/v1/assets", { method: "POST", body: json(input) }),
  update: (uid: string, input: Partial<AssetInput>) =>
    request<Asset>(`/v1/assets/${uid}`, { method: "PUT", body: json(input) }),
  /** The key a new record of this type would get; nothing is reserved. */
  nextKey: (schemaUid?: string) =>
    request<{ key: string; pattern: string }>(
      `/v1/assets/next-key${schemaUid ? `?schema_uid=${encodeURIComponent(schemaUid)}` : ""}`,
    ),
  delete: (uid: string) => request<void>(`/v1/assets/${uid}`, { method: "DELETE" }),
  bulkDelete: (uids: string[]) =>
    request<BulkDeleteResult>("/v1/assets/bulk-delete", { method: "POST", body: json({ uids }) }),
  uploadAvatar: async (uid: string, file: File): Promise<Asset> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${session.baseUrl}/v1/assets/${uid}/avatar`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as Asset;
  },
  setAvatarFromAttachment: (uid: string, attachmentUid: string) =>
    request<Asset>(`/v1/assets/${uid}/avatar/${attachmentUid}`, { method: "PUT" }),
  clearAvatar: (uid: string) => request<Asset>(`/v1/assets/${uid}/avatar`, { method: "DELETE" }),
};

export const relationsApi = {
  list: () => request<Relation[]>("/v1/relations"),
  create: (fromAssetUid: string, toAssetUid: string, relationType: string) =>
    request<Relation>("/v1/relations", {
      method: "POST",
      body: json({
        from_asset_uid: fromAssetUid,
        to_asset_uid: toAssetUid,
        relation_type: relationType,
      }),
    }),
  delete: (id: number) => request<void>(`/v1/relations/${id}`, { method: "DELETE" }),
};

export const issuesApi = {
  list: (schemaUid?: string) =>
    request<Issue[]>(`/v1/issues${schemaUid ? `?schema_uid=${schemaUid}` : ""}`),
  get: (uid: string) => request<Issue>(`/v1/issues/${uid}`),
  create: (input: IssueInput) =>
    request<Issue>("/v1/issues", { method: "POST", body: json(input) }),
  update: (uid: string, input: Partial<IssueInput>) =>
    request<Issue>(`/v1/issues/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/issues/${uid}`, { method: "DELETE" }),
  bulkDelete: (uids: string[]) =>
    request<BulkDeleteResult>("/v1/issues/bulk-delete", { method: "POST", body: json({ uids }) }),
  labels: () => request<string[]>("/v1/issues/labels"),
  listComments: (uid: string) =>
    request<IssueComment[]>(`/v1/issues/${uid}/comments`),
  addComment: (uid: string, author: string, body: string) =>
    request<IssueComment>(`/v1/issues/${uid}/comments`, {
      method: "POST",
      body: json({ uid: crypto.randomUUID(), author, body }),
    }),
};

export const assetSubresourcesApi = {
  history: (assetUid: string) =>
    request<AssetHistory[]>(`/v1/assets/${assetUid}/history`),
  comments: (assetUid: string) =>
    request<AssetComment[]>(`/v1/assets/${assetUid}/comments`),
  addComment: (assetUid: string, author: string, text: string) => {
    const now = new Date().toISOString();
    return request<AssetComment>(`/v1/assets/${assetUid}/comments`, {
      method: "POST",
      body: json({ uid: crypto.randomUUID(), author, text, created: now, updated: now }),
    });
  },
  tickets: (assetUid: string) =>
    request<AssetTicket[]>(`/v1/assets/${assetUid}/tickets`),
  labels: (assetUid: string) => request<AssetLabel[]>(`/v1/assets/${assetUid}/labels`),
  addLabel: (assetUid: string, input: AssetLabelInput) => {
    const now = new Date().toISOString();
    return request<AssetLabel>(`/v1/assets/${assetUid}/labels`, {
      method: "POST",
      body: json({
        uid: crypto.randomUUID(),
        created_at: now,
        updated_at: now,
        ...input,
      }),
    });
  },
  deleteLabel: (assetUid: string, labelUid: string) =>
    request<void>(`/v1/assets/${assetUid}/labels/${labelUid}`, { method: "DELETE" }),
};

export const labelsApi = {
  search: (query?: { search?: string; type?: string }) => {
    const params = new URLSearchParams();
    if (query?.search) params.set("search", query.search);
    if (query?.type) params.set("type", query.type);
    const qs = params.toString();
    return request<AssetLabelSearchResult[]>(`/v1/labels${qs ? `?${qs}` : ""}`);
  },
};

export type ExportKind = "document" | "asset" | "ticket";

const EXPORT_PATHS: Record<ExportKind, string> = { document: "documents", asset: "assets", ticket: "issues" };

/** A document, asset or ticket as Markdown — the download, and the text the
 * print view (and so the PDF) is made from. */
export const exportApi = {
  markdown: async (kind: ExportKind, uid: string, revisionUid?: string | null) => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const query = revisionUid ? `?revision_uid=${encodeURIComponent(revisionUid)}` : "";
    const resp = await fetch(`${session.baseUrl}/v1/${EXPORT_PATHS[kind]}/${encodeURIComponent(uid)}/markdown${query}`, {
      headers: authHeaders(session),
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    const name = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") ?? "")?.[1] ?? `${uid}.md`;
    return { text: await resp.text(), filename: name, baseUrl: session.baseUrl };
  },

  /** Save the record as a PDF the server lays out (A4, its pictures included): one click, no print dialog. */
  downloadPdf: async (kind: ExportKind, uid: string, revisionUid?: string | null) => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const query = revisionUid ? `?revision_uid=${encodeURIComponent(revisionUid)}` : "";
    const resp = await fetch(`${session.baseUrl}/v1/${EXPORT_PATHS[kind]}/${encodeURIComponent(uid)}/pdf${query}`, {
      headers: authHeaders(session),
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    const name = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") ?? "")?.[1] ?? `${uid}.pdf`;
    const url = URL.createObjectURL(await resp.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  },

  /** Save the Markdown file. Its links to attachments are made absolute, so
   * outside ARGUS they still say where each file is. */
  downloadMarkdown: async (kind: ExportKind, uid: string, revisionUid?: string | null) => {
    const { text, filename, baseUrl } = await exportApi.markdown(kind, uid, revisionUid);
    const absolute = text.replace(/\]\(\/v1\/attachments\//g, `](${baseUrl}/v1/attachments/`);
    const url = URL.createObjectURL(new Blob([absolute], { type: "text/markdown;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    a.click();
    URL.revokeObjectURL(url);
  },
};

export const attachmentsApi = {
  list: (assetUid: string) =>
    request<Attachment[]>(`/v1/attachments?asset_uid=${assetUid}`),
  upload: async (assetUid: string, file: File): Promise<Attachment> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(
      `${session.baseUrl}/v1/attachments?asset_uid=${assetUid}`,
      { method: "POST", headers: authHeaders(session), body: form },
    );
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as Attachment;
  },
  // The download endpoint requires the Bearer header, so a plain <img src=""> /
  // <a href=""> can't hit it directly — fetch as a blob and hand back an object
  // URL the caller is responsible for revoking (URL.revokeObjectURL) when done.
  /** An attachment's content as text — for the SVG sheets of a drawing,
   * which are rendered inline rather than shown through an <img>. */
  fetchText: async (uid: string): Promise<string> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}/v1/attachments/${uid}`, {
      headers: authHeaders(session),
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return resp.text();
  },

  fetchBlobUrl: async (uid: string): Promise<string> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}/v1/attachments/${uid}`, {
      headers: authHeaders(session),
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    const blob = await resp.blob();
    return URL.createObjectURL(blob);
  },
  delete: (uid: string) => request<void>(`/v1/attachments/${uid}`, { method: "DELETE" }),
};

/** The shared icon library types are chosen from — upload once, reuse
 * anywhere, unlike an object's avatar or a one-off attachment. */
export const iconsApi = {
  list: () => request<Icon[]>("/v1/icons"),
  upload: async (file: File, name?: string): Promise<Icon> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    const resp = await fetch(`${session.baseUrl}/v1/icons`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as Icon;
  },
  update: (uid: string, input: IconUpdate) =>
    request<Icon>(`/v1/icons/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/icons/${uid}`, { method: "DELETE" }),
  fetchBlobUrl: async (uid: string): Promise<string> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}/v1/icons/${uid}`, {
      headers: authHeaders(session),
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    const blob = await resp.blob();
    return URL.createObjectURL(blob);
  },
};

export const globalValuesApi = {
  list: () => request<GlobalValue[]>("/v1/global-values"),
  get: (uid: string) => request<GlobalValue>(`/v1/global-values/${uid}`),
  create: (input: GlobalValueInput) =>
    request<GlobalValue>("/v1/global-values", { method: "POST", body: json(input) }),
  update: (uid: string, input: Partial<GlobalValueInput>) =>
    request<GlobalValue>(`/v1/global-values/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/global-values/${uid}`, { method: "DELETE" }),
};

export const importsApi = {
  list: () => request<ImportJob[]>("/v1/imports"),
  get: (uid: string) => request<ImportJob>(`/v1/imports/${uid}`),
  create: (input: ImportInput) =>
    request<ImportJob>("/v1/imports", { method: "POST", body: json(input) }),
};

export const catalogueMappingApi = {
  sources: (workspaceId: string, kind: "catalogue" | "records" = "catalogue", target?: string) =>
    request<MappingSourceType[]>(
      `/v1/catalogue-mappings/sources?workspace_id=${encodeURIComponent(workspaceId)}&kind=${kind}` +
        (target ? `&target_workspace_id=${encodeURIComponent(target)}` : ""),
    ),
  vocabulary: (id: string) => request<MappingVocabulary>(`/v1/catalogue-mappings/${id}/vocabulary`),
  setPlan: (
    id: string,
    typeUid: string,
    input: {
      target_type_uid?: string;
      share?: boolean;
      fixed?: Record<string, string>;
      companions?: Record<
        string,
        {
          type_uid?: string;
          verb?: string;
          from_companion?: boolean;
          label?: string;
          suffix?: string;
          fixed?: Record<string, string>;
          share?: boolean;
        } | null
      >;
      fields?: Record<
        string,
        {
          kind: string;
          target?: string | null;
          values?: Record<string, string>;
          verb?: string | null;
          reverse?: boolean;
          text_to?: string;
          create_type?: string | null;
          companion?: string;
          create_missing?: boolean;
        }
      >;
      relations?: Record<string, { verb: string | null; reverse: boolean }>;
    },
  ) => request<PlanEntry>(`/v1/catalogue-mappings/${id}/plan/${typeUid}`, { method: "PUT", body: json(input) }),
  recheck: (id: string) =>
    request<{ rows: number; warnings: number }>(`/v1/catalogue-mappings/${id}/recheck`, { method: "POST" }),
  share: (id: string) => request<{ shared: number }>(`/v1/catalogue-mappings/${id}/share`, { method: "POST" }),
  list: () => request<CatalogueMapping[]>("/v1/catalogue-mappings"),
  get: (id: string) => request<CatalogueMapping>(`/v1/catalogue-mappings/${id}`),
  start: (input: {
    kind?: "catalogue" | "records";
    source_workspace_id: string;
    target_workspace_id: string;
    type_uids: string[];
    use_ai: boolean;
  }) => request<CatalogueMapping>("/v1/catalogue-mappings", { method: "POST", body: json(input) }),
  decide: (
    id: string,
    itemId: string,
    input: {
      status?: string;
      fields?: Record<string, string>;
      vendor?: string;
      action?: string;
      merge_into_uid?: string;
      attributes?: Record<string, unknown>;
    },
  ) => request<MappingItem>(`/v1/catalogue-mappings/${id}/items/${itemId}`, { method: "PATCH", body: json(input) }),
  decideMany: (id: string, input: { item_ids?: string[]; status?: string; min_confidence?: number; type_uid?: string }) =>
    request<{ changed: number; errors: { item: string; error: string }[] }>(`/v1/catalogue-mappings/${id}/items`, {
      method: "POST",
      body: json(input),
    }),
  apply: (id: string, keepText = false) =>
    request<{
      applied: number;
      failed: { source_key: string; error: string }[];
      carried: Record<string, number>;
      relations?: number;
      relations_failed?: { verb: string; error: string }[];
    }>(
      `/v1/catalogue-mappings/${id}/apply${keepText ? "?keep_text=true" : ""}`,
      { method: "POST" },
    ),
  shareReferences: (id: string) =>
    request<{ shared: number }>(`/v1/catalogue-mappings/${id}/share-references`, { method: "POST" }),
  fillReferences: (id: string) =>
    request<{ records: number; filled: number; still_hidden: number }>(
      `/v1/catalogue-mappings/${id}/fill-references`,
      { method: "POST" },
    ),
  carry: (id: string) =>
    request<{ rows: number; failed: { source_key: string; error: string }[]; carried: Record<string, number> }>(
      `/v1/catalogue-mappings/${id}/carry`,
      { method: "POST" },
    ),
  undo: (id: string) =>
    request<{ retired: number; relations_removed?: number }>(`/v1/catalogue-mappings/${id}/undo`, { method: "POST" }),
};

export const transfersApi = {
  list: () => request<TransferJob[]>("/v1/transfers"),
  get: (uid: string) => request<TransferJob>(`/v1/transfers/${uid}`),
  create: (input: TransferRequest) =>
    request<TransferJob>("/v1/transfers", { method: "POST", body: json(input) }),
};

export const importConfigsApi = {
  list: () => request<ImportConfig[]>("/v1/import-configs"),
  get: (uid: string) => request<ImportConfig>(`/v1/import-configs/${uid}`),
  create: (input: ImportConfigInput) =>
    request<ImportConfig>("/v1/import-configs", { method: "POST", body: json(input) }),
  update: (uid: string, input: ImportConfigUpdateInput) =>
    request<ImportConfig>(`/v1/import-configs/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/import-configs/${uid}`, { method: "DELETE" }),
  run: (uid: string) =>
    request<ImportConfig>(`/v1/import-configs/${uid}/run`, { method: "POST" }),
};

/** The user guide (backend/app/help/guide). */
export const helpApi = {
  topics: () => request<HelpTopicSummary[]>("/v1/help"),
  topic: (slug: string) => request<HelpTopic>(`/v1/help/${encodeURIComponent(slug)}`),
  search: (q: string) => request<HelpHit[]>(`/v1/help/search?q=${encodeURIComponent(q)}`),
};

export const workspacesApi = {
  me: () => request<Me>("/v1/me"),
  listMine: () => request<MyWorkspace[]>("/v1/me/workspaces"),
  /** `id` omitted: the server derives it from the name by the
   * installation's rule, so a stale form cannot make one that breaks it. */
  create: (name: string, id?: string, packages: string[] = [], catalogueWorkspaceId?: string) =>
    request<MyWorkspace>("/v1/workspaces", {
      method: "POST",
      body: json({ name, ...(id ? { id } : {}), packages,
                   ...(catalogueWorkspaceId ? { catalogue_workspace_id: catalogueWorkspaceId } : {}) }),
    }),
  suggestId: (name: string) =>
    request<WorkspaceIdSuggestion>(
      `/v1/workspaces/suggest-id?name=${encodeURIComponent(name)}`,
    ),
  idRule: () => request<WorkspaceIdRule>("/v1/workspaces/id-rule"),
  saveIdRule: (input: WorkspaceIdRule) =>
    request<WorkspaceIdRule>("/v1/workspaces/id-rule", {
      method: "PUT",
      body: json(input),
    }),
  keyRule: (workspaceId: string) => request<AssetKeyRule>(`/v1/workspaces/${workspaceId}/key-rule`),
  saveKeyRule: (workspaceId: string, pattern: string) =>
    request<AssetKeyRule>(`/v1/workspaces/${workspaceId}/key-rule`, {
      method: "PUT",
      body: json({ pattern }),
    }),
  get: (workspaceId: string) => request<WorkspaceDetail>(`/v1/workspaces/${workspaceId}`),
  update: (workspaceId: string, input: WorkspaceUpdateInput) =>
    request<Workspace>(`/v1/workspaces/${workspaceId}`, { method: "PUT", body: json(input) }),
  delete: (workspaceId: string) =>
    request<void>(`/v1/workspaces/${workspaceId}`, { method: "DELETE" }),
  integrityReport: (workspaceId: string) =>
    request<IntegrityReport>(`/v1/workspaces/${workspaceId}/integrity-report`),
  relink: (workspaceId: string) =>
    request<{ relink: RelinkResult; report: IntegrityReport }>(
      `/v1/workspaces/${workspaceId}/relink`,
      { method: "POST" },
    ),
  cleanup: (workspaceId: string, options: CleanupOptions) =>
    request<{ cleanup: CleanupResult; report: IntegrityReport }>(
      `/v1/workspaces/${workspaceId}/cleanup`,
      { method: "POST", body: json(options) },
    ),
  setDefaultAccess: (workspaceId: string, input: DefaultAccess) =>
    request<WorkspaceDetail>(`/v1/workspaces/${workspaceId}/default-access`, {
      method: "PUT",
      body: json(input),
    }),
  listMembers: (workspaceId: string) =>
    request<Member[]>(`/v1/workspaces/${workspaceId}/members`),
  /** People who have signed in, matching `q` by e-mail or name: whom one can add as a member. */
  memberCandidates: (workspaceId: string, q: string) =>
    request<MemberCandidate[]>(`/v1/workspaces/${workspaceId}/member-candidates?${new URLSearchParams({ q })}`),
  upsertMember: (workspaceId: string, input: MemberInput) =>
    request<Member>(`/v1/workspaces/${workspaceId}/members`, { method: "PUT", body: json(input) }),
  removeMember: (workspaceId: string, userId: string) =>
    request<void>(`/v1/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" }),
  listUsers: () => request<AdminUser[]>("/v1/admin/users"),
  setUserAdmin: (userId: string, isAdmin: boolean) =>
    request<AdminUser>(`/v1/admin/users/${userId}`, {
      method: "PUT",
      body: json({ is_admin: isAdmin }),
    }),
};

export const issueSubresourcesApi = {
  history: (uid: string) => request<IssueHistoryEntry[]>(`/v1/issues/${uid}/history`),
  attachments: (uid: string) => request<Attachment[]>(`/v1/issues/${uid}/attachments`),
  uploadAttachment: async (uid: string, file: File): Promise<Attachment> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${session.baseUrl}/v1/issues/${uid}/attachments`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as Attachment;
  },
};

export const issueLinksApi = {
  list: (uid: string) => request<IssueLinks>(`/v1/issues/${uid}/links`),
  linkAsset: (uid: string, assetUid: string, relation = "affects") =>
    request<IssueAssetLink>(`/v1/issues/${uid}/links/assets`, {
      method: "POST",
      body: json({ asset_uid: assetUid, relation }),
    }),
  unlinkAsset: (uid: string, assetUid: string) =>
    request<void>(`/v1/issues/${uid}/links/assets/${assetUid}`, { method: "DELETE" }),
  linkTicket: (uid: string, issueUid: string, relation = "relates") =>
    request<IssueTicketLink>(`/v1/issues/${uid}/links/tickets`, {
      method: "POST",
      body: json({ issue_uid: issueUid, relation }),
    }),
  unlinkTicket: (uid: string, linkId: number) =>
    request<void>(`/v1/issues/${uid}/links/tickets/${linkId}`, { method: "DELETE" }),
  linkDocument: (uid: string, documentUid: string, relation = "documents") =>
    request<IssueDocumentLink>(`/v1/issues/${uid}/links/documents`, {
      method: "POST",
      body: json({ document_uid: documentUid, relation }),
    }),
  unlinkDocument: (uid: string, relationId: number) =>
    request<void>(`/v1/issues/${uid}/links/documents/${relationId}`, { method: "DELETE" }),
};

export const membersApi = {
  directory: () => request<MemberDirectoryEntry[]>("/v1/members"),
};

export const documentsApi = {
  list: (documentTypeUid?: string) =>
    request<AppDocument[]>(`/v1/documents${documentTypeUid ? `?document_type_uid=${documentTypeUid}` : ""}`),
  get: (uid: string) => request<AppDocument>(`/v1/documents/${uid}`),
  create: (input: DocumentInput) =>
    request<AppDocument>("/v1/documents", { method: "POST", body: json(input) }),
  update: (uid: string, input: DocumentUpdateInput) =>
    request<AppDocument>(`/v1/documents/${uid}`, { method: "PUT", body: json(input) }),
  delete: (uid: string) => request<void>(`/v1/documents/${uid}`, { method: "DELETE" }),
  bulkDelete: (uids: string[]) =>
    request<BulkDeleteResult>("/v1/documents/bulk-delete", { method: "POST", body: json({ uids }) }),
  retire: (uid: string, reason: string) =>
    request<AppDocument>(`/v1/documents/${uid}/retire`, { method: "POST", body: json({ reason }) }),
  current: (uid: string) => request<DocumentRevision>(`/v1/documents/${uid}/current`),
  retention: (uid: string) => request<RetentionView>(`/v1/documents/${uid}/retention`),
  setRetention: (uid: string, retention_class: RetentionClass) =>
    request<RetentionView>(`/v1/documents/${uid}/retention`, { method: "PUT", body: json({ retention_class }) }),
  supersede: (uid: string, by_document_uid: string, reason: string) =>
    request<AppDocument>(`/v1/documents/${uid}/supersede`, { method: "POST", body: json({ by_document_uid, reason }) }),
  verifyAttachment: (attachmentUid: string) => request<AttachmentCheck>(`/v1/attachments/${attachmentUid}/verify`),

  listRevisions: (uid: string) => request<DocumentRevision[]>(`/v1/documents/${uid}/revisions`),
  createRevision: (uid: string, input: DocumentRevisionInput) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions`, { method: "POST", body: json(input) }),
  getRevision: (uid: string, revUid: string) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}`),
  updateRevision: (uid: string, revUid: string, input: DocumentRevisionInput) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}`, {
      method: "PUT",
      body: json(input),
    }),
  submitRevision: (uid: string, revUid: string) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}/submit`, { method: "POST" }),
  approveRevision: (uid: string, revUid: string, comment?: string) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}/approve`, {
      method: "POST",
      body: json({ comment }),
    }),
  rejectRevision: (uid: string, revUid: string, comment: string) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}/reject`, {
      method: "POST",
      body: json({ comment }),
    }),
  publishRevision: (uid: string, revUid: string) =>
    request<DocumentRevision>(`/v1/documents/${uid}/revisions/${revUid}/publish`, { method: "POST" }),

  listRelations: (uid: string) => request<DocumentRelation[]>(`/v1/documents/${uid}/relations`),
  addRelation: (
    uid: string,
    input: { to_type: DocumentRelation["to_type"]; to_uid: string; relation_type: string },
  ) => request<DocumentRelation>(`/v1/documents/${uid}/relations`, { method: "POST", body: json(input) }),
  removeRelation: (uid: string, relationId: number) =>
    request<void>(`/v1/documents/${uid}/relations/${relationId}`, { method: "DELETE" }),

  /** Move a batch of documents onto one type. */
  retype: (uids: string[], documentTypeUid: string | null) =>
    request<RetypeResult>("/v1/documents/retype", {
      method: "POST",
      body: json({ uids, document_type_uid: documentTypeUid }),
    }),

  /** Markdown files (and the images they use) as documents. */
  importMarkdown: async (
    files: File[],
    documentTypeUid: string | null,
  ): Promise<MarkdownImportResult> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    for (const file of files) {
      // A folder picker knows the path inside the folder; a plain multi-file
      // input does not. Sending the path when there is one is what lets
      // `images/layout.png` in a body find the file it names.
      const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
      form.append("files", file, path || file.name);
    }
    if (documentTypeUid) form.append("document_type_uid", documentTypeUid);
    const resp = await fetch(`${session.baseUrl}/v1/documents/import`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as MarkdownImportResult;
  },

  listRevisionAttachments: (uid: string, revUid: string) =>
    request<Attachment[]>(`/v1/documents/${uid}/revisions/${revUid}/attachments`),
  uploadRevisionAttachment: async (
    uid: string,
    revUid: string,
    file: File,
  ): Promise<Attachment> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(
      `${session.baseUrl}/v1/documents/${uid}/revisions/${revUid}/attachments`,
      { method: "POST", headers: authHeaders(session), body: form },
    );
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as Attachment;
  },
};

export const rolesApi = {
  list: () => request<Role[]>("/v1/roles"),
  listBindings: (workspaceId: string) =>
    request<RoleBinding[]>(`/v1/workspaces/${workspaceId}/bindings`),
  createBinding: (workspaceId: string, input: RoleBindingInput) =>
    request<RoleBinding>(`/v1/workspaces/${workspaceId}/bindings`, {
      method: "POST",
      body: json(input),
    }),
  deleteBinding: (workspaceId: string, bindingId: number) =>
    request<void>(`/v1/workspaces/${workspaceId}/bindings/${bindingId}`, { method: "DELETE" }),
  myPermissions: (workspaceId: string) =>
    request<EffectivePermissions>(`/v1/workspaces/${workspaceId}/my-permissions`),
};

export const directoryApi = {
  groups: (search?: string) =>
    request<DirectoryGroup[]>(`/v1/groups${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  groupMembers: (uid: string) => request<DirectoryGroupMember[]>(`/v1/groups/${uid}/members`),
  status: () => request<DirectoryStatus>("/v1/directory/status"),
  sync: () => request<Record<string, unknown>>("/v1/directory/sync", { method: "POST" }),
};

export const graphApi = {
  summary: () => request<GraphSummary>("/v1/graph/summary"),
  /** The records whose written knowledge is about the same thing as this one's (the knowledge index). */
  semantic: (kind: "asset" | "ticket" | "document", uid: string, limit = 10) =>
    request<SemanticGraph>(`/v1/graph/semantic?${new URLSearchParams({ kind, uid, limit: String(limit) }).toString()}`),
  /** This failed: what it takes with it, how, and by which path. */
  impact: (uid: string, layers?: string[]) => {
    const q = new URLSearchParams({ uid });
    if (layers?.length) q.set("layers", layers.join(","));
    return request<ImpactResult>(`/v1/graph/impact?${q.toString()}`);
  },
  /** These misbehave (and these work): what would explain them, ranked, with the paths. */
  rootCause: (body: { symptoms: string[]; healthy?: string[]; layers?: string[]; top?: number }) =>
    request<RootCauseResult>("/v1/graph/root-cause", { method: "POST", body: json(body) }),
  walk: (params: {
    kind: string;
    uid: string;
    depth: number;
    kinds?: string[];
    maxNodes?: number;
  }) => {
    const query = new URLSearchParams({
      kind: params.kind,
      uid: params.uid,
      depth: String(params.depth),
    });
    if (params.kinds?.length) query.set("kinds", params.kinds.join(","));
    if (params.maxNodes) query.set("max_nodes", String(params.maxNodes));
    return request<Graph>(`/v1/graph?${query.toString()}`);
  },
};

export const attributeValuesApi = {
  /** Every value an indexed attribute already holds in this workspace —
   * the vocabulary offered as you type. */
  list: (appliesTo: "objects" | "tickets" | "documents", key: string) =>
    request<string[]>(
      `/v1/attribute-values?applies_to=${appliesTo}&key=${encodeURIComponent(key)}&limit=200`,
    ),
};

/** Guided and AI-assisted entry (asset-model-revision §23). */
export type IntakeKind = "asset" | "ticket" | "document";
export type IntakeSuggestion = {
  value: unknown;
  label: string | null;
  confidence: number | null;
  evidence: string | null;
  grounded: boolean;
  method: string;
};
export type IntakeLink = { uid: string; key: string; name: string; path: string; matched_on?: string };
export type GuideCheck = {
  id: string;
  level: "error" | "warning" | "info" | "ok";
  message: string;
  field: string | null;
  fix?: { field: string; value?: unknown; options?: (string | { uid: string; name: string; key?: string })[] };
  links?: IntakeLink[];
};
export type GuideResult = {
  kind: IntakeKind;
  ready: boolean;
  checks: GuideCheck[];
  steps: { id: string; label: string; done: boolean }[];
  next: { field: string; question: string } | null;
};
export type AssistResult = {
  run_id: string;
  profile_id?: string | null;
  fields: Record<string, IntakeSuggestion>;
  dropped: { field: string; reason: string; link?: IntakeLink }[];
  hypotheses: { text: string; class: string }[];
  message?: string | null;
  redacted?: number;
  guide: GuideResult;
};

export type ProposeResult = {
  run_id: string;
  profile_id: string | null;
  proposed: { field: string; value: unknown; label: string | null; current: unknown; confidence: number | null; evidence: string | null }[];
  unchanged: string[];
  dropped: { field: string; reason: string; link?: IntakeLink }[];
  message?: string | null;
};
export type ProfileEvaluation = {
  dataset_version: string;
  passed: boolean;
  overall: number | null;
  failures: string[];
  fields: Record<string, { expected: number; hit: number; wrong: number; missing: number; accuracy: number | null }>;
  by_tag: Record<string, number>;
  security: { injection_cases: number; injection_failures: unknown[]; secret_cases: number; secret_failures: unknown[] };
  latency_ms_p95: number | null;
  cases: number;
  errors: { case: string; error: string }[];
  regressions: { field: string; before: number; after: number }[];
  at: string;
};
export type IntakeProfileView = {
  id: string;
  kind: IntakeKind;
  model: string;
  vision_model: string | null;
  prompt_version: string;
  status: "candidate" | "active" | "retired";
  created_by: string;
  created_at: string;
  activated_by: string | null;
  activated_at: string | null;
  exception_reason: string | null;
  evaluation: ProfileEvaluation | null;
  current_dataset: string;
};
export type ProfilesView = {
  profiles: IntakeProfileView[];
  gates: Record<string, unknown>;
  prompt_version: string;
  datasets: Record<IntakeKind, { version: string; cases: number }>;
};

/** A multipart POST with the session's headers. */
async function upload<T>(path: string, fields: Record<string, string | File | undefined>): Promise<T> {
  const session = await loadSession();
  if (!session) throw new Error("Not signed in");
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined) form.append(k, v);
  const resp = await fetch(`${session.baseUrl}${path}`, { method: "POST", headers: authHeaders(session), body: form });
  const data = await resp.json();
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data as T;
}

/** A folder's files, each sent with its path in the folder (the browser's folder picker gives it), or one .zip. */
async function uploadFolder<T>(path: string, files: File[], fields: Record<string, string> = {}): Promise<T> {
  const session = await loadSession();
  if (!session) throw new Error("Not signed in");
  const form = new FormData();
  for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  const resp = await fetch(`${session.baseUrl}${path}`, { method: "POST", headers: authHeaders(session), body: form });
  const data = await resp.json();
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data as T;
}

export interface WebFolderPreview {
  files: number;
  pages: { path: string; title: string; pictures: number; chars: number; links_to: string[] }[];
  unused: string[];
}
export interface WebFolderImported {
  documents: { uid: string; code: string; title: string; path: string; pictures: number; suggested: string[] }[];
  attached_to_first: string[];
  suggestions_failed: string[];
}

/** A web page saved as a folder (an HTML file and its pictures), imported as documents: one per page. */
export const webImportApi = {
  preview: (files: File[]) => uploadFolder<WebFolderPreview>("/v1/documents/import-web/preview", files),
  run: (files: File[], fields: { pages: string[]; document_type_uid?: string; confidentiality: string;
                                 authority_level: string; relate_asset?: string; suggest?: boolean }) =>
    uploadFolder<WebFolderImported>("/v1/documents/import-web", files, {
      pages: JSON.stringify(fields.pages), document_type_uid: fields.document_type_uid ?? "",
      confidentiality: fields.confidentiality, authority_level: fields.authority_level,
      relate_asset: fields.relate_asset ?? "", suggest: fields.suggest ? "true" : "false" }),
};

export const intakeApi = {
  guide: (kind: IntakeKind, draft: Record<string, unknown>) =>
    request<GuideResult>(`/v1/intake/guide/${kind}`, { method: "POST", body: json({ draft }) }),
  assist: (kind: IntakeKind, text: string, draft: Record<string, unknown>) =>
    request<AssistResult>(`/v1/intake/assist/${kind}`, { method: "POST", body: json({ text, draft }) }),
  /** A file's whole text (PDF, Word, Excel, e-mail, text), to keep as a document's body or to rework: nothing is
   * stored and no model reads it. */
  extract: (file: File) =>
    upload<{ text: string; format: string; truncated: boolean; filename: string | null }>("/v1/intake/extract", { file }),
  /** A file: a nameplate photo (assets), a datasheet, a Word or Excel file, an email. */
  assistFile: async (kind: IntakeKind, file: File, text: string, draft: Record<string, unknown>): Promise<AssistResult> =>
    upload<AssistResult>(`/v1/intake/assist/${kind}/file`, { file, text, draft: JSON.stringify(draft) }),
  /** What a file or a note says about an existing asset, as proposals for its owner. */
  propose: (assetUid: string, input: { file?: File; text?: string }) =>
    upload<ProposeResult>(`/v1/intake/propose/asset/${assetUid}`, { file: input.file, text: input.text ?? "" }),
  decide: (claimId: string, action: "confirm" | "edit" | "reject", value?: unknown, reason?: string) =>
    request<{ action: string }>(`/v1/intake/proposals/${claimId}`, {
      method: "POST",
      body: json({ action, value, reason }),
    }),
  status: () => request<Record<IntakeKind, { profile_id: string; model: string; passed: boolean | null; exception: string | null } | null>>(
    "/v1/intake/status"),
  profiles: () => request<ProfilesView>("/v1/intake/profiles"),
  createProfile: (input: { kind: IntakeKind; model: string; vision_model?: string }) =>
    request<IntakeProfileView>("/v1/intake/profiles", { method: "POST", body: json(input) }),
  evaluateProfile: (id: string) => request<ProfileEvaluation>(`/v1/intake/profiles/${id}/evaluate`, { method: "POST" }),
  activateProfile: (id: string, reason: string, exception?: string) =>
    request<IntakeProfileView>(`/v1/intake/profiles/${id}/activate`, { method: "POST", body: json({ reason, exception }) }),
  retireProfile: (id: string, reason: string) =>
    request<IntakeProfileView>(`/v1/intake/profiles/${id}/retire`, { method: "POST", body: json({ reason }) }),
  outcome: (runId: string, recordUid: string, final: Record<string, unknown>) =>
    request<{ counts: Record<string, number> }>(`/v1/intake/runs/${runId}/outcome`, {
      method: "POST",
      body: json({ record_uid: recordUid, final }),
    }),
};

/** Universal links shared with the field client (asset-model-revision §24.7). */
export const linksApi = {
  resolve: (path: string) =>
    request<{ kind: string; uid: string; web_path: string; name?: string; key?: string }>(
      `/v1/links/resolve?path=${encodeURIComponent(path)}`),
};

export const aiApi = {
  getConfig: () => request<LLMConfig | null>("/v1/ai/config"),
  saveConfig: (input: LLMConfigInput) =>
    request<LLMConfig>("/v1/ai/config", { method: "PUT", body: json(input) }),
  deleteConfig: () => request<void>("/v1/ai/config", { method: "DELETE" }),
  check: () => request<LLMCheckResult>("/v1/ai/config/check", { method: "POST" }),
  /** The installation's settings (Administration → AI): what every workspace without its own uses. */
  getInstallationConfig: () => request<LLMConfig | null>("/v1/admin/ai/config"),
  saveInstallationConfig: (input: LLMConfigInput) =>
    request<LLMConfig>("/v1/admin/ai/config", { method: "PUT", body: json(input) }),
  deleteInstallationConfig: () => request<void>("/v1/admin/ai/config", { method: "DELETE" }),
  checkInstallationConfig: () => request<LLMCheckResult>("/v1/admin/ai/config/check", { method: "POST" }),
  /** What the application asks before offering an AI action. */
  status: () => request<AIStatus>("/v1/ai/status"),

  suggestDocumentTypes: (onlyUntyped: boolean, limit: number) =>
    request<SuggestRunResult>("/v1/ai/suggest/document-types", {
      method: "POST",
      body: json({ only_untyped: onlyUntyped, limit }),
    }),
  suggestions: (status = "proposed") =>
    request<AISuggestion[]>(`/v1/ai/suggestions?status=${status}`),
  accept: (ids: number[]) =>
    request<{ applied: number; skipped: number[] }>("/v1/ai/suggestions/accept", {
      method: "POST",
      body: json({ ids }),
    }),
  draftDocument: (input: {
    title: string;
    document_type_uid?: string | null;
    notes?: string;
  }) => request<DraftDocumentResult>("/v1/ai/draft-document", {
    method: "POST",
    body: json(input),
  }),
  reviewDocument: (input: {
    title: string;
    document_type_uid?: string | null;
    body_markdown: string;
  }) => request<ReviewDocumentResult>("/v1/ai/review-document", {
    method: "POST",
    body: json(input),
  }),
  draftTicket: (input: { title: string; description: string }) =>
    request<DraftTicketResult>("/v1/ai/draft-ticket", {
      method: "POST",
      body: json(input),
    }),

  /** What is in this photograph, as a draft for the new-object form. */
  identifyObject: async (file: File): Promise<PhotoIdentification> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${session.baseUrl}/v1/ai/identify-object`, {
      method: "POST",
      headers: authHeaders(session),
      body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data as PhotoIdentification;
  },

  /** A question answered from this workspace's records, with its working. */
  ask: (question: string) =>
    request<AskResult>("/v1/ai/ask", { method: "POST", body: json({ question }) }),
  knowledge: () => request<KnowledgeStatus>("/v1/ai/knowledge"),
  reindexKnowledge: () => request<{ started: boolean }>("/v1/ai/knowledge/reindex", { method: "POST" }),
  conversations: () => request<AskConversation[]>("/v1/ai/conversations"),
  conversation: (id: string) => request<AskConversationDetail>(`/v1/ai/conversations/${encodeURIComponent(id)}`),
  /** Rate one of the conversation's answers (the `answerIndex`-th, from 0), once; kept anonymously. */
  rateAnswer: (id: string, answerIndex: number, rating: "up" | "down", comment?: string) =>
    request<AskFeedbackResult>(`/v1/ai/conversations/${encodeURIComponent(id)}/feedback`, {
      method: "POST", body: json({ answer_index: answerIndex, rating, comment: comment || null }),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/v1/ai/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** Changes the assistant proposed in a conversation; nothing changes until they are applied. */
  conversationActions: (id: string) =>
    request<AskAction[]>(`/v1/ai/conversations/${encodeURIComponent(id)}/actions`),
  applyActions: (id: string, ids: string[]) =>
    request<AskAction[]>(`/v1/ai/conversations/${encodeURIComponent(id)}/actions/apply`, {
      method: "POST", body: json({ ids }),
    }),
  discardActions: (id: string, ids: string[]) =>
    request<AskAction[]>(`/v1/ai/conversations/${encodeURIComponent(id)}/actions/discard`, {
      method: "POST", body: json({ ids }),
    }),

  reject: (ids: number[]) =>
    request<{ rejected: number; skipped: number[] }>("/v1/ai/suggestions/reject", {
      method: "POST",
      body: json({ ids }),
    }),
};

/** The unified knowledge layer: one object's whole context, one search across
 * assets, tickets and documents, and the operations cockpit. */
export const hubApi = {
  search: (q: string, limit = 8) =>
    request<HubSearchResult>(`/v1/hub/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  overview: () => request<HubOverview>("/v1/hub/overview"),
  assetContext: (uid: string) => request<AssetContext>(`/v1/hub/assets/${uid}/context`),
  ticketContext: (uid: string) => request<TicketContext>(`/v1/hub/tickets/${uid}/context`),
  documentContext: (uid: string) => request<DocumentContext>(`/v1/hub/documents/${uid}/context`),
};

type Ref = { uid: string; key: string };
/** What converting one old Serial Line into a path and a Bus Segment would build (§9.1, §12.4). */
export type SerialLineProposal = {
  line: Ref & { name: string };
  access_point: Ref | null;
  access_points: Ref[];
  converter: Ref | null;
  implements_access_point: boolean;
  paths: { ioc: Ref; devices: string[] }[];
  devices: Ref[];
  required_port: { tcp_port: number } | null;
  questions: string[];
  ready: boolean;
};

/** The fact ledger: review queue, provenance, decisions and installation
 * history. Every change here is a decision recorded in the audit ledger. */
export interface ControlBindingReport {
  proposed: number;
  by_tag: number;
  by_host: number;
  already_bound: number;
  ambiguous: { device: string; uid: string; candidates: { uid: string; name: string; type: string }[] }[];
  unmatched: { device: string; uid: string }[];
}

export interface ControlBindingProposal {
  claim_id: string;
  subject: { uid: string; name: string; type: string };
  predicate: string;
  target: { uid: string; name: string; type: string } | null;
  rule: string;
  confidence: number | null;
  evidence: Record<string, unknown> | null;
}

export const controlBindingApi = {
  propose: () => request<ControlBindingReport>("/v1/ledger/control-bindings/propose", { method: "POST" }),
  list: () => request<ControlBindingProposal[]>("/v1/ledger/control-bindings"),
  decide: (input: { claim_ids?: string[]; accept: boolean; min_confidence?: number; reason?: string }) =>
    request<{ decided: number }>("/v1/ledger/control-bindings/decide", { method: "POST", body: json(input) }),
};

export const ledgerApi = {
  review: () => request<ReviewQueue>("/v1/ledger/review"),
  queues: () => request<QueueDashboard>("/v1/ledger/review/queues"),
  ledgerOnly: () =>
    request<{ enabled: boolean; legacy: { ok: boolean; blocked: string[]; mixed_open: string[]; unplanned: number } }>(
      "/v1/ledger/ledger-only"),
  registry: () =>
    request<{ mode: string; total: number; unexplained: number; counts: Record<string, number>;
              violations: { id: string; rule: string; relation: string | null; from: string | null; to: string | null;
                            record?: string; message: string; explained_by: string | null }[] }>("/v1/ledger/registry/report"),
  acceptViolation: (violation_id: string, reason: string) =>
    request<{ decision_id: string }>("/v1/ledger/registry/exceptions", { method: "POST", body: json({ violation_id, reason }) }),
  setRegistryMode: (mode: "warn" | "enforce", reason: string) =>
    request<{ mode: string }>("/v1/ledger/registry/mode", { method: "PUT", body: json({ mode, reason }) }),
  serialLines: () => request<{ lines: SerialLineProposal[] }>("/v1/ledger/serial-lines"),
  convertSerialLine: (uid: string, body: { reason: string; access_point_uid?: string; accept_golden_loss?: string }) =>
    request<{ paths: { uid: string; key: string; devices: number }[]; removed: unknown[];
              golden: { ok: boolean | null; lost?: { incident: string; cause: string }[] } }>(
      `/v1/ledger/serial-lines/${encodeURIComponent(uid)}/convert`, { method: "POST", body: json(body) }),
  setLedgerOnly: (enabled: boolean, reason: string) =>
    request<{ enabled: boolean }>("/v1/ledger/ledger-only", { method: "PUT", body: json({ enabled, reason }) }),
  escalateReview: () =>
    request<{ backup: number; governance: number; without_recipient: number }>("/v1/ledger/review/escalate", { method: "POST" }),
  facts: (uid: string) => request<RecordFacts>(`/v1/ledger/records/${uid}/facts`),
  decide: (batch: LedgerDecision[]) =>
    request<{ decisions: string[] }>("/v1/ledger/decisions", { method: "POST", body: json({ batch }) }),
  edit: (uid: string, input: { predicate: string; value?: unknown; member?: unknown; present?: boolean; reason?: string }) =>
    request<{ ok: boolean }>(`/v1/ledger/records/${uid}/edit`, { method: "POST", body: json(input) }),
  approveRevision: (revisionId: string) =>
    request<{ state: string }>(`/v1/ledger/revisions/${revisionId}/approve`, { method: "POST" }),
  rejectRevision: (revisionId: string) =>
    request<{ state: string }>(`/v1/ledger/revisions/${revisionId}/reject`, { method: "POST" }),
  installations: (query: { position_uid?: string; asset_uid?: string; at?: string }) => {
    const q = new URLSearchParams(Object.entries(query).filter(([, v]) => v) as [string, string][]);
    return request<InstallationView[]>(`/v1/installations?${q.toString()}`);
  },
  confirmInstallation: (uid: string, validFrom?: TemporalValue) =>
    request<{ ok: boolean }>(`/v1/installations/${uid}/confirm`, {
      method: "POST",
      body: json(validFrom ? { valid_from: validFrom } : {}),
    }),
  rejectInstallation: (uid: string) =>
    request<{ ok: boolean }>(`/v1/installations/${uid}/reject`, { method: "POST" }),
  swap: (input: { position_uid: string; new_asset_uid: string; at: string; precision?: string; reason?: string }) =>
    request<{ ended: string[]; installation_uid: string }>("/v1/installations/swap", {
      method: "POST",
      body: json(input),
    }),
  accessPoint: (uid: string) =>
    request<{ access_point: AccessPointView; address_history: AccessPointView[] }>(`/v1/access-points/${uid}`),
  whoUsed: (address: string, at: string) =>
    request<{ access_points: AccessPointView[]; used_by: AddressUse[] }>(
      `/v1/access-points?${new URLSearchParams({ address, at }).toString()}`,
    ),
  reassign: (uid: string, input: { position_uid: string; at: TemporalValue }) =>
    request<AccessPointView>(`/v1/access-points/${uid}/reassign`, { method: "POST", body: json(input) }),
  segmentPort: (uid: string) => request<SegmentPort>(`/v1/ledger/segments/${uid}/port`),
  confirmPortMap: (uid: string, input: { installation_uid: string; port_uid: string }) =>
    request<SegmentPort>(`/v1/ledger/segments/${uid}/port-map`, { method: "POST", body: json(input) }),
  ticketLinks: (ticketUid: string) => request<TicketLinkView[]>(`/v1/ledger/tickets/${ticketUid}/links`),
  recordTickets: (uid: string) => request<RecordTickets>(`/v1/ledger/records/${uid}/tickets`),
  rules: () => request<{ rules: RuleEntry[]; check: string[] }>("/v1/ledger/rules"),
  streams: () => request<{ id: string; kind: string; frozen_at: string | null }[]>("/v1/ledger/streams"),
  merge: (input: { survivor_uid: string; loser_uid: string; reason?: string }) =>
    request<{ decision_id: string }>("/v1/ledger/identity/merge", { method: "POST", body: json(input) }),
  dismissCandidate: (input: { records: string[]; kind: "reject_candidate" | "confirm_new"; reason?: string }) =>
    request<{ decision_id: string }>("/v1/ledger/identity/dismiss", { method: "POST", body: json(input) }),
  lookup: (identifier: string) => request<LookupHit>(`/v1/lookup/${encodeURIComponent(identifier)}`),
};

export const equipmentApi = {
  get: (uid: string) => request<EquipmentState>(`/v1/equipment/${uid}`),
  setLifecycle: (uid: string, state: string, reason?: string) =>
    request<unknown>(`/v1/equipment/${uid}/lifecycle`, { method: "POST", body: json({ state, reason }) }),
  setCustody: (uid: string, custodian: string, reason?: string) =>
    request<ValueHistory>(`/v1/equipment/${uid}/custody`, { method: "POST", body: json({ custodian, reason }) }),
  positionSpares: (uid: string) =>
    request<{ basis: Record<string, string> | null; spares: SpareView[] }>(`/v1/equipment/positions/${uid}/spares`),
};

export const bulkApi = {
  list: () => request<BulkChangeView[]>("/v1/bulk-changes"),
  get: (id: string) => request<BulkChangeView>(`/v1/bulk-changes/${id}`),
  preview: (spec: Record<string, unknown>, description?: string) =>
    request<BulkChangeView>("/v1/bulk-changes", { method: "POST", body: json({ spec, description }) }),
  apply: (id: string) => request<BulkChangeView>(`/v1/bulk-changes/${id}/apply`, { method: "POST" }),
  approve: (id: string) => request<BulkChangeView>(`/v1/bulk-changes/${id}/approve`, { method: "POST" }),
  undo: (id: string) => request<BulkChangeView>(`/v1/bulk-changes/${id}/undo`, { method: "POST" }),
};

export const auditApi = {
  trail: (uid: string) => request<AuditEntry[]>(`/v1/ledger/records/${uid}/audit`),
  digests: () => request<AuditDigestView[]>("/v1/ledger/audit/digests"),
  verify: () => request<{ ok: boolean; day?: string; reason?: string; days?: number; head?: string }>("/v1/ledger/audit/verify"),
  seal: () => request<{ day: string; digest: string }>("/v1/ledger/audit/seal", { method: "POST" }),
  unmerge: (merge_decision_id: string, reason?: string) =>
    request<{ decision_id: string }>("/v1/ledger/identity/unmerge", { method: "POST", body: json({ merge_decision_id, reason }) }),
};

export const workflowApi = {
  transitions: (uid: string) => request<TicketTransitions>(`/v1/issues/${uid}/transitions`),
  transition: (uid: string, input: { to: string; comment?: string; resolution?: string; assignee?: string }) =>
    request<Issue>(`/v1/issues/${uid}/transition`, { method: "POST", body: json(input) }),
  watchers: (uid: string) => request<string[]>(`/v1/issues/${uid}/watchers`),
  watch: (uid: string, user?: string) =>
    request<string[]>(`/v1/issues/${uid}/watchers`, { method: "POST", body: json(user ? { user } : {}) }),
  unwatch: (uid: string, user: string) =>
    request<void>(`/v1/issues/${uid}/watchers/${encodeURIComponent(user)}`, { method: "DELETE" }),
  list: () => request<{ workflows: WorkflowDef[]; builtin: WorkflowDef; default: string | null }>("/v1/workflows"),
  create: (def: Omit<WorkflowDef, "uid">) => request<WorkflowDef>("/v1/workflows", { method: "POST", body: json(def) }),
  importJira: (definition: unknown, is_default = false) =>
    request<WorkflowDef>("/v1/workflows/import-jira", { method: "POST", body: json({ definition, is_default }) }),
  bind: (uid: string, schema_uid: string) =>
    request<{ ok: boolean }>(`/v1/workflows/${uid}/bind`, { method: "POST", body: json({ schema_uid }) }),
  rehearsal: (uid: string) => request<Rehearsal>(`/v1/workflows/${uid}/rehearsal`),
  escalate: () => request<{ escalated: number }>("/v1/workflows/escalate", { method: "POST" }),
  /** The latest hundred, read or not, from every workspace the person can open. */
  notifications: () => request<NotificationView[]>("/v1/notifications/everywhere?include_read=true"),
  readNotification: (id: number) =>
    request<{ ok: boolean }>(`/v1/notifications/everywhere/${id}/read`, { method: "POST" }),
  readAll: () => request<{ ok: boolean }>("/v1/notifications/everywhere/read-all", { method: "POST" }),
  /** Following a piece of equipment ("asset") or a document: each change to it becomes a notification. */
  following: (subject: "asset" | "document", uid: string) =>
    request<FollowState>(`/v1/notifications/following/${subject}/${encodeURIComponent(uid)}`),
  follow: (subject: "asset" | "document", uid: string, on: boolean) =>
    request<FollowState>(`/v1/notifications/following/${subject}/${encodeURIComponent(uid)}`,
                         { method: on ? "PUT" : "DELETE" }),
  emailPreferences: () => request<EmailPreferences>("/v1/notifications/preferences"),
  setEmailPreferences: (body: Pick<EmailPreferences, "email" | "muted">) =>
    request<EmailPreferences>("/v1/notifications/preferences", { method: "PUT", body: json(body) }),
  testEmail: () => request<{ sent_to: string }>("/v1/notifications/preferences/test", { method: "POST" }),
  subscriptions: () => request<WorkspaceSubscription[]>("/v1/notifications/subscriptions"),
  subscribe: (s: WorkspaceSubscription) =>
    request<WorkspaceSubscription>(`/v1/notifications/subscriptions/${encodeURIComponent(s.workspace_id)}`, {
      method: "PUT", body: json({ tickets: s.tickets, documents: s.documents, assets: s.assets }) }),
};

export const accessReviewsApi = {
  templates: () => request<RoleTemplate[]>("/v1/access-reviews/templates"),
  installTemplates: () => request<{ added: string[] }>("/v1/access-reviews/templates", { method: "POST" }),
  list: () => request<AccessReviewView[]>("/v1/access-reviews"),
  get: (id: string) => request<AccessReviewView>(`/v1/access-reviews/${id}`),
  create: (required_signers = 2) =>
    request<AccessReviewView>("/v1/access-reviews", { method: "POST", body: json({ required_signers }) }),
  sign: (id: string, input: { signer?: string; comment?: string }) =>
    request<AccessReviewView>(`/v1/access-reviews/${id}/sign`, { method: "POST", body: json(input) }),
};

export const legacyMigrationApi = {
  list: () => request<MigrationPlanView[]>("/v1/migration/plans"),
  get: (id: string) => request<MigrationPlanView>(`/v1/migration/plans/${id}`),
  plan: (inventory_workspace_id?: string) =>
    request<MigrationPlanView>("/v1/migration/plans", { method: "POST", body: json({ inventory_workspace_id }) }),
  override: (id: string, item: number, outcome: string, reason: string) =>
    request<MigrationRow>(`/v1/migration/plans/${id}/items/${item}/override`, { method: "POST", body: json({ outcome, reason }) }),
  apply: (id: string) => request<MigrationPlanView>(`/v1/migration/plans/${id}/apply`, { method: "POST" }),
  rollback: (id: string) => request<MigrationPlanView>(`/v1/migration/plans/${id}/rollback`, { method: "POST", body: json({}) }),
  finalize: (id: string, golden_waiver?: string) =>
    request<MigrationPlanView>(`/v1/migration/plans/${id}/finalize`, { method: "POST", body: json({ golden_waiver }) }),
  golden: () => request<GoldenIncident[]>("/v1/migration/golden-incidents"),
  addGolden: (input: { name: string; symptoms: string[]; expected_causes: string[]; symptom_kind?: Record<string, string> }) =>
    request<GoldenIncident>("/v1/migration/golden-incidents", { method: "POST", body: json(input) }),
  removeGolden: (id: string) => request<void>(`/v1/migration/golden-incidents/${id}`, { method: "DELETE" }),
  runGolden: () => request<GoldenRun>("/v1/migration/golden-incidents/run", { method: "POST" }),
  verify: (id: string) => request<MigrationPlanView>(`/v1/migration/plans/${id}/verify`, { method: "POST" }),
  gate: () => request<{ ok: boolean; blocked: string[]; mixed_open: string[]; unplanned: number }>("/v1/migration/gate"),
  /** The decision report as CSV (§12.5), as a download URL. */
  reportUrl: async (id: string): Promise<string> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}/v1/migration/plans/${id}/report.csv`, { headers: authHeaders(session) });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return URL.createObjectURL(await resp.blob());
  },
};

export interface CatalogueTypeAttribute {
  key: string;
  name: string;
  type: string;
  origin: string;
  required: boolean;
  multi: boolean;
  unique: boolean;
  options: string[];
  refers_to: string | null;
  relation: string | null;
}

export interface CatalogueType {
  uid: string;
  name: string;
  description: string | null;
  parent: string | null;
  path: string[];
  branch: string;
  abstract: boolean;
  shared: boolean;
  owner_workspace: string;
  is_global: boolean;
  icon_uid: string | null;
  aliases: string[];
  attributes: CatalogueTypeAttribute[];
  records: number;
  records_with_subtypes: number;
}

export interface TypeCatalogueView {
  types: CatalogueType[];
  equipment_classes: { name: string; status: string; promoted_type: string | null; note: string | null }[];
  branches: string[];
}

export const typeCatalogueApi = {
  get: () => request<TypeCatalogueView>("/v1/catalogue/types"),
};

export const catalogueApi = {
  classes: () => request<EquipmentClassView[]>("/v1/catalogue/equipment-classes"),
  addClass: (name: string, note?: string) =>
    request<EquipmentClassView>("/v1/catalogue/equipment-classes", { method: "POST", body: json({ name, note }) }),
  requestAttribute: (class_name: string, attribute: string, reason?: string) =>
    request<{ id: number }>("/v1/catalogue/equipment-classes/requests", { method: "POST", body: json({ class_name, attribute, reason }) }),
  report: () => request<EquipmentClassReport>("/v1/catalogue/equipment-classes/report"),
  reviews: () => request<ClassReview[]>("/v1/catalogue/equipment-classes/reviews"),
  runThresholds: () => request<ClassReview[]>("/v1/catalogue/equipment-classes/reviews/run", { method: "POST" }),
  openReview: (class_name: string, reason: string) =>
    request<ClassReview>("/v1/catalogue/equipment-classes/reviews", { method: "POST", body: json({ class_name, reason }) }),
  decline: (id: number, reason: string) =>
    request<ClassReview>(`/v1/catalogue/equipment-classes/reviews/${id}/decline`, { method: "POST", body: json({ reason }) }),
  promote: (class_name: string, type_name: string, reason: string) =>
    request<{ type: string; retyped: number }>("/v1/catalogue/equipment-classes/promote", {
      method: "POST",
      body: json({ class_name, type_name, reason }),
    }),
};

/** One trigger of §5.1 and the extensions declared for it (§13 S8). */
export type ExtensionTrigger = {
  trigger: string;
  label: string;
  extensions: {
    id: string; owner: string; source: string; summary: string;
    query: { name: string; question: string } | null;
    types: { name: string; parent: string }[];
    relations: { name: string; layer: string; flows: string; carries: string | null }[];
    problems: string[];
    fixture?: { ok: boolean; rows: number; error?: string };
    admitted: { decision_id: string; by: string; at: string; reason: string } | null;
  }[];
};

export const extensionsApi = {
  list: (runFixtures = false) =>
    request<{ triggers: ExtensionTrigger[] }>(`/v1/catalogue/extensions${runFixtures ? "?run_fixtures=true" : ""}`),
  admit: (id: string, reason: string) =>
    request<{ extension: string; types: string[]; decision_id: string }>(
      `/v1/catalogue/extensions/${encodeURIComponent(id)}/admit`, { method: "POST", body: json({ reason }) }),
};

export const retirementApi = {
  status: () => request<RetirementStatus>("/v1/retirement"),
  recordRetention: (input: { reference: string; jira_archive_until: string; exports_until?: string; audit_until?: string; note?: string }) =>
    request<{ decision_id: string }>("/v1/retirement/retention", { method: "POST", body: json(input) }),
  sign: (attestations: Record<string, boolean>, reason?: string) =>
    request<RetirementStatus>("/v1/retirement/sign", { method: "POST", body: json({ attestations, reason }) }),
};

export const domainsApi = {
  list: () => request<DomainView[]>("/v1/domains"),
  get: (id: string) => request<DomainDetail>(`/v1/domains/${encodeURIComponent(id)}`),
  create: (input: { id: string; name: string; resource: string; stream_ids: string[]; pilot: boolean; archive_url?: string }) =>
    request<DomainView>("/v1/domains", { method: "POST", body: json(input) }),
  stage: (id: string, stage: string) =>
    request<DomainView>(`/v1/domains/${encodeURIComponent(id)}/stage`, { method: "POST", body: json({ stage }) }),
  freeze: (id: string, watermark: unknown, manifest: unknown, attestations: Record<string, boolean> = {},
           waivers: Record<string, string> = {}) =>
    request<DomainView>(`/v1/domains/${encodeURIComponent(id)}/freeze`, {
      method: "POST",
      body: json({ watermark, manifest, attestations, waivers }),
    }),
  setStewards: (id: string, steward: string, backup: string) =>
    request<DomainView>(`/v1/domains/${encodeURIComponent(id)}/stewards`, { method: "PUT", body: json({ steward, backup }) }),
  reconcile: (id: string, manifest: unknown) =>
    request<ReconciliationBody & { id: string }>(`/v1/domains/${encodeURIComponent(id)}/reconcile`, {
      method: "POST",
      body: json({ manifest }),
    }),
  explain: (id: string, difference: string, reason: string) =>
    request<{ decision_id: string }>(`/v1/domains/${encodeURIComponent(id)}/explain`, {
      method: "POST",
      body: json({ difference, reason }),
    }),
  reversionExport: (id: string) =>
    request<Record<string, unknown> & { sha256: string }>(`/v1/domains/${encodeURIComponent(id)}/reversion-export`, {
      method: "POST",
    }),
  revert: (id: string, reason: string) =>
    request<DomainView>(`/v1/domains/${encodeURIComponent(id)}/revert`, { method: "POST", body: json({ reason }) }),
  exit: (id: string, attestations: Record<string, boolean>) =>
    request<DomainView>(`/v1/domains/${encodeURIComponent(id)}/exit`, { method: "POST", body: json({ attestations }) }),
};

/** A chat turn as it is worked out: each server-sent event is handed to `onEvent` as it arrives. Resolves
 * when the turn ends; rejects with an ApiError when the request is refused before it starts. */
export async function streamChat(
  body: { question: string; conversation_id?: string | null },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const session = await loadSession();
  if (!session) throw new Error("Not signed in");
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  headers.set("Authorization", `Bearer ${session.token}`);
  if (session.workspaceId) headers.set("X-Workspace-Id", session.workspaceId);
  const resp = await fetch(`${session.baseUrl}/v1/ai/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text();
    throw new ApiError(resp.status, text ? JSON.parse(text) : undefined);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data:")) onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
      }
    }
  }
}

/** The beam model (docs/beam-model.md): read-only views for the viewer page. */
export const beamModelApi = {
  models: () => request<BeamModelSummary[]>("/v1/beam-model/models"),
  /** In the format it was imported in, or `format` "1"/"2" (the editor asks for "1"; the hub keeps v2 extras). */
  exportModel: (id: string, format?: "1" | "2") =>
    request<CanonicalBeamModel>(`/v1/beam-model/models/${encodeURIComponent(id)}/export${format ? `?format=${format}` : ""}`),
  exportAll: () => request<{ format: string; models: CanonicalBeamModel[] }>("/v1/beam-model/export"),
  /** The whole model out of the workspace: its records retire (history kept), values, documents and bindings go. */
  removeModel: (id: string) =>
    request<{ model: string; retired: number; values: number; documents: number; bindings: number }>(
      `/v1/beam-model/models/${encodeURIComponent(id)}`, { method: "DELETE" }),
  validate: (doc: unknown) =>
    request<{ models: BeamModelCheck[] }>("/v1/beam-model/validate", { method: "POST", body: json(doc) }),
  importModels: (doc: unknown) =>
    request<BeamImportReport | { models: BeamImportReport[] }>("/v1/beam-model/import", { method: "POST", body: json(doc) }),
  schema: () => request<Record<string, unknown>>("/v1/beam-model/schema"),
  vocabulary: () => request<BeamVocabulary>("/v1/beam-model/vocabulary"),
  upgrade: (doc: unknown) => request<BeamModelV2>("/v1/beam-model/upgrade", { method: "POST", body: json(doc) }),
  exportV2: (id: string) => request<BeamModelV2>(`/v1/beam-model/models/${encodeURIComponent(id)}/export?format=2`),
  formats: () => request<{ name: string; label: string; extensions: string[] }[]>("/v1/beam-model/formats"),
  convert: (filename: string, content: string, options: Record<string, unknown> = {}, converter?: string) =>
    request<{ model: CanonicalBeamModel; report: BeamConversionReport; check: BeamModelCheck }>("/v1/beam-model/convert",
      { method: "POST", body: json({ filename, content, options, converter }) }),
  systems: () => request<BeamSystem[]>("/v1/beam-systems"),
  pathGraph: (uid: string, dataset?: string | null) =>
    request<BeamPathGraph>(`/v1/beam-paths/${encodeURIComponent(uid)}/graph${dataset ? `?dataset=${encodeURIComponent(dataset)}` : ""}`),
  datasets: (path: string) => request<BeamRecord[]>(`/v1/model-datasets?path=${encodeURIComponent(path)}`),
  context: (uid: string, dataset?: string | null) =>
    request<BeamElementContext>(`/v1/beam-elements/${encodeURIComponent(uid)}/context${dataset ? `?dataset=${encodeURIComponent(dataset)}` : ""}`),
  // Beamline asset synchronization (docs/beam-asset-sync.md)
  syncStatus: (model: string, filter?: string | null) =>
    request<AssetSyncStatus>(`/v1/beam-models/${encodeURIComponent(model)}/asset-sync/status${filter ? `?filter=${encodeURIComponent(filter)}` : ""}`),
  syncApply: (model: string, body: AssetSyncApply) =>
    request<AssetSyncApplied>(`/v1/beam-models/${encodeURIComponent(model)}/asset-sync/apply`, { method: "POST", body: json(body) }),
  assetBindings: (model: string, status?: string) =>
    request<AssetBinding[]>(`/v1/beam-models/${encodeURIComponent(model)}/asset-bindings${status ? `?status=${status}` : ""}`),
};

const P = "/v1/portability";

/** Portable exports and imports (docs/export-import-design.md §14). */
export const portabilityApi = {
  config: () => request<PortabilityConfig>(`${P}/config`),
  schedules: () => request<PortabilitySchedule[]>(`${P}/schedules`),
  createSchedule: (body: { export_id: string; every_minutes: number; chain: "incremental" | "complete";
                           skip_unchanged: boolean; confirm?: boolean }) =>
    request<PortabilitySchedule>(`${P}/schedules`, { method: "POST", body: json(body) }),
  changeSchedule: (id: string, body: { enabled?: boolean; every_minutes?: number; chain?: "incremental" | "complete";
                                       skip_unchanged?: boolean }) =>
    request<PortabilitySchedule>(`${P}/schedules/${encodeURIComponent(id)}`, { method: "PUT", body: json(body) }),
  removeSchedule: (id: string) =>
    request<void>(`${P}/schedules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runSchedule: (id: string) =>
    request<{ job: PortabilityJob }>(`${P}/schedules/${encodeURIComponent(id)}/run`, { method: "POST" }),
  setup: () => request<PortabilitySetup>(`${P}/setup`),
  addRepository: (body: { name: string; url: string; provider?: string | null; token?: string | null }) =>
    request<SetupRepository>(`${P}/setup/repositories`, { method: "POST", body: json({ ...body, confirm: true }) }),
  updateRepository: (name: string, body: { url?: string; provider?: string }) =>
    request<SetupRepository>(`${P}/setup/repositories/${encodeURIComponent(name)}`,
      { method: "POST", body: json({ ...body, confirm: true }) }),
  addStore: (name: string, note: string) =>
    request<{ name: string }>(`${P}/setup/stores`, { method: "POST", body: json({ name, note, confirm: true }) }),
  removeStore: (name: string) =>
    request<void>(`${P}/setup/stores/${encodeURIComponent(name)}/remove`, { method: "POST", body: json({ confirm: true }) }),
  noteTrustedKey: (id: string, note: string) =>
    request<{ note: string | null }>(`${P}/setup/trusted-keys/${encodeURIComponent(id)}/note`,
      { method: "POST", body: json({ note, confirm: true }) }),
  readHostKeys: (name: string) =>
    request<SetupRepository>(`${P}/setup/repositories/${encodeURIComponent(name)}/host-keys/read`, { method: "POST" }),
  confirmHostKeys: (name: string, fingerprints: string[]) =>
    request<SetupRepository>(`${P}/setup/repositories/${encodeURIComponent(name)}/host-keys/confirm`,
      { method: "POST", body: json({ fingerprints, confirm: true }) }),
  replaceToken: (name: string, token: string) =>
    request<SetupRepository>(`${P}/setup/repositories/${encodeURIComponent(name)}/token`,
      { method: "POST", body: json({ token, confirm: true }) }),
  testRepository: (name: string, write: boolean) =>
    request<SetupRepository>(`${P}/setup/repositories/${encodeURIComponent(name)}/test`,
      { method: "POST", body: json({ write }) }),
  removeRepository: (name: string) =>
    request<void>(`${P}/setup/repositories/${encodeURIComponent(name)}/remove`,
      { method: "POST", body: json({ confirm: true }) }),
  addTrustedKey: (line: string, note: string) =>
    request<{ id: string }>(`${P}/setup/trusted-keys`, { method: "POST", body: json({ line, note, confirm: true }) }),
  removeTrustedKey: (id: string) =>
    request<void>(`${P}/setup/trusted-keys/${encodeURIComponent(id)}/remove`,
      { method: "POST", body: json({ confirm: true }) }),
  generateSigningKey: (principal: string) =>
    request<{ public_line: string }>(`${P}/setup/signing-key`, { method: "POST", body: json({ principal, confirm: true }) }),
  approveSetup: (kind: "repository" | "trusted_key" | "signing_key" | "store", id: string) =>
    request<{ status: string }>(`${P}/setup/approve`, { method: "POST", body: json({ kind, id, confirm: true }) }),
  exports: () => request<ExportView[]>(`${P}/exports`),
  getExport: (id: string) => request<ExportView>(`${P}/exports/${encodeURIComponent(id)}`),
  createExport: (body: {
    mode: string; workspaces: string[]; classifications: string[]; repository: string | null;
    artifact_store: string | null; decisions?: Record<string, string>; base_export_id?: string | null;
    identity_profile?: string | null; purpose?: string | null; recipients?: string[];
  }) => request<ExportView>(`${P}/exports`, { method: "POST", body: json(body) }),
  decideExport: (id: string, decisions: Record<string, string>) =>
    request<ExportView>(`${P}/exports/${encodeURIComponent(id)}/decisions`, { method: "POST", body: json({ decisions }) }),
  exportStep: (id: string, step: "approve" | "generate" | "publish-git", opts: { confirm?: boolean } = {}) =>
    request<ExportView>(`${P}/exports/${encodeURIComponent(id)}/${step}`, {
      method: "POST", body: json({ confirm: !!opts.confirm }) }),
  /** A long step as a background job: returns the job to poll. */
  exportJob: (id: string, step: "generate" | "publish-git", opts: { confirm?: boolean } = {}) =>
    request<{ job: PortabilityJob }>(`${P}/exports/${encodeURIComponent(id)}/${step}?background=true`, {
      method: "POST", body: json({ confirm: !!opts.confirm }) }),
  legalHold: (kind: "exports" | "imports", id: string, on: boolean, reason: string) =>
    request<ExportView & ImportView>(`${P}/${kind}/${encodeURIComponent(id)}/legal-hold`, {
      method: "POST", body: json({ on, reason }) }),
  job: (id: string) => request<PortabilityJob>(`${P}/jobs/${encodeURIComponent(id)}`),
  jobs: (subject: string) => request<PortabilityJob[]>(`${P}/jobs?subject=${encodeURIComponent(subject)}`),
  revokeExport: (id: string, reason: string) =>
    request<ExportView>(`${P}/exports/${encodeURIComponent(id)}/revoke`, { method: "POST", body: json({ reason }) }),
  manifest: (id: string) =>
    request<{ manifest: ArchiveManifest; sha256: string }>(`${P}/exports/${encodeURIComponent(id)}/manifest`),
  /** The checkpoint as a tar, fetched with the person's own credentials: no capability in a URL. */
  downloadArchive: async (id: string): Promise<Blob> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}${P}/exports/${encodeURIComponent(id)}/archive`, {
      headers: authHeaders(session), cache: "no-store", referrerPolicy: "no-referrer" });
    if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => undefined));
    return resp.blob();
  },
  imports: () => request<ImportView[]>(`${P}/imports`),
  getImport: (id: string) => request<ImportView>(`${P}/imports/${encodeURIComponent(id)}`),
  createImport: (body: { mode: string; repository: string | null; ref: string | null; expected_commit?: string | null;
                         decisions?: Record<string, unknown> }) =>
    request<ImportView>(`${P}/imports`, { method: "POST", body: json(body) }),
  importStep: (id: string, step: "fetch-git" | "verify" | "approve" | "execute" | "resume" | "finalize",
               opts: { acknowledge_uninspected?: boolean } = {}) =>
    request<ImportView>(`${P}/imports/${encodeURIComponent(id)}/${step}`, {
      method: "POST", ...(step === "approve" ? { body: json({ acknowledge_uninspected: !!opts.acknowledge_uninspected }) } : {}) }),
  importJob: (id: string, step: "fetch-git" | "verify" | "execute" | "resume" | "finalize") =>
    request<{ job: PortabilityJob }>(`${P}/imports/${encodeURIComponent(id)}/${step}?background=true`, { method: "POST" }),
  discardImport: (id: string, reason: string) =>
    request<ImportView>(`${P}/imports/${encodeURIComponent(id)}/discard`, { method: "POST", body: json({ reason }) }),
  originChain: (id: string) => request<OriginChainCheck>(`${P}/imports/${encodeURIComponent(id)}/origin-chain`),
  evidenceFamilies: (id: string) =>
    request<{ family: string; visible_rows: number }[]>(`${P}/imports/${encodeURIComponent(id)}/evidence`),
  /** The dry run as a background job the page follows, with its progress. */
  dryRunJob: (id: string, decisions?: Record<string, unknown>) =>
    request<{ job: PortabilityJob }>(`${P}/imports/${encodeURIComponent(id)}/dry-run?background=true`, {
      method: "POST", body: json({ decisions: decisions ?? {} }) }),
  dryRun: (id: string, decisions?: Record<string, unknown>) =>
    request<ImportView>(`${P}/imports/${encodeURIComponent(id)}/dry-run`, {
      method: "POST", body: json({ decisions: decisions ?? {} }) }),
  upload: async (id: string, file: File): Promise<ImportView> => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportView>(`${P}/imports/${encodeURIComponent(id)}/upload`, { method: "POST", body: form });
  },
  reconciliation: (id: string) =>
    request<{ report: ReconciliationReport; sha256: string }>(`${P}/imports/${encodeURIComponent(id)}/reconciliation`),
  provenance: (id: string) => request<ProvenanceView>(`${P}/imports/${encodeURIComponent(id)}/provenance`),
  evidence: (id: string, family: string, offset = 0, limit = 50) =>
    request<{ family: string; total: number; offset: number; rows: { key: string; row: Record<string, unknown> }[] }>(
      `${P}/imports/${encodeURIComponent(id)}/evidence/${encodeURIComponent(family)}?offset=${offset}&limit=${limit}`),
};

/** The person-readable message of a portability error (the API's problem shape). */
export function problemText(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as { problem?: { error?: string; code?: string }; detail?: unknown } | undefined;
    const p = body?.problem;
    if (p?.error) return p.code && p.code !== "invalid" ? `${p.error} (${p.code})` : p.error;
    if (typeof body?.detail === "string") return body.detail;
    return `Request failed (${e.status})`;
  }
  return e instanceof Error ? e.message : String(e);
}

// --------------------------------------------------------------------------- who am I, and API tokens

export type TokenScope = "read" | "create" | "modify" | "delete" | "approve" | "admin";
export type TokenResource = "objects" | "tickets" | "documents";

export interface ApiTokenInfo {
  id: number;
  kind: "personal" | "robot";
  name: string | null;
  prefix: string | null;
  workspace_id: string | null;
  user_id: string | null;
  owner_email: string | null;
  scopes: TokenScope[];
  resources: TokenResource[];
  restricted_grants: string[];
  created_by: string | null;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  status: "active" | "expired" | "revoked";
}

export interface ApiTokenCreated extends ApiTokenInfo {
  /** Shown this once: it is never stored. */
  token: string;
}

export interface ApiTokenInput {
  name: string;
  scopes: TokenScope[];
  resources?: TokenResource[];
  workspace_id?: string | null;
  expires_in_days: number | null;
  restricted_grants?: string[];
}

export interface MyProfile {
  auth_type: "oidc" | "personal_token" | "robot_token";
  user: {
    id: string; email: string; name: string | null; username: string | null; is_admin: boolean;
    acting_as_admin: boolean; source: string; active: boolean; directory_dn: string | null;
    oidc_subject: string | null; created_at: string; last_login_at: string | null; synced_at: string | null;
  } | null;
  session: {
    issuer?: string | null; subject?: string | null; client?: string | null; auth_time?: number | null;
    expires?: number | null; identity_provider?: string | null; scopes?: string | null; realm_roles?: string[];
    workspace_id?: string;
  };
  token: ApiTokenInfo | null;
  groups: { uid: string; name: string; source: string; email: string | null; member_since: string | null }[];
  workspaces: {
    id: string; name: string; is_global: boolean;
    roles: { id: string; name: string; via: string }[];
    permissions: Record<string, string[]>;
  }[];
  counts: { personal_tokens?: number; devices?: number };
}

export const tokensApi = {
  profile: () => request<MyProfile>("/v1/me/profile"),
  mine: () => request<ApiTokenInfo[]>("/v1/me/tokens"),
  makeMine: (input: ApiTokenInput) =>
    request<ApiTokenCreated>("/v1/me/tokens", { method: "POST", body: json(input) }),
  revokeMine: (id: number) => request<void>(`/v1/me/tokens/${id}`, { method: "DELETE" }),
  robots: (ws: string) => request<ApiTokenInfo[]>(`/v1/workspaces/${encodeURIComponent(ws)}/robot-tokens`),
  makeRobot: (ws: string, input: ApiTokenInput) =>
    request<ApiTokenCreated>(`/v1/workspaces/${encodeURIComponent(ws)}/robot-tokens`, {
      method: "POST", body: json(input),
    }),
  revokeRobot: (ws: string, id: number) =>
    request<void>(`/v1/workspaces/${encodeURIComponent(ws)}/robot-tokens/${id}`, { method: "DELETE" }),
  all: () => request<ApiTokenInfo[]>("/v1/admin/tokens"),
  revokeAny: (id: number) => request<void>(`/v1/admin/tokens/${id}`, { method: "DELETE" }),
};

/** The API's address, for the examples a page shows. */
export async function apiBaseUrl(): Promise<string> {
  return (await loadSession())?.baseUrl ?? "";
}

export const metaApi = {
  /** Which release the API is running (public, no sign-in needed). */
  version: () =>
    request<{ version: string; commit: string | null; built_at: string | null; api_version: string }>(
      "/v1/meta/version"),
};

/** Advanced query (backend services/jql.py). */
export type JqlEntity = "tickets" | "assets" | "documents";

export interface JqlItem {
  uid: string;
  key?: string;
  code?: string;
  name?: string;
  title?: string;
  type?: string;
  state?: string | null;
  priority?: string | null;
  source_key?: string | null;
  workspace_id?: string;
  workspace_name?: string;
  updated_at?: string | null;
}

export interface JqlResult {
  entity: JqlEntity;
  jql: string;
  total: number;
  capped: boolean;
  offset: number;
  items: JqlItem[];
}

export interface JqlField {
  field: string;
  kind: string;
  help: string;
  orderable: boolean;
}

/** A query that cannot be read: what went wrong, and where in it (0-based). */
export class JqlError extends Error {
  detail: { error?: string; position?: number | null };
  constructor(detail: { error?: string; position?: number | null }) {
    super(detail.error ?? "The query cannot be read");
    this.detail = detail;
  }
}

export const jqlApi = {
  search: async (entity: JqlEntity, jql: string, limit = 50, offset = 0): Promise<JqlResult> => {
    const qs = new URLSearchParams({ entity, jql, limit: String(limit), offset: String(offset) });
    try {
      return await request<JqlResult>(`/v1/search/jql?${qs}`);
    } catch (e) {
      const detail = e instanceof ApiError && e.status === 422 ? (e.body as { detail?: unknown })?.detail : null;
      if (detail && typeof detail === "object") throw new JqlError(detail as JqlError["detail"]);
      throw e;
    }
  },
  fields: () => request<Record<JqlEntity, JqlField[]>>("/v1/search/jql/fields"),
};

/** Template packages: what the installation ships, and what a workspace uses (backend app/packages). */
export interface PackageInfo {
  id: string;
  version: string;
  name: string;
  description: string;
  owner: string;
  depends: Record<string, string>;
  provides: string[];
  checksum: string;
  contents: Record<string, number>;
  installable?: boolean;
  problems?: string[];
  requested?: boolean;
}

export interface WorkspacePackageRow {
  package_id: string;
  name: string;
  version: string;
  checksum: string;
  options: Record<string, string> | null;
  installed_at: string | null;
  installed_by: string | null;
  shipped_version: string | null;
  upgrade_available: boolean;
}

export interface PackageHistoryRow {
  package_id: string;
  action: string;
  from_version: string | null;
  to_version: string;
  checksum: string;
  actor: string | null;
  at: string | null;
  result: Record<string, unknown> | null;
}

export interface PackagePlan {
  workspace_id: string;
  options: Record<string, string>;
  changes: boolean;
  steps: { package_id: string; version: string; checksum: string; action: string; from_version: string | null; requested: boolean;
           result: Record<string, unknown> }[];
}

export interface PackagesInput {
  packages: string[];
  catalogue_workspace_id?: string;
  scope?: string;
  /** An upgrade's migration plan: for each breaking change, "apply" or "keep". */
  decisions?: Record<string, "apply" | "keep">;
}

export interface PackageChange {
  id: string;
  category: "additive" | "definition" | "breaking";
  area: string;
  subject: string;
  element: string | null;
  what: string;
  detail: string;
  conflict: string | null;
  records: number;
  violations: number;
  actions: ("apply" | "keep")[];
}

export const packagesApi = {
  list: () => request<PackageInfo[]>("/v1/packages"),
  resolve: (packages: string[]) =>
    request<PackageInfo[]>("/v1/packages/resolve", { method: "POST", body: json({ packages }) }),
  ofWorkspace: (workspaceId: string) =>
    request<{ workspace_id: string; packages: WorkspacePackageRow[]; history: PackageHistoryRow[] }>(
      `/v1/workspaces/${workspaceId}/packages`),
  preview: (workspaceId: string, input: PackagesInput) =>
    request<PackagePlan>(`/v1/workspaces/${workspaceId}/packages/preview`, { method: "POST", body: json(input) }),
  install: (workspaceId: string, input: PackagesInput) =>
    request<PackagePlan>(`/v1/workspaces/${workspaceId}/packages/install`, { method: "POST", body: json(input) }),
  /** What a new workspace made from these packages would get, worked out and rolled back (administrators). */
  previewNew: (input: PackagesInput) =>
    request<PackagePlan>("/v1/packages/preview", { method: "POST", body: json(input) }),
  capabilities: (workspaceId: string) =>
    request<WorkspaceCapabilities>(`/v1/workspaces/${workspaceId}/capabilities`),
};

/** What a workspace's packages let it do: which pages to show. */
export interface WorkspaceCapabilities {
  workspace_id: string;
  packages: string[];
  provides: string[];
  features: {
    tickets: boolean;
    documents: boolean;
    equipment: boolean;
    records: boolean;
    map: boolean;
    beam_model: boolean;
    control_system: boolean;
    type_catalogue: boolean;
  };
  map_layers: { id: string; name: string; description?: string }[];
  ticket_kinds: string[];
  document_kinds: string[];
  importers: string[];
}

/** GLPI connections (backend app/integrations/glpi, routers/glpi). */
export interface GlpiEntityMapEntry {
  entity_id: number | string;
  entity?: string;
  workspace_id: string;
  recursive: boolean;
}

export interface GlpiConnection {
  uid: string;
  name: string;
  workspace_id: string;
  base_url: string;
  verify_tls: boolean;
  key_prefix: string;
  documents: boolean;
  tickets: boolean;
  has_credentials: boolean;
  entity_map: GlpiEntityMapEntry[];
  authority: { records: "argus" | "glpi"; tickets: "argus" | "glpi" };
  discovery: GlpiDiscovery | null;
  schema_status: string | null;
  last_digest: string | null;
  last_run_at: string | null;
  last_import_job_uid: string | null;
  schema?: GlpiSchemaState | null;
}

export interface GlpiDiscovery {
  instance: string;
  read_at: string;
  version: string | null;
  major: number | null;
  api: { legacy: boolean; high_level: string | null; notes: string[] };
  entities: { id: number; name: string; completename: string; entities_id: number | null; records: number }[];
  itemtypes: Record<string, { count: number; status: string; maps_to: string | null; why?: string }>;
  custom_assets: { system_name: string; label: string; itemtype: string; active: boolean; records: number }[];
  custom_fields: { system_name: string; label: string; glpi_type: string; kind: string | null; note: string | null }[];
  plugin_fields: { container: string; itemtypes: string[]; name: string; label: string; kind: string | null;
                   note: string | null }[];
  generic_types: { itemtype: string; name: string }[];
  plugins: { directory: string; name: string; version: string; state: number }[];
  capabilities: Record<string, unknown>;
}

export interface GlpiProposedField {
  source: string;
  label: string;
  glpi_type: string;
  kind: string | null;
  argus_key: string;
  action: "create" | "reuse" | "unsupported" | "conflict";
  note: string | null;
  options?: { id: string; value: string }[];
}

export interface GlpiSchemaProposal {
  digest: string;
  types: { source: string; system_name: string; label: string; action: "create" | "reuse"; argus_type: string;
           parent: string | null; fields: GlpiProposedField[] }[];
  extensions: (GlpiProposedField & { on_itemtype: string; argus_type: string; container: string })[];
  unsupported: (Partial<GlpiProposedField> & { on: string })[];
  changes: number;
}

export interface GlpiSchemaState {
  proposal?: GlpiSchemaProposal;
  approved?: { digest: string; at: string; by: string };
  status?: string;
  history?: { digest: string; at: string; by: string; changes: number }[];
}

export interface GlpiWorkspacePlan {
  missing_packages: string[];
  creates: { ref: string; key: string; type: string; name: string }[];
  updates: { ref: string; key: string; type: string; name: string; fields: string[] }[];
  unchanged: number;
  conflicts: { ref: string; key: string; field: string; argus: unknown; glpi: unknown; previously: unknown;
               outcome: string }[];
  local_edits_kept: { ref: string; key: string; fields: string[] }[];
  retirement_candidates: { ref: string; key: string; name: string; reason: string }[];
  types_missing: { ref: string; type: string }[];
  locations: number;
  tickets: { creates: number; updates: number; unchanged: number;
             conflicts: { ref: string; field: string; argus: unknown; glpi: unknown; outcome: string }[] };
  documents: number;
}

export interface GlpiPlan {
  instance: string;
  version: string | null;
  schema_status: string;
  outside_entity_map: number;
  awaiting_schema_review: { itemtype: string; records: number }[];
  unsupported: unknown[];
  workspaces: Record<string, GlpiWorkspacePlan>;
  digest: string;
  job_uid?: string;
}

export interface GlpiConnectionInput {
  name: string;
  base_url: string;
  user_token?: string;
  app_token?: string;
  verify_tls: boolean;
  key_prefix: string;
  documents: boolean;
  tickets: boolean;
}

const glpiHeaders = (workspaceId: string) => ({ "X-Workspace-Id": workspaceId });

export const glpiApi = {
  list: (ws: string) => request<GlpiConnection[]>("/v1/glpi/connections", { headers: glpiHeaders(ws) }),
  get: (ws: string, uid: string) => request<GlpiConnection>(`/v1/glpi/connections/${uid}`, { headers: glpiHeaders(ws) }),
  create: (ws: string, input: GlpiConnectionInput) =>
    request<GlpiConnection>("/v1/glpi/connections", { method: "POST", body: json(input), headers: glpiHeaders(ws) }),
  update: (ws: string, uid: string, input: GlpiConnectionInput) =>
    request<GlpiConnection>(`/v1/glpi/connections/${uid}`, { method: "PUT", body: json(input), headers: glpiHeaders(ws) }),
  remove: (ws: string, uid: string) =>
    request<void>(`/v1/glpi/connections/${uid}`, { method: "DELETE", headers: glpiHeaders(ws) }),
  discover: (ws: string, uid: string) =>
    request<{ discovery: GlpiDiscovery; entity_map: GlpiEntityMapEntry[]; schema: GlpiSchemaState }>(
      `/v1/glpi/connections/${uid}/discover`, { method: "POST", headers: glpiHeaders(ws) }),
  setEntityMap: (ws: string, uid: string, entity_map: GlpiEntityMapEntry[]) =>
    request<GlpiConnection>(`/v1/glpi/connections/${uid}/entity-map`,
      { method: "PUT", body: json({ entity_map }), headers: glpiHeaders(ws) }),
  setAuthority: (ws: string, uid: string, records: string, tickets: string) =>
    request<GlpiConnection>(`/v1/glpi/connections/${uid}/authority`,
      { method: "PUT", body: json({ records, tickets }), headers: glpiHeaders(ws) }),
  approveSchema: (ws: string, uid: string, digest: string) =>
    request<GlpiSchemaState>(`/v1/glpi/connections/${uid}/schema/approve`,
      { method: "POST", body: json({ digest }), headers: glpiHeaders(ws) }),
  preview: (ws: string, uid: string) =>
    request<GlpiPlan>(`/v1/glpi/connections/${uid}/preview`, { method: "POST", headers: glpiHeaders(ws) }),
  run: (ws: string, uid: string, expect_digest?: string) =>
    request<GlpiPlan>(`/v1/glpi/connections/${uid}/run`,
      { method: "POST", body: json({ expect_digest }), headers: glpiHeaders(ws) }),
  candidates: (ws: string, uid: string) =>
    request<{ ref: string; uid: string; key: string; name: string; type: string; reason: string }[]>(
      `/v1/glpi/connections/${uid}/retirement-candidates`, { headers: glpiHeaders(ws) }),
  decide: (ws: string, uid: string, ref: string, decision: "retire" | "keep", reason?: string) =>
    request<unknown>(`/v1/glpi/connections/${uid}/retirement-candidates`,
      { method: "POST", body: json({ ref, decision, reason }), headers: glpiHeaders(ws) }),
};

/** Places: approved locations, field observations and their review, the map (backend services/spatial). */
export type GeoGeometry =
  | { type: "Point"; coordinates: [number, number] }
  | { type: "LineString"; coordinates: [number, number][] }
  | { type: "MultiLineString"; coordinates: [number, number][][] }
  | { type: "Polygon"; coordinates: [number, number][][] }
  | { type: "MultiPolygon"; coordinates: [number, number][][][] };

/** A location's role: a point, a line (cable, pipe, beamline) or an area (building, hall, room, zone). */
export type PlaceRole = "position" | "route" | "outline";

export interface PlacedFeature {
  uid: string;
  role: PlaceRole;
  geometry_type: string;
  geometry: GeoGeometry;
  /** A point's; null for a route or an outline. */
  latitude: number | null;
  longitude: number | null;
  /** An outline's heights, in metres: with them it is a volume. */
  base_m: number | null;
  top_m: number | null;
  length_m?: number;
  area_m2?: number;
  perimeter_m?: number;
  accuracy_m: number | null;
  source: string;
  valid_from: string | null;
  valid_until: string | null;
  state: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  reviewer: string | null;
  note: string | null;
}

export interface LocationObservation {
  id: number;
  subject_uid: string;
  latitude: number;
  longitude: number;
  accuracy_m: number | null;
  observed_at: string | null;
  observed_by: string | null;
  status: "consistent" | "pending" | "accepted" | "rejected";
  distance_m: number | null;
  decided_by: string | null;
  note: string | null;
  record?: { uid: string; key: string; name: string; type: string };
  approved?: PlacedFeature | null;
}

export interface AssetLocationView {
  uid: string;
  locatable: boolean;
  map_layer: string | null;
  hidden: boolean;
  location: PlacedFeature | null;
  route: PlacedFeature | null;
  outline: PlacedFeature | null;
  history: PlacedFeature[];
  observations: LocationObservation[];
}

export interface PlaceNeighbour {
  uid: string; key: string; name: string; type: string; workspace_id: string; role: PlaceRole;
  distance_m?: number; base_m?: number | null; top_m?: number | null;
}

/** What a record's location says about the others (backend spatial.context). */
export interface PlaceContext {
  uid: string; along_m: number;
  inside: PlaceNeighbour[]; crossing: PlaceNeighbour[]; along: PlaceNeighbour[]; within: PlaceNeighbour[];
}

export interface MapFeature {
  type: "Feature";
  id: string;
  geometry: GeoGeometry;
  properties: { uid: string; key: string; name: string; type: string; workspace_id: string; status: string;
                map_layer: string | null; role: PlaceRole; base_m: number | null; top_m: number | null;
                accuracy_m: number | null; source: string; distance_m?: number };
}

export interface MapFilters {
  workspaces?: string[];
  types?: string[];
  status?: string[];
}

function mapQuery(filters: MapFilters): string {
  const q = new URLSearchParams();
  if (filters.workspaces?.length) q.set("workspaces", filters.workspaces.join(","));
  if (filters.types?.length) q.set("types", filters.types.join(","));
  if (filters.status?.length) q.set("status", filters.status.join(","));
  return q.toString();
}

/** Indoors: a place's floors and floor plans, a plan placed on the map, records placed inside (backend indoor). */
export interface PlaceLevel {
  uid: string; place_uid: string; name: string; ordinal: number; elevation_m: number | null; height_m: number | null;
}
export interface ControlPoint { x: number; y: number; longitude: number; latitude: number }
export interface FloorPlanView {
  uid: string; name: string; place: { uid: string; name: string | null }; level: PlaceLevel | null;
  width_px: number; height_px: number; mime_type: string; source_kind: string; source_filename: string | null;
  control_points: ControlPoint[]; transform: Record<string, number> | null; residual_m: number | null;
  /** [longitude, latitude] of the top-left, top-right, bottom-right, bottom-left corners, once placed. */
  corners: [number, number][] | null;
  placed?: { uid: string; key: string; name: string; type: string; x: number; y: number; place_uid: string | null }[];
  residuals_m?: number[]; metres_per_px?: number; rotation_deg?: number;
}
export interface IndoorPlacementView {
  uid: string;
  place: { uid: string; key: string; name: string; type: string } | null;
  level: PlaceLevel | null;
  plan: { uid: string; name: string; width_px: number; height_px: number } | null;
  x: number | null; y: number | null; source: string; note: string | null; state: string;
  valid_from: string | null; valid_until: string | null; confirmed_by: string | null;
}
export interface IndoorView {
  uid: string; placement: IndoorPlacementView | null;
  in: { uid: string; key: string; name: string; type: string }[];
  contents: { uid: string; key: string; name: string; type: string; level_uid: string | null; plan_uid: string | null }[];
  history: IndoorPlacementView[];
}

export const indoorApi = {
  levels: (placeUid: string) => request<{ levels: PlaceLevel[]; plans: FloorPlanView[] }>(`/v1/assets/${placeUid}/levels`),
  addLevel: (placeUid: string, input: { name: string; ordinal: number; elevation_m?: number | null; height_m?: number | null }) =>
    request<PlaceLevel>(`/v1/assets/${placeUid}/levels`, { method: "POST", body: json(input) }),
  changeLevel: (uid: string, input: { name: string; ordinal: number; elevation_m?: number | null; height_m?: number | null }) =>
    request<PlaceLevel>(`/v1/levels/${uid}`, { method: "PATCH", body: json(input) }),
  removeLevel: (uid: string) => request<void>(`/v1/levels/${uid}`, { method: "DELETE" }),
  /** An image, an SVG, a PDF (its first page) or a DXF/DWG drawing. */
  addPlan: (placeUid: string, file: File, name: string, levelUid?: string | null) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    form.append("level_uid", levelUid ?? "");
    return request<FloorPlanView>(`/v1/assets/${placeUid}/plans`, { method: "POST", body: form });
  },
  plan: (uid: string) => request<FloorPlanView>(`/v1/plans/${uid}`),
  changePlan: (uid: string, input: { name?: string; level_uid?: string | null }) =>
    request<FloorPlanView>(`/v1/plans/${uid}`, { method: "PATCH", body: json(input) }),
  removePlan: (uid: string) => request<void>(`/v1/plans/${uid}`, { method: "DELETE" }),
  /** The plan's picture, fetched signed in, as a URL the page can show. */
  planImageUrl: async (uid: string): Promise<string> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}/v1/plans/${uid}/image`, { headers: authHeaders(session) });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return URL.createObjectURL(await resp.blob());
  },
  placePlan: (uid: string, points: ControlPoint[]) =>
    request<FloorPlanView>(`/v1/plans/${uid}/placement`, { method: "PUT", body: json({ points }) }),
  unplacePlan: (uid: string) => request<void>(`/v1/plans/${uid}/placement`, { method: "DELETE" }),
  indoors: (uid: string) => request<IndoorView>(`/v1/assets/${uid}/indoors`),
  setIndoors: (uid: string, input: { place_uid?: string | null; level_uid?: string | null; plan_uid?: string | null;
                                      x?: number | null; y?: number | null; note?: string | null }) =>
    request<IndoorPlacementView>(`/v1/assets/${uid}/indoors`, { method: "PUT", body: json(input) }),
  removeIndoors: (uid: string) => request<void>(`/v1/assets/${uid}/indoors`, { method: "DELETE" }),
  mapPlans: (bbox: [number, number, number, number]) =>
    request<FloorPlanView[]>(`/v1/map/plans?bbox=${bbox.map((n) => n.toFixed(6)).join(",")}`),
  /** Records whose key, name, label, serial… contains this (to choose the place something is in). */
  searchRecords: (q: string) => request<Asset[]>(`/v1/assets?q=${encodeURIComponent(q)}&sort=key&limit=20`),
};

export const placesApi = {
  location: (uid: string) => request<AssetLocationView>(`/v1/assets/${uid}/location`),
  setLocation: (uid: string, input: { latitude: number; longitude: number; accuracy_m?: number; note?: string }) =>
    request<PlacedFeature>(`/v1/assets/${uid}/location`, { method: "PUT", body: json(input) }),
  removeLocation: (uid: string) => request<void>(`/v1/assets/${uid}/location`, { method: "DELETE" }),
  /** A route (line) or an outline (area, with heights a volume), WGS 84 GeoJSON. */
  setShape: (uid: string, role: "route" | "outline", input: { geometry: GeoGeometry; base_m?: number | null;
                                                             top_m?: number | null; note?: string }) =>
    request<PlacedFeature>(`/v1/assets/${uid}/location/${role}`, { method: "PUT", body: json(input) }),
  removeShape: (uid: string, role: "route" | "outline") =>
    request<void>(`/v1/assets/${uid}/location/${role}`, { method: "DELETE" }),
  context: (uid: string, alongM = 5) => request<PlaceContext>(`/v1/assets/${uid}/location/context?along_m=${alongM}`),
  reviews: (status = "pending") => request<LocationObservation[]>(`/v1/location-reviews?status=${status}`),
  decide: (id: number, accept: boolean, note?: string) =>
    request<LocationObservation>(`/v1/location-reviews/${id}/${accept ? "accept" : "reject"}`,
                                 { method: "POST", body: json({ note }) }),
  features: (bbox: [number, number, number, number], filters: MapFilters) =>
    request<{ type: "FeatureCollection"; features: MapFeature[]; truncated: boolean }>(
      `/v1/map/features?bbox=${bbox.map((n) => n.toFixed(6)).join(",")}&${mapQuery(filters)}`),
  nearby: (latitude: number, longitude: number, radius: number, filters: MapFilters) =>
    request<{ type: "FeatureCollection"; features: MapFeature[] }>(
      `/v1/map/nearby?latitude=${latitude}&longitude=${longitude}&radius_m=${radius}&${mapQuery(filters)}`),
  layers: () => request<{ id: string; name: string; description?: string; package: string }[]>("/v1/map/layers"),
  /** A CSV or (Geo)JSON file of locations: dry_run says what would happen, row by row. */
  importLocations: (file: File, dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file);
    return request<LocationImport>(`/v1/locations/import?dry_run=${dryRun}`, { method: "POST", body: form });
  },
};

export interface LocationImport {
  dry_run: boolean;
  counts: { set: number; to_review: number; consistent: number; rejected: number };
  rows: { row: number; identifier: string; outcome: string; problem?: string; distance_m?: number;
          record?: { uid: string; key: string; name: string } }[];
}

/** The map's background: OpenStreetMap unless the installation names its own tile server. */
export const MAP_TILES = {
  url: import.meta.env.VITE_MAP_TILES_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: import.meta.env.VITE_MAP_TILES_ATTRIBUTION ||
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

// --- Spreadsheet import (backend services/spreadsheet_import.py) -------------------------------------

export const SHEET_NAME = "__name__";
export const SHEET_KEY = "__key__";
export const SHEET_DROP = "__drop__";
export const SHEET_NEW = "__new__";

export type SheetColumnProfile = {
  column: string;
  filled: number;
  distinct: number;
  samples: string[];
  kind: string;
  unique: boolean;
  options?: string[];
};
export type SheetNewProperty = { key: string; name: string; type: string; options?: string[] };
export type SheetColumnPlan = {
  column: string;
  target: string;
  new?: SheetNewProperty;
  source?: "rule" | "ai" | "person";
  confidence?: number;
  reason?: string;
};
export type SheetTarget =
  | { mode: "existing"; schema_uid: string; source?: string; confidence?: number; reason?: string }
  | { mode: "new"; name: string; parent_uid: string | null; source?: string; confidence?: number; reason?: string };
export type SheetPlan = { target: SheetTarget; columns: SheetColumnPlan[]; update_existing: boolean };
export type SheetProperty = {
  key: string;
  name: string;
  type: string;
  required: boolean;
  options: string[];
  reference: string | null;
};
export type SheetAnalysis = {
  file: { name: string; sheets: string[]; sheet: string | null; rows: number; title: string; digest: string };
  columns: SheetColumnProfile[];
  candidates: { uid: string; name: string; path: string; score: number; name_match: boolean; matched: string[]; own_workspace: boolean }[];
  parents: { uid: string; name: string; path: string; abstract: boolean }[];
  properties: SheetProperty[];
  plan: SheetPlan;
  ai: { used: boolean; reason?: string; model?: string };
};
export type SheetRowOutcome = {
  row: number;
  action: "create" | "update" | "unchanged" | "error";
  key: string | null;
  name: string | null;
  attributes: Record<string, unknown>;
  problems: string[];
};
export type SheetPreview = {
  type: { mode: string; name: string; uid: string | null; parent: string | null; new_properties: SheetProperty[] };
  counts: { create: number; update: number; unchanged: number; error: number };
  rows: SheetRowOutcome[];
  total_rows: number;
  digest: string;
};
export type SheetRun = { job_uid: string; type_uid: string; type: string; new_properties: string[]; rows: number };

export const spreadsheetImportApi = {
  analyse: (file: File, opts: { sheet?: string; useAi: boolean; target?: SheetTarget }) =>
    upload<SheetAnalysis>("/v1/spreadsheet-imports/analyse", {
      file,
      sheet: opts.sheet,
      use_ai: String(opts.useAi),
      target: opts.target ? JSON.stringify(opts.target) : undefined,
    }),
  preview: (file: File, sheet: string | undefined, plan: SheetPlan) =>
    upload<SheetPreview>("/v1/spreadsheet-imports/preview", { file, sheet, plan: JSON.stringify(plan) }),
  run: (file: File, sheet: string | undefined, plan: SheetPlan, digest: string) =>
    upload<SheetRun>("/v1/spreadsheet-imports/run", {
      file,
      sheet,
      plan: JSON.stringify(plan),
      expect_digest: digest,
    }),
};

/** How ARGUS is used, anonymously (administrators). */
export const statisticsApi = {
  get: (days: number, refreshStorage = false) =>
    request<Statistics>(`/v1/admin/statistics?days=${days}${refreshStorage ? "&refresh_storage=true" : ""}`),
};

/** Templates for documents reworked from raw text, and the rework itself. */
export const templatesApi = {
  list: (documentType?: string) =>
    request<TemplateListing[]>(`/v1/document-templates${documentType ? `?${new URLSearchParams({ document_type: documentType })}` : ""}`),
  resolve: (documentType: string, template?: string | null) =>
    request<TemplateChoice>(`/v1/document-templates/resolve?${new URLSearchParams({
      document_type: documentType, ...(template ? { template } : {}) })}`),
  official: (ref: string) => request<OfficialTemplate>(`/v1/document-templates/${encodeURIComponent(ref)}`),
  variant: (ref: string) => request<TemplateVariant>(`/v1/document-templates/${encodeURIComponent(ref)}`),
  validate: (source: string) =>
    request<{ valid: boolean; problems: TemplateProblem[]; template: TemplateDescription | null }>(
      "/v1/document-templates/validate", { method: "POST", body: json({ source }) }),
  create: (base: string, scope: "workspace" | "personal", name?: string) =>
    request<TemplateVariant>("/v1/document-templates", { method: "POST", body: json({ base, scope, name }) }),
  save: (ref: string, source: string) =>
    request<TemplateVariant>(`/v1/document-templates/${encodeURIComponent(ref)}`, { method: "PUT", body: json({ source }) }),
  publish: (ref: string, note?: string) =>
    request<TemplateVariant>(`/v1/document-templates/${encodeURIComponent(ref)}/publish`, {
      method: "POST", body: json({ note: note || null }) }),
  setActive: (ref: string, active: boolean) =>
    request<TemplateVariant>(`/v1/document-templates/${encodeURIComponent(ref)}/active`, {
      method: "PUT", body: json({ active }) }),
  compare: (ref: string) => request<TemplateComparison>(`/v1/document-templates/${encodeURIComponent(ref)}/compare`),
  rebase: (ref: string) =>
    request<TemplateVariant>(`/v1/document-templates/${encodeURIComponent(ref)}/rebase`, { method: "POST" }),
  archive: (ref: string) =>
    request<void>(`/v1/document-templates/${encodeURIComponent(ref)}`, { method: "DELETE" }),
};

export interface ReshapeRequest {
  source: ReshapeSource; document_type_uid: string; template?: string | null; template_source?: string | null;
  title?: string | null; confidentiality?: "pubblico" | "interno" | "riservato"; document_uid?: string | null;
}

export const reshapeApi = {
  /** The draft and what to check: nothing is saved. */
  preview: (body: ReshapeRequest) => request<ReshapeResult>("/v1/ai/reshape", { method: "POST", body: json(body) }),
  /** Save as a new document (draft) or as the next draft revision of `documentUid`. */
  save: (body: Record<string, unknown>, documentUid?: string | null) =>
    request<ReshapeSaved>(documentUid ? `/v1/documents/${encodeURIComponent(documentUid)}/reshape` : "/v1/documents/reshape",
                          { method: "POST", body: json(body) }),
  /** How the document's revisions were made from raw text. */
  generations: (documentUid: string) =>
    request<ReshapeGeneration[]>(`/v1/documents/${encodeURIComponent(documentUid)}/generations`),
};

/** An activity id in a URL path: an occurrence's `@` and `:` stay readable. */
const activityPath = (id: string) => encodeURIComponent(id).replace(/%40/g, "@").replace(/%3A/g, ":");

export const activitiesApi = {
  list: (params: Record<string, string | number | boolean | undefined>) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
    return request<ActivityPage>(`/v1/activities?${q}`);
  },
  get: (id: string) => request<Activity>(`/v1/activities/${activityPath(id)}`),
  create: (body: Record<string, unknown>) =>
    request<Activity>("/v1/activities", { method: "POST", body: json(body) }),
  change: (id: string, changes: Record<string, unknown>, scope: "this" | "future" | "series" = "this") =>
    request<Activity>(`/v1/activities/${activityPath(id)}?scope=${scope}`, { method: "PATCH", body: json(changes) }),
  act: (id: string, action: "start" | "complete" | "skip" | "cancel" | "reopen", body: Record<string, unknown> = {}) =>
    request<Activity>(`/v1/activities/${activityPath(id)}/${action}`, { method: "POST", body: json(body) }),
};

// ------------------------------------------------------------------ workspace bundles (instance administrators)

export interface BundleSummary {
  id?: string;
  name?: string;
  format_version?: number;
  created_at?: string;
  created_by?: string;
  source?: { instance?: string; argus_version?: string; schema_revision?: string } | null;
  workspace?: { id: string; name: string } | null;
  packages?: { id: string; version: string }[];
  rows: Record<string, number>;
  files: number;
  bytes: number;
  dependencies: { kind: string; detail: string }[];
  external_config: { what: string; detail: string }[];
  not_reproduced: { table: string; rows: number; reason: string }[];
  missing_files: { family: string; key: string; path?: string }[];
  demo?: WorkspaceTour | null;
  problems?: { kind: string; path?: string; detail: string }[];
  packages_status?: { id: string; version: string; status: string; detail: string | null }[];
}

export interface BundleReport {
  ok: boolean;
  blockers: { kind: string; detail: string }[];
  warnings: { kind?: string; family?: string; key?: string; detail: string }[];
  added: Record<string, number>;
  updated: Record<string, number>;
  renamed_count: number;
  people: Record<string, number | boolean>;
  packages: { id: string; version: string; status: string; detail: string | null }[];
  dependencies: { kind: string; detail: string }[];
  not_reproduced: { table: string; rows: number; reason: string }[];
  external_config: { what: string; detail: string }[];
  files: Record<string, number>;
}

export interface WorkspaceTour {
  title: string;
  organisation?: string;
  synthetic?: boolean;
  notice?: string;
  description?: string;
  steps: { title: string; text: string; link?: string }[];
}

const B = "/v1/admin/bundles";
export interface BundleApplyBody { workspace_id: string; name: string; people_access: boolean }

export const bundlesApi = {
  list: () => request<{ exports: BundleSummary[]; imports: BundleSummary[]; demos: BundleSummary[] }>(B),
  exportWorkspace: (workspace_id: string) =>
    request<BundleSummary>(`${B}/exports`, { method: "POST", body: json({ workspace_id }) }),
  /** The ZIP, fetched with the person's own credentials. */
  download: async (id: string): Promise<Blob> => {
    const session = await loadSession();
    if (!session) throw new Error("Not signed in");
    const resp = await fetch(`${session.baseUrl}${B}/exports/${encodeURIComponent(id)}/download`, {
      headers: authHeaders(session), cache: "no-store", referrerPolicy: "no-referrer" });
    if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => undefined));
    return resp.blob();
  },
  remove: (kind: "exports" | "imports", id: string) =>
    request<void>(`${B}/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BundleSummary>(`${B}/imports`, { method: "POST", body: form });
  },
  preview: (id: string, body: BundleApplyBody) =>
    request<BundleReport>(`${B}/imports/${encodeURIComponent(id)}/preview`, { method: "POST", body: json(body) }),
  apply: (id: string, body: BundleApplyBody) =>
    request<BundleReport>(`${B}/imports/${encodeURIComponent(id)}/apply`, { method: "POST", body: json(body) }),
  previewDemo: (name: string, body: BundleApplyBody) =>
    request<BundleReport>(`${B}/demos/${encodeURIComponent(name)}/preview`, { method: "POST", body: json(body) }),
  applyDemo: (name: string, body: BundleApplyBody) =>
    request<BundleReport>(`${B}/demos/${encodeURIComponent(name)}/apply`, { method: "POST", body: json(body) }),
  tour: (workspaceId: string) =>
    request<{ workspace_id: string; tour: WorkspaceTour | null }>(`/v1/workspaces/${encodeURIComponent(workspaceId)}/tour`),
};
