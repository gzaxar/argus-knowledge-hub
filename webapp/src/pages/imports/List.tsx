import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { importConfigsApi, importsApi } from "../../api/client";
import { MERGE_STRATEGIES, importSourceLabel, type ImportConfig } from "../../api/types";
import { IMPORT_SOURCES, importPaths } from "./paths";
import { WorkspaceScopeBanner } from "../../components/WorkspaceScopeBanner";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-slate-100 text-slate-600",
  running: "bg-blue-100 text-blue-700",
  succeeded: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** A saved import's schedule, and when it next runs. */
function ScheduleCell({ c }: { c: ImportConfig }) {
  if (!c.schedule_kind || c.schedule_kind === "off") return <span className="text-slate-400">No</span>;
  const when = c.schedule_kind === "hours" ? `Every ${c.schedule_every_hours} h`
    : c.schedule_kind === "daily" ? `Daily at ${c.schedule_time}`
    : `${DAYS[c.schedule_weekday ?? 0]} at ${c.schedule_time}`;
  return (
    <span>
      {when}
      {c.schedule_timezone && c.schedule_kind !== "hours" && <span className="text-xs text-slate-400"> {c.schedule_timezone}</span>}
      {c.running_since
        ? <span className="block text-xs text-blue-700">running now</span>
        : c.next_run_at && <span className="block text-xs text-slate-500">next {new Date(c.next_run_at).toLocaleString()}</span>}
    </span>
  );
}

function SavedConfigs({ workspaceId }: { workspaceId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [runningUid, setRunningUid] = useState<string | null>(null);

  const configs = useQuery({ queryKey: ["import-configs"], queryFn: importConfigsApi.list });

  const runMutation = useMutation({
    mutationFn: (uid: string) => {
      setRunningUid(uid);
      return importConfigsApi.run(uid);
    },
    onSuccess: (config) => {
      queryClient.invalidateQueries({ queryKey: ["import-configs"] });
      navigate(importPaths.job(workspaceId, config.last_import_job_uid!));
    },
    onSettled: () => setRunningUid(null),
  });

  const deleteMutation = useMutation({
    mutationFn: importConfigsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["import-configs"] }),
  });

  if (configs.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!configs.data || configs.data.length === 0) {
    return <p className="text-sm text-slate-500">No saved configurations yet.</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-4 py-2">Name</th>
            <th className="px-4 py-2">Source</th>
            <th className="px-4 py-2">Merge strategy</th>
            <th className="px-4 py-2">Runs by itself</th>
            <th className="px-4 py-2">Last run</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {configs.data.map((c) => (
            <tr key={c.uid} className="hover:bg-slate-50">
              <td className="px-4 py-2 font-medium text-slate-900">{c.name}</td>
              <td className="px-4 py-2 text-slate-600">{importSourceLabel(c.source)}</td>
              <td className="px-4 py-2 text-slate-600">
                {MERGE_STRATEGIES.find((s) => s.value === c.merge_strategy)?.label ?? c.merge_strategy}
              </td>
              <td className="px-4 py-2 text-slate-600"><ScheduleCell c={c} /></td>
              <td className="px-4 py-2 text-slate-500">
                {c.last_run_at ? new Date(c.last_run_at).toLocaleString() : "Never"}
                {c.last_outcome && (
                  <span className={`ml-2 rounded px-1.5 py-0.5 text-[11px] ${
                    c.last_outcome === "succeeded" ? "bg-green-100 text-green-700"
                      : c.last_outcome === "failed" ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600"}`}
                        title={c.last_message ?? undefined}>
                    {c.last_outcome === "succeeded" ? "scheduled run ok" : c.last_outcome === "failed" ? "scheduled run failed" : "skipped"}
                  </span>
                )}
                {c.last_outcome === "failed" && c.last_message && (
                  <span className="block max-w-xs truncate text-xs text-red-600" title={c.last_message}>{c.last_message}</span>
                )}
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  onClick={() => runMutation.mutate(c.uid)}
                  disabled={runningUid === c.uid}
                  className="mr-3 rounded bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  {runningUid === c.uid ? "Starting…" : "Run"}
                </button>
                <Link
                  to={importPaths.editConfig(workspaceId, c.uid)}
                  className="mr-3 text-xs text-slate-500 hover:text-slate-900"
                >
                  Edit
                </Link>
                <button
                  onClick={() => {
                    if (confirm(`Delete configuration "${c.name}"?`)) deleteMutation.mutate(c.uid);
                  }}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ImportList() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data, isLoading } = useQuery({
    queryKey: ["imports"],
    queryFn: () => importsApi.list(),
    refetchInterval: (query) =>
      query.state.data?.some((j) => j.status === "pending" || j.status === "running")
        ? 2000
        : false,
  });

  if (!workspaceId) return null;

  return (
    <div>
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Imports</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Everything this workspace pulls in from elsewhere — objects, tickets and
            documentation — with one history of what ran.
          </p>
          <WorkspaceScopeBanner action="These imports belong to" />
        </div>
        <Link
          to={importPaths.create(workspaceId)}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          New configuration
        </Link>
      </div>

      {/* Every source in one place. Reaching this page only from the Assets
          and Tickets sections left Confluence with no entry point at all. */}
      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Sources
      </h2>
      <div className="mt-2 grid grid-cols-2 gap-3">
        {IMPORT_SOURCES.map((s) => (
          <Link
            key={s.source}
            to={
              "href" in s
                ? s.href
                : "upload" in s && s.upload
                  ? importPaths.markdown(workspaceId)
                  : importPaths.create(workspaceId, s.source)
            }
            className="rounded-lg border border-slate-200 bg-white p-3 hover:border-slate-400"
          >
            <p className="text-sm font-medium text-slate-900">{s.label}</p>
            <p className="mt-0.5 text-xs text-slate-500">{s.blurb}</p>
          </Link>
        ))}
      </div>

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Saved configurations
      </h2>
      <div className="mt-2">
        <SavedConfigs workspaceId={workspaceId} />
      </div>

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-slate-500">
        History
      </h2>

      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && data.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">No imports yet.</p>
      )}

      {data && data.length > 0 && (
        <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Source</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Progress</th>
                <th className="px-4 py-2">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((job) => (
                <tr key={job.uid} className="hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <Link
                      to={importPaths.job(workspaceId, job.uid)}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {importSourceLabel(job.source)}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status] ?? ""}`}
                    >
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{job.progress ?? "—"}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {new Date(job.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
