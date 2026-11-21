import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { issuesApi, portalApi, portalError } from "../../api/client";
import type { Issue } from "../../api/types";

/** On a ticket the service portal made: who asked, from where, under which service and team — and moving it to
 *  another service or team of this workspace. The team is a queue, not the assignee. */
export function ServiceRequestCard({ issue }: { issue: Issue }) {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["issue-service-request", issue.uid, issue.state], queryFn: () => issuesApi.serviceRequest(issue.uid),
    enabled: !!issue.service_uid, retry: false });
  const queues = useQuery({ queryKey: ["support-queues"], queryFn: portalApi.queues, enabled: !!issue.service_uid,
    staleTime: 60_000 });
  const [error, setError] = useState<string | null>(null);
  const move = useMutation({
    mutationFn: (patch: { service_uid?: string; assigned_group_uid?: string }) => issuesApi.update(issue.uid, patch),
    onSuccess: () => {
      setError(null);
      for (const k of [["issues", issue.uid], ["issue-service-request", issue.uid], ["issue-history", issue.uid], ["issues"]])
        qc.invalidateQueries({ queryKey: k });
    },
    onError: (e) => setError(portalError(e)),
  });
  const d = info.data;
  if (!issue.service_uid || !d) return null;
  return (
    <section aria-label="Service request" className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-4 text-sm">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-indigo-800">Service request</h2>
      <dl className="mt-2 space-y-2">
        {d.requester && <div><dt className="text-xs text-slate-500">Requester</dt>
          <dd>{d.requester.name || d.requester.email}{d.requester.name && d.requester.email ? ` · ${d.requester.email}` : ""}</dd></div>}
        {d.origin_name && <div><dt className="text-xs text-slate-500">Reported from</dt><dd>{d.origin_name}</dd></div>}
        {d.request_type_name && <div><dt className="text-xs text-slate-500">Request type</dt><dd>{d.request_type_name}</dd></div>}
        <div><dt className="text-xs text-slate-500">Requester sees</dt><dd>{d.requester_status.label}</dd></div>
        <div>
          <dt><label htmlFor="sr-service" className="text-xs text-slate-500">Service</label></dt>
          <dd><select id="sr-service" value={issue.service_uid ?? ""} disabled={move.isPending}
                      onChange={(e) => move.mutate({ service_uid: e.target.value })}
                      className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm">
            {d.services.map((s) => <option key={s.uid} value={s.uid}>{s.name}</option>)}
          </select></dd>
        </div>
        <div>
          <dt><label htmlFor="sr-team" className="text-xs text-slate-500">Team queue</label></dt>
          <dd><select id="sr-team" value={issue.assigned_group_uid ?? ""} disabled={move.isPending}
                      onChange={(e) => move.mutate({ assigned_group_uid: e.target.value })}
                      className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm">
            {!issue.assigned_group_uid && <option value="">—</option>}
            {(queues.data?.teams ?? (d.team ? [{ uid: d.team.uid, name: d.team.name, active: true }] : [])).map((t) =>
              <option key={t.uid} value={t.uid}>{t.name}</option>)}
          </select></dd>
        </div>
      </dl>
      {d.route_reason && <p className="mt-2 text-xs text-slate-500">{d.route_reason}</p>}
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </section>
  );
}
