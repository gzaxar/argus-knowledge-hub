import { useEffect, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import { getActiveProfile } from "../../api/session";
import { readBrowseView, rememberBrowseView, type BrowseViewLinks } from "../../lib/browseViews";

const CHANGED = "argus:browse-view-changed";
const DEFAULTS = "/documents|/tickets|/assets/search";

function subscribe(changed: () => void) {
  window.addEventListener(CHANGED, changed);
  window.addEventListener("storage", changed);
  return () => {
    window.removeEventListener(CHANGED, changed);
    window.removeEventListener("storage", changed);
  };
}

function profileScope(): string {
  try {
    const profile = getActiveProfile();
    return profile ? JSON.stringify([profile.baseUrl, profile.id]) : "browser";
  } catch { return "browser"; }
}

/** The last visited view, per section and saved connection profile, in this browser only. */
export function useBrowseViewLinks(): BrowseViewLinks {
  const { pathname } = useLocation();
  const scope = profileScope();
  const snapshot = useSyncExternalStore(subscribe, () => [
    readBrowseView(scope, "documents"), readBrowseView(scope, "tickets"), readBrowseView(scope, "assets"),
  ].join("|"), () => DEFAULTS);

  useEffect(() => {
    if (rememberBrowseView(scope, pathname)) window.dispatchEvent(new Event(CHANGED));
  }, [scope, pathname]);

  const [documents, tickets, assets] = snapshot.split("|");
  return { documents, tickets, assets };
}
