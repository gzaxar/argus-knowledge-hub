import { ask, askTyped } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, workspacesApi } from "../../api/client";
import { CleanupOptions } from "../../api/types";

export function WorkspaceIntegrity() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  // The name typed to delete orphaned objects (docs/dangerous-actions.md); an administrator may not be a member.
  const workspace = useQuery({ queryKey: ["workspace", workspaceId], queryFn: () => workspacesApi.get(workspaceId!),
                               enabled: !!workspaceId });
  const nameOf = (id: string) => workspace.data?.name ?? id;

  const report = useQuery({
    queryKey: ["integrity-report", workspaceId],
    queryFn: () => workspacesApi.integrityReport(workspaceId!),
    enabled: !!workspaceId,
  });

  const relinkMutation = useMutation({
    mutationFn: () => workspacesApi.relink(workspaceId!),
    onSuccess: (data) => {
      queryClient.setQueryData(["integrity-report", workspaceId], data.report);
    },
  });

  const cleanupMutation = useMutation({
    mutationFn: (options: CleanupOptions) =>
      workspacesApi.cleanup(workspaceId!, options, options.delete_orphaned_objects ? nameOf(workspaceId!) : undefined),
    onSuccess: (data) => {
      queryClient.setQueryData(["integrity-report", workspaceId], data.report);
    },
  });

  if (report.isError) {
    const forbidden = report.error instanceof ApiError && report.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden ? "Owners and admins only." : "Failed to load the integrity report."}
      </p>
    );
  }

  const data = report.data;

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Data integrity</h1>
          <p className="mt-1 text-sm text-slate-500">
            Workspace <span className="font-mono text-xs">{workspaceId}</span> —{" "}
            <Link to="/admin/workspaces" className="text-indigo-600 hover:underline">
              back to workspaces
            </Link>
          </p>
        </div>
        <button
          onClick={() => relinkMutation.mutate()}
          disabled={relinkMutation.isPending}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {relinkMutation.isPending ? "Relinking…" : "Relink references"}
        </button>
      </div>
      <p className="mt-1 text-xs text-slate-400">
        Relink re-resolves reference/user attribute values that don't currently point at a real
        target — by matching key/name (references) or email/name (users) — and rebuilds every
        object's inbound/outbound relation cache. It never deletes anything.
      </p>

      {relinkMutation.data && (
        <p className="mt-3 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Scanned {relinkMutation.data.relink.assets_scanned} object(s), updated{" "}
          {relinkMutation.data.relink.assets_updated} with {relinkMutation.data.relink.values_relinked}{" "}
          relinked value(s).
        </p>
      )}
      {cleanupMutation.data && (
        <p className="mt-3 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Cleared {cleanupMutation.data.cleanup.cleared_references} reference(s), deleted{" "}
          {cleanupMutation.data.cleanup.deleted_orphaned_objects} orphaned object(s), removed{" "}
          {cleanupMutation.data.cleanup.removed_dangling_relations} dangling relation(s).
        </p>
      )}

      {report.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-6 space-y-8">
          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Missing link references ({data.counts.missing_references})
              </h2>
              {data.counts.missing_references > 0 && (
                <button
                  onClick={async () => {
                    if (await ask(`Clear ${data.counts.missing_references} broken reference value(s)? Each is set to empty; the object itself is not touched otherwise.`)) {
                      cleanupMutation.mutate({ clear_missing_references: true });
                    }
                  }}
                  disabled={cleanupMutation.isPending}
                  className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                >
                  Clear all
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Attribute values that don't resolve to any existing object or user — most often a
              Jira import label never linked to a real record.
            </p>
            {data.missing_references.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">None found.</p>
            ) : (
              <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-2">Object</th>
                      <th className="px-4 py-2">Attribute</th>
                      <th className="px-4 py-2">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.missing_references.map((m, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2">
                          <Link to={`/assets/${m.asset_uid}`} className="text-slate-900 hover:underline">
                            {m.asset_name}
                          </Link>{" "}
                          <span className="text-xs text-slate-400">({m.asset_key})</span>
                        </td>
                        <td className="px-4 py-2 text-slate-600">{m.attribute_name}</td>
                        <td className="px-4 py-2 font-mono text-xs text-red-700">{m.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Dangling objects ({data.counts.dangling_objects})
              </h2>
              {data.counts.dangling_objects > 0 && (
                <button
                  onClick={async () => {
                    if (await ask(`Remove ${data.counts.dangling_objects} relation(s) pointing at objects that are no longer visible? The target objects themselves are untouched.`)) {
                      cleanupMutation.mutate({ remove_dangling_relations: true });
                    }
                  }}
                  disabled={cleanupMutation.isPending}
                  className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                >
                  Remove all
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Relations pointing at an object that still exists but is no longer visible from
              this workspace — usually because a global flag was turned off.
            </p>
            {data.dangling_objects.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">None found.</p>
            ) : (
              <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-2">From</th>
                      <th className="px-4 py-2">Relation</th>
                      <th className="px-4 py-2">To (hidden)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.dangling_objects.map((d) => (
                      <tr key={d.relation_id}>
                        <td className="px-4 py-2">
                          <Link to={`/assets/${d.from_asset_uid}`} className="text-slate-900 hover:underline">
                            {d.from_asset_uid}
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-slate-600">{d.relation_type}</td>
                        <td className="px-4 py-2 font-mono text-xs text-amber-700">{d.to_asset_uid}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Orphaned objects ({data.counts.orphaned_objects})
              </h2>
              {data.counts.orphaned_objects > 0 && (
                <button
                  onClick={async () => {
                    if (await askTyped(`Permanently delete ${data.counts.orphaned_objects} orphaned object(s)? This cannot be undone.`,
                                       nameOf(workspaceId!))) {
                      cleanupMutation.mutate({ delete_orphaned_objects: true });
                    }
                  }}
                  disabled={cleanupMutation.isPending}
                  className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                >
                  Delete all
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Objects with no inbound or outbound relation at all — completely disconnected from
              the rest of the graph. Not necessarily wrong, just worth a look.
            </p>
            {data.orphaned_objects.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">None found.</p>
            ) : (
              <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-2">Name</th>
                      <th className="px-4 py-2">Key</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.orphaned_objects.map((o) => (
                      <tr key={o.asset_uid}>
                        <td className="px-4 py-2">
                          <Link to={`/assets/${o.asset_uid}`} className="text-slate-900 hover:underline">
                            {o.name}
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-slate-500">{o.key}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
