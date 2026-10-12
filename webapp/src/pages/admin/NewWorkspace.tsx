import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, workspacesApi } from "../../api/client";
import { PackagePicker } from "../../components/PackagePicker";

/** Creating a workspace.
 *
 * The identifier is derived from the name rather than typed. It goes into
 * URLs, into PAT scopes and into every object key the imports derive, and
 * it cannot be changed afterwards — so the one place it is decided should
 * follow one rule, not whatever each admin types that day.
 *
 * Still editable, because a convention should be a default and not a cage:
 * an admin recreating a workspace that already exists elsewhere needs the
 * exact identifier they already have.
 */
export function NewWorkspace() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [customId, setCustomId] = useState<string | null>(null);
  const [packages, setPackages] = useState<string[]>([]);
  const [catalogue, setCatalogue] = useState("");

  const rule = useQuery({ queryKey: ["workspace-id-rule"], queryFn: workspacesApi.idRule });

  const trimmed = name.trim();
  const suggestion = useQuery({
    queryKey: ["workspace-id-suggestion", trimmed],
    queryFn: () => workspacesApi.suggestId(trimmed),
    enabled: trimmed.length > 0 && customId === null,
  });

  const id = customId ?? suggestion.data?.id ?? "";

  const createMutation = useMutation({
    // Sent only when overridden: otherwise the server derives it, so a form
    // left open since the rule changed cannot produce a stale identifier.
    mutationFn: () => workspacesApi.create(trimmed, customId?.trim() || undefined, packages,
                                           packages.includes("accelerator") ? catalogue || undefined : undefined),
    onSuccess: (ws) => navigate(`/workspaces/${ws.id}/members`),
  });

  return (
    <div className="max-w-lg">
      <h1 className="text-2xl font-semibold text-slate-900">New workspace</h1>
      <p className="mt-1 text-sm text-slate-500">
        Admin only. You'll automatically get full rights on the new workspace.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate();
        }}
        className="mt-6 space-y-5"
      >
        <div>
          <label className="block text-sm font-medium text-slate-700">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Divisione Acceleratori"
            required
            autoFocus
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <div className="flex items-baseline justify-between">
            <label className="block text-sm font-medium text-slate-700">Workspace id</label>
            {customId === null ? (
              <button
                type="button"
                onClick={() => setCustomId(id)}
                className="text-xs text-slate-500 underline hover:text-slate-700"
              >
                Set it myself
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setCustomId(null)}
                className="text-xs text-slate-500 underline hover:text-slate-700"
              >
                Use the name
              </button>
            )}
          </div>

          {customId === null ? (
            <div className="mt-1 rounded border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700">
              {trimmed ? id || "…" : <span className="text-slate-400">from the name</span>}
            </div>
          ) : (
            <input
              value={customId}
              onChange={(e) => setCustomId(e.target.value)}
              required
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
            />
          )}

          <p className="mt-1 text-xs text-slate-400">
            Used in URLs and PAT tokens — it can't be changed later.
            {suggestion.data?.taken && customId === null && (
              <>
                {" "}
                <span className="text-amber-700">
                  “{suggestion.data.base}” is taken, so this one is numbered.
                </span>
              </>
            )}
            {rule.data && (
              <>
                {" "}
                <Link className="underline" to="/admin/settings">
                  {rule.data.prefix
                    ? `Rule: “${rule.data.prefix}” prefix, ${rule.data.case}ercase, “${rule.data.separator}” between words.`
                    : `Rule: ${rule.data.case}ercase, “${rule.data.separator}” between words.`}
                </Link>
              </>
            )}
          </p>
        </div>

        <PackagePicker chosen={packages} onChange={setPackages} catalogue={catalogue} onCatalogue={setCatalogue} />

        {createMutation.isError && (
          <p className="text-sm text-red-600">
            {createMutation.error instanceof ApiError
              ? String(
                  ((createMutation.error.body as { detail?: string | { error?: string } })?.detail as { error?: string })?.error ??
                    (createMutation.error.body as { detail?: string })?.detail ??
                    JSON.stringify(createMutation.error.body),
                )
              : "Failed to create workspace"}
          </p>
        )}

        <button
          type="submit"
          disabled={createMutation.isPending || !trimmed || !id}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {createMutation.isPending ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </div>
  );
}
