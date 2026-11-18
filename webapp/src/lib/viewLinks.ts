/** Build a view destination without carrying state that belongs only to the source view. */
export function viewHref(to: string, search: string, clearParams: readonly string[] = []): string {
  const [path, own] = to.split("?");
  const merged = new URLSearchParams(search);
  merged.delete("page");
  clearParams.forEach((key) => merged.delete(key));
  new URLSearchParams(own ?? "").forEach((value, key) => merged.set(key, value));
  const qs = merged.toString();
  return `${path}${qs ? `?${qs}` : ""}`;
}

// These describe a selected node / preview, not a table or board filter.
export const DOCUMENT_TREE_PARAMS = ["node", "nav", "panel", "type_group", "rev"] as const;
