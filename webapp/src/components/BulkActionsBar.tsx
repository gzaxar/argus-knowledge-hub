import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { transfersApi } from "../api/client";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import type { BulkDeleteResult, TransferMode } from "../api/types";
import { WorkspaceTargetPicker } from "./WorkspaceTargetPicker";

type Kind = "asset_uids" | "document_uids" | "issue_uids";

/** A bulk action bar — "copy/move N selected to workspace…" plus, where a
 * `bulkDelete` call is given, "Delete N selected". One bar, reused on every
 * list page that supports selecting assets, documents or tickets. It appears
 * only once something is selected: an empty bar is only noise above a list. */
export function BulkActionsBar({
  selected,
  kind,
  label,
  onStarted,
  onClear,
  bulkDelete,
  canTransfer = true,
  extra,
}: {
  selected: Set<string>;
  kind: Kind;
  label: string;
  onStarted: () => void;
  onClear: () => void;
  /** Enables the Delete button when given. Called with the selected uids;
   * onStarted() runs afterward the same way it does for copy/move. */
  bulkDelete?: (uids: string[]) => Promise<BulkDeleteResult>;
  /** Copying or moving needs the right to create (and, to move, to delete) here; without it the bar offers
   * neither. The server checks again. */
  canTransfer?: boolean;
  /** Further actions of this list (a document's "move to type"). */
  extra?: React.ReactNode;
}) {
  const navigate = useNavigate();
  const workspaceId = useCurrentWorkspaceId();
  const [target, setTarget] = useState("");
  const [mode, setMode] = useState<TransferMode>("copy");

  const transfer = useMutation({
    mutationFn: () =>
      transfersApi.create({ target_workspace_id: target, mode, [kind]: [...selected] }),
    onSuccess: (job) => {
      onStarted();
      if (workspaceId) navigate(`/workspaces/${workspaceId}/transfers/${job.uid}`);
    },
    onError: (err) => alert(err instanceof Error ? err.message : "Could not start the transfer."),
  });

  const deleteMutation = useMutation({
    mutationFn: () => bulkDelete!([...selected]),
    onSuccess: (result) => {
      onStarted();
      if (result.not_found.length) {
        alert(`Deleted ${result.deleted}. ${result.not_found.length} could not be found.`);
      }
    },
    onError: () => alert(`Could not delete those ${label}.`),
  });

  if (selected.size === 0) return null;
  return (
    <div role="region" aria-label={`Actions on the selected ${label}`}
         className="sticky top-0 z-20 flex flex-wrap items-center gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-1.5 text-sm shadow-sm">
      <span className="font-medium text-slate-800" aria-live="polite">{selected.size} selected</span>
      {extra}
      {canTransfer && (
        <>
          {extra && <span aria-hidden className="text-slate-300">|</span>}
          <label className="sr-only" htmlFor={`bulk-mode-${kind}`}>Copy or move</label>
          <select
            id={`bulk-mode-${kind}`}
            value={mode}
            onChange={(e) => setMode(e.target.value as TransferMode)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            <option value="copy">Copy</option>
            <option value="move">Move</option>
          </select>
          <span className="text-slate-500">to</span>
          <WorkspaceTargetPicker excludeWorkspaceId={workspaceId} value={target} onChange={setTarget} />
          <button
            type="button"
            onClick={() => transfer.mutate()}
            disabled={!target || transfer.isPending}
            className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {transfer.isPending ? "Starting…" : mode === "copy" ? "Copy" : "Move"}
          </button>
        </>
      )}
      {bulkDelete && (
        <button
          type="button"
          onClick={() => {
            if (confirm(`Delete ${selected.size} ${label}? This cannot be undone.`)) {
              deleteMutation.mutate();
            }
          }}
          disabled={deleteMutation.isPending}
          className="rounded border border-red-200 bg-white px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          {deleteMutation.isPending ? "Deleting…" : "Delete"}
        </button>
      )}
      <button type="button" onClick={onClear} className="ml-auto text-sm text-slate-600 hover:underline">
        Clear selection
      </button>
    </div>
  );
}
