import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { globalValuesApi, issuesApi, membersApi, schemasApi } from "../../api/client";
import { Issue } from "../../api/types";
import { PriorityBadge, SearchBox, ViewSwitch } from "../../components/browse/Browse";
import { typeFamily } from "../../components/browse/TypeExplorer";
import { ticketMatches, useTicketFilters } from "./List";

const STATE_ORDER = ["new", "in_progress", "pending", "resolved", "closed"];

const COLUMN_ACCENT: Record<string, string> = {
  new: "border-t-slate-400",
  in_progress: "border-t-blue-500",
  pending: "border-t-amber-500",
  resolved: "border-t-green-500",
  closed: "border-t-slate-300",
};


type GroupBy = "state" | "priority" | "assignee";

export function IssueBoard() {
  const queryClient = useQueryClient();
  const [groupBy, setGroupBy] = useState<GroupBy>("state");
  // The list's filters (in the address): switching between List and Board keeps them.
  const f = useTicketFilters();
  const typeFilter = f.type ?? "";
  const [dragging, setDragging] = useState<string | null>(null);
  const [overColumn, setOverColumn] = useState<string | null>(null);

  const issues = useQuery({ queryKey: ["issues"], queryFn: () => issuesApi.list() });
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  const globalValues = useQuery({ queryKey: ["global-values"], queryFn: globalValuesApi.list });

  const ticketGlobals = globalValues.data?.filter((gv) => gv.applies_to === "tickets") ?? [];
  const statusOptions = ticketGlobals.find((gv) => gv.key === "status")?.options ?? [];
  const priorityOptions = ticketGlobals.find((gv) => gv.key === "priority")?.options ?? [];
  const ticketTypes = schemas.data?.filter((s) => s.applies_to === "tickets") ?? [];

  const moveMutation = useMutation({
    mutationFn: ({ uid, state }: { uid: string; state: string }) =>
      issuesApi.update(uid, { state }),
    // The board is the whole page, so a move has to be reflected without a
    // visible reload — optimistic, then reconciled by the refetch.
    onMutate: async ({ uid, state }) => {
      await queryClient.cancelQueries({ queryKey: ["issues"] });
      const previous = queryClient.getQueryData<Issue[]>(["issues"]);
      queryClient.setQueryData<Issue[]>(["issues"], (old) =>
        (old ?? []).map((i) => (i.uid === uid ? { ...i, state } : i)),
      );
      return { previous };
    },
    onError: (_e, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(["issues"], context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["issues"] }),
  });

  const labelFor = (key: string, value: string | null) => {
    if (groupBy === "state") {
      return statusOptions.find((o) => o.id === key)?.value ?? key;
    }
    if (groupBy === "priority") {
      return value === null
        ? "No priority"
        : priorityOptions.find((o) => o.id === key)?.value ?? key;
    }
    if (value === null) return "Unassigned";
    const member = members.data?.find((m) => m.user_id === key);
    return member?.name || member?.email || key;
  };

  const { columns, cards } = useMemo(() => {
    const family = typeFamily(ticketTypes, typeFilter || null);
    // Columns are the states: every state shows, whatever the list's state filter.
    const visible = (issues.data ?? []).filter((i) => ticketMatches(i, { q: f.q, family, state: "all", assignee: f.assignee }));
    const grouped = new Map<string, Issue[]>();
    for (const issue of visible) {
      const raw =
        groupBy === "state"
          ? issue.state
          : groupBy === "priority"
            ? issue.priority
            : issue.assignee;
      const key = raw ?? "__none__";
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key)!.push(issue);
    }

    let keys: string[];
    if (groupBy === "state") {
      // Every state gets a column even when empty: an empty "Pending" is
      // information, and a column that appears only when used makes the
      // board jump around as work moves.
      keys = STATE_ORDER;
    } else {
      const order = groupBy === "priority" ? priorityOptions.map((o) => o.id) : [];
      const present = [...grouped.keys()].filter((k) => k !== "__none__");
      present.sort((a, b) => {
        const ia = order.indexOf(a);
        const ib = order.indexOf(b);
        if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
        return a.localeCompare(b);
      });
      keys = [...present, "__none__"];
    }
    return { columns: keys, cards: grouped };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issues.data, groupBy, typeFilter, f.q, f.assignee, priorityOptions, statusOptions, members.data, schemas.data]);

  if (issues.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Tickets</h1>
          <p className="mt-1 text-sm text-slate-500">
            {groupBy === "state"
              ? "Drag a ticket to another column to change its state."
              : "Grouped for viewing — drag to move only when grouped by state."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SearchBox value={f.q} onChange={(v) => f.set({ q: v })} label="Search tickets" placeholder="Search by title…" />
          <select
            aria-label="Ticket type"
            value={typeFilter}
            onChange={(e) => f.set({ type: e.target.value })}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All ticket types</option>
            {ticketTypes.map((t) => (
              <option key={t.uid} value={t.uid}>
                {t.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Group by"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="state">Group by state</option>
            <option value="priority">Group by priority</option>
            <option value="assignee">Group by assignee</option>
          </select>
          <ViewSwitch views={[
            { label: "List", to: "/tickets", current: false },
            { label: "Board", to: "/tickets/board", current: true },
          ]} />
        </div>
      </div>

      <div className="mt-4 flex min-h-0 flex-1 gap-3 overflow-x-auto pb-4">
        {columns.map((key) => {
          const value = key === "__none__" ? null : key;
          const items = cards.get(key) ?? [];
          const droppable = groupBy === "state" && value !== null;
          return (
            <div
              key={key}
              onDragOver={(e) => {
                if (!droppable || !dragging) return;
                e.preventDefault();
                setOverColumn(key);
              }}
              onDragLeave={() => setOverColumn((c) => (c === key ? null : c))}
              onDrop={(e) => {
                e.preventDefault();
                setOverColumn(null);
                if (!droppable || !dragging) return;
                const moved = (issues.data ?? []).find((i) => i.uid === dragging);
                setDragging(null);
                if (moved && moved.state !== value) {
                  moveMutation.mutate({ uid: moved.uid, state: value! });
                }
              }}
              className={`flex w-72 shrink-0 flex-col rounded-lg border border-t-4 bg-slate-50 ${
                COLUMN_ACCENT[key] ?? "border-t-slate-300"
              } ${
                overColumn === key && droppable
                  ? "border-indigo-400 bg-indigo-50"
                  : "border-slate-200"
              }`}
            >
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-sm font-medium text-slate-700">{labelFor(key, value)}</span>
                <span className="rounded bg-white px-1.5 py-0.5 text-xs tabular-nums text-slate-500">
                  {items.length}
                </span>
              </div>

              <div className="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
                {items.map((issue) => (
                  <Link
                    key={issue.uid}
                    to={`/tickets/${issue.uid}`}
                    draggable={groupBy === "state"}
                    onDragStart={() => setDragging(issue.uid)}
                    onDragEnd={() => {
                      setDragging(null);
                      setOverColumn(null);
                    }}
                    className={`block rounded border border-slate-200 bg-white p-2.5 text-sm shadow-sm hover:border-slate-300 ${
                      dragging === issue.uid ? "opacity-50" : ""
                    }`}
                  >
                    <p className="line-clamp-3 text-slate-900">{issue.title}</p>
                    <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                      <PriorityBadge priority={issue.priority}
                                     label={priorityOptions.find((o) => o.id === issue.priority)?.value} />
                      {typeof issue.attributes?.jira_key === "string" && (
                        <span className="font-mono">{issue.attributes.jira_key as string}</span>
                      )}
                      {issue.assignee && (
                        <span className="ml-auto truncate">
                          {members.data?.find((m) => m.user_id === issue.assignee)?.name ??
                            issue.assignee}
                        </span>
                      )}
                    </div>
                  </Link>
                ))}
                {items.length === 0 && (
                  <p className="px-1 py-4 text-center text-xs text-slate-400">Nothing here</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="shrink-0 text-xs text-slate-400">
        Moving a ticket changes it here only — nothing is written back to Jira.
      </p>
    </div>
  );
}
