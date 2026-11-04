type HeadingNode = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: HeadingNode[] };
export function headingAnchors() {
  return (tree: HeadingNode) => {
    const counts = new Map<string, number>();
    const text = (node: HeadingNode): string => node.type === "text" ? node.value ?? "" : (node.children ?? []).map(text).join("");
    const walk = (node: HeadingNode) => {
      if (/^h[1-6]$/.test(node.tagName ?? "")) {
        const slug = text(node).toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/\s/g, "-") || "section";
        const count = counts.get(slug) ?? 0; counts.set(slug, count + 1);
        node.properties = { ...node.properties, id: `argus-heading-${slug}${count ? `-${count}` : ""}` };
      }
      node.children?.forEach(walk);
    };
    walk(tree);
  };
}
