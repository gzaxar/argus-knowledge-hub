import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { assetsApi, documentsApi, iconsApi, issuesApi, schemasApi } from "../api/client";
import { AppSchema } from "../api/types";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import { useWorkspaceNames } from "../api/useWorkspaceNames";
import { AuthenticatedImage } from "./AuthenticatedImage";

export interface TreeNode {
  schema: AppSchema;
  children: TreeNode[];
}

export function buildTree(schemas: AppSchema[]): TreeNode[] {
  const byUid = new Map(schemas.map((s) => [s.uid, { schema: s, children: [] as TreeNode[] }]));
  const roots: TreeNode[] = [];
  for (const s of schemas) {
    const node = byUid.get(s.uid)!;
    if (s.parent_schema_uid && byUid.has(s.parent_schema_uid)) {
      byUid.get(s.parent_schema_uid)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => a.schema.name.localeCompare(b.schema.name));
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

/** Keeps a node if it (or any descendant) matches the query, expanding its full subtree. */
export function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  if (!query) return nodes;
  const q = query.toLowerCase();
  const walk = (node: TreeNode): TreeNode | null => {
    const children = node.children.map(walk).filter((n): n is TreeNode => n !== null);
    if (node.schema.name.toLowerCase().includes(q) || children.length > 0) {
      return { schema: node.schema, children };
    }
    return null;
  };
  return nodes.map(walk).filter((n): n is TreeNode => n !== null);
}

/** Objects of this type and of every type below it. A parent type such as
 * "Asset" has none of its own, so counting only direct instances showed every
 * branch of the tree as empty. */
function subtreeCount(node: TreeNode, counts: Map<string, number>): number {
  return (
    (counts.get(node.schema.uid) ?? 0) +
    node.children.reduce((sum, child) => sum + subtreeCount(child, counts), 0)
  );
}

function TreeNodeRow({
  node,
  depth,
  counts,
  selectedUid,
  onSelect,
  forceExpanded,
}: {
  node: TreeNode;
  depth: number;
  counts: Map<string, number>;
  selectedUid: string | null;
  onSelect: (uid: string) => void;
  forceExpanded?: boolean;
}) {
  const [expandedState, setExpanded] = useState(depth < 1);
  const expanded = forceExpanded || expandedState;
  const hasChildren = node.children.length > 0;
  const direct = counts.get(node.schema.uid) ?? 0;
  const count = subtreeCount(node, counts);
  const isSelected = node.schema.uid === selectedUid;

  return (
    <div>
      <div
        className={`flex cursor-pointer items-center gap-1 rounded px-1.5 py-1 text-xs hover:bg-slate-100 ${
          isSelected ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600"
        }`}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
        onClick={() => onSelect(node.schema.uid)}
      >
        <span
          className="w-3 shrink-0 text-slate-400"
          onClick={(e) => {
            if (hasChildren) {
              e.stopPropagation();
              setExpanded((v) => !v);
            }
          }}
        >
          {hasChildren ? (expanded ? "▾" : "▸") : ""}
        </span>
        {node.schema.icon_uid ? (
          <AuthenticatedImage
            uid={node.schema.icon_uid}
            alt=""
            fetchBlobUrl={iconsApi.fetchBlobUrl}
            className="h-3.5 w-3.5 shrink-0 rounded-sm object-contain"
          />
        ) : (
          <span className="h-3.5 w-3.5 shrink-0 rounded-sm bg-slate-200" />
        )}
        <span className="truncate">{node.schema.name}</span>
        {count > 0 && (
          <span
            className="ml-auto shrink-0 text-slate-400"
            title={
              hasChildren
                ? `${count} in all, ${direct} of this type itself and ${count - direct} of the types below it`
                : undefined
            }
          >
            {count}
          </span>
        )}
      </div>
      {hasChildren && expanded && (
        <div>
          {node.children.map((child) => (
            <TreeNodeRow
              key={child.schema.uid}
              node={child}
              depth={depth + 1}
              counts={counts}
              selectedUid={selectedUid}
              onSelect={onSelect}
              forceExpanded={forceExpanded}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function SchemaTree({
  appliesTo = "objects",
  selectedUid: controlledUid,
  onSelect: controlledSelect,
  fill = false,
}: {
  appliesTo?: "objects" | "tickets" | "documents";
  /** A browse pane: the type picked is reported here and nothing is navigated to. */
  selectedUid?: string | null;
  onSelect?: (uid: string | null) => void;
  /** Fill the height of the pane it is in (a browse layout), rather than the sidebar's share of it. */
  fill?: boolean;
}) {
  const navigate = useNavigate();
  const { uid: routeUid } = useParams<{ uid?: string }>();
  const selectedUid = controlledSelect ? controlledUid ?? null : routeUid ?? null;
  const choose = (uid: string) => {
    if (controlledSelect) controlledSelect(selectedUid === uid ? null : uid);
    else navigate(`/schemas/${uid}`);
  };
  const [query, setQuery] = useState("");
  const currentWorkspaceId = useCurrentWorkspaceId();

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const assets = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.list(),
    enabled: appliesTo === "objects",
  });
  const issues = useQuery({
    queryKey: ["issues"],
    queryFn: () => issuesApi.list(),
    enabled: appliesTo === "tickets",
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => documentsApi.list(),
    enabled: appliesTo === "documents",
  });

  // /v1/schemas also returns every *global* type owned by another workspace,
  // because references have to resolve across workspaces. Mixed into the tree
  // they buried a workspace's own types (24 of its own, listed among 105 once a
  // neighbour shared its catalogue), so the tree shows what this workspace owns
  // and the shared ones sit apart, below, under a "Shared" group per owner. A
  // type whose parent lives elsewhere simply surfaces as a root.
  const scopedSchemas = useMemo(
    () =>
      (schemas.data ?? []).filter(
        (s) =>
          (s.applies_to ?? "objects") === appliesTo &&
          (currentWorkspaceId === null || s.workspace_id === currentWorkspaceId),
      ),
    [schemas.data, appliesTo, currentWorkspaceId],
  );
  const sharedGroups = useMemo(() => {
    if (currentWorkspaceId === null) return [];
    const byOwner = new Map<string, AppSchema[]>();
    for (const s of schemas.data ?? []) {
      if ((s.applies_to ?? "objects") !== appliesTo || s.workspace_id === currentWorkspaceId) continue;
      byOwner.set(s.workspace_id, [...(byOwner.get(s.workspace_id) ?? []), s]);
    }
    return [...byOwner.entries()]
      .map(([owner, list]) => ({ owner, count: list.length, tree: buildTree(list) }))
      .sort((a, b) => a.owner.localeCompare(b.owner));
  }, [schemas.data, appliesTo, currentWorkspaceId]);
  const visibleShared = useMemo(
    () => sharedGroups.map((g) => ({ ...g, tree: filterTree(g.tree, query) })).filter((g) => g.tree.length > 0),
    [sharedGroups, query],
  );
  const nameOf = useWorkspaceNames();
  // Shared types folded away while the workspace has a tree of its own; open when it has next to none, or
  // the tree would show two rows of a workspace whose records are almost all of shared types.
  const [sharedChoice, setSharedOpen] = useState<boolean | null>(null);
  const sharedOpen = sharedChoice ?? scopedSchemas.length < 6;
  const tree = useMemo(() => buildTree(scopedSchemas), [scopedSchemas]);
  const visibleTree = useMemo(() => filterTree(tree, query), [tree, query]);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    if (appliesTo === "tickets") {
      for (const i of issues.data ?? []) {
        if (i.schema_uid) m.set(i.schema_uid, (m.get(i.schema_uid) ?? 0) + 1);
      }
    } else if (appliesTo === "documents") {
      for (const d of documents.data ?? []) {
        if (d.document_type_uid) m.set(d.document_type_uid, (m.get(d.document_type_uid) ?? 0) + 1);
      }
    } else {
      for (const a of assets.data ?? []) {
        m.set(a.schema_uid, (m.get(a.schema_uid) ?? 0) + 1);
      }
    }
    return m;
  }, [appliesTo, assets.data, issues.data, documents.data]);

  if (schemas.isLoading) {
    return <p className="px-2 py-1 text-xs text-slate-400">Loading schemas…</p>;
  }

  return (
    <div className={`flex min-h-0 flex-col ${fill ? "h-full" : "flex-1"}`}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={
          appliesTo === "tickets"
            ? "Search ticket types…"
            : appliesTo === "documents"
              ? "Search document types…"
              : "Search object types…"
        }
        className="mb-2 w-full shrink-0 rounded border border-slate-200 px-2 py-1 text-xs"
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {visibleTree.map((node) => (
          <TreeNodeRow
            key={node.schema.uid}
            node={node}
            depth={0}
            counts={counts}
            selectedUid={selectedUid}
            onSelect={choose}
            forceExpanded={query.length > 0}
          />
        ))}
        {visibleShared.length > 0 && (
          <div className="mt-2 border-t border-slate-200 pt-2">
            <button
              type="button"
              onClick={() => setSharedOpen(!sharedOpen)}
              className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs font-medium text-sky-700 hover:bg-slate-100"
              title="Types other workspaces have shared with this one. Their objects appear here too, and can be edited only where they live."
            >
              <span className="w-3 text-slate-400">{sharedOpen || query ? "▾" : "▸"}</span>
              Shared
              <span className="ml-auto text-slate-400">{visibleShared.reduce((n, g) => n + g.count, 0)}</span>
            </button>
            {(sharedOpen || query.length > 0) &&
              visibleShared.map((group) => (
                <div key={group.owner} className="ml-3">
                  <p className="px-1.5 pt-1 text-[11px] uppercase tracking-wide text-slate-400">
                    {nameOf(group.owner)}
                  </p>
                  {group.tree.map((node) => (
                    <TreeNodeRow
                      key={node.schema.uid}
                      node={node}
                      depth={0}
                      counts={counts}
                      selectedUid={selectedUid}
                      onSelect={choose}
                      forceExpanded={query.length > 0}
                    />
                  ))}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
