import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  assetsApi,
  attachmentsApi,
  globalValuesApi,
  documentsApi,
  issueLinksApi,
  issueSubresourcesApi,
  issuesApi,
  membersApi,
  schemasApi,
} from "../../api/client";
import { ApiError } from "../../api/client";
import { AttributeValue } from "../../components/AttributeValue";
import { TicketGraph } from "../../components/TicketGraph";
import { TicketPicker } from "../../components/TicketPicker";
import { AuthenticatedImage } from "../../components/AuthenticatedImage";
import { TransferItemAction } from "../../components/TransferItemAction";
import { effectiveAttributes } from "../../lib/schemaAttributes";
import { TicketContextPanel } from "../../components/hub/ContextPanels";
import { TicketWorkflowCard, WatchersCard } from "../../components/hub/WorkflowPanels";
import { ExportMenu } from "../../components/ExportMenu";
import { workflowApi } from "../../api/client";
import { SemanticRelated } from "../../components/SemanticRelated";

const STATE_STYLES: Record<string, string> = {
  new: "bg-slate-100 text-slate-600",
  in_progress: "bg-blue-100 text-blue-700",
  pending: "bg-amber-100 text-amber-700",
  resolved: "bg-green-100 text-green-700",
  closed: "bg-slate-200 text-slate-500",
};

const PRIORITY_STYLES: Record<string, string> = {
  blocker: "text-red-700",
  critical: "text-red-600",
  high: "text-orange-600",
  medium: "text-amber-600",
  low: "text-slate-500",
};

/** How a ticket-to-ticket edge reads from each end. "relates" and
 * "duplicates" mean the same thing both ways; the rest invert, and saying
 * "relates of" for a symmetric one is just wrong. */
const TICKET_RELATION_LABELS: Record<string, [string, string]> = {
  epic: ["in epic", "epic of"],
  parent: ["child of", "parent of"],
  blocks: ["blocks", "blocked by"],
  relates: ["relates to", "relates to"],
  duplicates: ["duplicates", "duplicated by"],
};

function ticketRelationLabel(relation: string, outgoing: boolean): string {
  const pair = TICKET_RELATION_LABELS[relation];
  if (!pair) return outgoing ? relation : `${relation} (inverse)`;
  return outgoing ? pair[0] : pair[1];
}

/** Fields the imported "Jira Issue" ticket type carries, grouped the way a
 * Jira issue view groups them — details on the left, people and dates on the
 * right — so a ticket imported from there reads the way it does at source. */
const DETAIL_KEYS = [
  "argus_category",
  "argus_impact",
  "argus_detected_by",
  "argus_system",
  "argus_subsystem",
  "argus_source_type",
  "argus_resolution",
  "argus_root_cause",
  "argus_corrective_action",
  "argus_affects_versions",
  "argus_fix_versions",
  "argus_components",
  "argus_environment",
  "argus_parent",
  "argus_epic",
  "argus_epic_name",
  "argus_sprint",
  "argus_story_points",
];
const PEOPLE_KEYS = ["argus_reporter", "argus_votes", "argus_watchers"];
const DATE_KEYS = [
  "argus_downtime_start",
  "argus_downtime_end",
  "argus_downtime_minutes",
  "argus_source_created",
  "argus_source_updated",
];
const HIDDEN_KEYS = [
  "argus_source",
  "argus_source_key",
  "argus_source_url",
  "argus_project",
  "argus_source_status",
];

async function downloadAttachment(uid: string, filename: string) {
  const url = await attachmentsApi.fetchBlobUrl(uid);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function Panel({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-1 py-1 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 text-slate-900">{children}</dd>
    </div>
  );
}

export function IssueDetail() {
  const { uid } = useParams<{ uid: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [commentAuthor, setCommentAuthor] = useState("web-user");
  const [commentBody, setCommentBody] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pasteHint, setPasteHint] = useState<string | null>(null);

  const issue = useQuery({
    queryKey: ["issues", uid],
    queryFn: () => issuesApi.get(uid!),
    enabled: !!uid,
  });
  const moves = useQuery({ queryKey: ["ticket-transitions", uid], queryFn: () => workflowApi.transitions(uid!),
                           enabled: !!uid });
  const comments = useQuery({
    queryKey: ["issue-comments", uid],
    queryFn: () => issuesApi.listComments(uid!),
    enabled: !!uid,
  });
  const asset = useQuery({
    queryKey: ["assets", issue.data?.asset_uid],
    queryFn: () => assetsApi.get(issue.data!.asset_uid!),
    enabled: !!issue.data?.asset_uid,
  });
  const schema = useQuery({
    queryKey: ["schemas", issue.data?.schema_uid],
    queryFn: () => schemasApi.get(issue.data!.schema_uid!),
    enabled: !!issue.data?.schema_uid,
  });
  const allSchemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const attrDefs = effectiveAttributes(schema.data, allSchemas.data);
  const allAssets = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.list(),
  });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  const globalValues = useQuery({ queryKey: ["global-values"], queryFn: globalValuesApi.list });
  const ticketGlobals = globalValues.data?.filter((gv) => gv.applies_to === "tickets") ?? [];
  const statusOptions = ticketGlobals.find((gv) => gv.key === "status")?.options ?? [];
  const priorityOptions = ticketGlobals.find((gv) => gv.key === "priority")?.options ?? [];

  const updateMutation = useMutation({
    mutationFn: (patch: { state?: string; priority?: string; assignee?: string | null }) =>
      issuesApi.update(uid!, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["issues", uid] });
      queryClient.invalidateQueries({ queryKey: ["ticket-transitions", uid] });
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    },
  });
  const addCommentMutation = useMutation({
    mutationFn: () => issuesApi.addComment(uid!, commentAuthor, commentBody),
    onSuccess: () => {
      setCommentBody("");
      queryClient.invalidateQueries({ queryKey: ["issue-comments", uid] });
    },
  });
  const attachments = useQuery({
    queryKey: ["issue-attachments", uid],
    queryFn: () => issueSubresourcesApi.attachments(uid!),
    enabled: !!uid,
  });
  const history = useQuery({
    queryKey: ["issue-history", uid],
    queryFn: () => issueSubresourcesApi.history(uid!),
    enabled: !!uid,
  });

  const links = useQuery({
    queryKey: ["issue-links", uid],
    queryFn: () => issueLinksApi.list(uid!),
    enabled: !!uid,
  });
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => documentsApi.list() });
  const allIssues = useQuery({ queryKey: ["issues"], queryFn: () => issuesApi.list() });
  const [ticketRelation, setTicketRelation] = useState("relates");
  const [showGraph, setShowGraph] = useState(false);

  const invalidateLinks = () => {
    queryClient.invalidateQueries({ queryKey: ["issue-links", uid] });
    queryClient.invalidateQueries({ queryKey: ["issue-history", uid] });
  };
  const linkAssetMutation = useMutation({
    mutationFn: (assetUid: string) => issueLinksApi.linkAsset(uid!, assetUid),
    onSuccess: invalidateLinks,
  });
  const unlinkAssetMutation = useMutation({
    mutationFn: (assetUid: string) => issueLinksApi.unlinkAsset(uid!, assetUid),
    onSuccess: invalidateLinks,
  });
  const linkTicketMutation = useMutation({
    mutationFn: (issueUid: string) => issueLinksApi.linkTicket(uid!, issueUid, ticketRelation),
    onSuccess: invalidateLinks,
  });
  const unlinkTicketMutation = useMutation({
    mutationFn: (linkId: number) => issueLinksApi.unlinkTicket(uid!, linkId),
    onSuccess: invalidateLinks,
  });
  const linkDocumentMutation = useMutation({
    mutationFn: (documentUid: string) => issueLinksApi.linkDocument(uid!, documentUid),
    onSuccess: invalidateLinks,
  });
  const unlinkDocumentMutation = useMutation({
    mutationFn: (relationId: number) => issueLinksApi.unlinkDocument(uid!, relationId),
    onSuccess: invalidateLinks,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => issueSubresourcesApi.uploadAttachment(uid!, file),
    onSuccess: () => {
      setPasteHint(null);
      queryClient.invalidateQueries({ queryKey: ["issue-attachments", uid] });
      queryClient.invalidateQueries({ queryKey: ["issue-history", uid] });
    },
  });
  const deleteAttachmentMutation = useMutation({
    mutationFn: attachmentsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["issue-attachments", uid] }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => issuesApi.delete(uid!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["issues"] });
      navigate("/tickets");
    },
  });

  if (issue.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!issue.data) return <p className="text-sm text-red-600">Ticket not found.</p>;

  const i = issue.data;
  const currentStatus = statusOptions.find((o) => o.id === i.state);
  // The quick status menu offers only moves the workflow allows without
  // extra input; the Workflow card handles the rest.
  const quickMoves = moves.data
    ? [
        { id: i.state, value: moves.data.state_name },
        ...moves.data.transitions.filter((t) => t.requires.length === 0).map((t) => ({ id: t.to, value: t.to_name })),
      ]
    : null;
  const assignedMember = members.data?.find((m) => m.user_id === i.assignee);
  const priorityLabel = priorityOptions.find((o) => o.id === i.priority)?.value ?? i.priority;
  const attr = (key: string) => i.attributes?.[key];
  const sourceKey = attr("argus_source_key") as string | undefined;
  const sourceUrl = attr("argus_source_url") as string | undefined;
  const sourceProject = attr("argus_project") as string | undefined;
  const sourceStatus = attr("argus_source_status") as string | undefined;

  // The fields come from the parent type ("Jira Issue"), not from the
  // child the ticket is an instance of ("Task") — saying otherwise sends
  // someone to the wrong type to edit them.
  const parentType = allSchemas.data?.find((s) => s.uid === schema.data?.parent_schema_uid);
  const byKey = new Map(attrDefs.map((a) => [a.key ?? a.name, a]));
  const renderAttr = (key: string) => {
    const def = byKey.get(key);
    if (!def) return null;
    const value = i.attributes?.[key];
    if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) return null;
    return (
      <FieldRow key={key} label={def.name}>
        <AttributeValue
          attribute={def}
          value={value}
          assets={allAssets.data}
          members={members.data}
        />
      </FieldRow>
    );
  };

  // Anything the type defines that isn't placed by hand above — a field a
  // project added to its own Bug type, say — still has to appear somewhere.
  const placed = new Set([...DETAIL_KEYS, ...PEOPLE_KEYS, ...DATE_KEYS, ...HIDDEN_KEYS]);
  const otherAttrs = attrDefs.filter((a) => !placed.has(a.key ?? a.name));

  return (
    <div>
      {showGraph && (
        <TicketGraph issueUid={i.uid} title={i.title} onClose={() => setShowGraph(false)} />
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-500">
            {sourceProject && <span>{sourceProject} / </span>}
            {sourceUrl && sourceKey ? (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="text-indigo-600 hover:underline"
              >
                {sourceKey}
              </a>
            ) : (
              sourceKey
            )}
          </p>
          <h1 className="mt-0.5 text-2xl font-semibold text-slate-900">{i.title}</h1>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <select
            value={i.state}
            onChange={(e) => updateMutation.mutate({ state: e.target.value })}
            title={
              currentStatus
                ? `${currentStatus.responsible ? `Responsible: ${currentStatus.responsible}. ` : ""}${currentStatus.meaning ?? ""}`
                : undefined
            }
            className={`rounded border-0 px-2 py-1 text-xs font-medium ${STATE_STYLES[i.state] ?? "bg-slate-100 text-slate-600"}`}
          >
            {quickMoves ? (
              quickMoves.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.value}
                </option>
              ))
            ) : statusOptions.length > 0 ? (
              statusOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.value}
                </option>
              ))
            ) : (
              <option value={i.state}>{i.state}</option>
            )}
          </select>
          <Link
            to={`/tickets/${i.uid}/edit`}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Edit
          </Link>
          <ExportMenu kind="ticket" uid={i.uid}
                      className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50" />
          <TransferItemAction
            kind="issue"
            uid={i.uid}
            buttonClassName="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          />
          <button
            onClick={() => {
              if (confirm("Delete this ticket?")) deleteMutation.mutate();
            }}
            className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>

      {sourceStatus && sourceStatus.toLowerCase() !== (currentStatus?.value ?? "").toLowerCase() && (
        <p className="mt-1 text-xs text-slate-400">
          Status at source: <span className="font-medium text-slate-500">{sourceStatus}</span>
        </p>
      )}
      {currentStatus?.meaning && (
        <p className="mt-1 text-xs text-slate-400">
          {currentStatus.meaning}
          {currentStatus.responsible && ` — responsible: ${currentStatus.responsible}`}
        </p>
      )}

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel title="Details">
            <dl>
              <FieldRow label="Priority">
                <span className={PRIORITY_STYLES[i.priority ?? ""] ?? "text-slate-900"}>
                  {priorityLabel ?? "—"}
                </span>
              </FieldRow>
              {DETAIL_KEYS.map(renderAttr)}
              {i.labels.length > 0 && (
                <FieldRow label="Labels">
                  <span className="flex flex-wrap gap-1">
                    {i.labels.map((l) => (
                      <span
                        key={l}
                        className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700"
                      >
                        {l}
                      </span>
                    ))}
                  </span>
                </FieldRow>
              )}
              {otherAttrs.map((a) => renderAttr(a.key ?? a.name))}
              {parentType && (
                <p className="pt-1 text-[10px] uppercase tracking-wide text-slate-400">
                  Fields inherited from {parentType.name}
                </p>
              )}
            </dl>
          </Panel>

          <Panel
            title="Affected objects and documents"
            action={
              (links.data?.assets.length ||
                links.data?.documents.length ||
                links.data?.tickets.length) ? (
                <button
                  onClick={() => setShowGraph(true)}
                  className="text-xs text-indigo-600 hover:text-indigo-800"
                >
                  View graph
                </button>
              ) : undefined
            }
          >
            <p className="mb-2 text-xs text-slate-500">
              What this ticket is about. These are links, not fields — the same
              connection is visible from the object and from the document.
            </p>

            <ul className="space-y-1 text-sm">
              {links.data?.assets.map((a) => (
                <li key={a.asset_uid} className="flex items-center gap-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {a.relation}
                  </span>
                  <Link to={`/assets/${a.asset_uid}`} className="text-indigo-600 hover:underline">
                    {a.name}
                  </Link>
                  <span className="text-xs text-slate-400">{a.key}</span>
                  <button
                    onClick={() => unlinkAssetMutation.mutate(a.asset_uid)}
                    className="ml-auto text-xs text-red-500 hover:text-red-700"
                  >
                    Unlink
                  </button>
                </li>
              ))}
              {links.data?.documents.map((d) => (
                <li key={d.relation_id} className="flex items-center gap-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {d.relation}
                  </span>
                  <Link
                    to={`/documents/${d.document_uid}`}
                    className="text-indigo-600 hover:underline"
                  >
                    {d.title}
                  </Link>
                  <span className="text-xs text-slate-400">{d.code}</span>
                  <button
                    onClick={() => unlinkDocumentMutation.mutate(d.relation_id)}
                    className="ml-auto text-xs text-red-500 hover:text-red-700"
                  >
                    Unlink
                  </button>
                </li>
              ))}
              {links.data?.tickets.map((t) => (
                <li key={t.link_id} className="flex items-center gap-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {ticketRelationLabel(t.relation, t.outgoing)}
                  </span>
                  <Link to={`/tickets/${t.issue_uid}`} className="text-indigo-600 hover:underline">
                    {t.title}
                  </Link>
                  {t.source_key && (
                    <span className="font-mono text-xs text-slate-400">{t.source_key}</span>
                  )}
                  <button
                    onClick={() => unlinkTicketMutation.mutate(t.link_id)}
                    className="ml-auto text-xs text-red-500 hover:text-red-700"
                  >
                    Unlink
                  </button>
                </li>
              ))}
              {links.data &&
                links.data.assets.length === 0 &&
                links.data.documents.length === 0 &&
                links.data.tickets.length === 0 && (
                  <p className="text-slate-400">Nothing linked yet.</p>
                )}
            </ul>

            <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
              <select
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) linkAssetMutation.mutate(e.target.value);
                  e.target.value = "";
                }}
                className="min-w-48 flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="">Link an object…</option>
                {allAssets.data?.map((a) => (
                  <option key={a.uid} value={a.uid}>
                    {a.name} ({a.key})
                  </option>
                ))}
              </select>
              <select
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) linkDocumentMutation.mutate(e.target.value);
                  e.target.value = "";
                }}
                className="min-w-48 flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="">Link a document…</option>
                {documents.data?.map((d) => (
                  <option key={d.uid} value={d.uid}>
                    {d.title} ({d.code})
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                value={ticketRelation}
                onChange={(e) => setTicketRelation(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="relates">relates to</option>
                <option value="epic">in epic</option>
                <option value="parent">child of</option>
                <option value="blocks">blocks</option>
                <option value="duplicates">duplicates</option>
              </select>
              <TicketPicker
                options={allIssues.data ?? []}
                excludeUid={i.uid}
                onPick={(issueUid) => linkTicketMutation.mutate(issueUid)}
                placeholder="Link a ticket…"
              />
            </div>
            {(linkAssetMutation.isError ||
              linkDocumentMutation.isError ||
              linkTicketMutation.isError) && (
              <p className="mt-2 text-xs text-red-600">
                {((linkAssetMutation.error ??
                  linkDocumentMutation.error ??
                  linkTicketMutation.error) as ApiError)?.detail ?? "Could not link that."}
              </p>
            )}
          </Panel>

          <Panel title="Description">
            {i.description ? (
              <p className="whitespace-pre-wrap break-words text-sm text-slate-700">
                {i.description}
              </p>
            ) : (
              <p className="text-sm text-slate-400">No description.</p>
            )}
          </Panel>

          <Panel
            title={`Attachments${attachments.data?.length ? ` (${attachments.data.length})` : ""}`}
            action={
              <button
                onClick={() => fileInputRef.current?.click()}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                + Upload
              </button>
            }
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadMutation.mutate(file);
                e.target.value = "";
              }}
            />
            {/* A fault is usually easiest to show rather than describe, and
                the screenshot is already on the clipboard — so take it from
                there instead of making someone save a file first. */}
            <div
              tabIndex={0}
              onPaste={(e) => {
                const item = [...e.clipboardData.items].find((i) =>
                  i.type.startsWith("image/"),
                );
                const file = item?.getAsFile();
                if (file) {
                  const named = new File(
                    [file],
                    `screenshot-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.png`,
                    { type: file.type },
                  );
                  uploadMutation.mutate(named);
                } else {
                  setPasteHint("That clipboard item isn't an image.");
                }
              }}
              className="mb-3 rounded border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 focus:border-indigo-400 focus:outline-none"
            >
              {uploadMutation.isPending
                ? "Uploading…"
                : (pasteHint ?? "Click here and press ⌘V to paste a screenshot.")}
            </div>

            <ul className="space-y-2 text-sm">
              {attachments.data?.map((att) => {
                const isImage = (att.mime_type ?? "").startsWith("image/");
                return (
                  <li key={att.uid} className="flex items-center gap-3">
                    {isImage ? (
                      <AuthenticatedImage
                        uid={att.uid}
                        alt={att.filename}
                        className="h-10 w-10 shrink-0 rounded border border-slate-200 bg-white object-contain"
                      />
                    ) : (
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-slate-200 bg-slate-50 text-[10px] uppercase text-slate-400">
                        {(att.filename.split(".").pop() ?? "file").slice(0, 4)}
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      {att.filename}{" "}
                      <span className="text-xs text-slate-400">
                        ({att.file_size ? `${Math.round(att.file_size / 1024)} KB` : "?"})
                      </span>
                    </span>
                    <span className="flex shrink-0 gap-3">
                      <button
                        onClick={() => downloadAttachment(att.uid, att.filename)}
                        className="text-xs text-indigo-600 hover:text-indigo-800"
                      >
                        Download
                      </button>
                      <button
                        onClick={() => deleteAttachmentMutation.mutate(att.uid)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Delete
                      </button>
                    </span>
                  </li>
                );
              })}
              {attachments.data?.length === 0 && (
                <p className="text-slate-400">No attachments.</p>
              )}
            </ul>
          </Panel>

          <Panel title={`Activity${comments.data?.length ? ` (${comments.data.length})` : ""}`}>
            <ul className="space-y-3">
              {comments.data?.map((c) => (
                <li key={c.uid} className="border-l-2 border-slate-100 pl-3">
                  <p className="whitespace-pre-wrap break-words text-sm text-slate-800">{c.body}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {c.author} · {new Date(c.created_at).toLocaleString()}
                  </p>
                </li>
              ))}
              {comments.data?.length === 0 && (
                <p className="text-sm text-slate-400">No comments yet.</p>
              )}
            </ul>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (commentBody.trim()) addCommentMutation.mutate();
              }}
              className="mt-4 space-y-2 border-t border-slate-100 pt-3"
            >
              <input
                value={commentAuthor}
                onChange={(e) => setCommentAuthor(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                placeholder="Your name"
              />
              <textarea
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                rows={3}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                placeholder="Add a comment…"
              />
              <button
                type="submit"
                className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
              >
                Comment
              </button>
            </form>
          </Panel>
        </div>

        <div className="space-y-4">
          <TicketWorkflowCard ticketUid={i.uid} />
          <WatchersCard ticketUid={i.uid} />
          <TicketContextPanel ticketUid={i.uid} />
          <Panel title="People">
            <dl>
              <FieldRow label="Assignee">
                <select
                  value={i.assignee ?? ""}
                  onChange={(e) =>
                    updateMutation.mutate({ assignee: e.target.value || null })
                  }
                  className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                >
                  <option value="">Unassigned</option>
                  {/* An imported assignee is a Jira display name, not one of
                      our users; keep it selectable so saving doesn't silently
                      drop it. */}
                  {i.assignee && !assignedMember && (
                    <option value={i.assignee}>{i.assignee}</option>
                  )}
                  {members.data?.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.name || m.email}
                    </option>
                  ))}
                </select>
              </FieldRow>
              {PEOPLE_KEYS.map(renderAttr)}
              {i.created_by && <FieldRow label="Created by">{i.created_by}</FieldRow>}
            </dl>
          </Panel>

          <Panel title="Dates">
            <dl>
              {DATE_KEYS.map(renderAttr)}
              <FieldRow label="Imported">{new Date(i.created_at).toLocaleString()}</FieldRow>
              {i.due_date && (
                <FieldRow label="Due">{new Date(i.due_date).toLocaleDateString()}</FieldRow>
              )}
              {i.closed_at && (
                <FieldRow label="Resolved">{new Date(i.closed_at).toLocaleString()}</FieldRow>
              )}
            </dl>
          </Panel>

          <Panel title="Related by meaning">
            <SemanticRelated kind="ticket" uid={i.uid} />
          </Panel>

          <Panel title="History">
            <ul className="space-y-2 text-sm">
              {history.data?.slice(0, 40).map((h) => (
                <li key={h.uid} className="border-l-2 border-slate-100 pl-2">
                  <p className="text-slate-800">
                    {h.field ? (
                      <>
                        <span className="text-slate-500">{h.field}</span>{" "}
                        {h.from_value && (
                          <span className="text-slate-400 line-through">{h.from_value}</span>
                        )}{" "}
                        {h.to_value && <span>{h.to_value}</span>}
                      </>
                    ) : (
                      h.details
                    )}
                  </p>
                  <p className="text-xs text-slate-400">
                    {h.author} · {new Date(h.timestamp).toLocaleString()}
                  </p>
                </li>
              ))}
              {history.data?.length === 0 && (
                <p className="text-slate-400">Nothing recorded yet.</p>
              )}
              {(history.data?.length ?? 0) > 40 && (
                <p className="text-xs text-slate-400">
                  Showing the 40 most recent of {history.data!.length}.
                </p>
              )}
            </ul>
          </Panel>

          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="block rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-indigo-600 hover:bg-slate-50"
            >
              Open at source ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
