import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { documentsApi, schemasApi } from "../../api/client";
import { useShowKeys } from "../../api/displayPrefs";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { useWorkspaceNames } from "../../api/useWorkspaceNames";
import { AttributeFilterInput } from "../../components/AttributeFilterInput";
import { activeFilterCount, defaultFilterFor, FilterState, matchesFilters } from "../../components/AttributeFilters";
import {
  BrowsePage, Clip, ColumnSettings, MenuButton, Pager, SearchBox, SelectAll, ToolbarSelect, useBrowseParams, useColumns,
  usePage, useSelection,
} from "../../components/browse/Browse";
import { countBy, TypeExplorer, typeFamily } from "../../components/browse/TypeExplorer";
import { BulkActionsBar } from "../../components/BulkActionsBar";
import { ListDate, SortHeader, useSort } from "../../components/SortableTable";
import { effectiveAttributes } from "../../lib/schemaAttributes";
import { useRights } from "../../lib/permissions";

const AUTHORITY_STYLES: Record<string, string> = {
  ufficiale: "bg-indigo-100 text-indigo-800",
  informativo: "bg-slate-100 text-slate-700",
  bozza_interna: "bg-amber-100 text-amber-900",
};

const COLUMNS = [
  { id: "title", label: "Title", required: true },
  { id: "code", label: "Code" },
  { id: "type", label: "Type", initial: true },
  { id: "status", label: "Status", initial: true },
  { id: "authority", label: "Authority" },
  { id: "confidentiality", label: "Confidentiality" },
  { id: "updated", label: "Updated", initial: true },
  { id: "created", label: "Created" },
];

export function DocumentList() {
  const showKeys = useShowKeys();
  const queryClient = useQueryClient();
  const rights = useRights();
  const workspaceId = useCurrentWorkspaceId();
  const workspaceName = useWorkspaceNames();
  const { get, set } = useBrowseParams();
  const q = get("q");
  const typeUid = get("type") || null;
  const status = get("status");
  const [fieldFilters, setFieldFilters] = useState<FilterState>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [target, setTarget] = useState("");
  const selection = useSelection("documents");
  const columns = useColumns("documents", COLUMNS.map((c) => (c.id === "code" ? { ...c, initial: showKeys } : c)));

  const documents = useQuery({ queryKey: ["documents"], queryFn: () => documentsApi.list() });
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, staleTime: 60_000 });
  const documentSchemas = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "documents"), [schemas.data]);
  const typeName = useMemo(() => new Map(documentSchemas.map((s) => [s.uid, s.name])), [documentSchemas]);
  const family = useMemo(() => typeFamily(documentSchemas, typeUid), [documentSchemas, typeUid]);
  const schema = documentSchemas.find((s) => s.uid === typeUid);
  const attrDefs = effectiveAttributes(schema, schemas.data);
  const counts = useMemo(() => countBy(documents.data, (d) => d.document_type_uid), [documents.data]);

  const typeMatches = useMemo(() => (documents.data ?? []).filter((d) =>
    (!family || (d.document_type_uid && family.has(d.document_type_uid))) &&
    (!status || (status === "published" ? !!d.current_revision_uid : !d.current_revision_uid))), [documents.data, family, status]);
  // A document's fields live on its current revision: fetched only once a type is chosen and a field filter set.
  const filtering = !!schema && activeFilterCount(fieldFilters) > 0;
  const revisions = useQueries({
    queries: filtering
      ? typeMatches.map((d) => ({ queryKey: ["document-current", d.uid], queryFn: () => documentsApi.current(d.uid),
                                  enabled: !!d.current_revision_uid, retry: false as const, staleTime: 60_000 }))
      : [],
  });
  const matched = useMemo(() => {
    const n = q.trim().toLowerCase();
    const text = typeMatches.filter((d) => !n || d.title.toLowerCase().includes(n) || d.code.toLowerCase().includes(n));
    if (!filtering) return text;
    const attrs = new Map(typeMatches.map((d, i) => [d.uid, revisions[i]?.data?.attributes ?? null]));
    return text.filter((d) => { const a = attrs.get(d.uid); return a != null && matchesFilters(a, fieldFilters); });
  }, [typeMatches, q, filtering, fieldFilters, revisions]);
  const revisionsLoading = filtering && revisions.some((r) => r.isLoading);

  const retype = useMutation({
    mutationFn: () => documentsApi.retype([...selection.selected], target || null),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      selection.clear();
      if (result!.not_found.length) alert(`Moved ${result!.moved}. ${result!.not_found.length} could not be found.`);
    },
    onError: () => alert("Could not move those documents."),
  });

  const { sorted, sort, toggle: sortBy } = useSort(
    matched,
    {
      code: (d) => d.code,
      title: (d) => d.title,
      type: (d) => (d.document_type_uid ? typeName.get(d.document_type_uid) : null),
      authority: (d) => d.authority_level,
      confidentiality: (d) => d.confidentiality,
      status: (d) => (d.current_revision_uid ? "published" : "unpublished"),
      created: (d) => d.created_at,
      updated: (d) => d.updated_at,
    },
    { key: "updated", dir: "desc" },
    "documents",
  );
  const paging = usePage(sorted);

  return (
    <BrowsePage
      title="Documents"
      count={documents.data ? `${matched.length}${matched.length !== documents.data.length ? ` of ${documents.data.length}` : ""}` : undefined}
      storageKey="documents"
      primary={rights.can_create_documents && (
        <Link to="/documents/new" className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">New document</Link>
      )}
      actions={
        <>
          {rights.can_create_documents && (
            <Link to="/documents/reshape" title="Notes, an e-mail or a transcript, rewritten as a draft that follows the type's template"
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:bg-slate-50">
              Rework from raw text
            </Link>
          )}
          <Link to="/documents/templates" className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:bg-slate-50">
            Templates
          </Link>
          <MenuButton label="Tools" items={[
            { to: "/search/advanced?entity=documents", label: "Advanced query", hint: "Combine conditions on any field" },
            { to: "/documents/suggestions", label: "Type suggestions", hint: "Documents whose type looks wrong" },
          ]} />
        </>
      }
      explorerLabel="Type"
      explorerSummary={schema?.name}
      explorer={<TypeExplorer appliesTo="documents" counts={counts} total={documents.data?.length ?? 0} selected={typeUid}
                              onSelect={(uid) => { set({ type: uid }); setFieldFilters({}); }} />}
      toolbar={
        <>
          <SearchBox value={q} onChange={(v) => set({ q: v })} label="Search documents" placeholder="Search by title or code…" />
          <ToolbarSelect label="Status" value={status} onChange={(v) => set({ status: v })}>
            <option value="">Any status</option>
            <option value="published">Published</option>
            <option value="unpublished">Not published</option>
          </ToolbarSelect>
          <ColumnSettings columns={columns} />
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
              {revisionsLoading && <p className="text-xs text-slate-500">Reading the documents' fields…</p>}
            </div>
          )}
        </div>
      )}

      <BulkActionsBar
        selected={selection.selected}
        kind="document_uids"
        label="documents"
        canTransfer={rights.can_create_documents}
        bulkDelete={rights.can_delete_documents ? documentsApi.bulkDelete : undefined}
        onStarted={() => { queryClient.invalidateQueries({ queryKey: ["documents"] }); selection.clear(); }}
        onClear={selection.clear}
        extra={rights.can_modify_documents && (
          <span className="flex flex-wrap items-center gap-2">
            <label htmlFor="retype-target" className="text-slate-600">Change type to</label>
            <select id="retype-target" value={target} onChange={(e) => setTarget(e.target.value)}
                    className="max-w-[12rem] rounded border border-slate-300 bg-white px-2 py-1 text-sm">
              <option value="">No type</option>
              {documentSchemas.map((s) => <option key={s.uid} value={s.uid}>{s.name}</option>)}
            </select>
            <button type="button" onClick={() => retype.mutate()} disabled={retype.isPending}
                    className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-800 disabled:opacity-50">
              {retype.isPending ? "Changing…" : "Change type"}
            </button>
          </span>
        )}
      />

      {documents.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {documents.isError && <p className="text-sm text-rose-700">The documents could not be loaded.</p>}
      {documents.data && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full table-fixed text-sm">
            <caption className="sr-only">Documents, sorted by {sort.key}</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="w-10 px-3 py-2"><SelectAll rows={paging.rows.map((d) => d.uid)} selection={selection} noun="documents" /></th>
                <SortHeader label="Title" column="title" sort={sort} onSort={sortBy} className="px-3 py-2" />
                {columns.show("code") && <SortHeader label="Code" column="code" sort={sort} onSort={sortBy} className="hidden w-36 px-3 py-2 lg:table-cell" />}
                {columns.show("type") && <SortHeader label="Type" column="type" sort={sort} onSort={sortBy} className="hidden w-36 px-3 py-2 sm:table-cell" />}
                {columns.show("status") && <SortHeader label="Status" column="status" sort={sort} onSort={sortBy} className="hidden w-28 px-3 py-2 md:table-cell" />}
                {columns.show("authority") && <SortHeader label="Authority" column="authority" sort={sort} onSort={sortBy} className="hidden w-32 px-3 py-2 lg:table-cell" />}
                {columns.show("confidentiality") && <SortHeader label="Confidentiality" column="confidentiality" sort={sort} onSort={sortBy} className="hidden w-36 px-3 py-2 xl:table-cell" />}
                {columns.show("updated") && <SortHeader label="Updated" column="updated" sort={sort} onSort={sortBy} time className="hidden w-24 px-3 py-2 md:table-cell" />}
                {columns.show("created") && <SortHeader label="Created" column="created" sort={sort} onSort={sortBy} time className="hidden w-28 px-3 py-2 xl:table-cell" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {paging.rows.map((d) => {
                const type = d.document_type_uid ? typeName.get(d.document_type_uid) ?? "—" : "—";
                return (
                  <tr key={d.uid} className={selection.selected.has(d.uid) ? "bg-sky-50" : "hover:bg-slate-50"}>
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={selection.selected.has(d.uid)} onChange={() => selection.toggle(d.uid)}
                             aria-label={`Select ${d.title}`} />
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex min-w-0 items-center gap-2">
                        <Link to={`/documents/${d.uid}`} className="min-w-0 truncate font-medium text-slate-900 hover:underline" title={d.title}>{d.title}</Link>
                        {d.is_global && (
                          <span className="shrink-0 rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800"
                                title={d.workspace_id === workspaceId ? "Readable in every workspace" : `Shared from ${workspaceName(d.workspace_id)}; edited there`}>
                            {d.workspace_id === workspaceId ? "shared" : `from ${workspaceName(d.workspace_id)}`}
                          </span>
                        )}
                      </span>
                      {showKeys && !columns.show("code") && <Clip className="font-mono text-xs text-slate-400">{d.code}</Clip>}
                      <Clip className="text-xs text-slate-500 sm:hidden">{`${type} · ${d.current_revision_uid ? "published" : "not published"}`}</Clip>
                    </td>
                    {columns.show("code") && <td className="hidden px-3 py-2 font-mono text-xs text-slate-500 lg:table-cell"><Clip>{d.code}</Clip></td>}
                    {columns.show("type") && <td className="hidden px-3 py-2 text-slate-600 sm:table-cell"><Clip>{type}</Clip></td>}
                    {columns.show("status") && (
                      <td className="hidden px-3 py-2 md:table-cell">
                        {d.current_revision_uid
                          ? <span className="inline-flex items-center gap-1 rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-800"><span aria-hidden>✓</span>Published</span>
                          : <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700"><span aria-hidden>○</span>Not published</span>}
                      </td>
                    )}
                    {columns.show("authority") && (
                      <td className="hidden px-3 py-2 lg:table-cell">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${AUTHORITY_STYLES[d.authority_level] ?? "bg-slate-100 text-slate-700"}`}>{d.authority_level}</span>
                      </td>
                    )}
                    {columns.show("confidentiality") && <td className="hidden px-3 py-2 text-slate-600 xl:table-cell"><Clip>{d.confidentiality}</Clip></td>}
                    {columns.show("updated") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 md:table-cell"><ListDate value={d.updated_at} /></td>}
                    {columns.show("created") && <td className="hidden whitespace-nowrap px-3 py-2 text-slate-500 xl:table-cell"><ListDate value={d.created_at} /></td>}
                  </tr>
                );
              })}
              {paging.rows.length === 0 && (
                <tr><td colSpan={1 + columns.count} className="px-4 py-8 text-center text-slate-400">No documents match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {documents.data && <Pager paging={paging} noun="documents" />}
    </BrowsePage>
  );
}
