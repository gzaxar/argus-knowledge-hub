import type { DocumentNavigationNode } from "../api/types";

export type SearchNode = DocumentNavigationNode & { searchText?: string };

/** Unique documents strictly below each node, independent of expansion/search. */
export function branchCounts(nodes: DocumentNavigationNode[]): Map<string, number> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const documentsByAncestor = new Map<string, Set<string>>();
  for (const node of nodes) {
    if (node.kind !== "document") continue;
    const visited = new Set([node.id]);
    let parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    while (parent && !visited.has(parent.id)) {
      visited.add(parent.id);
      // A document's own overview is not one of its descendants, even if a damaged graph repeats its UID.
      if (parent.kind !== "document" || parent.uid !== node.uid) {
        const found = documentsByAncestor.get(parent.id) ?? new Set<string>();
        found.add(node.uid); documentsByAncestor.set(parent.id, found);
      }
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
    }
  }
  return new Map(nodes.map((n) => [n.id, documentsByAncestor.get(n.id)?.size ?? 0]));
}

export function ancestorPath(nodes: DocumentNavigationNode[], id: string): DocumentNavigationNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const path: DocumentNavigationNode[] = [];
  const seen = new Set<string>();
  let current = byId.get(id);
  while (current && !seen.has(current.id)) {
    seen.add(current.id); path.push(current);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return path.reverse();
}

export function descendants(nodes: DocumentNavigationNode[], id: string): Set<string> {
  const children = new Map<string, string[]>();
  for (const node of nodes) if (node.parent_id) {
    const group = children.get(node.parent_id) ?? []; group.push(node.id); children.set(node.parent_id, group);
  }
  const found = new Set<string>();
  const pending = [id];
  while (pending.length) {
    const next = pending.pop()!;
    if (found.has(next)) continue;
    found.add(next); pending.push(...(children.get(next) ?? []));
  }
  return found;
}

export function treeRows(nodes: SearchNode[], expanded: Set<string>, query: string) {
  const children = new Map<string | null, SearchNode[]>();
  const known = new Set(nodes.map((n) => n.id));
  for (const node of nodes) {
    const parent = node.parent_id && known.has(node.parent_id) ? node.parent_id : null;
    const group = children.get(parent) ?? []; group.push(node); children.set(parent, group);
  }
  for (const group of children.values()) group.sort((a, b) => a.title.localeCompare(b.title, undefined, { numeric: true }) || a.id.localeCompare(b.id));
  const search = query.trim().toLowerCase();
  const allowed = new Set<string>();
  const byId = new Map(nodes.map((n) => [n.id, n]));
  if (search) for (const node of nodes) if ((node.searchText ?? node.title).toLowerCase().includes(search)) {
    let current: SearchNode | undefined = node;
    while (current && !allowed.has(current.id)) {
      allowed.add(current.id); current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
  }
  const pending = (children.get(null) ?? []).slice().reverse().map((node) => ({ node, depth: 0 }));
  const rows: { node: SearchNode; depth: number; hasChildren: boolean; open: boolean }[] = [];
  const visited = new Set<string>();
  while (pending.length) {
    const { node, depth } = pending.pop()!;
    if (visited.has(node.id) || (search && !allowed.has(node.id))) continue;
    visited.add(node.id);
    const branch = children.get(node.id) ?? [];
    const open = !!search || expanded.has(node.id);
    rows.push({ node, depth, hasChildren: branch.length > 0, open });
    if (open) for (const child of branch.slice().reverse()) pending.push({ node: child, depth: depth + 1 });
  }
  return rows;
}

/** The stored source H1 is preserved; the preview's card heading already displays it. */
export function previewBody(body: string, title: string): string {
  const match = /^(?:\r?\n)*#\s+([^\r\n]+)\r?\n(?:\r?\n)?/.exec(body);
  if (!match) return body;
  const heading = match[1].replace(/\s+#+\s*$/, "").replace(/\\([\\`*_{}\[\]<>!|#])/g, "$1");
  return heading === title ? body.slice(match[0].length) : body;
}
