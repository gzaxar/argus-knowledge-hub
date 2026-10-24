import { useQuery } from "@tanstack/react-query";
import { Fragment } from "react";
import { Link, useParams } from "react-router-dom";
import { importPaths } from "./paths";
import { importsApi } from "../../api/client";
import { importSourceLabel } from "../../api/types";

/** Every counter an importer can report, in the order they make sense to
 * read. One status page serves all four sources, so it shows what the run
 * actually produced rather than assuming an object import: a Confluence
 * run reporting "Schemas 0, Assets 0, Relations 0" says nothing about
 * whether the pages arrived. */
const COUNTS: [string, string][] = [
  ["schemas", "Types"],
  ["assets", "Objects"],
  ["relations", "Relations"],
  ["documents", "Documents"],
  ["documents_updated", "Documents updated"],
  ["documents_unchanged", "Documents unchanged (already current)"],
  ["tickets", "Tickets"],
  ["asset_links", "Links to objects"],
  ["page_tree_links", "Page hierarchy links"],
  ["attachments", "Attachments"],
  ["comments", "Comments"],
  ["history", "History entries"],
  ["labels", "QR codes"],
];

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-slate-100 text-slate-600",
  running: "bg-blue-100 text-blue-700",
  succeeded: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

export function ImportStatus() {
  const { uid, workspaceId } = useParams<{ uid: string; workspaceId: string }>();

  const { data, isLoading } = useQuery({
    queryKey: ["imports", uid],
    queryFn: () => importsApi.get(uid!),
    refetchInterval: (query) =>
      query.state.data && (query.state.data.status === "pending" || query.state.data.status === "running")
        ? 1500
        : false,
  });

  return (
    <div className="max-w-2xl">
      <Link to={importPaths.list(workspaceId!)} className="text-sm text-slate-500 hover:underline">
        &larr; Imports
      </Link>

      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-3">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-900">
              {importSourceLabel(data.source)} import
            </h1>
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[data.status] ?? ""}`}
            >
              {data.status}
            </span>
          </div>

          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
            <dl className="grid grid-cols-2 gap-y-3 text-sm">
              {/* A fact about this run, not about whichever workspace is
                  selected now: an import writes into one workspace and
                  afterwards nothing else on the page says which. */}
              <dt className="text-slate-500">Wrote into workspace</dt>
              <dd className="font-medium text-slate-900">{data.workspace_id}</dd>

              <dt className="text-slate-500">Progress</dt>
              <dd className="text-slate-900">{data.progress ?? "—"}</dd>

              {/* Only the counters this run reported — "did it actually
                  bring the attachments over?" was a question that
                  previously needed a database query. */}
              {COUNTS.map(([key, label]) =>
                data.counts[key] !== undefined ? (
                  <Fragment key={key}>
                    <dt className="text-slate-500">{label}</dt>
                    <dd className="text-slate-900">{data.counts[key]}</dd>
                  </Fragment>
                ) : null,
              )}
              {Object.keys(data.counts).length === 0 && data.status !== "failed" && (
                <>
                  <dt className="text-slate-500">Counts</dt>
                  <dd className="text-slate-400">not reported yet</dd>
                </>
              )}

              {data.counts.errors !== undefined && (
                <>
                  <dt className="text-slate-500">Errors</dt>
                  <dd className="text-slate-900">{data.counts.errors}</dd>
                </>
              )}

              <dt className="text-slate-500">Started</dt>
              <dd className="text-slate-900">
                {data.started_at ? new Date(data.started_at).toLocaleString() : "—"}
              </dd>

              <dt className="text-slate-500">Completed</dt>
              <dd className="text-slate-900">
                {data.completed_at ? new Date(data.completed_at).toLocaleString() : "—"}
              </dd>
            </dl>

            {data.error && (
              <div className="mt-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {data.error}
              </div>
            )}
          </div>

          {data.warnings.length > 0 && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-medium text-amber-800">
                {data.warnings.length} constraint warning{data.warnings.length === 1 ? "" : "s"}
              </p>
              <p className="mt-1 text-xs text-amber-700">
                These objects were imported anyway — their values just don't meet a
                unique/cardinality/regex rule configured on their type.
              </p>
              <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto text-xs text-amber-900">
                {data.warnings.map((w, i) => (
                  <li key={i} className="border-t border-amber-100 pt-1 first:border-t-0 first:pt-0">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.status === "succeeded" && (
            <p className="mt-4 text-sm text-slate-500">
              {data.source === "dokuwiki"
                ? "The wiki's pages are now under Documentation, published, with their pictures; a page under another is its child."
                : data.source === "confluence" || data.source === "git"
                ? "Imported pages are now under Documentation, typed from their labels."
                : data.source === "jira-issues"
                  ? "Imported tickets are now under Tickets, on the list and the board."
                  : "Imported types now appear in the Object types tree."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
