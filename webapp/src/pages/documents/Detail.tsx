import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { reshapeApi } from "../../api/client";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import {
  ApiError,
  assetsApi,
  attachmentsApi,
  documentsApi,
  issuesApi,
  schemasApi,
} from "../../api/client";
import { effectiveAttributes, inheritedKeys } from "../../lib/schemaAttributes";
import { AttributeInput } from "../../components/AttributeInput";
import { AttributeValue } from "../../components/AttributeValue";
import { DocumentAssistant } from "../../components/DocumentAssistant";
import { DrawingViewer } from "../../components/DrawingViewer";
import { RecordPicker } from "../../components/RecordPicker";
import { MarkdownEditor } from "../../components/MarkdownEditor";
import { MarkdownView } from "../../components/MarkdownView";
import { ImageGallery } from "../../components/ImageLightbox";
import { TransferItemAction } from "../../components/TransferItemAction";
import { StepsEditor } from "../../components/StepsEditor";
import { DocumentStep } from "../../api/types";
import { DocumentContextPanel } from "../../components/hub/ContextPanels";
import { DocumentControlCard, SupersededBanner, VerifyAttachment } from "../../components/hub/DocumentControl";
import { errorText } from "../../components/hub/LedgerPanels";
import { SemanticRelated } from "../../components/SemanticRelated";
import { ExportMenu } from "../../components/ExportMenu";
import { FollowButton } from "../../components/FollowButton";
import { useShowKeys } from "../../api/displayPrefs";

const STATE_STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  in_review: "bg-amber-100 text-amber-700",
  approved: "bg-blue-100 text-blue-700",
  published: "bg-green-100 text-green-700",
  superseded: "bg-slate-100 text-slate-400",
  retired: "bg-red-100 text-red-700",
};

export function DocumentDetail() {
  const showKeys = useShowKeys();
  const { uid } = useParams<{ uid: string }>();
  const workspaceId = useCurrentWorkspaceId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [viewedRevisionUid, setViewedRevisionUid] = useState<string | null>(null);
  const [rejectComment, setRejectComment] = useState("");
  const [viewingDrawing, setViewingDrawing] = useState<string | null>(null);
  const [showReject, setShowReject] = useState(false);

  const document = useQuery({
    queryKey: ["documents", uid],
    queryFn: () => documentsApi.get(uid!),
    enabled: !!uid,
  });
  const revisions = useQuery({
    queryKey: ["document-revisions", uid],
    queryFn: () => documentsApi.listRevisions(uid!),
    enabled: !!uid,
  });
  const schema = useQuery({
    queryKey: ["schemas", document.data?.document_type_uid],
    queryFn: () => schemasApi.get(document.data!.document_type_uid!),
    enabled: !!document.data?.document_type_uid,
  });
  const allSchemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const documentSchemas = (allSchemas.data ?? []).filter((s) => s.applies_to === "documents");
  const attrDefs = effectiveAttributes(schema.data, allSchemas.data);
  const inherited = inheritedKeys(schema.data, attrDefs);
  const allAssets = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.list(),
    enabled: attrDefs.some((a) => a.type === "reference"),
  });

  const sortedRevisions = [...(revisions.data ?? [])].sort((a, b) => b.revision_number - a.revision_number);
  const openRevision = sortedRevisions.find((r) => ["draft", "in_review", "approved"].includes(r.state));
  const currentRevision = sortedRevisions.find((r) => r.uid === document.data?.current_revision_uid);
  const latestRevision = sortedRevisions[0];
  const viewed =
    (viewedRevisionUid && sortedRevisions.find((r) => r.uid === viewedRevisionUid)) ||
    currentRevision ||
    latestRevision;

  const attachments = useQuery({
    queryKey: ["document-attachments", uid, viewedRevisionUid],
    queryFn: () => documentsApi.listRevisionAttachments(uid!, viewed!.uid),
    enabled: !!uid && !!viewed?.uid,
  });

  // Everything a document can point at. The relations are the references:
  // they are what the knowledge graph walks, what the Confluence import
  // creates, and until now the one thing a person could not add by hand.
  const relations = useQuery({
    queryKey: ["document-relations", uid],
    queryFn: () => documentsApi.listRelations(uid!),
    enabled: !!uid,
  });
  const allIssues = useQuery({ queryKey: ["issues"], queryFn: () => issuesApi.list() });
  const allDocuments = useQuery({ queryKey: ["documents"], queryFn: () => documentsApi.list() });
  const linkAssets = useQuery({ queryKey: ["assets"], queryFn: () => assetsApi.list() });

  const [linkKind, setLinkKind] = useState<"asset" | "issue" | "document">("asset");

  const [bodyMarkdown, setBodyMarkdown] = useState("");
  // Whether the images among the files are shown, remembered for this viewer.
  const [showImages, setShowImagesState] = useState(() => {
    try {
      return localStorage.getItem("argus.document.showImages") !== "false";
    } catch {
      return true;
    }
  });
  const setShowImages = (on: boolean) => {
    setShowImagesState(on);
    try {
      localStorage.setItem("argus.document.showImages", String(on));
    } catch {
      /* private window: remembered for this page only */
    }
  };
  const [steps, setSteps] = useState<DocumentStep[]>([]);
  const [attributes, setAttributes] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (viewed && viewed.state === "draft") {
      setBodyMarkdown(viewed.body_markdown ?? "");
      setSteps(viewed.steps);
      setAttributes(viewed.attributes);
    }
  }, [viewed?.uid, viewed?.state]);

  /** A file pasted or dropped into the editor: stored against this
   * revision, and handed back as the URL the body should point at. */
  const uploadIntoBody = async (file: File) => {
    const saved = await documentsApi.uploadRevisionAttachment(uid!, viewed!.uid, file);
    queryClient.invalidateQueries({ queryKey: ["document-attachments", uid] });
    return {
      url: `/v1/attachments/${saved.uid}`,
      filename: saved.filename,
      isImage: (saved.mime_type ?? "").startsWith("image/"),
    };
  };

  /** The download endpoint needs the Bearer header, so a plain link can't
   * reach it — fetch it as a blob and hand the browser that. */
  const downloadAttachment = async (attachmentUid: string, filename: string) => {
    const url = await attachmentsApi.fetchBlobUrl(attachmentUid);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents", uid] });
    queryClient.invalidateQueries({ queryKey: ["document-revisions", uid] });
    queryClient.invalidateQueries({ queryKey: ["document-retention", uid] });
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      documentsApi.updateRevision(uid!, viewed!.uid, { body_markdown: bodyMarkdown, steps, attributes }),
    onSuccess: invalidate,
    onError: () => alert("Save failed."),
  });
  const submitMutation = useMutation({
    mutationFn: () => documentsApi.submitRevision(uid!, viewed!.uid),
    onSuccess: invalidate,
    onError: () => alert("Submit failed."),
  });
  const approveMutation = useMutation({
    mutationFn: () => documentsApi.approveRevision(uid!, viewed!.uid),
    onSuccess: invalidate,
    // The author of a revision cannot approve it (separation of duties).
    onError: (e) => alert(`Approve failed — ${errorText(e)}`),
  });
  const rejectMutation = useMutation({
    mutationFn: () => documentsApi.rejectRevision(uid!, viewed!.uid, rejectComment),
    onSuccess: () => {
      invalidate();
      setShowReject(false);
      setRejectComment("");
    },
    onError: () => alert("Reject failed."),
  });
  const publishMutation = useMutation({
    mutationFn: () => documentsApi.publishRevision(uid!, viewed!.uid),
    onSuccess: invalidate,
    onError: () => alert("Publish failed — you may not have approval rights."),
  });
  const newRevisionMutation = useMutation({
    mutationFn: () =>
      documentsApi.createRevision(uid!, {
        body_markdown: currentRevision?.body_markdown ?? "",
        steps: currentRevision?.steps ?? [],
        attributes: currentRevision?.attributes ?? {},
      }),
    onSuccess: (rev) => {
      invalidate();
      setViewedRevisionUid(rev!.uid);
    },
    onError: () => alert("Could not start a new revision."),
  });
  const retireMutation = useMutation({
    mutationFn: (reason: string) => documentsApi.retire(uid!, reason),
    onSuccess: invalidate,
    onError: (e) => alert(errorText(e)),
  });
  const addRelationMutation = useMutation({
    mutationFn: (input: { to_type: "asset" | "issue" | "document"; to_uid: string }) =>
      documentsApi.addRelation(uid!, {
        to_type: input.to_type,
        to_uid: input.to_uid,
        // What the link means, by what it points at: a document describes
        // equipment, documents a piece of work, and references another
        // document.
        relation_type:
          input.to_type === "asset"
            ? "describes"
            : input.to_type === "issue"
              ? "documents"
              : "references",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-relations", uid] });
    },
    onError: (e) => alert((e as ApiError).detail ?? "Could not add that link."),
  });
  const removeRelationMutation = useMutation({
    mutationFn: (relationId: number) => documentsApi.removeRelation(uid!, relationId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document-relations", uid] }),
  });

  const retypeMutation = useMutation({
    mutationFn: (typeUid: string | null) => documentsApi.retype([uid!], typeUid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["documents", uid] });
    },
    onError: () => alert("Could not change the type."),
  });
  const deleteMutation = useMutation({
    mutationFn: () => documentsApi.delete(uid!),
    onSuccess: () => navigate("/documents"),
    // A released document under retention is refused with the date it is kept until.
    onError: (e) => alert(errorText(e)),
  });

  const sourceUrl = (viewed?.attributes?.argus_source_url as string | undefined) ?? null;

  // Rendered sheets are machinery, not documents: they are reachable only
  // through the drawing they came from, never listed as files of their own.
  const allAttachments = attachments.data ?? [];
  const sheetsBySource = new Map<string, typeof allAttachments>();
  for (const a of allAttachments) {
    const source = a.backend_id?.startsWith("sheet-of:")
      ? a.backend_id.slice("sheet-of:".length)
      : null;
    if (source) sheetsBySource.set(source, [...(sheetsBySource.get(source) ?? []), a]);
  }
  const visibleAttachments = allAttachments.filter(
    (a) => !a.backend_id?.startsWith("sheet-of:"),
  );
  const isDrawing = (filename: string) => /\.(dwg|dxf|dwf|dwfx)$/i.test(filename);
  const isImage = (a: { mime_type: string | null; filename: string }) =>
    (a.mime_type ?? "").startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(a.filename);
  // Images the text already shows are not repeated below it.
  const shownInText = new Set(
    [...(viewed?.body_markdown ?? "").matchAll(/\/v1\/attachments\/([A-Za-z0-9-]+)/g)].map((m) => m[1]),
  );
  const galleryImages = visibleAttachments.filter((a) => isImage(a) && !shownInText.has(a.uid));
  const sheetsFor = (a: { uid: string }) => sheetsBySource.get(a.uid) ?? [];

  const linkOptions = {
    asset: (linkAssets.data ?? []).map((a) => ({ uid: a.uid, label: a.name, sub: a.key })),
    issue: (allIssues.data ?? []).map((i) => ({
      uid: i.uid,
      label: i.title,
      sub: (i.attributes?.argus_source_key as string) ?? "",
    })),
    document: (allDocuments.data ?? [])
      .filter((d) => d.uid !== uid)
      .map((d) => ({ uid: d.uid, label: d.title, sub: d.code })),
  };
  const LINK_KINDS = [
    { kind: "asset" as const, label: "Object", href: "/assets" },
    { kind: "issue" as const, label: "Ticket", href: "/tickets" },
    { kind: "document" as const, label: "Document", href: "/documents" },
  ];
  const describeTarget = (toType: string, toUid: string) => {
    const kind = toType === "issue" ? "issue" : toType === "document" ? "document" : "asset";
    const found = linkOptions[kind as keyof typeof linkOptions].find((o) => o.uid === toUid);
    const href =
      kind === "issue" ? `/tickets/${toUid}` : kind === "document" ? `/documents/${toUid}` : `/assets/${toUid}`;
    return {
      label: found?.label ?? toUid,
      sub: found?.sub,
      href,
      // A relation whose target is gone still shows, as its uid: silently
      // hiding it would hide a broken edge the graph still walks.
      known: !!found,
      kindLabel: LINK_KINDS.find((k) => k.kind === kind)!.label,
    };
  };
  if (document.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!document.data) return <p className="text-sm text-red-600">Document not found.</p>;
  const doc = document.data;

  return (
    <div className="max-w-4xl">
      <div className="flex items-start justify-between">
        <div>
          {showKeys && <p className="font-mono text-xs text-slate-400">{doc.code}</p>}
          <h1 className="text-2xl font-semibold text-slate-900">{doc.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {/* An import has to guess the type from a label or a title, so
                correcting it is routine — it belongs here, not behind an
                edit form. */}
            <select
              value={doc.document_type_uid ?? ""}
              onChange={(e) => retypeMutation.mutate(e.target.value || null)}
              disabled={retypeMutation.isPending}
              className="rounded border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-700"
              title="Document type"
            >
              <option value="">No type</option>
              {documentSchemas.map((s) => (
                <option key={s.uid} value={s.uid}>
                  {s.name}
                </option>
              ))}
            </select>
            <span className="rounded bg-slate-100 px-2 py-0.5">{doc.authority_level}</span>
            <span className="rounded bg-slate-100 px-2 py-0.5">{doc.confidentiality}</span>
            {doc.is_global && (
              <span
                className="rounded bg-sky-100 px-2 py-0.5 text-sky-800"
                title={
                  doc.workspace_id === workspaceId
                    ? "Shared with every workspace"
                    : `Shared from ${doc.workspace_id} — editing belongs to that workspace`
                }
              >
                {doc.workspace_id === workspaceId ? "shared" : `shared from ${doc.workspace_id}`}
              </span>
            )}
            <span className="rounded bg-slate-100 px-2 py-0.5">source: {doc.source}</span>
            {sourceUrl && (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="rounded bg-slate-100 px-2 py-0.5 text-indigo-600 hover:underline"
              >
                original page ↗
              </a>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <FollowButton subject="document" uid={doc.uid} />
          <ExportMenu kind="document" uid={doc.uid} revisionUid={viewed?.uid} />
          {doc.current_revision_uid && (
            <button
              onClick={() => {
                const reason = prompt("Reason for retiring this document?");
                if (reason) retireMutation.mutate(reason);
              }}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              Retire
            </button>
          )}
          <TransferItemAction
            kind="document"
            uid={doc.uid}
            buttonClassName="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          />
          <button
            onClick={() => {
              if (confirm(`Delete document "${doc.title}"? This cannot be undone.`)) {
                deleteMutation.mutate();
              }
            }}
            className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>

      <SupersededBanner doc={doc} />
      <DocumentControlCard doc={doc} />
      <DocumentContextPanel documentUid={doc.uid} />
      <section className="mt-4 rounded-lg border border-slate-200 bg-white">
        <h2 className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-900">Related by meaning</h2>
        <div className="px-4 py-3"><SemanticRelated kind="document" uid={doc.uid} /></div>
      </section>

      {/* Revision selector */}
      <div className="mt-6 flex flex-wrap gap-2">
        {sortedRevisions.map((r) => (
          <button
            key={r.uid}
            onClick={() => setViewedRevisionUid(r.uid)}
            className={`rounded px-3 py-1 text-xs font-medium ${
              viewed?.uid === r.uid ? "ring-2 ring-slate-900" : ""
            } ${STATE_STYLES[r.state] ?? "bg-slate-100 text-slate-600"}`}
          >
            rev {r.revision_number} · {r.state}
            {r.uid === doc.current_revision_uid ? " · current" : ""}
          </button>
        ))}
        {!openRevision && doc.current_revision_uid && (
          <button
            onClick={() => newRevisionMutation.mutate()}
            disabled={newRevisionMutation.isPending}
            className="rounded border border-dashed border-slate-300 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50"
          >
            + New revision
          </button>
        )}
        {!openRevision && doc.current_revision_uid && (
          <Link
            to={`/documents/reshape?document=${encodeURIComponent(doc.uid)}${doc.document_type_uid ? `&document_type_uid=${encodeURIComponent(doc.document_type_uid)}` : ""}`}
            className="rounded border border-dashed border-slate-300 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50"
            title="A new draft revision rewritten from notes, an e-mail or a transcript"
          >
            + Revision from raw text
          </Link>
        )}
      </div>

      {viewed && <MadeFromRawText documentUid={doc.uid} revisionUid={viewed.uid} state={viewed.state} />}
      {viewed && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATE_STYLES[viewed.state]}`}>
              {viewed.state}
            </span>
            <div className="flex gap-2">
              {viewed.state === "draft" && (
                <>
                  <button
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => submitMutation.mutate()}
                    disabled={submitMutation.isPending}
                    className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800"
                  >
                    Submit for review
                  </button>
                </>
              )}
              {viewed.state === "in_review" && (
                <>
                  <button
                    onClick={() => setShowReject((v) => !v)}
                    className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => approveMutation.mutate()}
                    disabled={approveMutation.isPending}
                    className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800"
                  >
                    Approve
                  </button>
                </>
              )}
              {viewed.state === "approved" && (
                <button
                  onClick={() => publishMutation.mutate()}
                  disabled={publishMutation.isPending}
                  className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800"
                >
                  Publish
                </button>
              )}
            </div>
          </div>

          {showReject && viewed.state === "in_review" && (
            <div className="mt-3 space-y-2 rounded border border-red-200 bg-red-50 p-3">
              <textarea
                value={rejectComment}
                onChange={(e) => setRejectComment(e.target.value)}
                placeholder="Why is this being rejected? (required)"
                rows={2}
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <button
                onClick={() => rejectComment.trim() && rejectMutation.mutate()}
                disabled={rejectMutation.isPending || !rejectComment.trim()}
                className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50"
              >
                Confirm reject
              </button>
            </div>
          )}

          {viewed.review_comment && (
            <p className="mt-3 rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-600">
              {viewed.review_comment}
            </p>
          )}

          {/* Body */}
          <div className="mt-4">
            <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
              Body
            </label>
            {viewed.state === "draft" ? (
              <div className="mt-1">
                <MarkdownEditor
                  value={bodyMarkdown}
                  onChange={setBodyMarkdown}
                  onUpload={uploadIntoBody}
                  placeholder="Write the document in Markdown…"
                />
                <DocumentAssistant
                  title={doc.title}
                  documentTypeUid={doc.document_type_uid}
                  body={bodyMarkdown}
                  onDraft={setBodyMarkdown}
                  onLinkObject={(assetUid) =>
                    addRelationMutation.mutate({ to_type: "asset", to_uid: assetUid })
                  }
                />
              </div>
            ) : (
              <div className="mt-1">
                <div className="rounded border border-slate-100 bg-white p-3">
                  <MarkdownView markdown={viewed.body_markdown ?? ""} />
                </div>
                <DocumentAssistant
                  title={doc.title}
                  documentTypeUid={doc.document_type_uid}
                  body={viewed.body_markdown ?? ""}
                  onLinkObject={(assetUid) =>
                    addRelationMutation.mutate({ to_type: "asset", to_uid: assetUid })
                  }
                />
              </div>
            )}
          </div>

          {/* Steps */}
          <div className="mt-4">
            <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
              Steps
            </label>
            {viewed.state === "draft" ? (
              <div className="mt-1">
                <StepsEditor steps={steps} onChange={setSteps} />
              </div>
            ) : (
              <ol className="mt-1 space-y-1 text-sm">
                {viewed.steps.map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-slate-400">{i + 1}.</span>
                    <span className={s.voce_critica ? "font-medium text-red-700" : "text-slate-700"}>
                      {s.testo}
                    </span>
                    {s.checklist && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                        checklist
                      </span>
                    )}
                  </li>
                ))}
                {viewed.steps.length === 0 && <p className="text-slate-400">No steps.</p>}
              </ol>
            )}
          </div>

          {/* Links — the references a document carries. */}
          <div className="mt-4">
            <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
              Links
            </label>
            <div className="mt-1 space-y-1">
              {(relations.data ?? []).map((r) => {
                const target = describeTarget(r.to_type, r.to_uid);
                return (
                  <div
                    key={r.id}
                    className="flex items-center justify-between rounded border border-slate-100 px-2 py-1 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                        {target.kindLabel}
                      </span>
                      <span className="shrink-0 text-xs text-slate-400">{r.relation_type}</span>
                      {target.known ? (
                        <Link to={target.href} className="truncate text-slate-700 hover:underline">
                          {target.label}
                        </Link>
                      ) : (
                        <span className="truncate font-mono text-xs text-slate-400">
                          {target.label}
                        </span>
                      )}
                      {target.sub && (
                        <span className="shrink-0 text-xs text-slate-400">{target.sub}</span>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeRelationMutation.mutate(r.id)}
                      className="ml-3 shrink-0 text-xs text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </div>
                );
              })}
              {(relations.data ?? []).length === 0 && (
                <p className="text-sm text-slate-400">
                  Not linked to anything yet.
                </p>
              )}
            </div>

            <div className="mt-2 flex items-center gap-2">
              <select
                value={linkKind}
                onChange={(e) => setLinkKind(e.target.value as typeof linkKind)}
                className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {LINK_KINDS.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.label}
                  </option>
                ))}
              </select>
              <RecordPicker
                options={linkOptions[linkKind]}
                excludeUid={uid}
                onPick={(toUid) => addRelationMutation.mutate({ to_type: linkKind, to_uid: toUid })}
                placeholder={`Search ${LINK_KINDS.find((k) => k.kind === linkKind)!.label.toLowerCase()}s…`}
                disabled={addRelationMutation.isPending}
              />
            </div>
          </div>

          {/* Files */}
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
                Files
              </label>
              {galleryImages.length > 0 && (
                <label className="flex items-center gap-1.5 text-xs text-slate-500">
                  <input type="checkbox" checked={showImages} onChange={(e) => setShowImages(e.target.checked)} />
                  Show images ({galleryImages.length})
                </label>
              )}
            </div>
            {showImages && galleryImages.length > 0 && (
              <div className="mt-2">
                <ImageGallery images={galleryImages} />
              </div>
            )}
            <div className="mt-1 space-y-1">
              {visibleAttachments.map((a) => {
                // A DWG is shown through the DXF the server converted it
                // to; a DXF is shown directly. Either way the file people
                // download is the one they uploaded.
                const sheets = sheetsFor(a);
                return (
                <div
                  key={a.uid}
                  className="flex items-center justify-between rounded border border-slate-100 px-2 py-1 text-sm"
                >
                  <span className="truncate text-slate-700">{a.filename}</span>
                  <span className="ml-3 flex shrink-0 items-center gap-3 text-xs text-slate-400">
                    {a.file_size != null && <span>{Math.ceil(a.file_size / 1024)} KB</span>}
                    {sheets.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setViewingDrawing(a.uid)}
                        className="text-indigo-600 hover:underline"
                      >
                        View{sheets.length > 1 ? ` (${sheets.length} sheets)` : ""}
                      </button>
                    )}
                    {isDrawing(a.filename) && sheets.length === 0 && (
                      <span title={a.backend_url ?? undefined}>no preview</span>
                    )}
                    <VerifyAttachment uid={a.uid} />
                    <button
                      type="button"
                      onClick={() => downloadAttachment(a.uid, a.filename)}
                      className="text-slate-500 hover:text-slate-900 hover:underline"
                    >
                      Download
                    </button>
                  </span>
                </div>
                );
              })}
              {visibleAttachments.length === 0 && (
                <p className="text-sm text-slate-400">
                  {viewed.state === "draft"
                    ? "None yet — drop a file into the editor above."
                    : "None."}
                </p>
              )}
            </div>
          </div>

          {/* Type attributes */}
          {schema.data && attrDefs.length > 0 && (
            <div className="mt-4">
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
                {schema.data.name} attributes
              </label>
              {viewed.state === "draft" ? (
                <div className="mt-2 space-y-3 rounded border border-slate-200 p-3">
                  {attrDefs.map((attr) => (
                    <div key={attr.id ?? attr.name}>
                      <label className="block text-xs font-medium text-slate-500">
                        {attr.name}
                        {attr.required && <span className="text-red-500"> *</span>}
                        {inherited.has(attr.key ?? attr.name) && (
                          <span className="ml-1 text-[10px] uppercase tracking-wide text-slate-400">
                            inherited
                          </span>
                        )}
                      </label>
                      <div className="mt-1">
                        <AttributeInput
                          attribute={attr}
                          appliesTo="documents"
                          value={attributes[attr.key ?? attr.name]}
                          onChange={(v) =>
                            setAttributes((prev) => ({ ...prev, [attr.key ?? attr.name]: v }))
                          }
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <dl className="mt-2 space-y-1.5 text-sm">
                  {attrDefs.map((attr) => (
                    <div key={attr.id ?? attr.name} className="flex justify-between gap-4">
                      <dt className="text-slate-500">
                        {attr.name}
                        {inherited.has(attr.key ?? attr.name) && (
                          <span className="ml-1 text-[10px] uppercase tracking-wide text-slate-400">
                            inherited
                          </span>
                        )}
                      </dt>
                      <dd className="text-right text-slate-900">
                        <AttributeValue
                          attribute={attr}
                          value={viewed.attributes[attr.key ?? attr.name]}
                          assets={allAssets.data}
                        />
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}

          <p className="mt-4 text-xs text-slate-400">
            {viewed.published_at && `Published ${new Date(viewed.published_at).toLocaleString()}`}
            {!viewed.published_at &&
              viewed.submitted_at &&
              `Submitted ${new Date(viewed.submitted_at).toLocaleString()}`}
            {!viewed.published_at && !viewed.submitted_at && `Created ${new Date(viewed.created_at).toLocaleString()}`}
          </p>
        </div>
      )}

      {!viewed && <p className="mt-4 text-sm text-slate-400">No revisions.</p>}

      {viewingDrawing && (
        <DrawingViewer
          sheets={sheetsFor({ uid: viewingDrawing })}
          filename={
            allAttachments.find((a) => a.uid === viewingDrawing)?.filename ?? "Drawing"
          }
          onClose={() => setViewingDrawing(null)}
        />
      )}

      <p className="mt-4">
        <Link to="/documents" className="text-sm text-slate-500 hover:underline">
          &larr; All documents
        </Link>
      </p>
    </div>
  );
}

const OPERATIONAL = ["Procedure", "Safety Document", "Runbook", "Work Instruction"];

/** How this revision was made from raw text, when it was: the template and its exact version, where the original
 * is, the dates; and, until it is published, that it is not yet a validated instruction. */
function MadeFromRawText({ documentUid, revisionUid, state }: { documentUid: string; revisionUid: string; state: string }) {
  const gens = useQuery({
    queryKey: ["document-generations", documentUid],
    queryFn: () => reshapeApi.generations(documentUid),
  });
  const g = gens.data?.find((x) => x.revision_uid === revisionUid);
  if (!g) return null;
  const unpublished = !["published", "superseded", "retired"].includes(state);
  return (
    <div className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-xs text-indigo-900">
      Reworked from raw text ({g.source.kind}) with template <b>{g.template.id}</b> v{g.template.version}
      {" "}({g.template.scope}){g.model ? `, model ${g.model}` : ""}, on {new Date(g.created_at).toLocaleString()}.
      {g.dates.document_date && <> Document date {g.dates.document_date}{g.dates.document_date_basis ? ` (${g.dates.document_date_basis}${g.dates.document_date_confirmed ? ", confirmed" : ""})` : ""}.</>}
      {" "}The original text is among this revision's files.
      {unpublished && OPERATIONAL.some((t) => g.template.id.startsWith(t.toLowerCase().replace(/ /g, "-"))) && (
        <span className="mt-1 block font-medium text-amber-800">Not usable as an operational instruction until validated and published.</span>
      )}
    </div>
  );
}
