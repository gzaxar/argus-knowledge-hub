import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { transfersApi, type TransferPreview } from "../api/client";
import { problem } from "../pages/catalogue/catalogueText";
import { TransferReport } from "./TransferReport";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import type { TransferMode } from "../api/types";
import { WorkspaceTargetPicker } from "./WorkspaceTargetPicker";

type ItemKind = "asset" | "document" | "issue" | "type";

const FIELD: Record<ItemKind, "asset_uids" | "document_uids" | "issue_uids" | "type_uids"> = {
  asset: "asset_uids",
  document: "document_uids",
  issue: "issue_uids",
  type: "type_uids",
};

/** A "Copy to workspace…" / "Move to workspace…" popover for a single item
 * on its own detail page — the one-at-a-time counterpart to BulkActionsBar's
 * multi-select version on list pages. For a type, also offers whether to
 * bring its instances and/or its child types along. */
export function TransferItemAction({
  kind,
  uid,
  hasChildren,
  buttonClassName,
}: {
  kind: ItemKind;
  uid: string;
  /** Only meaningful for kind="type" — shows the include-descendants toggle. */
  hasChildren?: boolean;
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [mode, setMode] = useState<TransferMode>("copy");
  const [includeInstances, setIncludeInstances] = useState(true);
  const [includeDescendantTypes, setIncludeDescendantTypes] = useState(false);
  const [force, setForce] = useState(false);
  const navigate = useNavigate();
  const workspaceId = useCurrentWorkspaceId();

  const body = () => ({
    target_workspace_id: target,
    mode,
    [FIELD[kind]]: [uid],
    ...(kind === "type"
      ? { include_instances: includeInstances, include_descendant_types: includeDescendantTypes }
      : {}),
    ...(kind === "type" && mode === "copy" ? { force } : {}),
  });
  // A record's transfer is previewed first: its reconciliation report, for the target and mode chosen.
  const [report, setReport] = useState<{ key: string; data: TransferPreview } | null>(null);
  const key = `${mode}:${target}`;
  const preview = useMutation({
    mutationFn: () => transfersApi.preview(body()),
    onSuccess: (data) => setReport({ key, data }),
  });
  const previewed = kind !== "asset" || report?.key === key;
  const transfer = useMutation({
    mutationFn: () => transfersApi.create(body()),
    onSuccess: (job) => {
      setOpen(false);
      if (workspaceId) navigate(`/workspaces/${workspaceId}/transfers/${job.uid}`);
    },
    onError: (err) => alert(err instanceof Error ? err.message : "Could not start the transfer."),
  });

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={
          buttonClassName ?? "rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        }
      >
        Copy/Move…
      </button>
      {open && (
        <div className={`absolute right-0 z-10 mt-2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg ${
          report ? "w-[min(32rem,90vw)]" : "w-72"}`}>
          <div className="flex items-center gap-2">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as TransferMode)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="copy">Copy</option>
              <option value="move">Move</option>
            </select>
            <span className="text-sm text-slate-400">to</span>
          </div>
          <div className="mt-2">
            <WorkspaceTargetPicker excludeWorkspaceId={workspaceId} value={target} onChange={setTarget} />
          </div>
          {kind === "type" && (
            <div className="mt-2 space-y-1">
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={includeInstances}
                  onChange={(e) => setIncludeInstances(e.target.checked)}
                />
                Include its objects/documents/tickets
              </label>
              {hasChildren && (
                <label className="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={includeDescendantTypes}
                    onChange={(e) => setIncludeDescendantTypes(e.target.checked)}
                  />
                  Include its child type(s)
                </label>
              )}
              {mode === "copy" && (
                <label
                  className="flex items-center gap-2 text-xs text-slate-600"
                  title="If a type with the same name already exists at the same level in the target, merge into it instead of refusing."
                >
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                  Force overwrite
                </label>
              )}
            </div>
          )}
          {report?.key === key && <div className="mt-3 max-h-80 overflow-y-auto"><TransferReport report={report.data} /></div>}
          {preview.isError && <p className="mt-2 text-xs text-red-600">{problem(preview.error)}</p>}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-sm text-slate-500 hover:underline"
            >
              Cancel
            </button>
            {kind === "asset" && (
              <button
                type="button"
                onClick={() => preview.mutate()}
                disabled={!target || preview.isPending}
                className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50 disabled:opacity-50"
              >
                {preview.isPending ? "Checking…" : "Preview"}
              </button>
            )}
            <button
              type="button"
              onClick={() => transfer.mutate()}
              disabled={!target || !previewed || transfer.isPending}
              title={previewed ? undefined : "Preview the transfer first"}
              className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {transfer.isPending ? "Starting…" : mode === "copy" ? "Copy" : "Move"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
