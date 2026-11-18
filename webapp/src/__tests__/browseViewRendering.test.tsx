import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ViewSwitch } from "../components/browse/Browse";
import { DocumentViewSwitch } from "../components/DocumentViews";
import { areas, SideNav } from "../layout/AppShell";
import { browseViewKey } from "../lib/browseViews";
import { renderWith } from "../test/render";

type Features = Parameters<typeof areas>[0];
const ALL = { equipment: true, map: true, beam_model: true } as unknown as Features;
const nav = () => screen.getByRole("navigation", { name: "Main" });
afterEach(() => vi.restoreAllMocks());

describe("shared view selector and main navigation", () => {
  it("shows View and decorative icons while retaining readable link names", () => {
    renderWith(<ViewSwitch views={[
      { label: "List", to: "/documents", current: true },
      { label: "Tree", to: "/documents/tree", current: false },
      { label: "Board", to: "/documents/board", current: false },
      { label: "Map", to: "/map", current: false },
    ]} />);
    expect(screen.getByText("View")).toBeVisible();
    const views = screen.getByRole("navigation", { name: "View" });
    for (const label of ["List", "Tree", "Board", "Map"]) {
      const link = within(views).getByRole("link", { name: label });
      expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      expect(link.querySelector("svg")).toHaveAttribute("focusable", "false");
    }
    expect(within(views).getByRole("link", { name: "List" })).toHaveAttribute("aria-current", "page");
  });

  it("preserves filters and drops pagination when switching with the keyboard", async () => {
    const r = renderWith(<DocumentViewSwitch current="list" />, { path: "/documents?q=bpm&type=t1&page=4" });
    screen.getByRole("link", { name: "Tree" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(r.location()).toBe("/documents/tree?q=bpm&type=t1");
  });

  it("restores each section's choice from its own sidebar link", () => {
    localStorage.setItem(browseViewKey("browser", "documents"), "tree");
    localStorage.setItem(browseViewKey("browser", "tickets"), "board");
    localStorage.setItem(browseViewKey("browser", "assets"), "map");
    renderWith(<SideNav items={areas(ALL, 0)} />);
    expect(within(nav()).getByRole("link", { name: /Documents/ })).toHaveAttribute("href", "/documents/tree");
    expect(within(nav()).getByRole("link", { name: /Tickets/ })).toHaveAttribute("href", "/tickets/board");
    expect(within(nav()).getByRole("link", { name: /Assets/ })).toHaveAttribute("href", "/map");
  });

  it("records a selected view and restores it after leaving the section", async () => {
    const r = renderWith(<><SideNav items={areas(ALL, 0)} /><DocumentViewSwitch current="list" /></>,
                         { path: "/documents" });
    await userEvent.click(screen.getByRole("link", { name: "Tree" }));
    expect(localStorage.getItem(browseViewKey("browser", "documents"))).toBe("tree");
    await userEvent.click(within(nav()).getByRole("link", { name: /Cockpit/ }));
    expect(r.location()).toBe("/");
    await userEvent.click(within(nav()).getByRole("link", { name: /Documents/ }));
    expect(r.location()).toBe("/documents/tree");
  });

  it("honours a direct List URL instead of redirecting it to a remembered Tree", () => {
    localStorage.setItem(browseViewKey("browser", "documents"), "tree");
    const r = renderWith(<SideNav items={areas(ALL, 0)} />, { path: "/documents?q=bpm" });
    expect(r.location()).toBe("/documents?q=bpm");
    expect(localStorage.getItem(browseViewKey("browser", "documents"))).toBe("list");
  });

  it("leaves direct revision URLs and existing preferences alone", () => {
    localStorage.setItem(browseViewKey("browser", "documents"), "tree");
    const r = renderWith(<SideNav items={areas(ALL, 0)} />, { path: "/documents/doc1?revision=rev2" });
    expect(r.location()).toBe("/documents/doc1?revision=rev2");
    expect(localStorage.getItem(browseViewKey("browser", "documents"))).toBe("tree");
  });

  it("falls back to Assets List when Map is not available", () => {
    localStorage.setItem(browseViewKey("browser", "assets"), "map");
    const features = { ...ALL, map: false } as Features;
    renderWith(<SideNav items={areas(features, 0)} />);
    expect(within(nav()).getByRole("link", { name: /Assets/ })).toHaveAttribute("href", "/assets/search");
  });

  it("uses the active connection profile without sharing choices with another profile", () => {
    localStorage.setItem("assetmanagement.profiles", JSON.stringify([
      { id: "a", name: "A", baseUrl: "http://local", authType: "pat", token: "" },
      { id: "b", name: "B", baseUrl: "http://local", authType: "pat", token: "" },
    ]));
    localStorage.setItem("assetmanagement.activeProfileId", "a");
    localStorage.setItem(browseViewKey(JSON.stringify(["http://local", "a"]), "documents"), "board");
    const first = renderWith(<SideNav items={areas(ALL, 0)} />);
    expect(within(nav()).getByRole("link", { name: /Documents/ })).toHaveAttribute("href", "/documents/board");
    first.unmount();
    localStorage.setItem("assetmanagement.activeProfileId", "b");
    renderWith(<SideNav items={areas(ALL, 0)} />);
    expect(within(nav()).getByRole("link", { name: /Documents/ })).toHaveAttribute("href", "/documents");
  });

  it("updates sidebar destinations after a preference changes in another tab", () => {
    renderWith(<SideNav items={areas(ALL, 0)} />);
    act(() => {
      localStorage.setItem(browseViewKey("browser", "tickets"), "board");
      window.dispatchEvent(new Event("storage"));
    });
    expect(within(nav()).getByRole("link", { name: /Tickets/ })).toHaveAttribute("href", "/tickets/board");
  });

  it("keeps navigation usable when browser storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw Error("blocked"); });
    const r = renderWith(<SideNav items={areas(ALL, 0)} />);
    await userEvent.click(within(nav()).getByRole("link", { name: /Documents/ }));
    expect(r.location()).toBe("/documents");
  });
});
