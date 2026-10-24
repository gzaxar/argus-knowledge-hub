import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Activity } from "../api/types";
import { activitiesApi, hubApi } from "../api/client";
import type { HubOverview } from "../api/hubTypes";
import { DemoTour } from "../components/demo/DemoTour";
import { Card, DocumentRow, Empty, KindBadge, StatTile, TicketRow, relativeTime } from "../components/hub/ui";

/**
 * The operations cockpit: what needs attention today, across equipment, the
 * service desk and the knowledge base — in one place, because a faulty pump,
 * the ticket about it and the procedure to fix it are one problem.
 */
export function Dashboard() {
  const overview = useQuery({ queryKey: ["hub-overview"], queryFn: hubApi.overview, refetchInterval: 60_000 });

  if (overview.isLoading) return <p className="text-sm text-slate-500">Loading the cockpit…</p>;
  if (overview.isError || !overview.data)
    return <p className="text-sm text-red-600">The cockpit could not be loaded. Choose a workspace, or try again.</p>;

  const o = overview.data;
  return (
    <div className="mx-auto max-w-7xl space-y-4 sm:space-y-6">
      <DemoTour />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 sm:text-2xl">Operations cockpit</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Equipment, service and knowledge in one view — start from whatever needs attention.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/tickets/new" className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
            Report an issue
          </Link>
          <Link to="/tickets/board" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-white">
            Service board
          </Link>
        </div>
      </div>

      <Kpis o={o} />
      <Summary o={o} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <ActivitiesNow />
          {o.tickets && <Hotspots o={o} />}
          {o.tickets && <MyWork o={o} />}
        </div>
        <div className="space-y-4">
          {o.documents && <KnowledgeHealth o={o} />}
          {o.tickets && <OpenByState o={o} />}
        </div>
      </div>

      <RecentActivity o={o} />
    </div>
  );
}

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** The activities that need attention (one request, shared by the tiles and the card). */
function useAttention() {
  return useQuery({
    queryKey: ["activities", "attention", TZ],
    queryFn: () => activitiesApi.list({ view: "attention", tz: TZ, limit: 60 }),
    refetchInterval: 60_000,
  });
}

/** What needs someone: each tile a count to act on, and a link to where it is acted on. */
function Kpis({ o }: { o: HubOverview }) {
  const attention = useAttention();
  const overdue = attention.data?.counts?.overdue ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      {o.tickets && (
        <>
          <StatTile label="Open tickets" value={o.tickets.open} tone="amber" to="/tickets" />
          <StatTile label="Unassigned" value={o.tickets.unassigned} tone={o.tickets.unassigned ? "red" : "slate"}
                    to="/tickets?assignee=none" hint="Open, nobody on it" />
        </>
      )}
      {!attention.isError && (
        <StatTile label="Activities overdue" value={overdue} tone={overdue ? "red" : "slate"} to="/activities"
                  hint="Planned, not done in time" />
      )}
      {o.documents && (
        <>
          <StatTile label="Awaiting approval" value={o.documents.in_review} tone={o.documents.in_review ? "indigo" : "slate"}
                    to="/documents" hint="Revisions in review" />
          <StatTile label="Reviews overdue" value={o.documents.review_overdue.length}
                    tone={o.documents.review_overdue.length ? "red" : "slate"} to="/documents" hint="Past their review date" />
        </>
      )}
    </div>
  );
}

/** The totals, for context: one line, not a row of tiles competing with what needs doing. */
function Summary({ o }: { o: HubOverview }) {
  const parts: { text: string; to: string }[] = [];
  if (o.tickets) parts.push({ text: `${o.tickets.total} tickets in all`, to: "/tickets?state=all" });
  if (o.tickets?.without_asset) parts.push({ text: `${o.tickets.without_asset} open not linked to equipment`, to: "/tickets" });
  if (o.assets) parts.push({ text: `${o.assets.own.toLocaleString()} assets`, to: "/assets/search" });
  if (o.documents?.not_linked_to_assets) parts.push({ text: `${o.documents.not_linked_to_assets} documents not linked to equipment`, to: "/documents" });
  if (parts.length === 0) return null;
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
      {parts.map((p, i) => (
        <span key={p.text} className="flex items-center gap-3">
          {i > 0 && <span aria-hidden className="text-slate-300">·</span>}
          <Link to={p.to} className="hover:text-slate-800 hover:underline">{p.text}</Link>
        </span>
      ))}
    </p>
  );
}

function Hotspots({ o }: { o: HubOverview }) {
  const hotspots = o.tickets!.hotspots;
  return (
    <Card title="Equipment needing attention" action={<span className="text-xs text-slate-400">by open tickets</span>}>
      {hotspots.length === 0 ? (
        <Empty>No equipment has open tickets.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {hotspots.map((a) => (
            <li key={a.uid} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <Link to={`/assets/${a.uid}`} className="block truncate text-sm font-medium text-slate-900 hover:text-indigo-700">
                  {a.name}
                </Link>
                <p className="truncate text-xs text-slate-500">
                  <span className="font-mono">{a.key}</span> · {a.type}
                  {a.system ? ` · ${a.system}` : ""}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-sm font-semibold tabular-nums text-amber-700">
                  {a.open_tickets} open
                </span>
                <Link
                  to={`/assets/${a.uid}#service`}
                  className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Open 360°
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

interface ActivityGroup {
  key: string;
  title: string;
  recurring: boolean;
  items: Activity[];
  overdue: number;
  underWay: number;
}

/** Occurrences of one series together: a weekly test missed five times is one line with "5 overdue", not five. */
export function groupActivities(items: Activity[]): ActivityGroup[] {
  const groups = new Map<string, ActivityGroup>();
  for (const a of items) {
    const key = a.series_uid ?? a.id;
    const g = groups.get(key) ?? { key, title: a.title, recurring: !!a.series_uid, items: [], overdue: 0, underWay: 0 };
    g.items.push(a);
    if (a.status === "in_progress") g.underWay += 1;
    else if (a.overdue) g.overdue += 1;
    groups.set(key, g);
  }
  // Under way first, then the most overdue, then the rest in the order the server gave.
  return [...groups.values()].sort((x, y) => (y.underWay - x.underWay) || (y.overdue - x.overdue));
}

const when = (v: string | null, allDay: boolean) =>
  !v ? "" : allDay ? new Date(v).toLocaleDateString() : new Date(v).toLocaleString([], { dateStyle: "short", timeStyle: "short" });

function ActivityState({ a }: { a: Activity }) {
  return a.status === "in_progress"
    ? <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900"><span aria-hidden>◐ </span>Under way</span>
    : a.overdue
      ? <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-800"><span aria-hidden>! </span>Overdue</span>
      : <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-800"><span aria-hidden>○ </span>Today</span>;
}

function GroupRow({ g }: { g: ActivityGroup }) {
  const [open, setOpen] = useState(false);
  const first = g.items[0];
  if (g.items.length === 1) {
    return (
      <li>
        <Link to={`/activities?open=${encodeURIComponent(first.id)}`}
              className="flex items-center justify-between gap-3 py-2 text-sm hover:bg-slate-50">
          <span className="min-w-0 truncate text-slate-900" title={first.title}>{g.recurring && <span aria-label="Recurring">↻ </span>}{first.title}</span>
          <span className="flex shrink-0 items-center gap-2 text-xs">
            <ActivityState a={first} />
            <span className="hidden tabular-nums text-slate-400 sm:inline">
              {first.status === "in_progress" ? when(first.actual_start, false) : when(first.planned_start ?? first.due_at, first.all_day)}
            </span>
          </span>
        </Link>
      </li>
    );
  }
  const id = `occ-${g.key}`;
  return (
    <li className="py-1">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls={id}
              className="flex w-full items-center justify-between gap-3 py-1 text-left text-sm hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
        <span className="flex min-w-0 items-center gap-1">
          <span aria-hidden className="w-3 text-slate-400">{open ? "▾" : "▸"}</span>
          <span className="truncate text-slate-900" title={g.title}><span aria-label="Recurring">↻ </span>{g.title}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs">
          {g.underWay > 0 && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">{g.underWay} under way</span>}
          {g.overdue > 0 && <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-800"><span aria-hidden>! </span>{g.overdue} overdue</span>}
          {g.items.length - g.overdue - g.underWay > 0 && (
            <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-800">{g.items.length - g.overdue - g.underWay} today</span>
          )}
        </span>
      </button>
      {open && (
        <ul id={id} className="mb-1 ml-4 border-l border-slate-100 pl-3">
          {g.items.map((a) => (
            <li key={a.id}>
              <Link to={`/activities?open=${encodeURIComponent(a.id)}`}
                    className="flex items-center justify-between gap-3 py-1 text-xs hover:bg-slate-50">
                <span className="tabular-nums text-slate-700">{when(a.planned_start ?? a.due_at, a.all_day) || "—"}</span>
                <ActivityState a={a} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** The workspace's activities that need attention: under way, overdue, or planned for today, one line a series. */
function ActivitiesNow() {
  const q = useAttention();
  if (q.isError) return null;                                // e.g. a server without activities: no card
  const c = q.data?.counts ?? {};
  const groups = groupActivities(q.data?.items ?? []);
  const shown = groups.slice(0, 8);
  return (
    <Card title="Activities" action={
      <span className="flex flex-wrap justify-end gap-x-3 text-xs text-slate-500">
        <span>{c.in_progress ?? 0} under way</span>
        <span className={c.overdue ? "font-medium text-rose-700" : ""}>{c.overdue ?? 0} overdue</span>
        <span>{c.today ?? 0} today</span>
        <span className="hidden sm:inline">{c.done_today ?? 0} done today</span>
        <Link to="/activities" className="text-indigo-700 hover:underline">All</Link>
      </span>
    }>
      {q.isLoading ? <Empty>Loading…</Empty> : groups.length === 0 ? (
        <Empty>Nothing under way, overdue or planned for today.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {shown.map((g) => <GroupRow key={g.key} g={g} />)}
        </ul>
      )}
      {(groups.length > shown.length || (q.data && q.data.total > (q.data.items?.length ?? 0))) && (
        <Link to="/activities" className="mt-1 block text-xs text-indigo-700 hover:underline">More in Activities</Link>
      )}
    </Card>
  );
}

function MyWork({ o }: { o: HubOverview }) {
  const mine = o.tickets!.mine;
  return (
    <Card title="Assigned to me">
      {mine.length === 0 ? (
        <Empty>Nothing assigned to you is open.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {mine.map((t) => (
            <TicketRow key={t.uid} ticket={t} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function KnowledgeHealth({ o }: { o: HubOverview }) {
  const d = o.documents!;
  const items = [...d.review_overdue, ...d.awaiting_review.filter((x) => !d.review_overdue.some((y) => y.uid === x.uid))];
  return (
    <Card
      title="Knowledge health"
      action={
        d.not_linked_to_assets > 0 ? (
          <span className="text-xs text-slate-500" title="Documents that apply to no asset or type yet">
            {d.not_linked_to_assets} not linked to equipment
          </span>
        ) : undefined
      }
    >
      {items.length === 0 ? (
        <Empty>No document is overdue for review or waiting for approval.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.slice(0, 8).map((doc) => (
            <DocumentRow key={doc.uid} doc={doc} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function OpenByState({ o }: { o: HubOverview }) {
  const entries = Object.entries(o.tickets!.by_state).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((n, [, v]) => n + v, 0);
  return (
    <Card title="Open tickets by state">
      {entries.length === 0 ? (
        <Empty>No open tickets.</Empty>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {entries.map(([state, count]) => (
              <tr key={state} className="border-b border-slate-50 last:border-0">
                <td className="whitespace-nowrap py-1.5 pr-2 capitalize text-slate-700">{state.replace(/_/g, " ")}</td>
                <td className="w-full px-3 py-1.5">
                  <div className="h-1.5 rounded-full bg-slate-100" aria-hidden>
                    <div className="h-1.5 rounded-full bg-slate-500" style={{ width: `${(count / total) * 100}%` }} />
                  </div>
                </td>
                <td className="py-1.5 text-right tabular-nums text-slate-900">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function RecentActivity({ o }: { o: HubOverview }) {
  const rows = [
    ...(o.assets?.recent ?? []).map((a) => ({
      kind: "asset" as const, key: `a-${a.uid}`, label: a.name, sub: `${a.key} · ${a.type}`, to: `/assets/${a.uid}`, at: a.updated_at,
    })),
    ...(o.tickets?.recent ?? []).map((t) => ({
      kind: "ticket" as const, key: `t-${t.uid}`, label: t.title, sub: t.state, to: `/tickets/${t.uid}`, at: t.updated_at,
    })),
    ...(o.documents?.recent ?? []).map((d) => ({
      kind: "document" as const, key: `d-${d.uid}`, label: d.title, sub: d.code, to: `/documents/${d.uid}`, at: d.updated_at,
    })),
  ]
    .filter((r) => r.at)
    .sort((a, b) => new Date(b.at!).getTime() - new Date(a.at!).getTime())
    .slice(0, 12);
  return (
    <Card title="Recent activity">
      {rows.length === 0 ? (
        <Empty>Nothing yet.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {rows.map((r) => (
            <li key={r.key}>
              <Link to={r.to} className="flex items-center justify-between gap-3 py-2 text-sm hover:bg-slate-50">
                <span className="flex min-w-0 items-center gap-2">
                  <KindBadge kind={r.kind} className="w-[76px] shrink-0 justify-center" />
                  <span className="truncate text-slate-900">{r.label}</span>
                  <span className="hidden truncate text-xs text-slate-400 md:inline">{r.sub}</span>
                </span>
                <span className="shrink-0 text-xs text-slate-400">{relativeTime(r.at!)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
