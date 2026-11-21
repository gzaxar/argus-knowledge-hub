import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, quotasApi, workspacesApi } from "../../api/client";
import { Card } from "../admin/Statistics";
import { QuotaBar, shown } from "../admin/Quotas";

/** A workspace's quotas and what it uses, for its administrators. Set by the instance's (Administration → Quotas). */
export function WorkspaceQuotas() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const q = useQuery({ queryKey: ["workspace-quotas", workspaceId], queryFn: () => quotasApi.workspace(workspaceId!),
                       enabled: !!workspaceId, retry: false });
  if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    return <p className="text-sm text-red-600">{forbidden ? "The workspace's administrators only." : "Could not load its quotas."}</p>;
  }
  if (!q.data) return <p className="text-sm text-slate-500">Loading…</p>;
  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Quotas</h1>
        <p className="text-sm text-slate-600">What this workspace may hold and use. Past a quota ARGUS refuses what would add to
          it and says when it frees up; reading, editing and deleting always work, so deleting makes room.{" "}
          {me.data?.is_admin ? <Link to="/admin/quotas" className="underline">Change them in Administration → Quotas.</Link>
            : "The instance's administrators set them."}</p>
      </div>
      <Card title="Its quotas">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Quota</th><th>What it counts</th><th className="w-56">Used</th><th>From</th></tr></thead>
          <tbody>
            {q.data.quotas.map((r) => (
              <tr key={r.key} className="border-t border-slate-100">
                <td className="py-1.5 font-medium">{r.label}</td>
                <td className="text-xs text-slate-600">{r.what}</td>
                <td>{r.key === "file_bytes" ? <span className="text-xs">{shown(r.unit, r.limit)} at most</span> : <QuotaBar q={r} />}</td>
                <td className="text-xs text-slate-500">{r.source === "workspace" ? "its own" : "the default"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/** At 80% of a quota, and at 100%: said to the workspace's administrators wherever they administer it. */
export function QuotaBanner({ workspaceId }: { workspaceId: string }) {
  const q = useQuery({ queryKey: ["workspace-quotas", workspaceId], queryFn: () => quotasApi.workspace(workspaceId),
                       retry: false, staleTime: 60_000 });
  const near = (q.data?.quotas ?? []).filter((r) => r.level === "warn" || r.level === "over");
  if (near.length === 0) return null;
  const over = near.some((r) => r.level === "over");
  return (
    <div role="status" className={`rounded border px-3 py-2 text-sm ${over ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      {over ? "A quota of this workspace is reached: " : "A quota of this workspace is near: "}
      {near.map((r) => `${r.label} ${shown(r.unit, r.used)} of ${shown(r.unit, r.limit)}`).join(" · ")}.{" "}
      <Link to={`/workspaces/${workspaceId}/quotas`} className="underline">See its quotas</Link>
    </div>
  );
}
