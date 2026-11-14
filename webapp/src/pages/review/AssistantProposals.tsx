import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { problemText, proposalsApi, type AssistantProposal } from "../../api/client";
import { Card } from "../../components/hub/ui";

const KIND: Record<string, string> = {
  create: "New record", update: "Change", relate: "Relation", unrelate: "Remove relation", ticket: "Ticket",
  document: "Draft document",
};

const linkOf = (p: AssistantProposal) => {
  const uid = p.result?.uid;
  if (!uid) return null;
  return p.kind === "ticket" ? `/tickets/${uid}` : p.kind === "document" ? `/documents/${uid}` : `/assets/${uid}`;
};

/** Changes assistants proposed through MCP (Claude, ChatGPT…): nothing happens until a person applies them, with
 *  their own permissions and in their name. Grouped by the day's batch of each token or person. */
export function AssistantProposals() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["assistant-proposals"], queryFn: () => proposalsApi.list(), refetchInterval: 30_000 });
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [outcome, setOutcome] = useState<AssistantProposal[]>([]);
  const after = (rows: AssistantProposal[]) => {
    setOutcome(rows);
    setChosen(new Set());
    queryClient.invalidateQueries({ queryKey: ["assistant-proposals"] });
  };
  const apply = useMutation({ mutationFn: (ids: string[]) => proposalsApi.apply(ids), onSuccess: after });
  const discard = useMutation({ mutationFn: (ids: string[]) => proposalsApi.discard(ids), onSuccess: after });

  const rows = list.data ?? [];
  if (rows.length === 0 && outcome.length === 0) return null;
  const groups = new Map<string, AssistantProposal[]>();
  for (const r of rows) groups.set(r.conversation.id, [...(groups.get(r.conversation.id) ?? []), r]);
  const toggle = (id: string) => setChosen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const busy = apply.isPending || discard.isPending;
  const failed = apply.error ?? discard.error;

  return (
    <Card title={`Proposed by assistants (${rows.length})`}>
      <p className="text-xs text-slate-500">
        Sent through the MCP server by an assistant such as Claude or ChatGPT. Applying one makes the change with your
        permissions and in your name, through the same checks as the forms; discarding it changes nothing.
      </p>
      {failed && <p className="mt-2 text-sm text-red-600">{problemText(failed)}</p>}
      {outcome.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs" aria-live="polite">
          {outcome.map((o) => (
            <li key={o.id} className={o.status === "failed" ? "text-red-700" : "text-slate-600"}>
              {o.status === "applied" ? "Applied" : o.status === "discarded" ? "Discarded" : "Failed"}: {o.summary}
              {o.error && ` — ${o.error}`}
              {o.status === "applied" && linkOf(o) && <> · <Link to={linkOf(o)!} className="text-indigo-700 underline">open</Link></>}
            </li>
          ))}
        </ul>
      )}
      {[...groups.values()].map((items) => (
        <section key={items[0].conversation.id} className="mt-3" aria-label={items[0].conversation.title}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-slate-800">{items[0].conversation.title}</h3>
            <button type="button" className="text-xs text-indigo-700 underline"
                    onClick={() => setChosen((s) => new Set([...s, ...items.map((i) => i.id)]))}>choose all</button>
          </div>
          <ul className="mt-1 divide-y divide-slate-100">
            {items.map((p) => (
              <li key={p.id} className="flex items-start gap-2 py-1.5 text-sm">
                <input type="checkbox" className="mt-1" checked={chosen.has(p.id)} onChange={() => toggle(p.id)}
                       aria-label={`Choose ${p.summary}`} />
                <div className="min-w-0">
                  <span className="mr-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{KIND[p.kind] ?? p.kind}</span>
                  <span className="text-slate-900">{p.summary}</span>
                  <span className="ml-1 text-xs text-slate-400">A{p.number}</span>
                  {p.reason && <p className="text-xs text-slate-500">Why: {p.reason}</p>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {rows.length > 0 && (
        <div className="mt-3 flex gap-2">
          <button type="button" disabled={!chosen.size || busy} onClick={() => apply.mutate([...chosen])}
                  className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">
            {apply.isPending ? "Applying…" : `Apply ${chosen.size || ""}`.trim()}
          </button>
          <button type="button" disabled={!chosen.size || busy} onClick={() => discard.mutate([...chosen])}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40">Discard</button>
          <span className="self-center text-xs text-slate-500">
            A relation to a record proposed in the same batch needs that record applied first, or with it.
          </span>
        </div>
      )}
    </Card>
  );
}
