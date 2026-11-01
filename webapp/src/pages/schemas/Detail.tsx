import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Asset, AppDocument, Issue, MemberDirectoryEntry } from "../../api/types";
import { assetsApi, documentsApi, globalValuesApi, iconsApi, issuesApi, membersApi, schemasApi } from "../../api/client";
import { AuthenticatedImage } from "../../components/AuthenticatedImage";
import { IconPicker } from "../../components/IconPicker";
import { ImageSlot } from "../../components/ImageSlot";
import {
  ColumnDef,
  ColumnPickerButton,
  formatCellValue,
  formatDate,
  SortableTh,
  useConfigurableColumns,
} from "../../components/ConfigurableTable";
import { TransferItemAction } from "../../components/TransferItemAction";
import { originText } from "../../components/browse/TypeExplorer";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { useWorkspaceNames } from "../../api/useWorkspaceNames";
import { effectiveAttributes, inheritedKeys } from "../../lib/schemaAttributes";

function resolveUserLabel(members: MemberDirectoryEntry[] | undefined, value: unknown): string {
  if (value == null || value === "") return "—";
  const m = members?.find((x) => x.user_id === value);
  return m?.name || m?.email || String(value);
}

const ISSUE_STATE_STYLES: Record<string, string> = {
  new: "bg-slate-100 text-slate-600",
  in_progress: "bg-blue-100 text-blue-700",
  pending: "bg-amber-100 text-amber-700",
  resolved: "bg-green-100 text-green-700",
  closed: "bg-slate-200 text-slate-500",
};

export function SchemaDetail() {
  const { uid } = useParams<{ uid: string }>();
  const currentWs = useCurrentWorkspaceId();
  const nameOf = useWorkspaceNames();
  const [tab, setTab] = useState<"items" | "attributes">("items");
  const [search, setSearch] = useState("");
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { data: schema, isLoading } = useQuery({
    queryKey: ["schemas", uid],
    queryFn: () => schemasApi.get(uid!),
    enabled: !!uid,
  });
  const isTicketType = schema?.applies_to === "tickets";
  const isDocumentType = schema?.applies_to === "documents";
  const allSchemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const assets = useQuery({
    queryKey: ["assets", uid],
    queryFn: () => assetsApi.list(uid),
    enabled: !!uid && tab === "items" && !isTicketType && !isDocumentType,
  });
  const issues = useQuery({
    queryKey: ["issues", uid],
    queryFn: () => issuesApi.list(uid),
    enabled: !!uid && tab === "items" && isTicketType,
  });
  const documents = useQuery({
    queryKey: ["documents", uid],
    queryFn: () => documentsApi.list(uid),
    enabled: !!uid && tab === "items" && isDocumentType,
  });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory });
  const ticketGlobalValues = useQuery({
    queryKey: ["global-values"],
    queryFn: globalValuesApi.list,
    enabled: isTicketType,
  });
  const priorityOptions =
    ticketGlobalValues.data?.find((gv) => gv.applies_to === "tickets" && gv.key === "priority")?.options ?? [];

  const deleteMutation = useMutation({
    mutationFn: assetsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assets"] }),
    onError: () => alert("Delete failed."),
  });

  // The icon shows up in the type tree and next to every object of the type,
  // so both queries have to be refreshed, not just this page's.
  const invalidateIcon = () => {
    queryClient.invalidateQueries({ queryKey: ["schemas"] });
    queryClient.invalidateQueries({ queryKey: ["schemas", uid] });
  };
  const uploadIconMutation = useMutation({
    mutationFn: (file: File) => schemasApi.uploadIcon(uid!, file),
    onSuccess: invalidateIcon,
  });
  const setIconMutation = useMutation({
    mutationFn: (iconUid: string) => schemasApi.setIconFromLibrary(uid!, iconUid),
    onSuccess: invalidateIcon,
  });
  const clearIconMutation = useMutation({
    mutationFn: () => schemasApi.clearIcon(uid!),
    onSuccess: invalidateIcon,
  });

  const deleteSchemaMutation = useMutation({
    mutationFn: () => schemasApi.delete(uid!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["issues"] });
      navigate("/");
    },
    onError: () => alert("Delete failed."),
  });

  const filteredAssets = useMemo(() => {
    if (!assets.data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return assets.data;
    return assets.data.filter(
      (a) => a.name.toLowerCase().includes(q) || a.key.toLowerCase().includes(q),
    );
  }, [assets.data, search]);

  const filteredIssues = useMemo(() => {
    if (!issues.data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return issues.data;
    return issues.data.filter((i) => i.title.toLowerCase().includes(q));
  }, [issues.data, search]);

  const filteredDocuments = useMemo(() => {
    if (!documents.data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return documents.data;
    return documents.data.filter(
      (d) => d.title.toLowerCase().includes(q) || d.code.toLowerCase().includes(q),
    );
  }, [documents.data, search]);

  const attrDefsForColumns = useMemo(
    () => effectiveAttributes(schema, allSchemas.data),
    [schema, allSchemas.data],
  );

  const assetColumns = useMemo<ColumnDef<Asset>[]>(() => {
    const attrCols: ColumnDef<Asset>[] = attrDefsForColumns.map((attr) => {
      const attrKey = attr.key ?? attr.name;
      const isUserAttr = attr.type === "user" || attr.type === "current_user";
      return {
        key: `attr:${attrKey}`,
        label: attr.name,
        defaultVisible: false,
        render: (a) =>
          isUserAttr
            ? resolveUserLabel(members.data, a.attributes[attrKey])
            : formatCellValue(a.attributes[attrKey]),
        sortValue: (a) => {
          const v = a.attributes[attrKey];
          return typeof v === "number" ? v : v == null ? null : String(v);
        },
      };
    });
    return [
      {
        key: "name",
        label: "Name",
        alwaysOn: true,
        render: (a) => (
          <Link to={`/assets/${a.uid}`} className="font-medium text-slate-900 hover:underline">
            {a.name}
          </Link>
        ),
        sortValue: (a) => a.name.toLowerCase(),
      },
      { key: "key", label: "Key", render: (a) => a.key, sortValue: (a) => a.key.toLowerCase() },
      { key: "type", label: "Type", defaultVisible: false, render: (a) => a.type, sortValue: (a) => a.type },
      ...attrCols,
      {
        key: "created_at",
        label: "Created",
        defaultVisible: false,
        render: (a) => formatDate(a.created_at),
        sortValue: (a) => a.created_at,
      },
      {
        key: "updated_at",
        label: "Updated",
        defaultVisible: false,
        render: (a) => formatDate(a.updated_at),
        sortValue: (a) => a.updated_at,
      },
      {
        key: "actions",
        label: "",
        alwaysOn: true,
        align: "right",
        render: (a) => (
          <>
            <Link to={`/assets/${a.uid}/edit`} className="mr-3 text-slate-500 hover:text-slate-900">
              Edit
            </Link>
            <button
              onClick={() => {
                if (confirm(`Delete asset "${a.name}"?`)) deleteMutation.mutate(a.uid);
              }}
              className="text-red-500 hover:text-red-700"
            >
              Delete
            </button>
          </>
        ),
      },
    ];
  }, [attrDefsForColumns, deleteMutation, members.data]);

  const issueColumns = useMemo<ColumnDef<Issue>[]>(() => {
    const attrCols: ColumnDef<Issue>[] = attrDefsForColumns.map((attr) => {
      const attrKey = attr.key ?? attr.name;
      const isUserAttr = attr.type === "user" || attr.type === "current_user";
      return {
        key: `attr:${attrKey}`,
        label: attr.name,
        defaultVisible: false,
        render: (i) =>
          isUserAttr
            ? resolveUserLabel(members.data, i.attributes[attrKey])
            : formatCellValue(i.attributes[attrKey]),
        sortValue: (i) => {
          const v = i.attributes[attrKey];
          return typeof v === "number" ? v : v == null ? null : String(v);
        },
      };
    });
    return [
      {
        key: "title",
        label: "Title",
        alwaysOn: true,
        render: (i) => (
          <Link to={`/tickets/${i.uid}`} className="font-medium text-slate-900 hover:underline">
            {i.title}
          </Link>
        ),
        sortValue: (i) => i.title.toLowerCase(),
      },
      {
        key: "state",
        label: "State",
        render: (i) => (
          <span
            className={`rounded px-2 py-0.5 text-xs ${ISSUE_STATE_STYLES[i.state] ?? "bg-slate-100 text-slate-600"}`}
          >
            {i.state}
          </span>
        ),
        sortValue: (i) => i.state,
      },
      {
        key: "priority",
        label: "Priority",
        render: (i) => priorityOptions.find((o) => o.id === i.priority)?.value ?? i.priority ?? "—",
        sortValue: (i) => i.priority,
      },
      {
        key: "assignee",
        label: "Assignee",
        defaultVisible: false,
        render: (i) => resolveUserLabel(members.data, i.assignee),
        sortValue: (i) => i.assignee,
      },
      {
        key: "due_date",
        label: "Due date",
        defaultVisible: false,
        render: (i) => formatDate(i.due_date),
        sortValue: (i) => i.due_date,
      },
      ...attrCols,
      {
        key: "created_at",
        label: "Created",
        defaultVisible: false,
        render: (i) => formatDate(i.created_at),
        sortValue: (i) => i.created_at,
      },
      {
        key: "updated_at",
        label: "Updated",
        defaultVisible: false,
        render: (i) => formatDate(i.updated_at),
        sortValue: (i) => i.updated_at,
      },
    ];
  }, [attrDefsForColumns, priorityOptions, members.data]);

  const documentColumns = useMemo<ColumnDef<AppDocument>[]>(
    () => [
      {
        key: "code",
        label: "Code",
        alwaysOn: true,
        render: (d) => (
          <Link to={`/documents/${d.uid}`} className="font-mono text-xs text-slate-500 hover:underline">
            {d.code}
          </Link>
        ),
        sortValue: (d) => d.code.toLowerCase(),
      },
      {
        key: "title",
        label: "Title",
        render: (d) => (
          <Link to={`/documents/${d.uid}`} className="font-medium text-slate-900 hover:underline">
            {d.title}
          </Link>
        ),
        sortValue: (d) => d.title.toLowerCase(),
      },
      {
        key: "status",
        label: "Status",
        render: (d) => (d.current_revision_uid ? "published" : "unpublished"),
        sortValue: (d) => (d.current_revision_uid ? "published" : "unpublished"),
      },
      {
        key: "confidentiality",
        label: "Confidentiality",
        defaultVisible: false,
        render: (d) => d.confidentiality,
        sortValue: (d) => d.confidentiality,
      },
      {
        key: "authority_level",
        label: "Authority",
        defaultVisible: false,
        render: (d) => d.authority_level,
        sortValue: (d) => d.authority_level,
      },
      {
        key: "created_at",
        label: "Created",
        defaultVisible: false,
        render: (d) => formatDate(d.created_at),
        sortValue: (d) => d.created_at,
      },
      {
        key: "updated_at",
        label: "Updated",
        defaultVisible: false,
        render: (d) => formatDate(d.updated_at),
        sortValue: (d) => d.updated_at,
      },
    ],
    [],
  );

  const assetTable = useConfigurableColumns(`argus.columns.objects.${uid}`, assetColumns);
  const issueTable = useConfigurableColumns(`argus.columns.tickets.${uid}`, issueColumns);
  const documentTable = useConfigurableColumns(`argus.columns.documents.${uid}`, documentColumns);

  const sortedAssets = useMemo(() => assetTable.sortRows(filteredAssets), [assetTable, filteredAssets]);
  const sortedIssues = useMemo(() => issueTable.sortRows(filteredIssues), [issueTable, filteredIssues]);
  const sortedDocuments = useMemo(
    () => documentTable.sortRows(filteredDocuments),
    [documentTable, filteredDocuments],
  );

  if (isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!schema) return <p className="text-sm text-red-600">Schema not found.</p>;

  const parent = allSchemas.data?.find((s) => s.uid === schema.parent_schema_uid);
  const children = allSchemas.data?.filter((s) => s.parent_schema_uid === schema.uid) ?? [];
  const attrDefs = effectiveAttributes(schema, allSchemas.data);
  const inherited = inheritedKeys(schema, attrDefs);

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ImageSlot
            attachmentUid={schema.icon_uid}
            fallbackText={schema.name}
            alt={`${schema.name} icon`}
            size={40}
            busy={uploadIconMutation.isPending}
            onPick={(file) => uploadIconMutation.mutate(file)}
            onClear={() => clearIconMutation.mutate()}
            fetchBlobUrl={iconsApi.fetchBlobUrl}
            extra={
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setIconPickerOpen((v) => !v)}
                  className="text-xs text-indigo-600 hover:text-indigo-800"
                >
                  Choose from library
                </button>
                {iconPickerOpen && (
                  <div className="absolute left-0 z-20 mt-1 w-64">
                    <IconPicker
                      onPick={(iconUid) => {
                        setIconMutation.mutate(iconUid);
                        setIconPickerOpen(false);
                      }}
                    />
                  </div>
                )}
              </div>
            }
          />
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
              {schema.name}
              {schema.is_global && (
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-700">
                  Global
                </span>
              )}
            </h1>
            <p className="text-sm text-slate-500">{schema.description ?? "No description"}</p>
            <p className="text-xs text-slate-400">Origin: {originText(schema, currentWs, nameOf)}</p>
          </div>
        </div>
        <div className="space-x-2">
          <Link
            to={`/schemas/${schema.uid}/edit`}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Edit
          </Link>
          <TransferItemAction kind="type" uid={schema.uid} hasChildren={children.length > 0} />
          <button
            onClick={() => {
              const noun = isTicketType ? "ticket" : isDocumentType ? "document" : "object";
              const warning = children.length > 0
                ? `Delete "${schema.name}"? This also permanently deletes its ${children.length} child type(s) and every ${noun} of this type or any child type — including ones in other workspaces if it's global. This cannot be undone.`
                : `Delete "${schema.name}"? This also permanently deletes every ${noun} of this type — including ones in other workspaces if it's global. This cannot be undone.`;
              if (confirm(warning)) deleteSchemaMutation.mutate();
            }}
            disabled={deleteSchemaMutation.isPending}
            className="rounded border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>

      {children.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Child types
          </span>
          {children.map((c) => (
            <Link
              key={c.uid}
              to={`/schemas/${c.uid}`}
              className="rounded border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 hover:border-slate-300"
            >
              {c.name}
            </Link>
          ))}
        </div>
      )}
      {parent && (
        <p className="mt-2 text-sm text-slate-500">
          Part of{" "}
          <Link to={`/schemas/${parent.uid}`} className="text-indigo-600 hover:underline">
            {parent.name}
          </Link>
        </p>
      )}

      <div className="mt-6 flex gap-2">
        {(["items", "attributes"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded px-4 py-2 text-sm font-medium capitalize ${
              tab === t ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {t === "items"
              ? isTicketType
                ? "Tickets"
                : isDocumentType
                  ? "Documents"
                  : "Objects"
              : t}
          </button>
        ))}
      </div>

      {tab === "items" ? (
        isDocumentType ? (
          <div className="mt-4">
            <div className="flex items-center justify-between gap-3">
              <input
                placeholder="Search by title or code…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-64 rounded border border-slate-300 px-3 py-1.5 text-sm"
              />
              <div className="flex items-center gap-2">
                <ColumnPickerButton
                  columns={documentColumns}
                  visibleKeys={documentTable.visibleKeys}
                  onToggle={documentTable.toggleColumn}
                />
                <Link
                  to={`/documents/new?document_type_uid=${schema.uid}`}
                  className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
                >
                  New document
                </Link>
              </div>
            </div>

            {documents.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

            {documents.data && (
              <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      {documentTable.orderedColumns.map((col) => (
                        <SortableTh
                          key={col.key}
                          column={col}
                          sort={documentTable.sort}
                          onToggleSort={documentTable.toggleSort}
                        />
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {sortedDocuments.map((d) => (
                      <tr key={d.uid} className="hover:bg-slate-50">
                        {documentTable.orderedColumns.map((col) => (
                          <td key={col.key} className="px-4 py-2 text-slate-500">
                            {col.render(d)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {sortedDocuments.length === 0 && (
                      <tr>
                        <td colSpan={documentTable.orderedColumns.length} className="px-4 py-6 text-center text-slate-400">
                          No documents found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
            {documents.data && (
              <p className="mt-2 text-xs text-slate-400">
                Showing {sortedDocuments.length} of {documents.data.length}
              </p>
            )}
          </div>
        ) : isTicketType ? (
          <div className="mt-4">
            <div className="flex items-center justify-between gap-3">
              <input
                placeholder="Search by title…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-64 rounded border border-slate-300 px-3 py-1.5 text-sm"
              />
              <div className="flex items-center gap-2">
                <ColumnPickerButton
                  columns={issueColumns}
                  visibleKeys={issueTable.visibleKeys}
                  onToggle={issueTable.toggleColumn}
                />
                <Link
                  to={`/tickets/new?schema_uid=${schema.uid}`}
                  className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
                >
                  New ticket
                </Link>
              </div>
            </div>

            {issues.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

            {issues.data && (
              <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      {issueTable.orderedColumns.map((col) => (
                        <SortableTh
                          key={col.key}
                          column={col}
                          sort={issueTable.sort}
                          onToggleSort={issueTable.toggleSort}
                        />
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {sortedIssues.map((i) => (
                      <tr key={i.uid} className="hover:bg-slate-50">
                        {issueTable.orderedColumns.map((col) => (
                          <td key={col.key} className="px-4 py-2 text-slate-500">
                            {col.render(i)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {sortedIssues.length === 0 && (
                      <tr>
                        <td colSpan={issueTable.orderedColumns.length} className="px-4 py-6 text-center text-slate-400">
                          No tickets found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
            {issues.data && (
              <p className="mt-2 text-xs text-slate-400">
                Showing {sortedIssues.length} of {issues.data.length}
              </p>
            )}
          </div>
        ) : (
          <div className="mt-4">
            <div className="flex items-center justify-between gap-3">
              <input
                placeholder="Search by name or key…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-64 rounded border border-slate-300 px-3 py-1.5 text-sm"
              />
              <div className="flex items-center gap-2">
                <ColumnPickerButton
                  columns={assetColumns}
                  visibleKeys={assetTable.visibleKeys}
                  onToggle={assetTable.toggleColumn}
                />
                <Link
                  to={`/assets/new?schema_uid=${schema.uid}`}
                  className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
                >
                  New object
                </Link>
              </div>
            </div>

            {assets.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

            {assets.data && (
              <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      {assetTable.orderedColumns.map((col) => (
                        <SortableTh
                          key={col.key}
                          column={col}
                          sort={assetTable.sort}
                          onToggleSort={assetTable.toggleSort}
                          className={col.align === "right" ? "text-right" : undefined}
                        />
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {sortedAssets.map((a) => (
                      <tr key={a.uid} className="hover:bg-slate-50">
                        {assetTable.orderedColumns.map((col) => (
                          <td
                            key={col.key}
                            className={`px-4 py-2 text-slate-500 ${col.align === "right" ? "text-right whitespace-nowrap" : ""}`}
                          >
                            {col.render(a)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {sortedAssets.length === 0 && (
                      <tr>
                        <td colSpan={assetTable.orderedColumns.length} className="px-4 py-6 text-center text-slate-400">
                          No objects found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
            {assets.data && (
              <p className="mt-2 text-xs text-slate-400">
                Showing {sortedAssets.length} of {assets.data.length}
              </p>
            )}
          </div>
        )
      ) : (
        <div className="mt-4">
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="rounded border border-slate-200 bg-white p-4">
              <p className="text-slate-500">Concrete</p>
              <p className="font-medium">{schema.is_concrete ? "Yes" : "No"}</p>
            </div>
            <div className="rounded border border-slate-200 bg-white p-4">
              <p className="text-slate-500">Version</p>
              <p className="font-medium">{schema.version}</p>
            </div>
            <div className="rounded border border-slate-200 bg-white p-4">
              <p className="text-slate-500">Attributes</p>
              <p className="font-medium">
                {attrDefs.length}
                {inherited.size > 0 && (
                  <span className="ml-1 text-xs font-normal text-slate-400">
                    ({attrDefs.length - inherited.size} own + {inherited.size} inherited)
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">Key</th>
                  <th className="px-4 py-2">Type</th>
                  <th className="px-4 py-2">Required</th>
                  <th className="px-4 py-2">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {attrDefs.map((a, i) => (
                  <tr key={a.id ?? i}>
                    <td className="px-4 py-2 font-medium text-slate-900">{a.name}</td>
                    <td className="px-4 py-2 text-slate-500">{a.key ?? a.name}</td>
                    <td className="px-4 py-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs ${
                          a.type === "reference"
                            ? "bg-indigo-50 text-indigo-700"
                            : a.global
                              ? "bg-amber-50 text-amber-700"
                              : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {a.type}
                        {a.type === "reference" && a.referenceType ? ` → ${a.referenceType}` : ""}
                        {a.global ? " (global)" : ""}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-slate-500">{a.required ? "Yes" : "No"}</td>
                    <td className="px-4 py-2 text-slate-500">
                      {inherited.has(a.key ?? a.name) ? (
                        <span className="text-xs text-slate-400">inherited</span>
                      ) : (
                        <span className="text-xs text-slate-600">own</span>
                      )}
                    </td>
                  </tr>
                ))}
                {attrDefs.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                      No attributes defined.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
