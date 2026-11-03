import { useEffect, useMemo, useState } from "react";
import { AppSchema } from "../api/types";
import { buildTree, filterTree, TreeNode } from "./SchemaTree";

/** A type and every type below it. */
export function subtree(schemas: AppSchema[], root: string): AppSchema[] {
  const below = new Set([root]);
  for (let grew = true; grew;) {
    grew = false;
    for (const s of schemas) {
      if (s.parent_schema_uid && below.has(s.parent_schema_uid) && !below.has(s.uid)) { below.add(s.uid); grew = true; }
    }
  }
  return schemas.filter((s) => below.has(s.uid));
}

function BrowserRow({
  node,
  depth,
  expandAll,
  onPick,
}: {
  node: TreeNode;
  depth: number;
  expandAll: boolean;
  onPick: (schema: AppSchema) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const expanded = expandAll || open;
  const hasChildren = node.children.length > 0;
  // A category (not concrete) groups kinds; only a kind can have records.
  const pickable = node.schema.is_concrete !== false;

  return (
    <div>
      <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: `${depth * 16}px` }}>
        <button
          type="button"
          onClick={() => hasChildren && setOpen((v) => !v)}
          className="w-4 shrink-0 text-xs text-slate-400"
          aria-label={hasChildren ? (expanded ? "Collapse" : "Expand") : undefined}
          tabIndex={hasChildren ? 0 : -1}
        >
          {hasChildren ? (expanded ? "▾" : "▸") : ""}
        </button>
        {pickable ? (
          <button
            type="button"
            onClick={() => onPick(node.schema)}
            className="truncate rounded px-1.5 py-0.5 text-left text-sm text-slate-800 hover:bg-indigo-50 hover:text-indigo-700"
            title={node.schema.description ?? undefined}
          >
            {node.schema.name}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => hasChildren && setOpen((v) => !v)}
            className="truncate px-1.5 py-0.5 text-left text-sm font-medium text-slate-500"
            title="A category: choose one of its kinds"
          >
            {node.schema.name}
          </button>
        )}
        {node.schema.is_global && (
          <span className="rounded bg-amber-50 px-1 py-0.5 text-[10px] font-medium text-amber-700">global</span>
        )}
      </div>
      {hasChildren && expanded && (
        <div>
          {node.children.map((child) => (
            <BrowserRow key={child.schema.uid} node={child} depth={depth + 1} expandAll={expandAll} onPick={onPick} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Every type, grouped by category, for when searching by name is not
 * enough: you know roughly what it is, not what the type is called. */
export function SchemaBrowser({
  schemas,
  onPick,
  onClose,
  within,
}: {
  schemas: AppSchema[];
  onPick: (schema: AppSchema) => void;
  onClose: () => void;
  /** Only this type and the types below it (an abstract type chosen on the Assets page: its kinds). */
  within?: string | null;
}) {
  const [query, setQuery] = useState("");
  const tree = useMemo(() => buildTree(within ? subtree(schemas, within) : schemas), [schemas, within]);
  const shown = useMemo(() => filterTree(tree, query.trim()), [tree, query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-slate-900/30 p-4 pt-[10vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div role="dialog" aria-label="All types" className="flex max-h-[75vh] w-full max-w-lg flex-col rounded-lg bg-white shadow-xl">
        <div className="flex items-center gap-2 border-b border-slate-200 p-3">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter types…"
            className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
          <button type="button" onClick={onClose} className="text-sm text-slate-500 hover:text-slate-900">
            Close
          </button>
        </div>
        <div className="overflow-y-auto p-3">
          {shown.map((node) => (
            <BrowserRow key={node.schema.uid} node={node} depth={0} expandAll={!!query.trim()} onPick={onPick} />
          ))}
          {shown.length === 0 && <p className="text-sm text-slate-400">No matching types.</p>}
        </div>
        <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-400">
          Grey names are categories; open one to choose a kind inside it.
        </p>
      </div>
    </div>
  );
}
