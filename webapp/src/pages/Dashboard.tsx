import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { activitiesApi, hubApi } from "../api/client";
import type { HubOverview } from "../api/hubTypes";
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
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Operations cockpit</h1>
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

function Kpis({ o }: { o: HubOverview }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {o.tickets && (
        <>
          <StatTile label="Open tickets" value={o.tickets.open} tone="amber" to="/tickets" hint={`${o.tickets.total} in total`} />
          <StatTile
            label="Unassigned"
            value={o.tickets.unassigned}
            tone={o.tickets.unassigned ? "red" : "slate"}
            to="/tickets/board"
            hint="Open, nobody on it"
          />
          <StatTile
            label="Not linked to equipment"
            value={o.tickets.without_asset}
            tone={o.tickets.without_asset ? "amber" : "slate"}
            to="/tickets"
            hint="Open tickets with no asset"
          />
        </>
      )}
      {o.documents && (
        <>
          <StatTile label="Awaiting approval" value={o.documents.in_review} tone="indigo" to="/documents" hint="Revisions in review" />
          <StatTile
            label="Reviews overdue"
            value={o.documents.review_overdue.length}
            tone={o.documents.review_overdue.length ? "red" : "slate"}
            to="/documents"
            hint="Published past their review date"
          />
        </>
      )}
      {o.assets && <StatTile label="Assets" value={o.assets.own.toLocaleString()} to="/assets/search" hint="Owned by this workspace" />}
    </div>
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

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** The workspace's activities that need attention: under way, overdue, or planned for today. */
function ActivitiesNow() {
  const q = useQuery({
    queryKey: ["activities", "attention", TZ],
    queryFn: () => activitiesApi.list({ view: "attention", tz: TZ, limit: 8 }),
    refetchInterval: 60_000,
  });
  if (q.isError) return null;                                // e.g. a server without activities: no card
  const c = q.data?.counts ?? {};
  const items = q.data?.items ?? [];
  const at = (v: string | null, allDay: boolean) =>
    !v ? "" : allDay ? new Date(v).toLocaleDateString() : new Date(v).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  return (
    <Card title="Activities" action={
      <span className="flex gap-3 text-xs text-slate-500">
        <span>{c.in_progress ?? 0} under way</span>
        <span className={c.overdue ? "font-medium text-rose-700" : ""}>{c.overdue ?? 0} overdue</span>
        <span>{c.today ?? 0} today</span>
        <span>{c.done_today ?? 0} done today</span>
        <Link to="/activities" className="text-indigo-600 hover:underline">All</Link>
      </span>
    }>
      {q.isLoading ? <Empty>Loading…</Empty> : items.length === 0 ? (
        <Empty>Nothing under way, overdue or planned for today.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((a) => (
            <li key={a.id}>
              <Link to={`/activities?open=${encodeURIComponent(a.id)}`}
                    className="flex items-center justify-between gap-3 py-2 text-sm hover:bg-slate-50">
                <span className="min-w-0 truncate text-slate-900">{a.recurring && "↻ "}{a.title}</span>
                <span className="flex shrink-0 items-center gap-2 text-xs">
                  {a.status === "in_progress"
                    ? <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">Under way</span>
                    : a.overdue
                      ? <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-800">Overdue</span>
                      : <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-800">Today</span>}
                  <span className="tabular-nums text-slate-400">
                    {a.status === "in_progress" ? at(a.actual_start, false) : at(a.planned_start ?? a.due_at, a.all_day)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {q.data && q.data.total > items.length && (
        <Link to="/activities" className="mt-1 block text-xs text-indigo-600 hover:underline">{q.data.total - items.length} more</Link>
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
