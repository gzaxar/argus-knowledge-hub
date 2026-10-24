import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { iconsApi, schemasApi } from "../../api/client";
import type { AppSchema } from "../../api/types";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";
import { useWorkspaceNames } from "../../api/useWorkspaceNames";
import { AuthenticatedImage } from "../AuthenticatedImage";
import { buildTree, filterTree, type TreeNode } from "../SchemaTree";

type AppliesTo = "objects" | "tickets" | "documents";

/** Records of a type and of every type below it, for each node of the trees given: computed once, bottom up. */
function subtreeCounts(roots: TreeNode[], direct: Map<string, number>): Map<string, number> {
  const out = new Map<string, number>();
  const walk = (n: TreeNode): number => {
    const total = (direct.get(n.schema.uid) ?? 0) + n.children.reduce((s, c) => s + walk(c), 0);
    out.set(n.schema.uid, total);
    return total;
  };
  roots.forEach(walk);
  return out;
}

interface Row {
  node: TreeNode;
  level: number;
  parent: string | null;
}

/** The nodes a person can see: a node's children only while it is open (or a search shows them). */
function visibleRows(roots: TreeNode[], open: Set<string>, all: boolean): Row[] {
  const rows: Row[] = [];
  const walk = (n: TreeNode, level: number, parent: string | null) => {
    rows.push({ node: n, level, parent });
    if (n.children.length && (all || open.has(n.schema.uid))) n.children.forEach((c) => walk(c, level + 1, n.schema.uid));
  };
  roots.forEach((r) => walk(r, 1, null));
  return rows;
}

/** One hierarchy as an accessible tree (WAI-ARIA tree view): arrow keys move, Right and Left open and close,
 * Enter or Space selects, Home and End jump. Only open branches are rendered. */
function TypeTree({ roots, label, counts, selected, onSelect, searching }: {
  roots: TreeNode[];
  label: string;
  counts: Map<string, number>;
  selected: string | null;
  onSelect: (uid: string) => void;
  searching: boolean;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(roots.map((r) => r.schema.uid)));
  const rows = useMemo(() => visibleRows(roots, open, searching), [roots, open, searching]);
  const [focus, setFocus] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLLIElement>());
  const current = rows.some((r) => r.node.schema.uid === focus) ? focus
    : rows.some((r) => r.node.schema.uid === selected) ? selected : rows[0]?.node.schema.uid ?? null;

  // A selection made elsewhere (a link, the URL) opens the branches above it.
  useEffect(() => {
    if (!selected) return;
    const parents = new Map<string, string | null>();
    const walk = (n: TreeNode, p: string | null) => { parents.set(n.schema.uid, p); n.children.forEach((c) => walk(c, n.schema.uid)); };
    roots.forEach((r) => walk(r, null));
    let p = parents.get(selected) ?? null;
    const add: string[] = [];
    while (p) { add.push(p); p = parents.get(p) ?? null; }
    if (add.some((a) => !open.has(a))) setOpen((o) => new Set([...o, ...add]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, roots]);

  const move = (uid: string | null) => {
    if (!uid) return;
    setFocus(uid);
    refs.current.get(uid)?.focus();
  };
  const toggle = (uid: string, to?: boolean) =>
    setOpen((o) => {
      const next = new Set(o);
      if (to ?? !next.has(uid)) next.add(uid); else next.delete(uid);
      return next;
    });

  const onKey = (e: React.KeyboardEvent, row: Row, index: number) => {
    const uid = row.node.schema.uid;
    const hasKids = row.node.children.length > 0;
    const isOpen = searching || open.has(uid);
    switch (e.key) {
      case "ArrowDown": move(rows[index + 1]?.node.schema.uid ?? null); break;
      case "ArrowUp": move(rows[index - 1]?.node.schema.uid ?? null); break;
      case "Home": move(rows[0]?.node.schema.uid ?? null); break;
      case "End": move(rows[rows.length - 1]?.node.schema.uid ?? null); break;
      case "ArrowRight":
        if (hasKids && !isOpen) toggle(uid, true);
        else if (hasKids) move(rows[index + 1]?.node.schema.uid ?? null);
        break;
      case "ArrowLeft":
        if (hasKids && isOpen && !searching) toggle(uid, false);
        else move(row.parent);
        break;
      case "Enter":
      case " ":
        onSelect(uid);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  // Rendered flat with aria-level: the same tree to assistive technology, one list to the browser.
  return (
    <ul role="tree" aria-label={label} className="space-y-px">
      {rows.map((row, i) => {
        const uid = row.node.schema.uid;
        const hasKids = row.node.children.length > 0;
        const isOpen = searching || open.has(uid);
        const count = counts.get(uid) ?? 0;
        const isSelected = uid === selected;
        return (
          <li
            key={uid}
            ref={(el) => { if (el) refs.current.set(uid, el); else refs.current.delete(uid); }}
            role="treeitem"
            aria-level={row.level}
            aria-selected={isSelected}
            aria-expanded={hasKids ? isOpen : undefined}
            tabIndex={uid === current ? 0 : -1}
            onKeyDown={(e) => onKey(e, row, i)}
            onFocus={() => setFocus(uid)}
            onClick={() => onSelect(uid)}
            title={row.node.schema.name}
            className={`flex cursor-pointer items-center gap-1 rounded py-1 pr-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
              isSelected ? "bg-slate-900 font-medium text-white" : "text-slate-700 hover:bg-slate-100"
            }`}
            style={{ paddingLeft: `${(row.level - 1) * 12 + 4}px` }}
          >
            <span
              aria-hidden
              className={`w-3 shrink-0 text-center ${isSelected ? "text-slate-300" : "text-slate-400"}`}
              onClick={(e) => { if (hasKids) { e.stopPropagation(); toggle(uid); } }}
            >
              {hasKids ? (isOpen ? "▾" : "▸") : ""}
            </span>
            {row.node.schema.icon_uid ? (
              <AuthenticatedImage uid={row.node.schema.icon_uid} alt="" fetchBlobUrl={iconsApi.fetchBlobUrl}
                                  className="h-3.5 w-3.5 shrink-0 rounded-sm object-contain" />
            ) : (
              <span aria-hidden className="h-3.5 w-3.5 shrink-0 rounded-sm bg-slate-200" />
            )}
            <span className="min-w-0 flex-1 truncate">{row.node.schema.name}</span>
            {count > 0 && (
              <span className={`shrink-0 tabular-nums ${isSelected ? "text-slate-300" : "text-slate-400"}`}
                    aria-label={`${count} records`}>{count}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

const WORDS: Record<AppliesTo, { title: string; all: string; newType: string; search: string }> = {
  objects: { title: "Object types", all: "All objects", newType: "/schemas/new", search: "Filter types" },
  tickets: { title: "Ticket types", all: "All tickets", newType: "/schemas/new?applies_to=tickets", search: "Filter types" },
  documents: { title: "Document types", all: "All documents", newType: "/schemas/new?applies_to=documents", search: "Filter types" },
};

/** The type filter of a browse page: the workspace's types as a tree with how many records each holds (its
 * own and below), the types other workspaces share apart, a search, and links to manage the catalogue. */
export function TypeExplorer({ appliesTo, counts, total, selected, onSelect, title, allLabel }: {
  appliesTo: AppliesTo;
  /** Records of each type itself (not counting the types below it). */
  counts: Map<string, number>;
  total: number;
  selected: string | null;
  onSelect: (uid: string | null) => void;
  title?: string;
  allLabel?: string;
}) {
  const words = WORDS[appliesTo];
  const searchId = useId();
  const [query, setQuery] = useState("");
  const ws = useCurrentWorkspaceId();
  const nameOf = useWorkspaceNames();
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, staleTime: 60_000 });

  const { own, shared } = useMemo(() => {
    const mine: AppSchema[] = [];
    const others = new Map<string, AppSchema[]>();
    for (const s of schemas.data ?? []) {
      if ((s.applies_to ?? "objects") !== appliesTo) continue;
      if (ws === null || s.workspace_id === ws) mine.push(s);
      else others.set(s.workspace_id, [...(others.get(s.workspace_id) ?? []), s]);
    }
    return {
      own: buildTree(mine),
      shared: [...others.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([owner, list]) => ({ owner, tree: buildTree(list) })),
    };
  }, [schemas.data, appliesTo, ws]);
  const allCounts = useMemo(() => subtreeCounts([...own, ...shared.flatMap((g) => g.tree)], counts), [own, shared, counts]);
  const visibleOwn = useMemo(() => filterTree(own, query.trim()), [own, query]);
  const visibleShared = useMemo(
    () => shared.map((g) => ({ ...g, tree: filterTree(g.tree, query.trim()) })).filter((g) => g.tree.length > 0),
    [shared, query],
  );
  const [sharedOpen, setSharedOpen] = useState(false);
  const searching = query.trim().length > 0;
  const selectedName = (schemas.data ?? []).find((s) => s.uid === selected)?.name;
  const pick = (uid: string) => onSelect(uid === selected ? null : uid);

  return (
    <section aria-label={title ?? words.title} className="flex min-h-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title ?? words.title}</h2>
        <span className="flex items-center gap-2 text-xs">
          <Link to="/catalogue/types" className="text-slate-500 hover:text-slate-900 hover:underline">Catalogue</Link>
          <Link to={words.newType} className="rounded px-1 font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                aria-label={`New ${words.title.toLowerCase().replace(/s$/, "")}`} title="New type">+</Link>
        </span>
      </div>
      <label htmlFor={searchId} className="sr-only">{words.search}</label>
      <input id={searchId} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`${words.search}…`}
             className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500" />
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => onSelect(null)} aria-pressed={!selected}
                className={`flex flex-1 items-center rounded px-2 py-1 text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                  !selected ? "bg-slate-900 font-medium text-white" : "text-slate-700 hover:bg-slate-100"}`}>
          <span className="flex-1">{allLabel ?? words.all}</span>
          <span className={`tabular-nums ${!selected ? "text-slate-300" : "text-slate-400"}`}>{total}</span>
        </button>
        {selected && (
          <button type="button" onClick={() => onSelect(null)} className="shrink-0 rounded px-1.5 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                  aria-label={`Clear the type filter${selectedName ? ` (${selectedName})` : ""}`}>Clear</button>
        )}
      </div>
      {selected && selectedName && (
        <Link to={`/schemas/${encodeURIComponent(selected)}`} className="truncate px-2 text-xs text-sky-700 hover:underline"
              title={`Fields, icon and permissions of ${selectedName}`}>
          {selectedName}: type settings ›
        </Link>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
        {schemas.isLoading && <p className="px-2 py-1 text-xs text-slate-400">Loading types…</p>}
        {visibleOwn.length > 0 && (
          <TypeTree key={searching ? "s" : "t"} roots={visibleOwn} label={title ?? words.title} counts={allCounts}
                    selected={selected} onSelect={pick} searching={searching} />
        )}
        {searching && visibleOwn.length === 0 && visibleShared.length === 0 && (
          <p className="px-2 py-1 text-xs text-slate-400">No type matches “{query.trim()}”.</p>
        )}
        {visibleShared.length > 0 && (
          <div className="mt-2 border-t border-slate-100 pt-2">
            <button type="button" aria-expanded={sharedOpen || searching} onClick={() => setSharedOpen((v) => !v)}
                    className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs font-medium text-sky-700 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                    title="Types other workspaces share with this one; their records can be changed only where they live.">
              <span aria-hidden className="w-3 text-slate-400">{sharedOpen || searching ? "▾" : "▸"}</span>
              Shared by other workspaces
            </button>
            {(sharedOpen || searching) && visibleShared.map((g) => (
              <div key={g.owner} className="mt-1">
                <p className="truncate px-1.5 text-[11px] uppercase tracking-wide text-slate-400" title={nameOf(g.owner)}>{nameOf(g.owner)}</p>
                <TypeTree roots={g.tree} label={`Types shared by ${nameOf(g.owner)}`} counts={allCounts}
                          selected={selected} onSelect={pick} searching={searching} />
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** The type chosen and every type below it, to filter records by a branch of the tree. */
export function typeFamily(schemas: AppSchema[] | undefined, uid: string | null): Set<string> | null {
  if (!uid) return null;
  const children = new Map<string, string[]>();
  for (const s of schemas ?? []) {
    if (s.parent_schema_uid) children.set(s.parent_schema_uid, [...(children.get(s.parent_schema_uid) ?? []), s.uid]);
  }
  const out = new Set<string>();
  const walk = (u: string) => { if (out.has(u)) return; out.add(u); (children.get(u) ?? []).forEach(walk); };
  walk(uid);
  return out;
}

/** How many records of each type, from the records a list already holds. */
export function countBy<T>(rows: T[] | undefined, typeOf: (row: T) => string | null | undefined): Map<string, number> {
  const m = new Map<string, number>();
  for (const r of rows ?? []) {
    const t = typeOf(r);
    if (t) m.set(t, (m.get(t) ?? 0) + 1);
  }
  return m;
}
