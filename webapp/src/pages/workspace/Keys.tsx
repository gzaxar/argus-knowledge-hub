import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, workspacesApi } from "../../api/client";

const TOKENS: [string, string][] = [
  ["{WS}", "the workspace id, in capitals"],
  ["{TYPE}", "the type's code: its key prefix if the type sets one, else its initials (Ion Pump → IP, Magnet → MAG)"],
  ["{YYYY} / {YY}", "the year"],
  ["{SEQ} / {SEQ:4}", "the next number, padded to 4 digits; required, exactly once"],
];

const EXAMPLES = ["{WS}-{TYPE}-{SEQ:4}", "{WS}-{SEQ:5}", "{TYPE}-{YYYY}-{SEQ:4}"];

export function WorkspaceKeys() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const rule = useQuery({
    queryKey: ["key-rule", workspaceId],
    queryFn: () => workspacesApi.keyRule(workspaceId!),
    enabled: !!workspaceId,
    retry: false,
  });
  const [pattern, setPattern] = useState("");
  useEffect(() => {
    if (rule.data) setPattern(rule.data.pattern);
  }, [rule.data]);

  const save = useMutation({
    mutationFn: (value: string) => workspacesApi.saveKeyRule(workspaceId!, value),
    onSuccess: (data) => {
      queryClient.setQueryData(["key-rule", workspaceId], data);
      queryClient.invalidateQueries({ queryKey: ["asset-next-key"] });
    },
  });

  if (rule.isError) {
    const forbidden = rule.error instanceof ApiError && rule.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden ? "Owners and admins only." : "Failed to load the key rule."}
      </p>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold text-slate-900">Record keys</h1>
      <p className="mt-1 text-sm text-slate-500">
        Workspace <span className="font-mono text-xs">{workspaceId}</span>. A record created without a key gets
        the next one from this pattern. Keys are unique across every workspace, so keep{" "}
        <span className="font-mono text-xs">{"{WS}"}</span> in it unless the rest is unique on its own. Changing
        the pattern changes only new keys: existing ones stay, since labels and links carry them. Tickets take their
        key from it too, with <span className="font-mono text-xs">TCK</span> as their type, and so do the records a
        beam model brings.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(pattern.trim());
        }}
        className="mt-6 space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <label className="block text-sm font-medium text-slate-700">Pattern</label>
        <input
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
        />
        <div className="flex flex-wrap gap-2 text-xs">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setPattern(ex)}
              className="rounded border border-slate-200 px-2 py-0.5 font-mono text-slate-600 hover:bg-slate-50"
            >
              {ex}
            </button>
          ))}
        </div>
        {rule.data && (
          <p className="text-sm text-slate-600">
            Now: <span className="font-mono">{rule.data.pattern}</span>
            {rule.data.is_default && <span className="text-slate-400"> (the default)</span>}. A first ion pump would
            be <span className="font-mono">{rule.data.example}</span>.
          </p>
        )}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={save.isPending || !rule.data}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => save.mutate("")}
            disabled={save.isPending || rule.data?.is_default}
            className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50"
          >
            Back to the default
          </button>
          {save.isError && <p className="text-sm text-red-600">{(save.error as Error).message}</p>}
        </div>
      </form>

      <table className="mt-6 w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {TOKENS.map(([token, meaning]) => (
            <tr key={token}>
              <td className="whitespace-nowrap py-1.5 pr-4 font-mono text-xs text-slate-700">{token}</td>
              <td className="py-1.5 text-slate-600">{meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-500">
        Each prefix counts on its own: with {"{TYPE}"} every type has its own sequence. A number someone already used
        as a key is skipped. A type's key prefix is set in its metadata as{" "}
        <span className="font-mono">key_prefix</span>.{" "}
        <Link to="/admin/workspaces" className="text-indigo-600 hover:underline">
          Back to workspaces
        </Link>
      </p>
    </div>
  );
}
