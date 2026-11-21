import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, quotasApi } from "../../api/client";
import type { QuotaDefinition, QuotaStatus } from "../../api/types";
import { bytes, Card, said } from "./Statistics";

const GiB = 2 ** 30;

/** A quota's value as a person writes it: GB for bytes, a plain number otherwise. */
export function shown(unit: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "unlimited";
  if (unit === "bytes") return bytes(v);
  return v.toLocaleString() + (unit === "tokens" ? " tokens" : "");
}
const toInput = (unit: string, v: number | null) => (v === null ? "" : unit === "bytes" ? String(+(v / GiB).toFixed(3)) : String(v));
const fromInput = (unit: string, s: string): number | null | "bad" => {
  if (s.trim() === "") return null;
  const x = Number(s.replace(",", "."));
  if (!Number.isFinite(x) || x < 0) return "bad";
  return Math.round(unit === "bytes" ? x * GiB : x);
};
const unitHint = (unit: string) => (unit === "bytes" ? "GB" : unit === "tokens" ? "tokens" : "");

export function QuotaBar({ q }: { q: QuotaStatus }) {
  const share = q.ratio === null ? 0 : Math.min(1, q.ratio);
  const color = q.level === "over" ? "bg-rose-500" : q.level === "warn" ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="min-w-32">
      <div className="flex justify-between gap-2 text-xs tabular-nums">
        <span>{q.used === null ? "—" : shown(q.unit, q.used)}</span>
        <span className="text-slate-500">of {shown(q.unit, q.limit)}</span>
      </div>
      {q.limit !== null && (
        <div className="mt-0.5 h-1.5 overflow-hidden rounded bg-slate-100" role="meter" aria-label={q.label}
             aria-valuenow={Math.round(share * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className={`h-full ${color}`} style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  );
}

/** Administration → Quotas: the defaults every workspace starts from, each workspace's own, and what it uses. At
 *  100% ARGUS refuses what would add to a quota (reading, editing and deleting go on); at 80% it warns. */
export function AdminQuotasPage() {
  const q = useQuery({ queryKey: ["quotas"], queryFn: quotasApi.all, retry: false });
  const [open, setOpen] = useState<string | null>(null);
  if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    return <p className="text-sm text-red-600">{forbidden ? "Instance administrators only." : "Could not load the quotas."}</p>;
  }
  if (!q.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const workspaceQuotas = q.data.quotas.filter((d) => d.scope === "workspace");
  const imports = q.data.installation.imports_at_once;
  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Quotas</h1>
        <p className="text-sm text-slate-600">
          What a workspace may hold and use. Past a quota ARGUS refuses what would add to it — a record, a file, a
          member, a call to the language model, an API request — and says which quota and when it frees up; reading,
          editing and deleting always work. At 80% the workspace's administrators are warned. Instance administrators
          signed in are never stopped. Storage itself is in <Link to="/admin/storage" className="underline">Storage</Link>.
        </p>
      </div>
      <Defaults definitions={q.data.quotas} />
      <Card title="Workspaces" hint="What each uses against its quotas. Open one to give it its own.">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1 pr-3">Workspace</th>{workspaceQuotas.map((d) => <th key={d.key} className="pr-3">{d.label}</th>)}<th /></tr>
            </thead>
            <tbody>
              {q.data.workspaces.map((w) => (
                <Fragment key={w.id}>
                  <tr className="border-t border-slate-100 align-top">
                    <td className="py-1.5 pr-3">
                      <div className="font-medium">{w.name}</div>
                      <div className="font-mono text-[11px] text-slate-500">{w.id}</div>
                      {w.level !== "ok" && <span className={`text-[11px] ${w.level === "over" ? "text-rose-700" : "text-amber-700"}`}>
                        {w.level === "over" ? "a quota is reached" : "a quota is near"}</span>}
                    </td>
                    {w.quotas.map((s) => (
                      <td key={s.key} className="py-1.5 pr-3">
                        <QuotaBar q={s} />
                        {s.source === "workspace" && <span className="text-[10px] text-indigo-700">its own</span>}
                      </td>
                    ))}
                    <td className="py-1.5 text-right">
                      <button type="button" onClick={() => setOpen(open === w.id ? null : w.id)}
                              className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">
                        {open === w.id ? "Close" : "Its quotas"}</button>
                    </td>
                  </tr>
                  {open === w.id && (
                    <tr><td colSpan={workspaceQuotas.length + 2} className="bg-slate-50 p-3">
                      <WorkspaceOverrides id={w.id} rows={w.quotas} overrides={w.overrides} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="The installation" hint="Quotas for the installation as a whole, set with the defaults above.">
        <p className="text-sm">Portability imports not over: <b>{imports.used}</b> of {shown("count", imports.limit)}
          {imports.imports.length > 0 && <> — {imports.imports.map((id, i) => (
            <span key={id}>{i > 0 && ", "}<Link to={`/admin/portability/imports/${id}`} className="font-mono underline">{id}</Link></span>))}</>}.
          A new import waits until one is finalized or discarded.</p>
      </Card>
    </div>
  );
}

function Defaults({ definitions }: { definitions: QuotaDefinition[] }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(definitions.map((d) => [d.key, toInput(d.unit, d.default)])));
  const parsed = Object.fromEntries(definitions.map((d) => [d.key, fromInput(d.unit, draft[d.key] ?? "")]));
  const bad = Object.values(parsed).some((v) => v === "bad");
  const save = useMutation({
    mutationFn: (reset: string[]) => {
      const values = Object.fromEntries(definitions.filter((d) => !reset.includes(d.key)).map((d) => [d.key, parsed[d.key] as number | null]));
      return quotasApi.setDefaults(values, reset);
    },
    onSuccess: (r) => {
      setDraft(Object.fromEntries(r.quotas.map((d) => [d.key, toInput(d.unit, d.default)])));
      void qc.invalidateQueries({ queryKey: ["quotas"] });
    },
  });
  return (
    <Card title="Defaults" hint="Every workspace has these unless it has its own. Empty is unlimited.">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr><th className="py-1">Quota</th><th>What it counts</th><th>Built in</th><th className="w-48">Default</th></tr>
        </thead>
        <tbody>
          {definitions.map((d) => (
            <tr key={d.key} className="border-t border-slate-100">
              <td className="py-1.5 font-medium">{d.label}{d.scope === "installation" && <span className="ml-1 text-[10px] text-slate-500">(installation)</span>}</td>
              <td className="text-xs text-slate-600">{d.what}</td>
              <td className="text-xs tabular-nums text-slate-600">{shown(d.unit, d.builtin)}</td>
              <td>
                <input aria-label={`Default for ${d.label}${unitHint(d.unit) ? `, in ${unitHint(d.unit)}` : ""}`} inputMode="decimal"
                       value={draft[d.key] ?? ""} placeholder="unlimited" onChange={(e) => setDraft({ ...draft, [d.key]: e.target.value })}
                       className={`w-28 rounded border px-2 py-1 text-sm tabular-nums ${parsed[d.key] === "bad" ? "border-rose-400" : "border-slate-300"}`} />
                {unitHint(d.unit) && <span className="ml-1 text-xs text-slate-500">{unitHint(d.unit)}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" disabled={bad || save.isPending} onClick={() => save.mutate([])}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">
          {save.isPending ? "Saving…" : "Save the defaults"}</button>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate(definitions.map((d) => d.key))}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Back to the built-in ones</button>
        {bad && <span className="text-xs text-rose-700">A quota is a number from 0, or empty for unlimited.</span>}
        {save.isSuccess && <span role="status" className="text-xs text-emerald-700">Saved.</span>}
        {save.isError && <span className="text-xs text-rose-700">{said(save.error, "Could not save.")}</span>}
      </div>
    </Card>
  );
}

function WorkspaceOverrides({ id, rows, overrides }: { id: string; rows: QuotaStatus[]; overrides: Record<string, number | null> }) {
  const qc = useQueryClient();
  // "default": follow the installation's; "unlimited"; or a number.
  const [mode, setMode] = useState<Record<string, "default" | "unlimited" | "value">>(() => Object.fromEntries(rows.map((r) =>
    [r.key, !(r.key in overrides) ? "default" : overrides[r.key] === null ? "unlimited" : "value"])));
  const [value, setValue] = useState<Record<string, string>>(() => Object.fromEntries(rows.map((r) =>
    [r.key, r.key in overrides && overrides[r.key] !== null ? toInput(r.unit, overrides[r.key]) : ""])));
  const parsed = Object.fromEntries(rows.map((r) => [r.key, fromInput(r.unit, value[r.key] ?? "")]));
  const bad = rows.some((r) => mode[r.key] === "value" && (parsed[r.key] === "bad" || parsed[r.key] === null));
  const save = useMutation({
    mutationFn: () => {
      const values: Record<string, number | null> = {};
      const reset: string[] = [];
      for (const r of rows) {
        if (mode[r.key] === "default") reset.push(r.key);
        else values[r.key] = mode[r.key] === "unlimited" ? null : (parsed[r.key] as number);
      }
      return quotasApi.setWorkspace(id, values, reset);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["quotas"] }),
  });
  return (
    <div className="space-y-2" aria-label={`Quotas of ${id}`}>
      <div className="grid gap-2 md:grid-cols-3">
        {rows.map((r) => (
          <fieldset key={r.key} className="rounded border border-slate-200 bg-white p-2 text-xs">
            <legend className="px-1 font-medium text-slate-700">{r.label}</legend>
            <select aria-label={`${r.label}: what applies`} value={mode[r.key]}
                    onChange={(e) => setMode({ ...mode, [r.key]: e.target.value as "default" | "unlimited" | "value" })}
                    className="rounded border border-slate-300 px-1 py-0.5">
              <option value="default">the default</option>
              <option value="unlimited">unlimited</option>
              <option value="value">its own</option>
            </select>
            {mode[r.key] === "value" && (
              <>
                <input aria-label={`${r.label} of ${id}${unitHint(r.unit) ? `, in ${unitHint(r.unit)}` : ""}`} inputMode="decimal"
                       value={value[r.key]} onChange={(e) => setValue({ ...value, [r.key]: e.target.value })}
                       className="ml-1 w-24 rounded border border-slate-300 px-1 py-0.5 tabular-nums" />
                <span className="ml-1 text-slate-500">{unitHint(r.unit)}</span>
              </>
            )}
            <div className="mt-1 text-slate-500">uses {r.used === null ? "—" : shown(r.unit, r.used)}</div>
          </fieldset>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button type="button" disabled={bad || save.isPending} onClick={() => save.mutate()}
                className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-40">
          {save.isPending ? "Saving…" : "Save its quotas"}</button>
        {bad && <span className="text-xs text-rose-700">Give each "its own" a number from 0.</span>}
        {save.isError && <span className="text-xs text-rose-700">{said(save.error, "Could not save.")}</span>}
      </div>
    </div>
  );
}
