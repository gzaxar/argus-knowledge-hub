import { ask } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { globalValuesApi } from "../../api/client";

export function GlobalValueList() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["global-values"],
    queryFn: globalValuesApi.list,
  });
  const deleteMutation = useMutation({
    mutationFn: globalValuesApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["global-values"] }),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Global Values</h1>
        <Link
          to="/global-values/new"
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          New value
        </Link>
      </div>

      {isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-6 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Key</th>
                <th className="px-4 py-2">Context</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Options</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((gv) => (
                <tr key={gv.uid} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">
                    {gv.name}
                    {/* Next to Ticket workflows it read as a copy of the default workflow's states: it is where the
                        board and the list take them from. */}
                    {gv.applies_to === "tickets" && gv.key === "status" && (
                      <span className="block text-xs font-normal text-slate-500" data-testid="ticket-status-note">
                        The states of tickets that follow the default workflow: the board's columns and the list's
                        filter. A type with its own workflow uses that one (<Link to="/tickets/workflows"
                        className="text-indigo-600 hover:underline">Ticket workflows</Link>).
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-slate-500">{gv.key}</td>
                  <td className="px-4 py-2 text-slate-500 capitalize">{gv.applies_to}</td>
                  <td className="px-4 py-2 text-slate-500">{gv.type}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {gv.options?.map((o) => o.value).join(", ") ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      to={`/global-values/${gv.uid}/edit`}
                      className="mr-3 text-slate-500 hover:text-slate-900"
                    >
                      Edit
                    </Link>
                    <button
                      onClick={async () => {
                        if (await ask(`Delete "${gv.name}"?`)) deleteMutation.mutate(gv.uid);
                      }}
                      className="text-red-500 hover:text-red-700"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                    No global values yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
