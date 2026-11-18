import { describe, expect, it } from "vitest";
import {
  browseViewAt, browseViewKey, preferredAreaHref, readBrowseView, rememberBrowseView,
  type ViewStorage,
} from "../lib/browseViews";

function store(): ViewStorage {
  const values = new Map<string, string>();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); } };
}

describe("remembered browse views", () => {
  it("defaults each section to its list", () => {
    const s = store();
    expect(readBrowseView("p", "documents", s)).toBe("/documents");
    expect(readBrowseView("p", "tickets", s)).toBe("/tickets");
    expect(readBrowseView("p", "assets", s)).toBe("/assets/search");
  });

  it("keeps choices separate for the three sections", () => {
    const s = store();
    rememberBrowseView("p", "/documents/tree", s);
    rememberBrowseView("p", "/tickets/board", s);
    rememberBrowseView("p", "/map", s);
    expect(readBrowseView("p", "documents", s)).toBe("/documents/tree");
    expect(readBrowseView("p", "tickets", s)).toBe("/tickets/board");
    expect(readBrowseView("p", "assets", s)).toBe("/map");
  });

  it("keeps connection profiles separate", () => {
    const s = store();
    rememberBrowseView("server-a/profile-a", "/documents/board", s);
    expect(readBrowseView("server-a/profile-a", "documents", s)).toBe("/documents/board");
    expect(readBrowseView("server-a/profile-b", "documents", s)).toBe("/documents");
    expect(readBrowseView("server-b/profile-a", "documents", s)).toBe("/documents");
  });

  it("remembers a return to List and skips duplicate writes", () => {
    const s = store();
    expect(rememberBrowseView("p", "/documents/tree", s)).toBe(true);
    expect(rememberBrowseView("p", "/documents/tree", s)).toBe(false);
    expect(rememberBrowseView("p", "/documents", s)).toBe(true);
    expect(readBrowseView("p", "documents", s)).toBe("/documents");
  });

  it("does not treat record details, tools or unrelated pages as views", () => {
    const s = store();
    rememberBrowseView("p", "/documents/tree", s);
    for (const path of ["/documents/d1", "/documents/new", "/documents/templates", "/tickets/t1", "/assets/a1", "/ask"]) {
      expect(browseViewAt(path)).toBeNull();
      expect(rememberBrowseView("p", path, s)).toBe(false);
    }
    expect(readBrowseView("p", "documents", s)).toBe("/documents/tree");
  });

  it("rejects unknown, foreign-section and arbitrary stored destinations", () => {
    const s = store();
    for (const value of ["map", "/documents/tree", "https://example.invalid", "__proto__", "toString"]) {
      s.setItem(browseViewKey("p", "documents"), value);
      expect(readBrowseView("p", "documents", s)).toBe("/documents");
    }
  });

  it("falls back safely when storage is blocked", () => {
    const s: ViewStorage = { getItem: () => { throw Error("blocked"); }, setItem: () => { throw Error("blocked"); } };
    expect(readBrowseView("p", "documents", s)).toBe("/documents");
    expect(rememberBrowseView("p", "/documents/tree", s)).toBe(false);
  });

  it("does not offer a remembered Map where the feature is absent", () => {
    const views = { documents: "/documents/tree", tickets: "/tickets/board", assets: "/map" };
    expect(preferredAreaHref("/assets/search", views, false)).toBe("/assets/search");
    expect(preferredAreaHref("/assets/search", views, true)).toBe("/map");
  });

  it("changes only generic main-menu destinations, never direct links", () => {
    const views = { documents: "/documents/tree", tickets: "/tickets/board", assets: "/map" };
    expect(preferredAreaHref("/documents", views, true)).toBe("/documents/tree");
    expect(preferredAreaHref("/tickets", views, true)).toBe("/tickets/board");
    for (const to of ["/documents?node=d%3Ax", "/documents/board", "/documents/d1?revision=r1", "/tickets/123", "/map"]) {
      expect(preferredAreaHref(to, views, true)).toBe(to);
    }
  });

  it("stores a view name only", () => {
    const s = store();
    rememberBrowseView("p", "/documents/tree", s);
    expect(s.getItem(browseViewKey("p", "documents"))).toBe("tree");
  });
});
