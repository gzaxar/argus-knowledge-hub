import type { AppSchema } from "../api/types";

/* The type hierarchy as a tree, for the type explorer of the browse pages (components/browse/TypeExplorer)
   and the schema browser. */

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
