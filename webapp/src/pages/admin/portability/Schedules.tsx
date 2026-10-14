import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { portabilityApi, problemText } from "../../../api/client";
import type { ExportView, PortabilitySchedule } from "../../../api/portabilityTypes";
import { ActionButton, Section, when } from "./shared";

const EVERY: [number, string][] = [
  [60, "every hour"],
  [360, "every 6 hours"],
  [720, "every 12 hours"],
  [1440, "every day"],
  [10080, "every week"],
];

export function every(minutes: number): string {
  const preset = EVERY.find(([m]) => m === minutes);
  if (preset) return preset[1];
  return minutes % 1440 === 0 ? `every ${minutes / 1440} days` : `every ${Math.round(minutes / 60)} hours`;
}

const OUTCOME: Record<string, [string, string]> = {
  published: ["published", "text-emerald-700"],
  unchanged: ["nothing changed", "text-slate-500"],
  waiting: ["waiting for a person", "text-amber-800"],
  failed: ["failed", "text-rose-700"],
};

function Outcome({ s }: { s: PortabilitySchedule }) {
  if (!s.last_outcome) return <span className="text-slate-400">not run yet</span>;
  const [label, style] = OUTCOME[s.last_outcome] ?? [s.last_outcome, "text-slate-600"];
  return (
    <span className={style} title={s.last_message ?? undefined}>
      {label}
      {s.last_run_at && <span className="text-slate-400"> · {when(s.last_run_at)}</span>}
    </span>
  );
}

function useSchedules() {
  return useQuery({ queryKey: ["portability-schedules"], queryFn: portabilityApi.schedules });
}

/** One schedule's state and controls: on/off, how often, run now, remove. */
function ScheduleControls({ s, onError }: { s: PortabilitySchedule; onError: (e: unknown) => void }) {
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["portability-schedules"] });
  const change = useMutation({
    mutationFn: (body: Parameters<typeof portabilityApi.changeSchedule>[1]) => portabilityApi.changeSchedule(s.id, body),
    onSuccess: refresh,
    onError,
  });
  const run = useMutation({
    mutationFn: () => portabilityApi.runSchedule(s.id),
    onSuccess: () => {
      refresh();
      // The run is a background job: the list shows its outcome when it ends.
      window.setTimeout(refresh, 4000);
      window.setTimeout(refresh, 15000);
    },
    onError,
  });
  const remove = useMutation({ mutationFn: () => portabilityApi.removeSchedule(s.id), onSuccess: refresh, onError });
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={s.enabled} disabled={change.isPending}
               onChange={(ev) => change.mutate({ enabled: ev.target.checked })} />
        On
      </label>
      <select value={EVERY.some(([m]) => m === s.every_minutes) ? s.every_minutes : ""} disabled={change.isPending}
              onChange={(ev) => ev.target.value && change.mutate({ every_minutes: Number(ev.target.value) })}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-sm">
        {!EVERY.some(([m]) => m === s.every_minutes) && <option value="">{every(s.every_minutes)}</option>}
        {EVERY.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
      </select>
      <ActionButton label="Run now" busy={run.isPending} disabled={s.running} onClick={() => run.mutate()} />
      {s.running && <span className="text-xs text-sky-700">running…</span>}
      <ActionButton label="Remove" danger busy={remove.isPending} onClick={() => remove.mutate()}
                    confirm="Stop repeating this export? What it published stays published." />
    </div>
  );
}

/** On a published export: repeat it periodically, or the schedule it already has. */
export function SchedulePanel({ e, isAdmin, highRiskNeedsConfirm }: {
  e: ExportView; isAdmin: boolean; highRiskNeedsConfirm: boolean;
}) {
  const qc = useQueryClient();
  const list = useSchedules();
  const [minutes, setMinutes] = useState(1440);
  const [chain, setChain] = useState<"incremental" | "complete">("incremental");
  const [skip, setSkip] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => portabilityApi.createSchedule({ export_id: e.id, every_minutes: minutes, chain,
                                                     skip_unchanged: skip, confirm: confirmed }),
    onSuccess: () => {
      setError(null);
      void qc.invalidateQueries({ queryKey: ["portability-schedules"] });
    },
    onError: (x) => setError(problemText(x)),
  });
  if (!isAdmin || e.state !== "published" || !e.destination.repository) return null;
  const mine = (list.data ?? []).find((s) => s.source_export_id === e.id || s.last_published_export_id === e.id);

  return (
    <Section title="Repeat periodically">
      {mine ? (
        <div className="space-y-2 text-sm">
          <p className="text-slate-700">
            {mine.source_export_id === e.id ? "This export" : <>This export's chain (from{" "}
              <Link className="font-mono text-indigo-700 hover:underline" to={`/admin/portability/exports/${mine.source_export_id}`}>
                {mine.source_export_id}</Link>)</>}{" "}
            is repeated <b>{every(mine.every_minutes)}</b>, as {mine.chain === "incremental" ? "increments" : "complete exports"} to{" "}
            <b>{mine.repository}</b>{mine.skip_unchanged ? ", only when something changed" : ""}.
            {mine.enabled && mine.next_run_at ? <> Next run {when(mine.next_run_at)}.</> : <> Switched off.</>}
          </p>
          <p>Last run: <Outcome s={mine} /></p>
          {mine.last_message && mine.last_outcome !== "unchanged" && (
            <p className="text-xs text-slate-500">
              {mine.last_message}
              {mine.last_export_id && (
                <> — <Link className="text-indigo-700 hover:underline" to={`/admin/portability/exports/${mine.last_export_id}`}>open {mine.last_export_id}</Link></>
              )}
            </p>
          )}
          <ScheduleControls s={mine} onError={(x) => setError(problemText(x))} />
        </div>
      ) : e.classifications.length > 0 ? (
        <p className="text-sm text-slate-500">
          An export carrying restricted classes is not repeated automatically: generating one needs a recent sign-in
          every time.
        </p>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-slate-600">
            Each run makes a new export with this one's scope, destination and outcomes, and publishes it to{" "}
            <b>{e.destination.repository}</b> — analysed, approved, generated, verified and audited as this one was.
            Setting it is the standing approval of its runs; a run whose analysis needs a decision waits for you here.
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2">
              Repeat
              <select value={minutes} onChange={(ev) => setMinutes(Number(ev.target.value))}
                      className="rounded border border-slate-300 px-2 py-1">
                {EVERY.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2">
              as
              <select value={chain} onChange={(ev) => setChain(ev.target.value as "incremental" | "complete")}
                      className="rounded border border-slate-300 px-2 py-1">
                <option value="incremental">increments on the last publication</option>
                <option value="complete">a complete {e.mode} export each time</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={skip} onChange={(ev) => setSkip(ev.target.checked)} />
              Only when something changed
            </label>
          </div>
          {e.risk === "high" && (
            <p className="text-xs text-amber-800">
              A high-risk export: setting the schedule needs a recent sign-in, and an administrator other than its
              requester.
              {highRiskNeedsConfirm && (
                <label className="ml-2 inline-flex items-center gap-1 text-slate-700">
                  <input type="checkbox" checked={confirmed} onChange={(ev) => setConfirmed(ev.target.checked)} />
                  I confirm
                </label>
              )}
            </p>
          )}
          <ActionButton label="Repeat this export" busy={create.isPending} onClick={() => create.mutate()}
                        confirm={`Publish a new export to ${e.destination.repository} ${every(minutes)}?`} />
        </div>
      )}
      {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
    </Section>
  );
}

/** Every schedule, on the Exports tab. */
export function SchedulesList() {
  const list = useSchedules();
  const [error, setError] = useState<string | null>(null);
  if (!list.data || list.data.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <p className="border-b border-slate-100 px-3 py-2 text-sm font-semibold text-slate-900">Periodic exports</p>
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr><th className="px-3 py-2">Repeats</th><th className="px-3 py-2">To</th><th className="px-3 py-2">Last run</th>
            <th className="px-3 py-2">Next run</th><th className="px-3 py-2"></th></tr>
        </thead>
        <tbody>
          {list.data.map((s) => (
            <tr key={s.id} className="border-t border-slate-100 align-top">
              <td className="px-3 py-2">
                <Link to={`/admin/portability/exports/${s.last_published_export_id ?? s.source_export_id}`}
                      className="font-mono text-xs text-indigo-700 hover:underline">{s.source_export_id}</Link>
                <div className="text-xs text-slate-500">
                  {s.mode === "full" ? "every workspace" : s.workspaces.join(", ")} · {s.chain} · {every(s.every_minutes)}
                </div>
              </td>
              <td className="px-3 py-2 text-xs">{s.repository}</td>
              <td className="px-3 py-2 text-xs"><Outcome s={s} />
                {s.last_outcome === "waiting" && s.last_export_id && (
                  <div><Link className="text-indigo-700 hover:underline" to={`/admin/portability/exports/${s.last_export_id}`}>
                    decide on {s.last_export_id}</Link></div>
                )}</td>
              <td className="px-3 py-2 text-xs text-slate-500">{s.enabled ? when(s.next_run_at) : "off"}</td>
              <td className="px-3 py-2"><ScheduleControls s={s} onError={(x) => setError(problemText(x))} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="px-3 py-2 text-sm text-rose-700">{error}</p>}
    </div>
  );
}
