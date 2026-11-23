/** §18.2: each review queue's size and age in working days, against its
 * targets; overdue items go to the backup steward, then the governance group. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ledgerApi } from "../../api/client";
import { errorText } from "./LedgerPanels";
import { Card } from "./ui";

export function QueueAgeingCard() {
  const queryClient = useQueryClient();
  const dash = useQuery({ queryKey: ["review-queues"], queryFn: ledgerApi.queues, retry: false });
  const escalate = useMutation({
    mutationFn: ledgerApi.escalateReview,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["review-queues"] }),
  });
  if (!dash.data) return null;
  const d = dash.data;
  const buckets = d.queues[0]?.buckets.map((b) => b.label) ?? [];
  return (
    <Card
      title="Queue ageing"
      action={
        <button onClick={() => escalate.mutate()} className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">
          Escalate overdue now
        </button>
      }
    >
      <p className="py-1 text-xs text-slate-500">
        Ages in working days. Past its target an item goes to the backup steward
        {d.backup_steward ? ` (${d.backup_steward})` : ""}, then to the governance group
        {d.governance.length ? ` (${d.governance.join(", ")})` : ""}.
        {!d.steward && " No steward is named for this workspace's domain yet."}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-400">
            <tr>
              <th className="py-1 font-normal">Queue</th>
              <th className="font-normal" title="due / to backup / to governance">Targets</th>
              <th className="text-right font-normal">Open</th>
              {buckets.map((b) => (
                <th key={b} className="text-right font-normal">{b} d</th>
              ))}
              <th className="text-right font-normal">Overdue</th>
              <th className="text-right font-normal">At backup</th>
              <th className="text-right font-normal">At governance</th>
              <th className="text-right font-normal">Oldest</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {d.queues.map((q) => (
              <tr key={q.queue} className={q.size ? "" : "text-slate-400"}>
                <td className="py-1.5 pr-3">{q.label}</td>
                <td className="pr-3 text-xs text-slate-500">
                  {q.targets.due} / {q.targets.backup} / {q.targets.governance}
                </td>
                <td className="text-right tabular-nums">{q.size}</td>
                {q.buckets.map((b) => (
                  <td key={b.label} className="text-right tabular-nums text-slate-600">{b.count || "·"}</td>
                ))}
                <td className={`text-right tabular-nums ${q.overdue ? "font-medium text-red-600" : ""}`}>{q.overdue || "·"}</td>
                <td className="text-right tabular-nums">{q.at_backup || "·"}</td>
                <td className={`text-right tabular-nums ${q.at_governance ? "font-medium text-red-600" : ""}`}>{q.at_governance || "·"}</td>
                <td className="text-right tabular-nums">{q.oldest ?? "·"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {escalate.data && (
        <p className="mt-2 text-xs text-slate-600">
          Escalated {escalate.data.backup} to the backup steward and {escalate.data.governance} to the governance group
          {escalate.data.without_recipient ? `; ${escalate.data.without_recipient} had nobody to go to` : ""}.
        </p>
      )}
      {escalate.isError && <p className="mt-2 text-xs text-red-600">{errorText(escalate.error)}</p>}
    </Card>
  );
}
