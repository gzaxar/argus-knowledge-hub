import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, statisticsApi } from "../../api/client";
import type { Statistics, StorageArea, StorageReport } from "../../api/types";

const CLIENT_COLORS: Record<string, string> = {
  web: "bg-indigo-500",
  app: "bg-emerald-500",
  mcp: "bg-amber-500",
  api: "bg-slate-400",
};
const CLIENT_LABELS: Record<string, string> = { web: "Web", app: "Android app", mcp: "MCP (assistants)", api: "API & scripts" };

const n = (v: number) => v.toLocaleString();
const bytes = (v: number | null | undefined) => {
  if (v == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let x = v, i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${x >= 100 || i === 0 ? Math.round(x) : x.toFixed(1)} ${units[i]}`;
};
const AREA_LABELS: Record<string, string> = { attachments: "Attachment files", database: "Database", portability: "Portability archives" };
const tokens = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)} M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)} k` : String(v));

/** A bar per day, stacked by series. */
function DayBars({ rows, series, height = 120 }: {
  rows: { day: string; [k: string]: number | string | null }[];
  series: { key: string; color: string; label: string }[];
  height?: number;
}) {
  const max = Math.max(1, ...rows.map((r) => series.reduce((s, x) => s + Number(r[x.key] ?? 0), 0)));
  return (
    <div>
      <div className="flex items-end gap-px" style={{ height }}>
        {rows.map((r) => {
          const total = series.reduce((s, x) => s + Number(r[x.key] ?? 0), 0);
          return (
            <div key={r.day} className="flex flex-1 flex-col-reverse" style={{ height: "100%" }}
                 title={`${r.day}: ${series.map((x) => `${x.label} ${n(Number(r[x.key] ?? 0))}`).join(", ")}`}>
              {series.map((x) => (
                <div key={x.key} className={x.color} style={{ height: `${(Number(r[x.key] ?? 0) / max) * 100}%` }} />
              ))}
              {total === 0 && <div className="h-px bg-slate-200" />}
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>{rows[0]?.day}</span>
        <span>max {n(max)}</span>
        <span>{rows[rows.length - 1]?.day}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-600">
        {series.map((x) => (
          <span key={x.key} className="flex items-center gap-1">
            <span className={`inline-block h-2.5 w-2.5 rounded-sm ${x.color}`} /> {x.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function Card({ title, children, hint }: { title: string; children: React.ReactNode; hint?: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      {hint && <p className="mb-2 text-xs text-slate-500">{hint}</p>}
      <div className={hint ? "" : "mt-2"}>{children}</div>
    </section>
  );
}

/** Up or down against the period before, in per cent. */
function Delta({ now, before }: { now: number; before: number }) {
  if (!before && !now) return null;
  if (!before) return <span className="ml-2 text-xs font-medium text-emerald-700" title="nothing in the period before">new</span>;
  const pct = Math.round(((now - before) / before) * 100);
  const tone = pct > 0 ? "text-emerald-700" : pct < 0 ? "text-rose-700" : "text-slate-500";
  return <span className={`ml-2 text-xs font-medium ${tone}`} title={`${n(before)} in the period before`}>
    {pct > 0 ? "▲" : pct < 0 ? "▼" : "="} {Math.abs(pct)}%</span>;
}

function Figure({ label, value, sub, before }: { label: string; value: string | number; sub?: string;
                                                 before?: { now: number; before: number } }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-slate-900">{typeof value === "number" ? n(value) : value}
        {before && <Delta now={before.now} before={before.before} />}</div>
      {sub && <div className="text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr>{head.map((h, i) => <th key={i} className={`py-1 pr-3 font-normal ${i ? "text-right" : ""}`}>{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => (
              <td key={j} className={`py-1 pr-3 ${j ? "text-right tabular-nums text-slate-600" : "font-mono text-xs text-slate-800"}`}>
                {typeof c === "number" ? n(c) : c}
              </td>
            ))}</tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={head.length} className="py-2 text-xs text-slate-400">Nothing yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

/** A 7-day moving average (fewer at the start). */
function smooth(values: number[], window = 7): number[] {
  return values.map((_, i) => {
    const part = values.slice(Math.max(0, i - window + 1), i + 1);
    return part.reduce((a, b) => a + b, 0) / part.length;
  });
}

/** Lines over the days: each series faint day by day, bold as its 7-day average. */
function TrendLines({ days, series, height = 160 }: {
  days: string[]; series: { label: string; color: string; values: number[] }[]; height?: number;
}) {
  const width = 600;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const x = (i: number) => (days.length <= 1 ? width / 2 : (i / (days.length - 1)) * width);
  const y = (v: number) => height - 4 - (v / max) * (height - 12);
  const path = (vs: number[]) => vs.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" preserveAspectRatio="none" role="img">
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={width} y1={y(max * f)} y2={y(max * f)} stroke="#e2e8f0" strokeWidth={1} />
        ))}
        {series.map((s) => (
          <g key={s.label}>
            <path d={path(s.values)} fill="none" stroke={s.color} strokeOpacity={0.3} strokeWidth={1}
                  vectorEffect="non-scaling-stroke" />
            <path d={path(smooth(s.values))} fill="none" stroke={s.color} strokeWidth={2.5}
                  vectorEffect="non-scaling-stroke" />
          </g>
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>{days[0]}</span><span>max {n(max)} a day · bold: 7-day average</span><span>{days[days.length - 1]}</span>
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  const w = 120, h = 24;
  const pts = smooth(values).map((v, i) => `${values.length <= 1 ? 0 : (i / (values.length - 1)) * w},${h - 2 - (v / max) * (h - 4)}`);
  const half = Math.floor(values.length / 2);
  const first = values.slice(0, half).reduce((a, b) => a + b, 0), second = values.slice(half).reduce((a, b) => a + b, 0);
  const color = second > first * 1.1 ? "#059669" : second < first * 0.9 ? "#e11d48" : "#64748b";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="inline-block h-6 w-28" role="img"
         aria-label={second > first ? "growing" : second < first ? "slowing" : "steady"}>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const TREND_SERIES: { id: string; label: string; color: string; of: (s: Statistics) => number[] }[] = [
  { id: "requests", label: "Requests", color: "#6366f1", of: (s) => s.requests_per_day.map((d) => d.web + d.app + d.mcp + d.api) },
  { id: "people", label: "People", color: "#e11d48", of: (s) => s.people_per_day.map((d) => d.all) },
  { id: "objects_new", label: "New objects", color: "#059669", of: (s) => s.records_per_day.map((d) => d.objects_new) },
  { id: "objects_changed", label: "Changed objects", color: "#6ee7b7", of: (s) => s.records_per_day.map((d) => d.objects_changed) },
  { id: "tickets_new", label: "New tickets", color: "#d97706", of: (s) => s.records_per_day.map((d) => d.tickets_new) },
  { id: "tickets_changed", label: "Changed tickets", color: "#fcd34d", of: (s) => s.records_per_day.map((d) => d.tickets_changed) },
  { id: "documents_new", label: "New documents", color: "#4338ca", of: (s) => s.records_per_day.map((d) => d.documents_new) },
  { id: "documents_changed", label: "Changed documents", color: "#a5b4fc", of: (s) => s.records_per_day.map((d) => d.documents_changed) },
  { id: "questions", label: "Ask questions", color: "#0891b2", of: (s) => s.ask.questions_per_day.map((d) => d.questions) },
];

/** Activity over time: pick what to compare. */
function TrendsCard({ s }: { s: Statistics }) {
  const [picked, setPicked] = useState<Set<string>>(new Set(["tickets_new", "tickets_changed", "documents_changed"]));
  const days = s.records_per_day.map((d) => d.day);
  const toggle = (id: string) => setPicked((p) => { const q = new Set(p); if (q.has(id)) q.delete(id); else q.add(id); return q; });
  return (
    <Card title="Trends" hint="Day by day (faint) and as a 7-day average (bold). Pick what to compare; each line is scaled with the others.">
      <div className="mb-2 flex flex-wrap gap-1.5">
        {TREND_SERIES.map((t) => (
          <button key={t.id} type="button" onClick={() => toggle(t.id)}
                  className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${picked.has(t.id)
                    ? "border-slate-400 bg-slate-100 text-slate-900" : "border-slate-200 text-slate-500"}`}>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: t.color }} /> {t.label}
          </button>
        ))}
      </div>
      {picked.size === 0 ? <p className="text-xs text-slate-400">Pick something to draw.</p> : (
        <TrendLines days={days} series={TREND_SERIES.filter((t) => picked.has(t.id))
          .map((t) => ({ label: t.label, color: t.color, values: t.of(s) }))} />
      )}
    </Card>
  );
}

const RECORD_KINDS = [
  { key: "objects", label: "Objects", colors: ["bg-emerald-600", "bg-emerald-300"] },
  { key: "tickets", label: "Tickets", colors: ["bg-amber-600", "bg-amber-300"] },
  { key: "documents", label: "Documents", colors: ["bg-indigo-600", "bg-indigo-300"] },
] as const;

/** Records created and changed each day, by kind. */
function RecordsCard({ rows }: { rows: Statistics["records_per_day"] }) {
  const total = (k: string, op: string) => rows.reduce((t, r) => t + Number((r as Record<string, unknown>)[`${k}_${op}`] ?? 0), 0);
  return (
    <Card title="New and changed records" hint="New: created that day, imports included (from the records themselves, so the whole history shows). Changed and deleted: edits, transitions, comments, revisions, links and deletions made through ARGUS (counted since version 1.35.37).">
      <div className="mb-3 grid grid-cols-3 gap-3">
        {RECORD_KINDS.map((k) => (
          <div key={k.key} className="rounded border border-slate-200 px-3 py-2">
            <div className="text-xs text-slate-500">{k.label}</div>
            <div className="text-sm tabular-nums text-slate-800">
              <b>{n(total(k.key, "new"))}</b> new · <b>{n(total(k.key, "changed"))}</b> changed
              {total(k.key, "deleted") > 0 && <> · {n(total(k.key, "deleted"))} deleted</>}
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-slate-600">New</div>
          <DayBars height={90} rows={rows} series={RECORD_KINDS.map((k) => ({ key: `${k.key}_new`, color: k.colors[0], label: k.label }))} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-slate-600">Changed</div>
          <DayBars height={90} rows={rows} series={RECORD_KINDS.map((k) => ({ key: `${k.key}_changed`, color: k.colors[1], label: k.label }))} />
        </div>
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
        <dd className="text-right tabular-nums">{a.growth_per_day_bytes != null ? `${bytes(a.growth_per_day_bytes)}/day` : "—"}</dd>
        <dt className="text-slate-500">Full in</dt>
        <dd className={`text-right tabular-nums ${a.days_left != null && a.days_left < 30 ? "font-semibold text-rose-700" : ""}`}>
          {a.days_left == null ? "—" : a.days_left > 3650 ? "over 10 years" : `about ${n(a.days_left)} days`}
        </dd>
      </dl>
      {diskBound && <p className="mt-1 text-[11px] text-rose-700">The disk under it has less free space than its planned room.</p>}
      {a.area === "database" && <p className="mt-1 text-[11px] text-slate-400">On another node: only its planned room is known.</p>}
    </div>
  );
}

function StorageSection({ storage, refreshing, onRefresh }: { storage: StorageReport; refreshing: boolean; onRefresh: () => void }) {
  return (
    <Card title="Storage" hint={`What is used, how much is left and how fast it grows. Measured hourly${storage.measured_at ? `, last at ${new Date(storage.measured_at).toLocaleString()}` : ""}; a volume's planned room is its size in the deployment, and the disk under it can run out first.`}>
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

/** How ARGUS is used, counted without saying by whom. Administrators. */
const TABS = [
  { id: "usage", label: "Usage" },
  { id: "ai", label: "AI" },
  { id: "storage", label: "Storage" },
  { id: "nerds", label: "Nerds" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function StatisticsPage() {
  const [days, setDays] = useState(30);
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "usage") as Tab;
  const setTab = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const measureNow = async () => {
    setRefreshing(true);
    try {
      queryClient.setQueryData(["statistics", days], await statisticsApi.get(days, true));
    } finally {
      setRefreshing(false);
    }
  };
  const q = useQuery({ queryKey: ["statistics", days], queryFn: () => statisticsApi.get(days), retry: false,
                       refetchInterval: 60_000 });
  if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    return <p className="text-sm text-red-600">{forbidden ? "Admins only." : "Could not load the statistics."}</p>;
  }
  const s: Statistics | undefined = q.data;
  const sum = (rows: Record<string, unknown>[], key: string) => rows.reduce((t, r) => t + Number(r[key] ?? 0), 0);

  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Statistics</h1>
          <p className="mt-1 text-sm text-slate-500">
            How ARGUS is used, counted without saying by whom: people are counted as a keyed hash, per five minutes.
          </p>
        </div>
        <label className="text-sm text-slate-600">
          Period{" "}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  className="rounded border border-slate-300 px-2 py-1 text-sm">
            {[7, 30, 90, 365].map((d) => <option key={d} value={d}>last {d} days</option>)}
          </select>
        </label>
      </div>
      {!s && <p className="text-sm text-slate-500">Loading…</p>}
      {s && !s.counting && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Counting is switched off on this installation (ARGUS_USAGE_STATS=0): only what the records themselves say is shown.
        </p>
      )}
      {s && (
        <>
          <nav className="flex flex-wrap gap-1 border-b border-slate-200" aria-label="Statistics">
            {TABS.map((t) => (
              <button key={t.id} type="button" onClick={() => setTab(t.id)}
                      className={`-mb-px rounded-t border px-3 py-1.5 text-sm ${tab === t.id
                        ? "border-slate-200 border-b-white bg-white font-medium text-slate-900"
                        : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                {t.label}
              </button>
            ))}
          </nav>

          {tab === "usage" && (
            <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Figure label="Active now" value={s.now.active_5m} sub={`${s.now.active_15m} in 15 min · ${s.now.active_24h} in 24 h`} />
            <Figure label="Peak at the same time" value={Math.max(0, ...s.people_per_day.map((d) => d.peak_at_once))}
                    sub="most people in one five-minute slot" />
            <Figure label="People in the period" value={s.current.people}
                    before={{ now: s.current.people, before: s.previous.people }}
                    sub={`${n(s.users.total)} signed up · ${s.users.signed_in_7d} in 7 days · ${s.users.new_in_period} new`} />
            <Figure label="Records new / changed" value={`${n(s.current.records_new)} / ${n(s.current.records_changed)}`}
                    before={{ now: s.current.records_new + s.current.records_changed,
                              before: s.previous.records_new + s.previous.records_changed }}
                    sub={`${n(s.current.requests)} requests · web ${n(sum(s.requests_per_day, "web"))} · app ${n(sum(s.requests_per_day, "app"))}`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Requests per day" hint="By client: the web, the Android app, assistants through MCP, scripts and robots.">
              <DayBars rows={s.requests_per_day}
                       series={Object.keys(CLIENT_COLORS).map((k) => ({ key: k, color: CLIENT_COLORS[k], label: CLIENT_LABELS[k] }))} />
            </Card>
            <Card title="People per day" hint="Different people each day by client; the line under it is the peak at the same time.">
              <DayBars rows={s.people_per_day}
                       series={Object.keys(CLIENT_COLORS).map((k) => ({ key: k, color: CLIENT_COLORS[k], label: CLIENT_LABELS[k] }))} />
              <div className="mt-3">
                <DayBars height={50} rows={s.people_per_day} series={[{ key: "peak_at_once", color: "bg-rose-400", label: "peak at the same time" }]} />
              </div>
            </Card>
          </div>
          <TrendsCard s={s} />

          <RecordsCard rows={s.records_per_day} />

          <Card title="Activity in the workspaces" hint="New: records created in the period (imports included). Changed: edits, transitions, comments, revisions and links made through ARGUS.">
            <Table head={["Workspace", "Trend", "Requests", "Objects new", "changed", "Tickets new", "changed", "Documents new", "changed", "Ask questions"]}
                   rows={s.workspaces.map((w) => [
                     <span key={w.workspace} title={w.workspace}>{w.name}</span>,
                     <Sparkline key={`t${w.workspace}`} values={w.activity_per_day ?? []} />, w.requests,
                     w.objects_created, w.objects_changed, w.tickets_created, w.tickets_changed,
                     w.documents_created, w.documents_changed, w.ask_questions])} />
          </Card>

            </>
          )}

          {tab === "ai" && (
            <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Figure label="Model tokens" value={tokens(sum(s.llm.per_day, "prompt_tokens") + sum(s.llm.per_day, "completion_tokens"))}
                    before={{ now: s.current.tokens, before: s.previous.tokens }}
                    sub={`${n(sum(s.llm.per_day, "calls"))} calls`} />
            <Figure label="Ask questions" value={sum(s.ask.questions_per_day, "questions")}
                    before={{ now: s.current.ask_questions, before: s.previous.ask_questions }}
                    sub={s.ask.avg_seconds != null ? `${s.ask.avg_seconds} s an answer on average` : undefined} />
            <Figure label="Rated useful" value={sum(s.feedback.per_day, "up")} sub="👍" />
            <Figure label="Rated not useful" value={sum(s.feedback.per_day, "down")} sub="👎 each one a ticket" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Language model" hint="Tokens per day; calls whose provider reported none are estimated (about four characters a token).">
              <DayBars rows={s.llm.per_day} series={[
                { key: "prompt_tokens", color: "bg-sky-500", label: "prompt" },
                { key: "completion_tokens", color: "bg-violet-500", label: "completion" },
              ]} />
              <div className="mt-3">
                <Table head={["Model", "Calls", "Failed", "Prompt", "Completion", "Avg s"]}
                       rows={s.llm.by_model.map((m) => [m.model, m.calls, m.failures, tokens(m.prompt_tokens), tokens(m.completion_tokens), m.avg_seconds])} />
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <Table head={["For", "Calls", "Tokens"]}
                       rows={s.llm.by_purpose.map((m) => [m.purpose, m.calls, tokens(m.prompt_tokens + m.completion_tokens)])} />
                <Table head={["Workspace", "Calls", "Tokens"]}
                       rows={s.llm.by_workspace.map((m) => [m.workspace, m.calls, tokens(m.prompt_tokens + m.completion_tokens)])} />
              </div>
            </Card>
            <Card title="Ask ARGUS" hint={`Questions per day and how the answers were rated. ${s.ask.avg_seconds != null ? `An answer takes ${s.ask.avg_seconds} s on average.` : ""}`}>
              <DayBars rows={s.ask.questions_per_day} series={[{ key: "questions", color: "bg-indigo-400", label: "questions" }]} />
              <div className="mt-3">
                <DayBars height={50} rows={s.feedback.per_day} series={[
                  { key: "up", color: "bg-emerald-500", label: "👍 useful" },
                  { key: "down", color: "bg-rose-500", label: "👎 not useful" },
                ]} />
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <Table head={["Answers", "Count"]} rows={Object.entries(s.ask.outcomes).map(([k, v]) => [k, v])} />
                <Table head={["Lookup", "Used"]} rows={s.ask.tools.map((t) => [t.tool, t.count])} />
              </div>
              <div className="mt-3">
                <Table head={["Model", "👍", "👎"]} rows={s.feedback.by_model.map((m) => [m.model, m.up, m.down])} />
              </div>
            </Card>
          </div>
          <Card title="Answers rated not useful" hint={`Each is a ticket in the ${s.feedback.workspace} workspace, assigned to ${s.feedback.assignee ?? "nobody"}. Who asked is not recorded.`}>
            <ul className="divide-y divide-slate-100 text-sm">
              {s.feedback.recent_negative.map((f, i) => (
                <li key={i} className="py-2">
                  <div className="text-slate-800">{f.question}</div>
                  {f.comment && <div className="mt-0.5 text-rose-700">“{f.comment}”</div>}
                  <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-slate-400">
                    <span>{f.at ? new Date(f.at).toLocaleString() : ""}</span>
                    <span>{f.workspace}</span>
                    <span>{f.model}</span>
                    <span>{f.client}</span>
                    {f.ticket_uid && (
                      <Link to={`/tickets/${f.ticket_uid}?ws=${encodeURIComponent(s.feedback.workspace)}`} className="text-indigo-600 hover:underline">ticket</Link>
                    )}
                  </div>
                </li>
              ))}
              {s.feedback.recent_negative.length === 0 && <li className="py-2 text-xs text-slate-400">None in this period.</li>}
            </ul>
          </Card>

            </>
          )}

          {tab === "storage" && (
<StorageSection storage={s.storage} refreshing={refreshing} onRefresh={() => void measureNow()} />
          )}

          {tab === "nerds" && (
            <>
          <p className="text-sm text-slate-500">For whoever looks after ARGUS: which routes are called, how long they
            take and which ones fail. Server errors are worth a look in the logs.</p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Most used functions">
              <Table head={["Function", "Calls", "Avg ms", "5xx"]}
                     rows={s.functions.top.map((f) => [f.function, f.count, f.avg_ms, f.errors])} />
            </Card>
            <div className="space-y-4">
              <Card title="Slowest functions" hint="Average time to answer, among those called at least 20 times (the streamed chat left out).">
                <Table head={["Function", "Avg ms", "Calls"]} rows={s.functions.slowest.map((f) => [f.function, f.avg_ms, f.count])} />
              </Card>
              <Card title="Functions that failed" hint="Server errors (5xx): worth a look in the logs.">
                <Table head={["Function", "5xx", "Calls"]} rows={s.functions.failing.map((f) => [f.function, f.errors, f.count])} />
              </Card>
              <Card title="Most used, by client">
                <div className="grid gap-3 md:grid-cols-2">
                  {Object.entries(s.functions.by_client).map(([client, rows]) => (
                    <div key={client}>
                      <div className="mb-1 text-xs font-medium text-slate-600">{CLIENT_LABELS[client] ?? client}</div>
                      <Table head={["Function", "Calls"]} rows={rows.map((f) => [f.function, f.count])} />
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
