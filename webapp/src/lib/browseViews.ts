/** Only view names are remembered, never filters, record IDs, credentials or arbitrary destinations. */
export const BROWSE_VIEW_PATHS = {
  documents: { list: "/documents", tree: "/documents/tree", board: "/documents/board" },
  tickets: { list: "/tickets", board: "/tickets/board" },
  assets: { list: "/assets/search", map: "/map" },
} as const;

export type BrowseSection = keyof typeof BROWSE_VIEW_PATHS;
export type BrowseViewLinks = Record<BrowseSection, string>;
export type ViewStorage = Pick<Storage, "getItem" | "setItem">;

export function browseViewKey(scope: string, section: BrowseSection): string {
  return `argus.browse.view.v1.${encodeURIComponent(scope)}.${section}`;
}

function browserStorage(): ViewStorage | undefined {
  try { return typeof localStorage === "undefined" ? undefined : localStorage; }
  catch { return undefined; }
}

export function browseViewAt(pathname: string): { section: BrowseSection; view: string } | null {
  for (const section of Object.keys(BROWSE_VIEW_PATHS) as BrowseSection[]) {
    for (const [view, path] of Object.entries(BROWSE_VIEW_PATHS[section])) {
      if (pathname === path) return { section, view };
    }
  }
  return null;
}

export function readBrowseView(scope: string, section: BrowseSection, storage?: ViewStorage): string {
  const paths: Readonly<Record<string, string>> = BROWSE_VIEW_PATHS[section];
  try {
    const view = (storage ?? browserStorage())?.getItem(browseViewKey(scope, section));
    return view && Object.prototype.hasOwnProperty.call(paths, view) ? paths[view] : paths.list;
  } catch { return paths.list; }
}

export function rememberBrowseView(scope: string, pathname: string, storage?: ViewStorage): boolean {
  const selected = browseViewAt(pathname);
  if (!selected) return false;
  try {
    const target = storage ?? browserStorage();
    if (!target) return false;
    const key = browseViewKey(scope, selected.section);
    if (target.getItem(key) === selected.view) return false;
    target.setItem(key, selected.view);
    return true;
  } catch { return false; }
}

/** Only the main menu's generic entry links restore a preference. All explicit URLs stay unchanged. */
export function preferredAreaHref(to: string, views: BrowseViewLinks, mapAvailable: boolean): string {
  if (to === "/documents") return views.documents;
  if (to === "/tickets") return views.tickets;
  if (to === "/assets/search") return views.assets === "/map" && !mapAvailable ? "/assets/search" : views.assets;
  return to;
}
