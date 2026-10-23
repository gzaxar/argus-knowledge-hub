import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { activitiesApi, membersApi, problemText, workspacesApi } from "../../api/client";
import type { Activity, ActivityStatus, MyWorkspace } from "../../api/types";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const STATUSES: { id: ActivityStatus; label: string; tone: string }[] = [
  { id: "planned", label: "Planned", tone: "bg-sky-100 text-sky-800" },
  { id: "in_progress", label: "Under way", tone: "bg-amber-100 text-amber-900" },
  { id: "completed", label: "Done", tone: "bg-emerald-100 text-emerald-800" },
  { id: "skipped", label: "Skipped", tone: "bg-slate-100 text-slate-600" },
  { id: "cancelled", label: "Cancelled", tone: "bg-slate-100 text-slate-500 line-through" },
];
const label = (s: string) => STATUSES.find((x) => x.id === s)?.label ?? s;
const tone = (s: string) => STATUSES.find((x) => x.id === s)?.tone ?? "";

const day0 = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromIsoDay = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const weekStart = (d: Date) => addDays(day0(d), -((d.getDay() + 6) % 7));

/** The workspaces one may put an activity in: one's own, readable. */
function useMyWorkspaces(): MyWorkspace[] {
  const q = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  return (q.data ?? []).filter((w) => w.can_read || w.can_read_tickets);
}

/** Choose workspaces among one's own; ones already chosen that are not one's own stay, shown by count. */
function WorkspacePicker({ value, onChange, mine }: { value: string[]; onChange: (v: string[]) => void; mine: MyWorkspace[] }) {
  const others = value.filter((id) => !mine.some((w) => w.id === id)).length;
  return (
    <fieldset className="space-y-1">
      <legend className="text-xs text-slate-600">In the workspaces</legend>
      {mine.map((w) => (
        <label key={w.id} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.includes(w.id)}
                 onChange={(e) => onChange(e.target.checked ? [...value, w.id] : value.filter((x) => x !== w.id))} />
          {w.name}
        </label>
      ))}
      {others > 0 && <p className="text-xs text-slate-500">and {others} more you are not a member of (kept)</p>}
    </fieldset>
  );
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

function when(a: Activity, basis: "planned" | "actual"): Date | null {
  const v = basis === "actual" ? (a.actual_start ?? a.actual_end) : (a.planned_start ?? a.due_at);
  return v ? new Date(v) : null;
}
function fmt(v: string | null, allDay: boolean): string {
  if (!v) return "—";
  const d = new Date(v);
  return allDay ? d.toLocaleDateString() : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

/** The workspace's activities over a range — by when they are planned or when the work was actually done —
 * as a calendar or a list, filtered, with counts. Only what you may see is shown or counted. */
export function ActivitiesPage() {
  const qc = useQueryClient();
  const [from, setFrom] = useState(() => weekStart(new Date()));
  const [to, setTo] = useState(() => addDays(weekStart(new Date()), 7));         // exclusive
  const [basis, setBasis] = useState<"planned" | "actual">("planned");
  const [mode, setMode] = useState<"calendar" | "list">("calendar");
  const [statuses, setStatuses] = useState<Set<ActivityStatus>>(new Set());
  const [owner, setOwner] = useState("");
  const [mine, setMine] = useState(false);
  const [recurring, setRecurring] = useState<"" | "true" | "false">("");
  const [visibility, setVisibility] = useState<"" | "workspace" | "private">("");
  const [asset, setAsset] = useState("");
  const [ticket, setTicket] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(200);
  const [search, setSearch] = useSearchParams();
  const [open, setOpenState] = useState<string | null>(() => search.get("open"));
  const setOpen = (id: string | null) => {
    setOpenState(id);
    if (!id && search.has("open")) { search.delete("open"); setSearch(search, { replace: true }); }
  };
  const [creating, setCreating] = useState(false);

  const params = {
    from: from.toISOString(), to: to.toISOString(), basis, tz: TZ, limit,
    status: [...statuses].sort().join(","), owner, mine: mine || undefined, recurring, visibility,
    asset_uid: asset, ticket_uid: ticket, q,
  };
  const list = useQuery({ queryKey: ["activities", params], queryFn: () => activitiesApi.list(params) });
  const members = useQuery({ queryKey: ["member-directory"], queryFn: membersApi.directory });
  const names = useMemo(() => new Map((members.data ?? []).map((m) => [m.user_id, m.name || m.email])), [members.data]);
  const items = list.data?.items ?? [];
  // Assets and tickets to filter by: those the range's activities refer to.
  const assets = useMemo(() => [...new Set(items.map((a) => a.asset_uid).filter(Boolean) as string[])], [items]);
  const tickets = useMemo(() => [...new Set(items.map((a) => a.ticket_uid).filter(Boolean) as string[])], [items]);
  const days = Math.round((to.getTime() - from.getTime()) / 86400000);

  const shift = (sign: number) => { setFrom(addDays(from, sign * days)); setTo(addDays(to, sign * days)); };
  const preset = (p: "week" | "month" | "next30") => {
    const now = new Date();
    if (p === "week") { setFrom(weekStart(now)); setTo(addDays(weekStart(now), 7)); }
    if (p === "month") { const s = new Date(now.getFullYear(), now.getMonth(), 1); setFrom(s); setTo(new Date(now.getFullYear(), now.getMonth() + 1, 1)); }
    if (p === "next30") { setFrom(day0(now)); setTo(addDays(day0(now), 30)); }
  };
  const toggle = (s: ActivityStatus) => setStatuses((cur) => { const n = new Set(cur); if (n.has(s)) n.delete(s); else n.add(s); return n; });
  const counts = list.data?.counts ?? {};

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Activities</h1>
          <p className="mt-1 text-sm text-slate-500">
            Work planned, under way and done in this workspace. Times are in {TZ}; a recurring activity shows each of its
            occurrences in the range.
          </p>
        </div>
        <button type="button" onClick={() => setCreating(true)} className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white">
          New activity
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm">
        <button type="button" onClick={() => shift(-1)} className="rounded border border-slate-300 px-2 py-1" aria-label="Previous">‹</button>
        <input type="date" value={isoDay(from)} onChange={(e) => e.target.value && setFrom(fromIsoDay(e.target.value))}
               className="rounded border border-slate-300 px-2 py-1" aria-label="From" />
        <span>to</span>
        <input type="date" value={isoDay(addDays(to, -1))} onChange={(e) => e.target.value && setTo(addDays(fromIsoDay(e.target.value), 1))}
               className="rounded border border-slate-300 px-2 py-1" aria-label="To (inclusive)" />
        <button type="button" onClick={() => shift(1)} className="rounded border border-slate-300 px-2 py-1" aria-label="Next">›</button>
        <span className="mx-1 text-slate-300">|</span>
        {(["week", "month", "next30"] as const).map((p) => (
          <button key={p} type="button" onClick={() => preset(p)} className="rounded px-2 py-1 text-slate-600 hover:bg-slate-100">
            {p === "week" ? "This week" : p === "month" ? "This month" : "Next 30 days"}
          </button>
        ))}
        <span className="mx-1 text-slate-300">|</span>
        <div className="flex overflow-hidden rounded border border-slate-300" role="group" aria-label="Dates by">
          {(["planned", "actual"] as const).map((b) => (
            <button key={b} type="button" onClick={() => setBasis(b)}
                    className={`px-3 py-1 ${basis === b ? "bg-slate-900 text-white" : "bg-white text-slate-700"}`}>
              {b === "planned" ? "Planned for" : "Done on"}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded border border-slate-300" role="group" aria-label="View">
          {(["calendar", "list"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)}
                    className={`px-3 py-1 ${mode === m ? "bg-slate-900 text-white" : "bg-white text-slate-700"}`}>
              {m === "calendar" ? "Calendar" : "List"}
            </button>
          ))}
        </div>
        <p className="w-full text-xs text-slate-500">
          {basis === "planned"
            ? "By planned date: what is planned in the range, including what starts before it and runs into it."
            : "By the date the work was actually done — which may be recorded long after."}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {STATUSES.map((s) => (
          <button key={s.id} type="button" onClick={() => toggle(s.id)} aria-pressed={statuses.has(s.id)}
                  className={`rounded-full border px-3 py-1 ${statuses.has(s.id) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white"}`}>
            {s.label} <span className="tabular-nums opacity-70">{counts[s.id] ?? 0}</span>
          </button>
        ))}
        {(counts.overdue ?? 0) > 0 && (
          <span className="rounded-full bg-rose-100 px-3 py-1 text-rose-800">Overdue {counts.overdue}</span>
        )}
        <span className="mx-1 text-slate-300">|</span>
        <label className="flex items-center gap-1"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine</label>
        <select value={owner} onChange={(e) => setOwner(e.target.value)} className="rounded border border-slate-300 px-2 py-1" aria-label="Owner">
          <option value="">Any owner</option>
          {(members.data ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>)}
        </select>
        <select value={recurring} onChange={(e) => setRecurring(e.target.value as typeof recurring)} className="rounded border border-slate-300 px-2 py-1" aria-label="Recurrence">
          <option value="">Recurring or not</option><option value="true">Recurring</option><option value="false">One-off</option>
        </select>
        <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)} className="rounded border border-slate-300 px-2 py-1" aria-label="Visibility">
          <option value="">Any visibility</option><option value="workspace">Workspace</option><option value="private">Private</option>
        </select>
        {assets.length > 0 && (
          <select value={asset} onChange={(e) => setAsset(e.target.value)} className="rounded border border-slate-300 px-2 py-1" aria-label="Asset">
            <option value="">Any asset</option>
            {assets.map((a) => <option key={a} value={a}>{a.slice(0, 18)}</option>)}
          </select>
        )}
        {tickets.length > 0 && (
          <select value={ticket} onChange={(e) => setTicket(e.target.value)} className="rounded border border-slate-300 px-2 py-1" aria-label="Ticket">
            <option value="">Any ticket</option>
            {tickets.map((t) => <option key={t} value={t}>{t.slice(0, 18)}</option>)}
          </select>
        )}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="w-40 rounded border border-slate-300 px-2 py-1" />
      </div>

      {list.isError && <p className="text-sm text-rose-700">{problemText(list.error)}</p>}
      {list.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {list.data && (mode === "calendar" && days <= 42
        ? <Calendar items={items} from={from} to={to} basis={basis} onOpen={setOpen} />
        : <ActivityTable items={items} basis={basis} names={names} onOpen={setOpen} calendarTooWide={mode === "calendar"} />)}
      {list.data?.next_offset != null && (
        <button type="button" onClick={() => setLimit((l) => l + 200)} className="text-sm text-indigo-600 hover:underline">
          Show more ({list.data.total - items.length} more in this range)
        </button>
      )}
      {list.data?.truncated && <p className="text-xs text-amber-800">This range holds more than can be shown: narrow it or filter.</p>}

      {open && <ActivityPanel id={open} names={names} onClose={() => setOpen(null)}
                              onChanged={() => void qc.invalidateQueries({ queryKey: ["activities"] })} />}
      {creating && <NewActivity onClose={() => setCreating(false)}
                                onCreated={() => { setCreating(false); void qc.invalidateQueries({ queryKey: ["activities"] }); }} />}
    </div>
  );
}

function Calendar({ items, from, to, basis, onOpen }: {
  items: Activity[]; from: Date; to: Date; basis: "planned" | "actual"; onOpen: (id: string) => void;
}) {
  const byDay = new Map<string, Activity[]>();
  for (const a of items) {
    let d = when(a, basis);
    if (!d) continue;
    if (d < from) d = from;                                   // began before the range: on its first day
    const k = isoDay(d);
    byDay.set(k, [...(byDay.get(k) ?? []), a]);
  }
  const start = weekStart(from);
  const cells: Date[] = [];
  for (let d = start; d < to || cells.length % 7 !== 0; d = addDays(d, 1)) cells.push(d);
  const today = isoDay(new Date());
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[760px] grid-cols-7 gap-px rounded-lg border border-slate-200 bg-slate-200">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} className="bg-slate-50 px-2 py-1 text-xs font-medium text-slate-500">{d}</div>
        ))}
        {cells.map((d) => {
          const k = isoDay(d);
          const inRange = d >= from && d < to;
          return (
            <div key={k} className={`min-h-28 p-1.5 ${inRange ? "bg-white" : "bg-slate-50 text-slate-400"}`}>
              <div className={`mb-1 text-xs ${k === today ? "font-bold text-indigo-700" : "text-slate-500"}`}>{d.getDate()}</div>
              <ul className="space-y-1">
                {inRange && (byDay.get(k) ?? []).map((a) => (
                  <li key={a.id}>
                    <button type="button" onClick={() => onOpen(a.id)}
                            className={`w-full truncate rounded px-1.5 py-0.5 text-left text-xs ${tone(a.status)} ${a.overdue ? "ring-1 ring-rose-400" : ""}`}
                            title={`${a.title} — ${label(a.status)}`}>
                      {!a.all_day && when(a, basis) && (
                        <span className="tabular-nums">{when(a, basis)!.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} </span>
                      )}
                      {a.recurring && "↻ "}{a.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ActivityTable({ items, basis, names, onOpen, calendarTooWide }: {
  items: Activity[]; basis: "planned" | "actual"; names: Map<string, string>; onOpen: (id: string) => void; calendarTooWide: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      {calendarTooWide && <p className="px-3 py-2 text-xs text-slate-500">The calendar shows up to six weeks: here is the list.</p>}
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2">{basis === "planned" ? "Planned" : "Done"}</th><th className="px-3 py-2">Activity</th>
            <th className="px-3 py-2">State</th><th className="px-3 py-2">Owner</th><th className="px-3 py-2">Recorded</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((a) => (
            <tr key={a.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(a.id)}>
              <td className="whitespace-nowrap px-3 py-2 tabular-nums">{fmt(basis === "planned" ? (a.planned_start ?? a.due_at) : (a.actual_end ?? a.actual_start), a.all_day)}</td>
              <td className="px-3 py-2">{a.recurring && <span title={a.recurrence ?? ""}>↻ </span>}{a.title}
                {a.visibility === "private" && <span className="ml-1 text-xs text-slate-400">(private)</span>}</td>
              <td className="px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-xs ${tone(a.status)}`}>{label(a.status)}</span>
                {a.overdue && <span className="ml-1 text-xs text-rose-700">overdue</span>}</td>
              <td className="px-3 py-2 text-slate-600">{a.owner_user_id ? names.get(a.owner_user_id) ?? "—" : "—"}</td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{fmt(a.created_at, false)}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-400">Nothing in this range.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function ActivityPanel({ id, names, onClose, onChanged }: {
  id: string; names: Map<string, string>; onClose: () => void; onChanged: () => void;
}) {
  const qc = useQueryClient();
  const [current, setCurrent] = useState(id);
  const a = useQuery({ queryKey: ["activity", current], queryFn: () => activitiesApi.get(current) });
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [planned, setPlanned] = useState("");
  const [scope, setScope] = useState<"this" | "future" | "series">("this");
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const mine = useMyWorkspaces();
  const wsName = (id: string) => mine.find((w) => w.id === id)?.name;
  const [error, setError] = useState<string | null>(null);
  const done = (x: Activity) => { setError(null); setEditing(false); setCurrent(x.id); qc.setQueryData(["activity", x.id], x); onChanged(); };
  const act = useMutation({ mutationFn: (action: "start" | "complete" | "skip" | "cancel" | "reopen") => activitiesApi.act(current, action),
                            onSuccess: done, onError: (e) => setError(problemText(e)) });
  const save = useMutation({
    mutationFn: () => activitiesApi.change(current, {
      ...(title !== a.data?.title ? { title } : {}),
      ...(planned ? { planned_start: new Date(planned).toISOString() } : {}),
      ...(a.data && !sameSet(workspaces, a.data.workspace_ids) ? { workspace_ids: workspaces } : {}),
    }, scope),
    onSuccess: done, onError: (e) => setError(problemText(e)) });
  const x = a.data;
  const workspacesChanged = !!x && editing && !sameSet(workspaces, x.workspace_ids);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-lg font-semibold text-slate-900">{x?.title ?? "…"}</h2>
          <button type="button" onClick={onClose} className="text-slate-500" aria-label="Close">✕</button>
        </div>
        {a.isError && <p className="text-sm text-rose-700">{problemText(a.error)}</p>}
        {x && (
          <div className="mt-2 space-y-3 text-sm">
            <p><span className={`rounded px-1.5 py-0.5 text-xs ${tone(x.status)}`}>{label(x.status)}</span>
              {x.overdue && <span className="ml-2 text-xs text-rose-700">overdue</span>}
              <span className="ml-2 text-xs text-slate-500">{x.visibility === "private" ? "Private: its owner and assignee" : "The workspace sees it"}</span></p>
            {x.description && <p className="whitespace-pre-wrap text-slate-700">{x.description}</p>}
            <dl className="grid grid-cols-[110px_1fr] gap-y-1">
              <dt className="text-slate-500">Planned</dt><dd>{fmt(x.planned_start, x.all_day)}</dd>
              {x.due_at && <><dt className="text-slate-500">Due</dt><dd>{fmt(x.due_at, x.all_day)}</dd></>}
              <dt className="text-slate-500">Started</dt><dd>{fmt(x.actual_start, false)}</dd>
              <dt className="text-slate-500">Done</dt><dd>{fmt(x.actual_end, x.all_day)}</dd>
              <dt className="text-slate-500">Recorded</dt><dd>{fmt(x.created_at, false)}</dd>
              <dt className="text-slate-500">Workspaces</dt>
              <dd>{x.workspace_ids.map((id) => wsName(id) ?? null).filter(Boolean).join(", ") || "—"}
                {x.workspace_ids.some((id) => !wsName(id)) &&
                  <span className="text-xs text-slate-400"> + {x.workspace_ids.filter((id) => !wsName(id)).length} other</span>}</dd>
              <dt className="text-slate-500">Owner</dt><dd>{x.owner_user_id ? names.get(x.owner_user_id) ?? x.owner_user_id : "—"}</dd>
              {x.assignee_user_id && <><dt className="text-slate-500">Assignee</dt><dd>{names.get(x.assignee_user_id) ?? x.assignee_user_id}</dd></>}
              {x.series && <><dt className="text-slate-500">Repeats</dt><dd>{x.series.text} <span className="text-xs text-slate-400">({x.series.timezone})</span></dd></>}
              {x.asset_uid && <><dt className="text-slate-500">Asset</dt><dd><Link to={`/assets/${x.asset_uid}`} className="text-indigo-600 hover:underline">open</Link></dd></>}
              {x.ticket_uid && <><dt className="text-slate-500">Ticket</dt><dd><Link to={`/tickets/${x.ticket_uid}`} className="text-indigo-600 hover:underline">open</Link> <span className="text-xs text-slate-400">(not changed by it)</span></dd></>}
            </dl>
            {typeof x.provenance?.transcript === "string" && (
              <p className="text-xs text-slate-500">Captured by voice: “{x.provenance.transcript as string}”</p>
            )}
            {error && <p className="text-rose-700">{error}</p>}
            {x.may_change && !editing && (
              <div className="flex flex-wrap gap-2">
                {x.status === "planned" && <button type="button" onClick={() => act.mutate("start")} className="rounded border border-slate-300 px-3 py-1">Start</button>}
                {(x.status === "planned" || x.status === "in_progress") && <button type="button" onClick={() => act.mutate("complete")} className="rounded bg-emerald-700 px-3 py-1 text-white">Done</button>}
                {x.status === "planned" && x.recurring && <button type="button" onClick={() => act.mutate("skip")} className="rounded border border-slate-300 px-3 py-1">Skip this one</button>}
                {(x.status === "planned" || x.status === "in_progress") && <button type="button" onClick={() => act.mutate("cancel")} className="rounded border border-slate-300 px-3 py-1">Cancel</button>}
                {!(x.status === "planned" || x.status === "in_progress") && <button type="button" onClick={() => act.mutate("reopen")} className="rounded border border-slate-300 px-3 py-1">Reopen</button>}
                <button type="button" onClick={() => { setEditing(true); setTitle(x.title); setPlanned(""); setWorkspaces(x.workspace_ids); }} className="rounded border border-slate-300 px-3 py-1">Change…</button>
              </div>
            )}
            {editing && (
              <div className="space-y-2 rounded border border-slate-200 p-3">
                <input value={title} onChange={(e) => setTitle(e.target.value)} className="w-full rounded border border-slate-300 px-2 py-1" aria-label="Title" />
                <label className="block text-xs text-slate-600">New planned time (leave empty to keep it)
                  <input type="datetime-local" value={planned} onChange={(e) => setPlanned(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1" /></label>
                <WorkspacePicker value={workspaces} onChange={setWorkspaces} mine={mine} />
                {workspacesChanged && (x.asset_uid || x.ticket_uid || x.document_uid) && !workspaces.includes(x.workspace_id) && (
                  <p className="text-xs text-amber-800">It refers to records of {wsName(x.workspace_id) ?? "its own workspace"}: it cannot leave it while it does.</p>
                )}
                {x.recurring && workspacesChanged && scope === "this" && (
                  <p className="text-xs text-amber-800">The workspaces belong to the series: choose “this and future” or “the entire series”.</p>
                )}
                {x.recurring && (
                  <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} className="w-full rounded border border-slate-300 px-2 py-1" aria-label="Apply to">
                    <option value="this">This occurrence</option><option value="future">This and future occurrences</option><option value="series">The entire series</option>
                  </select>
                )}
                <div className="flex gap-2">
                  <button type="button" onClick={() => save.mutate()}
                          disabled={save.isPending || workspaces.length === 0 || (x.recurring && workspacesChanged && scope === "this")}
                          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40">Save</button>
                  <button type="button" onClick={() => setEditing(false)} className="rounded border border-slate-300 px-3 py-1">Cancel</button>
                </div>
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

const RULES: { id: string; label: string; rule: (d: Date) => string | null }[] = [
  { id: "", label: "Once", rule: () => null },
  { id: "daily", label: "Every day", rule: () => "FREQ=DAILY" },
  { id: "weekdays", label: "Every weekday", rule: () => "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" },
  { id: "weekly", label: "Every week on that day", rule: (d) => `FREQ=WEEKLY;BYDAY=${["SU", "MO", "TU", "WE", "TH", "FR", "SA"][d.getDay()]}` },
  { id: "monthly", label: "Every month on that date", rule: (d) => `FREQ=MONTHLY;BYMONTHDAY=${d.getDate()}` },
];

function NewActivity({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [start, setStart] = useState("");
  const [repeat, setRepeat] = useState("");
  const [count, setCount] = useState("");
  const [privateOnly, setPrivateOnly] = useState(false);
  const here = useCurrentWorkspaceId();
  const mine = useMyWorkspaces();
  const [also, setAlso] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => {
      const d = new Date(start);
      const base = RULES.find((r) => r.id === repeat)?.rule(d) ?? null;
      return activitiesApi.create({
        uid: crypto.randomUUID(), title, description: description || null, timezone: TZ, planned_start: d.toISOString(),
        visibility: privateOnly ? "private" : "workspace", rrule: base ? (count ? `${base};COUNT=${count}` : base) : null,
        ...(also.length ? { workspace_ids: also } : {}),
      });
    },
    onSuccess: onCreated, onError: (e) => setError(problemText(e)) });
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/20" onClick={onClose}>
      <div className="w-full max-w-md space-y-2 rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">New activity</h2>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" rows={3} className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        <label className="block text-xs text-slate-600">Planned for ({TZ})
          <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm" /></label>
        <div className="flex gap-2">
          <select value={repeat} onChange={(e) => setRepeat(e.target.value)} className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" aria-label="Repeats">
            {RULES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
          {repeat && <input value={count} onChange={(e) => setCount(e.target.value.replace(/\D/g, ""))} placeholder="times (∞)" className="w-24 rounded border border-slate-300 px-2 py-1.5 text-sm" />}
        </div>
        {mine.filter((w) => w.id !== here).length > 0 && (
          <fieldset className="space-y-1">
            <legend className="text-xs text-slate-600">Also in</legend>
            {mine.filter((w) => w.id !== here).map((w) => (
              <label key={w.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={also.includes(w.id)}
                       onChange={(e) => setAlso(e.target.checked ? [...also, w.id] : also.filter((x) => x !== w.id))} />
                {w.name}
              </label>
            ))}
          </fieldset>
        )}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={privateOnly} onChange={(e) => setPrivateOnly(e.target.checked)} /> Only for me (private)</label>
        {error && <p className="text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-3 py-1.5 text-sm">Cancel</button>
          <button type="button" onClick={() => create.mutate()} disabled={!title.trim() || !start || create.isPending}
                  className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40">Create</button>
        </div>
      </div>
    </div>
  );
}
