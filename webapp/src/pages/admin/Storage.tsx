import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, statisticsApi, storageApi } from "../../api/client";
import type { StorageAdminReport, StorageArea, StorageCleanupPreview, StoragePlanned } from "../../api/types";
import { ask } from "../../lib/dialogs";
import { AREA_LABELS, bytes, Card, DayBars, growth, n, said, Table } from "./Statistics";

/** Administration → Storage: what each area uses and has left, the room planned for it, and the commands that free
 *  space (services/storage.py, services/storage_cleanup.py). Instance administrators; a workspace's own share is on
 *  its administration's Storage page. */
export function AdminStoragePage() {
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const q = useQuery({ queryKey: ["storage-report"], queryFn: () => storageApi.report(30), retry: false });
  const measureNow = async () => {
    setRefreshing(true);
    try {
      qc.setQueryData(["storage-report"], await storageApi.report(30, true));
    } finally {
      setRefreshing(false);
    }
  };
  if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    return <p className="text-sm text-red-600">{forbidden ? "Instance administrators only." : "Could not load the storage."}</p>;
  }
  if (!q.data) return <p className="text-sm text-slate-500">Measuring…</p>;
  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Storage</h1>
        <p className="text-sm text-slate-600">The whole installation. A workspace's own files are on its administration's
          Storage page; usage statistics are in <Link to="/admin/statistics" className="underline">Statistics</Link>.</p>
      </div>
      <StorageSection storage={q.data} refreshing={refreshing} onRefresh={() => void measureNow()} />
      <PlannedRoom planned={q.data.planned} />
    </div>
  );
}

const GiB = 2 ** 30;
const SOURCE: Record<string, string> = { setting: "set here", deployment: "the deployment's", default: "the default" };

/** Each area's planned room: what the gauges measure against. Empty goes back to the deployment's (or the default). */
function PlannedRoom({ planned }: { planned: Record<string, StoragePlanned> }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(planned).map(
    ([a, p]) => [a, p.setting_bytes ? String(+(p.setting_bytes / GiB).toFixed(2)) : ""])));
  const save = useMutation({
    mutationFn: () => storageApi.setPlanned(Object.fromEntries(Object.entries(draft).map(
      ([a, v]) => [a, v.trim() === "" ? null : Math.round(parseFloat(v) * GiB)]))),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["storage-report"] }),
  });
  const invalid = Object.values(draft).some((v) => v.trim() !== "" && !(parseFloat(v) > 0));
  return (
    <Card title="Planned room" hint="What each area is measured against. Leave a field empty to use the deployment's size or the default (portability: 10 GB). It does not resize a volume: the disk under it can run out first, and the gauge says so.">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr><th className="py-1">Area</th><th>In effect</th><th>Deployment</th><th>Default</th><th className="w-44">Set here (GB)</th></tr>
        </thead>
        <tbody>
          {Object.entries(planned).map(([a, p]) => (
            <tr key={a} className="border-t border-slate-100">
              <td className="py-1.5">{AREA_LABELS[a] ?? a}</td>
              <td className="tabular-nums">{bytes(p.planned_bytes)} <span className="text-xs text-slate-500">({p.source ? SOURCE[p.source] : "none"})</span></td>
              <td className="tabular-nums text-slate-600">{bytes(p.deployment_bytes)}</td>
              <td className="tabular-nums text-slate-600">{bytes(p.default_bytes)}</td>
              <td>
                <input aria-label={`Planned room for ${AREA_LABELS[a] ?? a}, in GB`} inputMode="decimal" value={draft[a] ?? ""}
                       placeholder="not set" onChange={(e) => setDraft({ ...draft, [a]: e.target.value })}
                       className="w-28 rounded border border-slate-300 px-2 py-1 text-sm tabular-nums" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-3">
        <button type="button" disabled={invalid || save.isPending} onClick={() => save.mutate()}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">
          {save.isPending ? "Saving…" : "Save"}</button>
        {invalid && <span className="text-xs text-rose-700">A planned room is a number of GB, more than 0.</span>}
        {save.isSuccess && <span role="status" className="text-xs text-emerald-700">Saved, and measured again.</span>}
        {save.isError && <span className="text-xs text-rose-700">{said(save.error, "Could not save.")}</span>}
      </div>
    </Card>
  );
}

/** One storage area: how full against its planned room, what is left and, at the recent growth, for how long. */
function StorageGauge({ a }: { a: StorageArea }) {
  const capacity = a.available_bytes != null ? a.used_bytes + a.available_bytes : a.planned_bytes;
  const share = capacity ? Math.min(1, a.used_bytes / capacity) : null;
  const color = share == null ? "bg-slate-400" : share > 0.9 ? "bg-rose-500" : share > 0.75 ? "bg-amber-500" : "bg-emerald-500";
  const diskBound = a.disk_free_bytes != null && a.planned_bytes != null && a.disk_free_bytes < a.planned_bytes - a.used_bytes;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-slate-900">{AREA_LABELS[a.area] ?? a.area}</span>
        {share != null && <span className="text-xs tabular-nums text-slate-500">{Math.round(share * 100)}%</span>}
      </div>
      <div className="mt-2 h-2.5 overflow-hidden rounded bg-slate-100">
        <div className={`h-full ${color}`} style={{ width: `${(share ?? 0) * 100}%` }} />
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-slate-500">Used</dt>
        <dd className="text-right tabular-nums">{bytes(a.used_bytes)}{a.files != null ? ` · ${n(a.files)} files` : ""}{a.complete ? "" : "+"}</dd>
        <dt className="text-slate-500">Planned</dt><dd className="text-right tabular-nums">{bytes(a.planned_bytes)}</dd>
        <dt className="text-slate-500">Available</dt>
        <dd className={`text-right tabular-nums ${diskBound ? "text-rose-700" : ""}`}>{bytes(a.available_bytes)}</dd>
        <dt className="text-slate-500">Growth</dt>
        <dd className="text-right tabular-nums">{growth(a.growth_per_day_bytes)}</dd>
        <dt className="text-slate-500">Full in</dt>
        <dd className={`text-right tabular-nums ${a.days_left != null && a.days_left < 30 ? "font-semibold text-rose-700" : ""}`}>
          {a.days_left == null ? "—" : a.days_left > 3650 ? "over 10 years" : `about ${n(a.days_left)} days`}
        </dd>
      </dl>
      {diskBound && <p className="mt-1 text-[11px] text-rose-700">The disk under it has less free space than its planned room.</p>}
      {a.area === "database" && <p className="mt-1 text-[11px] text-slate-400">On another node: only its planned room is known.</p>}
      {a.area === "portability" && <FreeRoom />}
    </div>
  );
}

function StorageSection({ storage, refreshing, onRefresh }: { storage: StorageAdminReport; refreshing: boolean; onRefresh: () => void }) {
  return (
    <Card title="Storage" hint={`What is used, how much is left and how fast it grows. Measured hourly${storage.measured_at ? `, last at ${new Date(storage.measured_at).toLocaleString()}` : ""}; a volume's planned room is set below (or by the deployment), and the disk under it can run out first.`}>
      <div className="mb-3 flex justify-end">
        <button type="button" onClick={onRefresh} disabled={refreshing}
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
          {refreshing ? "Measuring…" : "Measure now"}
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {storage.areas.map((a) => <StorageGauge key={a.area} a={a} />)}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-slate-600">Attachments over time (from their upload dates)</div>
          <DayBars height={90} rows={storage.attachment_growth.map((g) => ({ day: g.day, total: g.total_bytes }))}
                   series={[{ key: "total", color: "bg-indigo-400", label: "attachment bytes in total" }]} />
          <div className="mt-2">
            <DayBars height={50} rows={storage.attachment_growth.map((g) => ({ day: g.day, added: g.added_bytes }))}
                     series={[{ key: "added", color: "bg-emerald-500", label: "added that day" }]} />
          </div>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-slate-600">Measured each day</div>
          {storage.trend.length < 2 ? (
            <p className="text-xs text-slate-400">The trend builds up from today: one measurement a day.</p>
          ) : (
            <DayBars height={90} rows={storage.trend.map((t) => ({ day: t.day, attachments: t.attachments ?? 0, database: t.database ?? 0, portability: t.portability ?? 0 }))}
                     series={[{ key: "attachments", color: "bg-indigo-400", label: "attachments" },
                              { key: "database", color: "bg-sky-500", label: "database" },
                              { key: "portability", color: "bg-amber-400", label: "portability" }]} />
          )}
        </div>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Table head={["Attachments by workspace", "Files", "Size"]}
               rows={storage.attachments_by_workspace.map((w) => [w.workspace, w.files, bytes(w.bytes)])} />
        <Table head={["Largest database tables", "Size"]} rows={storage.largest_tables.map((t) => [t.table, bytes(t.bytes)])} />
      </div>
    </Card>
  );
}

/** Freeing room in the portability area (services/storage_cleanup.py): what is there, what may go, chosen and done
 *  by an administrator. Each cleanup says what it frees and why it is safe; one that is not is not offered. */
function FreeRoom() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const preview = useQuery({ queryKey: ["storage-cleanup"], queryFn: statisticsApi.cleanupPreview, enabled: open });
  const run = useMutation({
    mutationFn: (ids: string[]) => statisticsApi.cleanup(ids),
    onSuccess: () => { setChosen(new Set()); void qc.invalidateQueries({ queryKey: ["storage-cleanup"] });
                       void qc.invalidateQueries({ queryKey: ["storage-report"] }); },
  });
  const p: StorageCleanupPreview | undefined = preview.data;
  const toggle = (id: string) => setChosen((c) => { const n2 = new Set(c); if (n2.has(id)) n2.delete(id); else n2.add(id); return n2; });
  const total = (p?.actions ?? []).filter((a) => chosen.has(a.id)).reduce((t, a) => t + a.frees_up_to, 0);
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)}
                   className="mt-2 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">Free up space…</button>;
  }
  return (
    <div className="mt-3 space-y-2 border-t border-slate-200 pt-2 text-xs" aria-label="Free up space">
      {preview.isLoading && <p className="text-slate-500">Looking at what is there…</p>}
      {preview.isError && <p className="text-rose-700">{said(preview.error, "Could not look.")}</p>}
      {p && (
        <>
          <ul className="space-y-0.5 text-slate-600">
            {p.holds.filter((h) => h.bytes > 0).map((h) => (
              <li key={h.part} className="flex justify-between gap-2"><span><b>{h.part}</b> · {h.what}</span>
                <span className="tabular-nums">{bytes(h.bytes)}</span></li>
            ))}
          </ul>
          <ul className="space-y-1">
            {p.actions.map((a) => (
              <li key={a.id}>
                <label className={`flex items-start gap-2 ${a.available ? "" : "text-slate-400"}`}>
                  <input type="checkbox" disabled={!a.available} checked={chosen.has(a.id)} onChange={() => toggle(a.id)} className="mt-0.5" />
                  <span className="flex-1">{a.label}{a.count != null && a.count > 0 ? ` (${a.count})` : ""}
                    <span className="block text-[11px] text-slate-500">{a.note}</span></span>
                  <span className="tabular-nums">{a.frees_up_to ? `up to ${bytes(a.frees_up_to)}` : "—"}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-2">
            <button type="button" onClick={() => setOpen(false)} className="text-slate-500 underline">close</button>
            <button type="button" disabled={chosen.size === 0 || run.isPending}
                    onClick={async () => { if (await ask(`Remove these files from the portability area? Up to ${bytes(total)} is freed.`)) run.mutate([...chosen]); }}
                    className="rounded bg-slate-900 px-2 py-1 font-medium text-white disabled:opacity-40">
              {run.isPending ? "Freeing…" : "Free the space"}</button>
          </div>
          {run.data && <p role="status" className="text-emerald-700">Freed {bytes(run.data.freed)}.</p>}
          {run.isError && <p className="text-rose-700">{said(run.error, "Could not do it.")}</p>}
        </>
      )}
    </div>
  );
}
