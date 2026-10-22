import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
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

function Figure({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-slate-900">{typeof value === "number" ? n(value) : value}</div>
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
export function StatisticsPage() {
  const [days, setDays] = useState(30);
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
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Figure label="Active now" value={s.now.active_5m} sub={`${s.now.active_15m} in 15 min · ${s.now.active_24h} in 24 h`} />
            <Figure label="Peak at the same time" value={Math.max(0, ...s.people_per_day.map((d) => d.peak_at_once))}
                    sub="most people in one five-minute slot" />
            <Figure label="Signed in" value={s.users.signed_in_30d} sub={`of ${n(s.users.total)} · ${s.users.signed_in_7d} in 7 days · ${s.users.new_in_period} new`} />
            <Figure label="Model tokens" value={tokens(sum(s.llm.per_day, "prompt_tokens") + sum(s.llm.per_day, "completion_tokens"))}
                    sub={`${n(sum(s.llm.per_day, "calls"))} calls`} />
          </div>

          <StorageSection storage={s.storage} refreshing={refreshing} onRefresh={() => void measureNow()} />

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

          <Card title="Activity in the workspaces" hint="Requests and changes through ARGUS, and what was created, in the period.">
            <Table head={["Workspace", "Requests", "Changes", "Objects", "Tickets", "Documents", "Ask questions"]}
                   rows={s.workspaces.map((w) => [
                     <span key={w.workspace} title={w.workspace}>{w.name}</span>, w.requests, w.writes, w.objects_created,
                     w.tickets_created, w.documents_created, w.ask_questions])} />
          </Card>

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
    </div>
  );
}
