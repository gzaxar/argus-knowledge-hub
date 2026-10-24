import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { globalValuesApi, issuesApi, membersApi, schemasApi } from "../../api/client";
import type { Issue } from "../../api/types";
import { AttributeFilterInput } from "../../components/AttributeFilterInput";
import { activeFilterCount, defaultFilterFor, FilterState, matchesFilters } from "../../components/AttributeFilters";
import {
  BrowsePage, Clip, ColumnSettings, MenuButton, Pager, PriorityBadge, SearchBox, SelectAll, StateBadge, ToolbarSelect,
  ViewSwitch, useBrowseParams, useColumns, usePage, useSelection,
} from "../../components/browse/Browse";
import { countBy, TypeExplorer, typeFamily } from "../../components/browse/TypeExplorer";
import { BulkActionsBar } from "../../components/BulkActionsBar";
import { ListDate, SortHeader, priorityRank, useSort } from "../../components/SortableTable";
import { effectiveAttributes } from "../../lib/schemaAttributes";
import { useRights } from "../../lib/permissions";

const COLUMNS = [
  { id: "title", label: "Title", required: true },
  { id: "state", label: "State", initial: true },
  { id: "priority", label: "Priority", initial: true },
  { id: "assignee", label: "Assignee", initial: true },
  { id: "type", label: "Type" },
  { id: "updated", label: "Updated", initial: true },
  { id: "created", label: "Created" },
];

/** Filters the board shares with the list (both read the address). */
export function useTicketFilters() {
  const { get, set } = useBrowseParams();
  return {
    q: get("q"),
    type: get("type") || null,
    state: get("state", "open"),
    assignee: get("assignee"),
    set,
  };
}

/** Whether a ticket passes the filters the list and the board share. */
export function ticketMatches(i: Issue, f: { q: string; family: Set<string> | null; state: string; assignee: string }): boolean {
  const n = f.q.trim().toLowerCase();
  if (n && !i.title.toLowerCase().includes(n)) return false;
  if (f.family && !(i.schema_uid && f.family.has(i.schema_uid))) return false;
  if (f.state === "open" && i.state === "closed") return false;
  if (f.state === "closed" && i.state !== "closed") return false;
  if (!["open", "closed", "all"].includes(f.state) && i.state !== f.state) return false;
  if (f.assignee === "none" && i.assignee) return false;
  if (f.assignee && f.assignee !== "none" && i.assignee !== f.assignee) return false;
  return true;
}

export function IssueList() {
  const queryClient = useQueryClient();
  const rights = useRights();
  const f = useTicketFilters();
  const [fieldFilters, setFieldFilters] = useState<FilterState>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const selection = useSelection("tickets");
  const columns = useColumns("tickets", COLUMNS);

  const issues = useQuery({ queryKey: ["issues"], queryFn: () => issuesApi.list() });
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, staleTime: 60_000 });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory, staleTime: 60_000 });
  const globals = useQuery({ queryKey: ["global-values"], queryFn: globalValuesApi.list, staleTime: 60_000 });
  const statusOptions = globals.data?.find((g) => g.applies_to === "tickets" && g.key === "status")?.options ?? [];
  const priorityOptions = globals.data?.find((g) => g.applies_to === "tickets" && g.key === "priority")?.options ?? [];
  const label = (options: { id: string; value: string }[], id: string | null) => options.find((o) => o.id === id)?.value;
  const rank = (options: { id: string }[], id: string | null) => {
    if (!id) return null;
    const at = options.findIndex((o) => o.id === id);
    return at === -1 ? options.length : at;
  };
  const people = useMemo(() => new Map((members.data ?? []).map((m) => [m.user_id, m.name || m.email])), [members.data]);

  const ticketSchemas = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "tickets"), [schemas.data]);
  const typeName = useMemo(() => new Map(ticketSchemas.map((s) => [s.uid, s.name])), [ticketSchemas]);
  const family = useMemo(() => typeFamily(ticketSchemas, f.type), [ticketSchemas, f.type]);
  const schema = ticketSchemas.find((s) => s.uid === f.type);
  const attrDefs = effectiveAttributes(schema, schemas.data);

  const counts = useMemo(() => countBy(issues.data, (i) => i.schema_uid), [issues.data]);
  const matched = useMemo(() => (issues.data ?? []).filter((i) =>
    ticketMatches(i, { q: f.q, family, state: f.state, assignee: f.assignee }) &&
    (!schema || Object.keys(fieldFilters).length === 0 || matchesFilters(i.attributes, fieldFilters))),
  [issues.data, f.q, family, f.state, f.assignee, schema, fieldFilters]);
  const { sorted, sort, toggle: sortBy } = useSort(
    matched,
    {
      title: (i) => i.title,
      state: (i) => (statusOptions.length ? rank(statusOptions, i.state) : i.state),
      priority: (i) => (priorityOptions.length ? rank(priorityOptions, i.priority) : priorityRank(i.priority)),
      assignee: (i) => (i.assignee ? people.get(i.assignee) ?? i.assignee : null),
      type: (i) => (i.schema_uid ? typeName.get(i.schema_uid) : null),
      created: (i) => i.created_at,
      updated: (i) => i.updated_at,
    },
    { key: "updated", dir: "desc" },
    "tickets",
  );
  const paging = usePage(sorted);

  return (
    <BrowsePage
      title="Tickets"
      count={issues.data ? `${matched.length}${matched.length !== issues.data.length ? ` of ${issues.data.length}` : ""}` : undefined}
      storageKey="tickets"
      primary={rights.can_create_tickets && (
        <Link to="/tickets/new" className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">New ticket</Link>
      )}
      actions={<MenuButton label="Tools" items={[
        { to: "/search/advanced?entity=tickets", label: "Advanced query", hint: "Combine conditions on any field" },
        { to: "/tickets/workflows", label: "Workflows", hint: "States and transitions of each type" },
        { to: "/activities", label: "Activities", hint: "Planned and recurring work" },
      ]} />}
      explorerLabel="Type"
      explorerSummary={schema?.name}
      explorer={<TypeExplorer appliesTo="tickets" counts={counts} total={issues.data?.length ?? 0} selected={f.type}
                              onSelect={(uid) => { f.set({ type: uid }); setFieldFilters({}); }} />}
      toolbar={
        <>
          <SearchBox value={f.q} onChange={(v) => f.set({ q: v })} label="Search tickets" placeholder="Search by title…" />
          <ToolbarSelect label="State" value={f.state} onChange={(v) => f.set({ state: v === "open" ? null : v })}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="all">Any state</option>
            {statusOptions.length > 0 && (
              <optgroup label="Exactly">
                {statusOptions.map((o) => <option key={o.id} value={o.id}>{o.value}</option>)}
              </optgroup>
            )}
          </ToolbarSelect>
          <ToolbarSelect label="Assignee" value={f.assignee} onChange={(v) => f.set({ assignee: v })}>
            <option value="">Anyone</option>
            <option value="none">Unassigned</option>
            {(members.data ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>)}
          </ToolbarSelect>
          <ColumnSettings columns={columns} />
          <ViewSwitch views={[
            { label: "List", to: "/tickets", current: true },
            { label: "Board", to: "/tickets/board", current: false },
          ]} />
        </>
      }
    >
      {schema && attrDefs.length > 0 && (
        <div>
          <button type="button" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((v) => !v)} className="text-sm text-slate-600 hover:text-slate-900">
            <span aria-hidden>{advancedOpen ? "▾" : "▸"}</span> Filter by {schema.name} fields
            {activeFilterCount(fieldFilters) > 0 && (
              <span className="ml-1 rounded-full bg-slate-900 px-1.5 py-0.5 text-[10px] text-white">{activeFilterCount(fieldFilters)}</span>
            )}
          </button>
          {advancedOpen && (
            <div className="mt-2 grid gap-2 rounded-md border border-slate-200 bg-white p-3 md:grid-cols-2">
              {attrDefs.map((attr) => {
                const key = attr.key ?? attr.name;
                return (
                  <div key={key} className="flex min-w-0 items-center gap-2">
                    <span className="w-32 shrink-0 truncate text-xs font-medium text-slate-600" title={attr.name}>{attr.name}</span>
                    <AttributeFilterInput attribute={attr} value={fieldFilters[key] ?? defaultFilterFor(attr)}
                                          onChange={(v) => setFieldFilters((p) => ({ ...p, [key]: v }))} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <BulkActionsBar
        selected={selection.selected}
        kind="issue_uids"
        label="tickets"
        canTransfer={rights.can_create_tickets}
        bulkDelete={rights.can_delete_tickets ? issuesApi.bulkDelete : undefined}
        onStarted={() => { queryClient.invalidateQueries({ queryKey: ["issues"] }); selection.clear(); }}
        onClear={selection.clear}
      />

      {issues.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {issues.isError && <p className="text-sm text-rose-700">The tickets could not be loaded.</p>}
      {issues.data && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full table-fixed text-sm">
            <caption className="sr-only">Tickets, sorted by {sort.key}</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="w-10 px-3 py-2"><SelectAll rows={paging.rows.map((i) => i.uid)} selection={selection} noun="tickets" /></th>
                <SortHeader label="Title" column="title" sort={sort} onSort={sortBy} className="px-3 py-2" />
                {columns.show("state") && <SortHeader label="State" column="state" sort={sort} onSort={sortBy} className="hidden w-32 px-3 py-2 sm:table-cell" />}
                {columns.show("priority") && <SortHeader label="Priority" column="priority" sort={sort} onSort={sortBy} className="hidden w-24 px-3 py-2 md:table-cell" />}
                {columns.show("assignee") && <SortHeader label="Assignee" column="assignee" sort={sort} onSort={sortBy} className="hidden w-32 px-3 py-2 lg:table-cell" />}
                {columns.show("type") && <SortHeader label="Type" column="type" sort={sort} onSort={sortBy} className="hidden w-36 px-3 py-2 lg:table-cell" />}
                {columns.show("updated") && <SortHeader label="Updated" column="updated" sort={sort} onSort={sortBy} time className="hidden w-24 px-3 py-2 md:table-cell" />}
                {columns.show("created") && <SortHeader label="Created" column="created" sort={sort} onSort={sortBy} time className="hidden w-28 px-3 py-2 xl:table-cell" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {paging.rows.map((i) => {
                const who = i.assignee ? people.get(i.assignee) ?? i.assignee : null;
                const stateLabel = label(statusOptions, i.state);
                const prioLabel = label(priorityOptions, i.priority);
                return (
                  <tr key={i.uid} className={selection.selected.has(i.uid) ? "bg-sky-50" : "hover:bg-slate-50"}>
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={selection.selected.has(i.uid)} onChange={() => selection.toggle(i.uid)}
                             aria-label={`Select ${i.title}`} />
                    </td>
                    <td className="px-3 py-2">
                      <Link to={`/tickets/${i.uid}`} className="block truncate font-medium text-slate-900 hover:underline" title={i.title}>{i.title}</Link>
                      <span className="mt-0.5 flex flex-wrap items-center gap-2 sm:hidden">
                        <StateBadge state={i.state} label={stateLabel} />
                        <PriorityBadge priority={i.priority} label={prioLabel} />
                      </span>
                    </td>
                    {columns.show("state") && <td className="hidden px-3 py-2 sm:table-cell"><StateBadge state={i.state} label={stateLabel} /></td>}
                    {columns.show("priority") && <td className="hidden px-3 py-2 md:table-cell"><PriorityBadge priority={i.priority} label={prioLabel} /></td>}
                    {columns.show("assignee") && (
                      <td className="hidden px-3 py-2 text-slate-600 lg:table-cell">{who ? <Clip>{who}</Clip> : <span className="text-slate-400">Unassigned</span>}</td>
                    )}
                    {columns.show("type") && <td className="hidden px-3 py-2 text-slate-600 lg:table-cell"><Clip>{(i.schema_uid && typeName.get(i.schema_uid)) || "—"}</Clip></td>}
                    {columns.show("updated") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 md:table-cell"><ListDate value={i.updated_at} /></td>}
                    {columns.show("created") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 xl:table-cell"><ListDate value={i.created_at} /></td>}
                  </tr>
                );
              })}
              {paging.rows.length === 0 && (
                <tr><td colSpan={1 + columns.count} className="px-4 py-8 text-center text-slate-400">No tickets match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {issues.data && <Pager paging={paging} noun="tickets" />}
    </BrowsePage>
  );
}
