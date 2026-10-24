import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { assetsApi, schemasApi } from "../../api/client";
import { useShowKeys } from "../../api/displayPrefs";
import { has, useCapabilities } from "../../api/useCapabilities";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { AttributeFilterInput } from "../../components/AttributeFilterInput";
import { activeFilterCount, defaultFilterFor, FilterState, matchesFilters } from "../../components/AttributeFilters";
import {
  BrowsePage, Clip, ColumnSettings, MenuButton, Pager, SearchBox, SelectAll, ToolbarSelect, ViewSwitch,
  useBrowseParams, useColumns, usePage, useSelection,
} from "../../components/browse/Browse";
import { countBy, TypeExplorer, typeFamily } from "../../components/browse/TypeExplorer";
import { BulkActionsBar } from "../../components/BulkActionsBar";
import { OwnerBadge } from "../../components/OwnerBadge";
import { ListDate, SortHeader, useSort } from "../../components/SortableTable";
import { effectiveAttributes } from "../../lib/schemaAttributes";
import { useRights } from "../../lib/permissions";

const COLUMNS = [
  { id: "name", label: "Name", required: true },
  { id: "key", label: "Key" },
  { id: "type", label: "Type", initial: true },
  { id: "updated", label: "Updated", initial: true },
  { id: "created", label: "Created" },
];

/** Assets: the type explorer, the search and filters, the list (or the map), and what can be done with a
 * selection. The filters are in the address, so the map view and a reload keep them. */
export function AssetSearch() {
  const showKeys = useShowKeys();
  const queryClient = useQueryClient();
  const features = useCapabilities();
  const rights = useRights();
  const ws = useCurrentWorkspaceId();
  const { get, set } = useBrowseParams();
  const q = get("q");
  const schemaUid = get("type") || null;
  const owner = (get("owner", "own") as "all" | "own" | "shared");
  const [filters, setFilters] = useState<FilterState>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const selection = useSelection("assets");
  const columns = useColumns("assets", COLUMNS.map((c) => (c.id === "key" ? { ...c, initial: showKeys } : c)));

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, staleTime: 60_000 });
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => assetsApi.list() });
  const equipment = has(features, "equipment");
  const noun = equipment ? "objects" : "records";

  const objectSchemas = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "objects"), [schemas.data]);
  const family = useMemo(() => typeFamily(objectSchemas, schemaUid), [objectSchemas, schemaUid]);
  const schema = objectSchemas.find((s) => s.uid === schemaUid);
  const attrDefs = effectiveAttributes(schema, schemas.data);

  // Beyond the key and the name: labels (QR codes, barcodes, former keys, aliases), serial, inventory number.
  const needle = q.trim();
  const byIdentifier = useQuery({
    queryKey: ["asset-match", needle],
    queryFn: () => assetsApi.matching(needle),
    enabled: needle.length >= 2,
    staleTime: 30_000,
  });
  const inScope = useMemo(() => (assets.data ?? []).filter((a) =>
    ws === null || owner === "all" || (owner === "own" ? a.workspace_id === ws : a.workspace_id !== ws)), [assets.data, owner, ws]);
  const counts = useMemo(() => countBy(inScope, (a) => a.schema_uid), [inScope]);
  const matched = useMemo(() => {
    const n = needle.toLowerCase();
    return inScope.filter((a) => {
      if (n && !a.name.toLowerCase().includes(n) && !a.key.toLowerCase().includes(n) && !byIdentifier.data?.has(a.uid)) return false;
      if (family && !family.has(a.schema_uid)) return false;
      if (schema && Object.keys(filters).length > 0 && !matchesFilters(a.attributes, filters)) return false;
      return true;
    });
  }, [inScope, needle, family, schema, filters, byIdentifier.data]);
  const { sorted, sort, toggle: sortBy } = useSort(
    matched,
    { name: (a) => a.name, key: (a) => a.key, type: (a) => a.type, created: (a) => a.created_at, updated: (a) => a.updated_at },
    { key: "name", dir: "asc" },
    "assets",
  );
  const paging = usePage(sorted);

  const tools = [
    { to: "/search/advanced?entity=assets", label: "Advanced query", hint: "Combine conditions on any field" },
    { to: "/assets/import", label: "Import a spreadsheet" },
    ...(equipment ? [{ to: "/labels", label: "Labels & QR codes" }] : []),
    { to: "/bulk-changes", label: "Bulk changes", hint: "Change a field on many records" },
    ...(equipment ? [{ to: "/migration/catalogue", label: "Map imported records" }] : []),
    ...(has(features, "control_system") ? [{ to: "/control-bindings", label: "Channels ↔ hardware" }] : []),
  ];

  return (
    <BrowsePage
      title={equipment ? "Assets" : "Records"}
      count={assets.data ? `${matched.length}${matched.length !== inScope.length ? ` of ${inScope.length}` : ""}` : undefined}
      storageKey="assets"
      primary={rights.can_create && (
        <Link to="/assets/new" className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
          New {equipment ? "object" : "record"}
        </Link>
      )}
      actions={<MenuButton label="Tools" items={tools} />}
      explorerLabel="Type"
      explorerSummary={schema?.name}
      explorer={
        <TypeExplorer appliesTo="objects" counts={counts} total={inScope.length} selected={schemaUid}
                      onSelect={(uid) => { set({ type: uid }); setFilters({}); }} allLabel={`All ${noun}`} />
      }
      toolbar={
        <>
          <SearchBox value={q} onChange={(v) => set({ q: v })} label={`Search ${noun}`}
                     placeholder="Name, key, label, serial or inventory number…" />
          {ws !== null && (
            <ToolbarSelect label="Whose records" value={owner} onChange={(v) => set({ owner: v === "own" ? null : v })}>
              <option value="own">This workspace</option>
              <option value="all">This workspace + shared</option>
              <option value="shared">Shared with it</option>
            </ToolbarSelect>
          )}
          <ColumnSettings columns={columns} />
          {has(features, "map") && (
            <ViewSwitch views={[
              { label: "List", to: "/assets/search", current: true },
              { label: "Map", to: `/map${schemaUid ? `?types=${encodeURIComponent(schemaUid)}` : ""}`, current: false },
            ]} />
          )}
        </>
      }
    >
      {schema && attrDefs.length > 0 && (
        <div>
          <button type="button" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((v) => !v)}
                  className="text-sm text-slate-600 hover:text-slate-900">
            <span aria-hidden>{advancedOpen ? "▾" : "▸"}</span> Filter by {schema.name} fields
            {activeFilterCount(filters) > 0 && (
              <span className="ml-1 rounded-full bg-slate-900 px-1.5 py-0.5 text-[10px] text-white">{activeFilterCount(filters)}</span>
            )}
          </button>
          {advancedOpen && (
            <div className="mt-2 grid gap-2 rounded-md border border-slate-200 bg-white p-3 md:grid-cols-2">
              {attrDefs.map((attr) => {
                const key = attr.key ?? attr.name;
                return (
                  <div key={key} className="flex min-w-0 items-center gap-2">
                    <span className="w-32 shrink-0 truncate text-xs font-medium text-slate-600" title={attr.name}>{attr.name}</span>
                    <AttributeFilterInput attribute={attr} value={filters[key] ?? defaultFilterFor(attr)}
                                          onChange={(v) => setFilters((prev) => ({ ...prev, [key]: v }))} />
                  </div>
                );
              })}
              {activeFilterCount(filters) > 0 && (
                <button type="button" onClick={() => setFilters({})} className="text-left text-xs text-slate-500 hover:text-slate-800">
                  Clear field filters
                </button>
              )}
            </div>
          )}
        </div>
      )}

      <BulkActionsBar
        selected={selection.selected}
        kind="asset_uids"
        label={noun}
        canTransfer={rights.can_create}
        bulkDelete={rights.can_delete ? assetsApi.bulkDelete : undefined}
        onStarted={() => { queryClient.invalidateQueries({ queryKey: ["assets"] }); selection.clear(); }}
        onClear={selection.clear}
      />

      {assets.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {assets.isError && <p className="text-sm text-rose-700">The {noun} could not be loaded.</p>}
      {assets.data && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full table-fixed text-sm">
            <caption className="sr-only">{noun}, sorted by {sort.key}</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="w-10 px-3 py-2"><SelectAll rows={paging.rows.map((a) => a.uid)} selection={selection} noun={noun} /></th>
                <SortHeader label="Name" column="name" sort={sort} onSort={sortBy} className="px-3 py-2" />
                {columns.show("key") && <SortHeader label="Key" column="key" sort={sort} onSort={sortBy} className="hidden w-44 px-3 py-2 lg:table-cell" />}
                {columns.show("type") && <SortHeader label="Type" column="type" sort={sort} onSort={sortBy} className="hidden w-48 px-3 py-2 sm:table-cell" />}
                {columns.show("updated") && <SortHeader label="Updated" column="updated" sort={sort} onSort={sortBy} time className="hidden w-24 px-3 py-2 md:table-cell" />}
                {columns.show("created") && <SortHeader label="Created" column="created" sort={sort} onSort={sortBy} time className="hidden w-28 px-3 py-2 md:table-cell" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {paging.rows.map((a) => (
                <tr key={a.uid} className={selection.selected.has(a.uid) ? "bg-sky-50" : "hover:bg-slate-50"}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selection.selected.has(a.uid)} onChange={() => selection.toggle(a.uid)}
                           aria-label={`Select ${a.name}`} />
                  </td>
                  <td className="min-w-0 px-3 py-2">
                    <Link to={`/assets/${a.uid}`} className="block truncate font-medium text-slate-900 hover:underline" title={a.name}>
                      {a.name}
                    </Link>
                    {/* What the hidden columns would say, on a narrow screen. */}
                    <Clip className="text-xs text-slate-500 sm:hidden" title={`${a.type} · ${a.key}`}>{a.type} · {a.key}</Clip>
                    {showKeys && !columns.show("key") && <Clip className="hidden font-mono text-xs text-slate-400 sm:block">{a.key}</Clip>}
                  </td>
                  {columns.show("key") && <td className="hidden px-3 py-2 font-mono text-xs text-slate-500 lg:table-cell"><Clip>{a.key}</Clip></td>}
                  {columns.show("type") && (
                    <td className="hidden px-3 py-2 text-slate-600 sm:table-cell">
                      <span className="flex min-w-0 items-center gap-1"><Clip>{a.type}</Clip><OwnerBadge workspaceId={a.workspace_id} /></span>
                    </td>
                  )}
                  {columns.show("updated") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 md:table-cell"><ListDate value={a.updated_at} /></td>}
                  {columns.show("created") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 md:table-cell"><ListDate value={a.created_at} /></td>}
                </tr>
              ))}
              {paging.rows.length === 0 && (
                <tr><td colSpan={1 + columns.count} className="px-4 py-8 text-center text-slate-400">No {noun} match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {assets.data && <Pager paging={paging} noun={noun} />}
    </BrowsePage>
  );
}
