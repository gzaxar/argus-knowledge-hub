import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, storageApi, workspacesApi } from "../../api/client";
import { ask } from "../../lib/dialogs";
import { bytes, Card, DayBars, n, said, Table } from "../admin/Statistics";

/** A workspace's share of the storage (backend routers/storage.py): its attachment files and the workspace bundles
 *  exported of it. Its administrators see it; removing a bundle is an instance administrator's, signed in. The whole
 *  installation, the planned room and the other cleanups are in Administration → Storage. */
export function WorkspaceStorage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const q = useQuery({ queryKey: ["workspace-storage", workspaceId], queryFn: () => storageApi.workspace(workspaceId!),
                       enabled: !!workspaceId, retry: false });
  const remove = useMutation({
    mutationFn: (id: string) => storageApi.removeBundle(workspaceId!, id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workspace-storage", workspaceId] }),
  });
  if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    return <p className="text-sm text-red-600">{forbidden ? "The workspace's administrators only." : "Could not load its storage."}</p>;
  }
  if (!q.data) return <p className="text-sm text-slate-500">Measuring…</p>;
  const a = q.data.attachments;
  const instanceAdmin = !!me.data?.is_admin;
  return (
    <div className="max-w-5xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Storage</h1>
        <p className="text-sm text-slate-600">
          This workspace's files.{" "}
          {instanceAdmin
            ? <>The whole installation, the planned room and freeing space are in <Link to="/admin/storage" className="underline">Administration → Storage</Link>.</>
            : "The whole installation's storage is for its administrators."}
        </p>
      </div>
      <Card title="Attachment files" hint="Files attached to this workspace's records, tickets and documents.">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm md:grid-cols-4">
          <dt className="text-slate-500">Files</dt><dd className="tabular-nums">{n(a.files)}</dd>
          <dt className="text-slate-500">Size</dt><dd className="tabular-nums">{bytes(a.bytes)}</dd>
          <dt className="text-slate-500">Share of all attachments</dt>
          <dd className="tabular-nums">{a.share_of_area == null ? "—" : `${(a.share_of_area * 100).toFixed(1)}% of ${bytes(a.area_bytes)}`}</dd>
        </dl>
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-slate-600">Added each day, the last 30 days</div>
          <DayBars height={60} rows={a.per_day.map((d) => ({ day: d.day, added: d.added_bytes }))}
                   series={[{ key: "added", color: "bg-emerald-500", label: "bytes added" }]} />
        </div>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <Table head={["Largest files", "Size", "Added"]} rows={a.largest.map((f) => [
            f.asset_uid ? <Link to={`/assets/${f.asset_uid}`} className="underline">{f.filename}</Link>
              : f.issue_uid ? <Link to={`/issues/${f.issue_uid}`} className="underline">{f.filename}</Link> : f.filename,
            bytes(f.bytes), f.created_at ? new Date(f.created_at).toLocaleDateString() : "—"])} />
          <Table head={["By type", "Files", "Size"]} rows={a.by_type.map((t) => [t.mime_type, n(t.files), bytes(t.bytes)])} />
        </div>
      </Card>
      <Card title="Workspace bundles exported of it" hint="Kept in the portability area to download. Export the workspace again for a fresh one.">
        {q.data.bundles.length === 0 ? <p className="text-sm text-slate-500">None kept.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Exported</th><th>By</th><th>Size</th><th /></tr></thead>
            <tbody>
              {q.data.bundles.map((b) => (
                <tr key={b.id} className="border-t border-slate-100">
                  <td className="py-1.5">{b.created_at ? new Date(b.created_at).toLocaleString() : b.id}</td>
                  <td>{b.created_by ?? "—"}</td>
                  <td className="tabular-nums">{bytes(b.bytes)}</td>
                  <td className="text-right">
                    {instanceAdmin && (
                      <button type="button" disabled={remove.isPending}
                              onClick={async () => { if (await ask(`Remove this bundle? ${bytes(b.bytes)} is freed.`)) remove.mutate(b.id); }}
                              className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {remove.data && <p role="status" className="mt-2 text-xs text-emerald-700">Freed {bytes(remove.data.freed)}.</p>}
        {remove.isError && <p className="mt-2 text-xs text-rose-700">{said(remove.error, "Could not remove it.")}</p>}
      </Card>
    </div>
  );
}
