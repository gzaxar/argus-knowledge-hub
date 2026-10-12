import { OwnerBadge } from "../../components/OwnerBadge";
import { SuggestFromFile } from "../../components/SuggestFromFile";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  assetSubresourcesApi,
  assetsApi,
  attachmentsApi,
  membersApi,
  relationsApi,
  schemasApi,
} from "../../api/client";
import { LABEL_ISSUERS, LABEL_TYPES } from "../../api/types";
import { AttributeValue } from "../../components/AttributeValue";
import { AuthenticatedImage } from "../../components/AuthenticatedImage";
import { ImageSlot } from "../../components/ImageSlot";
import { isScannableType, LabelCode, printLabel } from "../../components/LabelCode";
import { LabelScanner } from "../../components/LabelScanner";
import { RelationGraph } from "../../components/RelationGraph";
import { TransferItemAction } from "../../components/TransferItemAction";
import { effectiveAttributes, inheritedKeys } from "../../lib/schemaAttributes";
import { AssetContextPanel } from "../../components/hub/ContextPanels";
import { SemanticRelated } from "../../components/SemanticRelated";
import { LocationCard } from "../../components/LocationCard";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { FollowButton } from "../../components/FollowButton";
import { useShowKeys } from "../../api/displayPrefs";

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

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

export function AssetDetail() {
  const currentWorkspaceForLocation = useCurrentWorkspaceId();
  const showKeys = useShowKeys();
  const { uid } = useParams<{ uid: string }>();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [commentText, setCommentText] = useState("");
  const [commentAuthor, setCommentAuthor] = useState("web-user");
  const [relationTarget, setRelationTarget] = useState("");
  const [relationType, setRelationType] = useState("related_to");
  const [showGraph, setShowGraph] = useState(false);
  const [labelType, setLabelType] = useState<string>(LABEL_TYPES[0]);
  const [labelValue, setLabelValue] = useState("");
  const [labelIssuer, setLabelIssuer] = useState<string>(LABEL_ISSUERS[0]);
  const [scanning, setScanning] = useState(false);

  const asset = useQuery({
    queryKey: ["assets", uid],
    queryFn: () => assetsApi.get(uid!),
    enabled: !!uid,
  });
  const schema = useQuery({
    queryKey: ["schemas", asset.data?.schema_uid],
    queryFn: () => schemasApi.get(asset.data!.schema_uid),
    enabled: !!asset.data,
  });
  const allSchemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const allAssets = useQuery({ queryKey: ["assets"], queryFn: () => assetsApi.list() });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  const relations = useQuery({ queryKey: ["relations"], queryFn: relationsApi.list });
  const attachments = useQuery({
    queryKey: ["attachments", uid],
    queryFn: () => attachmentsApi.list(uid!),
    enabled: !!uid,
  });
  const history = useQuery({
    queryKey: ["asset-history", uid],
    queryFn: () => assetSubresourcesApi.history(uid!),
    enabled: !!uid,
  });
  const comments = useQuery({
    queryKey: ["asset-comments", uid],
    queryFn: () => assetSubresourcesApi.comments(uid!),
    enabled: !!uid,
  });
  const labels = useQuery({
    queryKey: ["asset-labels", uid],
    queryFn: () => assetSubresourcesApi.labels(uid!),
    enabled: !!uid,
  });

  const deleteMutation = useMutation({
    mutationFn: () => assetsApi.delete(uid!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      navigate("/assets/search");
    },
    onError: () => alert("Delete failed."),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => attachmentsApi.upload(uid!, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["attachments", uid] }),
  });
  const deleteAttachmentMutation = useMutation({
    mutationFn: attachmentsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["attachments", uid] }),
  });
  // Avatar changes touch both the object and its attachment list: an
  // uploaded avatar is stored as an attachment, and clearing one puts that
  // picture back among them.
  const invalidateAvatar = () => {
    queryClient.invalidateQueries({ queryKey: ["assets", uid] });
    queryClient.invalidateQueries({ queryKey: ["attachments", uid] });
    queryClient.invalidateQueries({ queryKey: ["assets"] });
  };
  const uploadAvatarMutation = useMutation({
    mutationFn: (file: File) => assetsApi.uploadAvatar(uid!, file),
    onSuccess: invalidateAvatar,
  });
  const setAvatarMutation = useMutation({
    mutationFn: (attachmentUid: string) => assetsApi.setAvatarFromAttachment(uid!, attachmentUid),
    onSuccess: invalidateAvatar,
  });
  const clearAvatarMutation = useMutation({
    mutationFn: () => assetsApi.clearAvatar(uid!),
    onSuccess: invalidateAvatar,
  });
  const addCommentMutation = useMutation({
    mutationFn: () => assetSubresourcesApi.addComment(uid!, commentAuthor, commentText),
    onSuccess: () => {
      setCommentText("");
      queryClient.invalidateQueries({ queryKey: ["asset-comments", uid] });
    },
  });
  const addRelationMutation = useMutation({
    mutationFn: () => relationsApi.create(uid!, relationTarget, relationType),
    onSuccess: () => {
      setRelationTarget("");
      queryClient.invalidateQueries({ queryKey: ["relations"] });
      queryClient.invalidateQueries({ queryKey: ["assets", uid] });
    },
  });
  const deleteRelationMutation = useMutation({
    mutationFn: relationsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["relations"] }),
  });
  const addLabelMutation = useMutation({
    mutationFn: () =>
      assetSubresourcesApi.addLabel(uid!, {
        type: labelType,
        value: labelValue,
        issuer: labelIssuer,
      }),
    onSuccess: () => {
      setLabelValue("");
      queryClient.invalidateQueries({ queryKey: ["asset-labels", uid] });
    },
  });
  const deleteLabelMutation = useMutation({
    mutationFn: (labelUid: string) => assetSubresourcesApi.deleteLabel(uid!, labelUid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["asset-labels", uid] }),
  });

  if (asset.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!asset.data) return <p className="text-sm text-red-600">Asset not found.</p>;

  const a = asset.data;
  const attrDefs = effectiveAttributes(schema.data, allSchemas.data);
  const inherited = inheritedKeys(schema.data, attrDefs);
  const assetName = (id: string) => allAssets.data?.find((x) => x.uid === id)?.name ?? id;
  const outbound = relations.data?.filter((r) => r.from_asset_uid === a.uid) ?? [];
  const inbound = relations.data?.filter((r) => r.to_asset_uid === a.uid) ?? [];
  const visibleAttachments = attachments.data?.filter((att) => att.uid !== a.avatar_icon_uid) ?? [];

  return (
    <div>
      {showGraph && <RelationGraph assetUid={a.uid} onClose={() => setShowGraph(false)} />}
      {scanning && (
        <LabelScanner
          title="Scan a code for this object"
          onClose={() => setScanning(false)}
          onScan={(value) => {
            // Filling the field rather than saving straight away: the type
            // and issuer still need picking, and a misread should be
            // correctable before it becomes a label.
            setLabelValue(value);
            setLabelType(value.startsWith("http") ? "qrcode" : "barcode");
            setScanning(false);
          }}
        />
      )}

      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <ImageSlot
            attachmentUid={a.avatar_icon_uid}
            fallbackText={a.name}
            alt={a.name}
            size={64}
            busy={uploadAvatarMutation.isPending}
            onPick={(file) => uploadAvatarMutation.mutate(file)}
            onClear={() => clearAvatarMutation.mutate()}
          />
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
              {a.name}
              {a.is_global && (
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-700">
                  Global
                </span>
              )}
              <OwnerBadge workspaceId={a.workspace_id} />
            </h1>
            <p className="text-sm text-slate-500">
              {showKeys && <>{a.key} · </>}{a.type} · schema:{" "}
              <Link to={`/schemas/${a.schema_uid}`} className="hover:underline">
                {schema.data?.name ?? a.schema_uid}
              </Link>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FollowButton subject="asset" uid={a.uid} />
          <Link
            to={`/assets/${a.uid}/edit`}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Edit
          </Link>
          <TransferItemAction kind="asset" uid={a.uid} />
          <button
            onClick={() => {
              if (confirm(`Delete object "${a.name}"? This cannot be undone.`)) deleteMutation.mutate();
            }}
            disabled={deleteMutation.isPending}
            className="rounded border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>

      <AssetContextPanel assetUid={a.uid} />

      <div className="mt-6">
        <SuggestFromFile assetUid={a.uid} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectionCard title="Attributes">
          {attrDefs.length === 0 ? (
            <p className="text-sm text-slate-400">This schema has no attributes defined.</p>
          ) : (
            <dl className="space-y-1.5 text-sm">
              {attrDefs.map((attr) => {
                const long = attr.type === "text";
                return (
                <div key={attr.id ?? attr.name} className={long ? "space-y-1" : "flex justify-between gap-4"}>
                  <dt className="text-slate-500">
                    {attr.name}
                    {inherited.has(attr.key ?? attr.name) && (
                      <span className="ml-1 text-[10px] uppercase tracking-wide text-slate-400">
                        inherited
                      </span>
                    )}
                  </dt>
                  <dd className={long ? "text-slate-900" : "text-right text-slate-900"}>
                    <AttributeValue
                      attribute={attr}
                      value={a.attributes[attr.key ?? attr.name]}
                      assets={allAssets.data}
                      members={members.data}
                    />
                  </dd>
                </div>
                );
              })}
            </dl>
          )}
        </SectionCard>

        <SectionCard
          title="Relations"
          action={
            (outbound.length > 0 || inbound.length > 0) && (
              <button
                onClick={() => setShowGraph(true)}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                View graph
              </button>
            )
          }
        >
          <div className="space-y-3 text-sm">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Outbound {outbound.length > 0 && `(${outbound.length})`}
              </p>
              {outbound.length === 0 && <p className="text-slate-400">None</p>}
              {outbound.map((r) => (
                <div key={r.id} className="flex items-center justify-between">
                  <span>
                    {r.relation_type} →{" "}
                    <Link to={`/assets/${r.to_asset_uid}`} className="hover:underline">
                      {assetName(r.to_asset_uid)}
                    </Link>
                  </span>
                  {r.derivation ? (
                    <span
                      className="text-[11px] text-slate-400"
                      title="Maintained by the fact ledger from sources, installations and decisions; not edited here"
                    >
                      {r.derivation === "derived" ? "derived" : "from sources"}
                    </span>
                  ) : (
                    <button
                      onClick={() => deleteRelationMutation.mutate(r.id)}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Inbound {inbound.length > 0 && `(${inbound.length})`}
              </p>
              {inbound.length === 0 && <p className="text-slate-400">None</p>}
              {inbound.map((r) => (
                <div key={r.id} className="flex items-center justify-between">
                  <span>
                    <Link to={`/assets/${r.from_asset_uid}`} className="hover:underline">
                      {assetName(r.from_asset_uid)}
                    </Link>{" "}
                    → {r.relation_type}
                  </span>
                  {r.derivation ? (
                    <span
                      className="text-[11px] text-slate-400"
                      title="Maintained by the fact ledger from sources, installations and decisions; not edited here"
                    >
                      {r.derivation === "derived" ? "derived" : "from sources"}
                    </span>
                  ) : (
                    <button
                      onClick={() => deleteRelationMutation.mutate(r.id)}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (relationTarget) addRelationMutation.mutate();
            }}
            className="mt-3 flex gap-2"
          >
            <select
              value={relationTarget}
              onChange={(e) => setRelationTarget(e.target.value)}
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
            >
              <option value="">Target asset…</option>
              {allAssets.data
                ?.filter((x) => x.uid !== a.uid)
                .map((x) => (
                  <option key={x.uid} value={x.uid}>
                    {x.name}
                  </option>
                ))}
            </select>
            <input
              value={relationType}
              onChange={(e) => setRelationType(e.target.value)}
              className="w-28 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button
              type="submit"
              className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800"
            >
              Add
            </button>
          </form>
        </SectionCard>

        <SectionCard
          title="Attachments"
          action={
            <button
              onClick={() => fileInputRef.current?.click()}
              className="text-xs text-slate-600 hover:text-slate-900"
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
          <ul className="space-y-2 text-sm">
            {visibleAttachments.map((att) => {
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
                    {isImage && (
                      <button
                        onClick={() => setAvatarMutation.mutate(att.uid)}
                        className="text-xs text-slate-600 hover:text-slate-900"
                      >
                        Set as avatar
                      </button>
                    )}
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
            {visibleAttachments.length === 0 && (
              <p className="text-slate-400">No attachments.</p>
            )}
          </ul>
        </SectionCard>

        <SectionCard title="Labels">
          <ul className="space-y-3 text-sm">
            {labels.data?.map((l) => (
              <li key={l.uid} className="flex items-start gap-3">
                {isScannableType(l.type) && (
                  <LabelCode type={l.type} value={l.value} size={64} />
                )}
                <div className="min-w-0 flex-1">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {l.type}
                  </span>{" "}
                  <span className="break-all">{l.value}</span>
                  <div className="mt-0.5 text-xs text-slate-400">
                    issued by {l.issuer}
                    {l.verified && <span className="ml-1 text-green-600">· verified</span>}
                  </div>
                </div>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <button
                    onClick={() => printLabel(l, { name: a.name, key: a.key })}
                    className="text-xs text-indigo-600 hover:text-indigo-800"
                  >
                    Print
                  </button>
                  <button
                    onClick={() => deleteLabelMutation.mutate(l.uid)}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Remove
                  </button>
                </span>
              </li>
            ))}
            {labels.data?.length === 0 && <p className="text-slate-400">No labels yet.</p>}
          </ul>
          {addLabelMutation.isError && (
            <p className="mt-2 text-xs text-red-600">
              {(addLabelMutation.error as ApiError)?.detail ?? "Could not add this label."}
            </p>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (labelValue.trim()) addLabelMutation.mutate();
            }}
            className="mt-3 flex gap-2"
          >
            <select
              value={labelType}
              onChange={(e) => setLabelType(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              {LABEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <input
              value={labelValue}
              onChange={(e) => setLabelValue(e.target.value)}
              placeholder="Value"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button
              type="button"
              onClick={() => setScanning(true)}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
              title="Scan a code with the camera"
            >
              Scan
            </button>
            <select
              value={labelIssuer}
              onChange={(e) => setLabelIssuer(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              {LABEL_ISSUERS.map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800"
            >
              Add
            </button>
          </form>
        </SectionCard>

        <LocationCard uid={a.uid} editable={a.workspace_id === currentWorkspaceForLocation} />

        <SectionCard title="Related by meaning">
          <SemanticRelated kind="asset" uid={a.uid} />
        </SectionCard>

        <SectionCard title="History">
          <ul className="space-y-2 text-sm">
            {history.data?.map((h) => (
              <li key={h.uid} className="border-l-2 border-slate-200 pl-2">
                <p className="text-slate-900">
                  {h.type} — <span className="text-slate-500">{h.author}</span>
                </p>
                <p className="text-xs text-slate-400">
                  {new Date(h.timestamp).toLocaleString()}
                </p>
              </li>
            ))}
            {history.data?.length === 0 && <p className="text-slate-400">No history yet.</p>}
          </ul>
        </SectionCard>

        <SectionCard title="Comments">
          <ul className="space-y-2 text-sm">
            {comments.data?.map((c) => (
              <li key={c.uid}>
                <p className="text-slate-900">{c.text}</p>
                <p className="text-xs text-slate-400">
                  {c.author} · {new Date(c.created).toLocaleString()}
                </p>
              </li>
            ))}
            {comments.data?.length === 0 && <p className="text-slate-400">No comments yet.</p>}
          </ul>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (commentText.trim()) addCommentMutation.mutate();
            }}
            className="mt-3 space-y-2"
          >
            <input
              value={commentAuthor}
              onChange={(e) => setCommentAuthor(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
              placeholder="Your name"
            />
            <textarea
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
              rows={2}
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder="Add a comment…"
            />
            <button
              type="submit"
              className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800"
            >
              Comment
            </button>
          </form>
        </SectionCard>
      </div>
    </div>
  );
}
