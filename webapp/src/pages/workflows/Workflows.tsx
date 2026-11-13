/** Ticket workflows: the states each ticket type moves through, imported
 * from Jira or written here, bound to ticket types, and rehearsed against
 * the migrated tickets' Jira history before the ticket cutover. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { schemasApi, workflowApi } from "../../api/client";
import type { Rehearsal, WorkflowDef } from "../../api/ledgerTypes";
import { errorText } from "../../components/hub/LedgerPanels";
import { Card, Empty } from "../../components/hub/ui";

const TONE: Record<string, string> = {
  open: "bg-slate-100 text-slate-700",
  active: "bg-indigo-50 text-indigo-700",
  waiting: "bg-amber-50 text-amber-800",
  done: "bg-emerald-50 text-emerald-700",
};

export function WorkflowsPage() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["workflows"], queryFn: workflowApi.list });
  const [jira, setJira] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["workflows"] });
  const importJira = useMutation({ mutationFn: () => workflowApi.importJira(JSON.parse(jira)), onSuccess: () => { setJira(""); refresh(); } });
  const escalate = useMutation({ mutationFn: workflowApi.escalate });
  const valid = (() => {
    try {
      JSON.parse(jira);
      return true;
    } catch {
      return false;
    }
  })();
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Ticket workflows</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Each ticket type moves through its own states. Tickets without one follow the built-in workflow.
          </p>
        </div>
        <button onClick={() => escalate.mutate()} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs">
          Run escalation timers now
        </button>
      </div>
      {escalate.data && <p className="text-sm text-slate-600">{escalate.data.escalated} ticket(s) escalated.</p>}
      {(list.data?.workflows ?? []).length === 0 && <Empty>No workflow yet: every ticket follows the built-in one.</Empty>}
      {(list.data?.workflows ?? []).map((wf) => (
        <WorkflowCard key={wf.uid} wf={wf} onChanged={refresh} />
      ))}
      {list.data && <WorkflowCard wf={list.data.builtin} onChanged={refresh} builtin />}
      <Card title="Import a Jira workflow">
        <p className="text-xs text-slate-500">
          Paste the workflow as JSON: <span className="font-mono">{"{name, statuses: [{name, statusCategory: {key}}], transitions: [{name, from: [...], to}]}"}</span>.
          Statuses keep their names; categories map new → open, indeterminate → active, done → done.
        </p>
        <textarea value={jira} onChange={(e) => setJira(e.target.value)} rows={6} spellCheck={false} className="mt-2 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
        {importJira.isError && <p className="text-sm text-red-600">{errorText(importJira.error)}</p>}
        <button disabled={!valid || importJira.isPending} onClick={() => importJira.mutate()} className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
          Import
        </button>
      </Card>
    </div>
  );
}

function WorkflowCard({ wf, onChanged, builtin = false }: { wf: WorkflowDef; onChanged: () => void; builtin?: boolean }) {
  const types = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, enabled: !builtin });
  const [schema, setSchema] = useState("");
  const bind = useMutation({ mutationFn: () => workflowApi.bind(wf.uid!, schema), onSuccess: onChanged });
  const rehearse = useMutation({ mutationFn: () => workflowApi.rehearsal(wf.uid!) });
  const ticketTypes = (types.data ?? []).filter((s) => s.applies_to === "tickets");
  return (
    <Card
      title={
        <span>
          {wf.name}
          {builtin && <span className="ml-2 text-xs font-normal text-slate-400">built-in · every move allowed</span>}
          {wf.is_default && !builtin && <span className="ml-2 text-xs font-normal text-emerald-700">workspace default</span>}
        </span>
      }
      action={sourceOf(wf.source) ? <span className="text-xs text-slate-400">from {sourceOf(wf.source)}</span> : undefined}
    >
      <ol className="flex flex-wrap items-center gap-1.5 py-2">
        {wf.states.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${TONE[s.category]}`}>
              {s.name}
              {s.key === wf.initial ? " ●" : ""}
              {s.sla_hours ? ` · ${s.sla_hours} h` : ""}
            </span>
            {i < wf.states.length - 1 && <span className="text-slate-300">·</span>}
          </li>
        ))}
      </ol>
      {!builtin && (
        <ul className="grid grid-cols-1 gap-x-6 text-xs text-slate-600 md:grid-cols-2">
          {wf.transitions.map((t, i) => (
            <li key={i}>
              <span className="font-medium text-slate-800">{t.name ?? "Move"}</span>: {t.from} → {t.to}
              {t.requires?.length ? <span className="text-amber-700"> (needs {t.requires.join(", ")})</span> : null}
            </li>
          ))}
        </ul>
      )}
      {!builtin && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <select value={schema} onChange={(e) => setSchema(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-xs">
            <option value="">Use for ticket type…</option>
            {ticketTypes.map((t) => (
              <option key={t.uid} value={t.uid}>
                {t.name}
              </option>
            ))}
          </select>
          <button disabled={!schema} onClick={() => bind.mutate()} className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50">
            Bind
          </button>
          <button onClick={() => rehearse.mutate()} className="rounded bg-slate-900 px-2 py-1 text-xs text-white">
            Rehearse against migrated tickets
          </button>
          {bind.isSuccess && <span className="text-xs text-emerald-700">bound</span>}
        </div>
      )}
      {rehearse.data && <RehearsalReport r={rehearse.data} />}
      {(bind.isError || rehearse.isError) && <p className="mt-1 text-sm text-red-600">{errorText(bind.error ?? rehearse.error)}</p>}
    </Card>
  );
}

function RehearsalReport({ r }: { r: Rehearsal }) {
  if (r.transitions_checked === 0 && Object.keys(r.unmapped_statuses).length === 0)
    return (
      <p className="mt-3 rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
        Nothing to rehearse yet: no migrated ticket of a type using this workflow has a Jira status history.
      </p>
    );
  return (
    <div className={`mt-3 rounded border p-3 text-sm ${r.ok ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
      <p className="font-medium">
        {r.ok ? "Rehearsal passed" : "Rehearsal found problems"}: {r.transitions_checked} status change(s) in {r.tickets} migrated
        ticket(s).
      </p>
      {Object.keys(r.unmapped_statuses).length > 0 && (
        <p className="mt-1 text-xs">
          Unmapped statuses:{" "}
          {Object.entries(r.unmapped_statuses)
            .map(([k, v]) => `${k} (${v})`)
            .join(", ")}
        </p>
      )}
      {r.disallowed.map((d) => (
        <p key={`${d.from}-${d.to}`} className="mt-1 text-xs">
          {d.from} → {d.to} is not allowed, but happened {d.count} time(s){d.example ? `, e.g. ${d.example}` : ""}
        </p>
      ))}
    </div>
  );
}

/** Where a workflow came from: an import ("jira") or a package ("the it package, 1.1.0"). */
function sourceOf(source: unknown): string | null {
  const s = (source ?? {}) as { system?: string; package?: string; version?: string };
  if (s.system) return s.system;
  if (s.package) return `the ${s.package} package${s.version ? `, ${s.version}` : ""}`;
  return null;
}
