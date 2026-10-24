import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { areas, SideNav } from "../layout/AppShell";
import { renderWith } from "../test/render";

type Features = Parameters<typeof areas>[0];
const ALL = { equipment: true, map: true, beam_model: true } as unknown as Features;

describe("the main navigation", () => {
  it("lists the ten areas in a stable order", () => {
    expect(areas(ALL, 0).map((a) => a.label)).toEqual([
      "Cockpit", "Assets", "Tickets", "Documents", "Activities", "Map", "Knowledge graph", "Beam model", "Ask ARGUS",
      "Review queue",
    ]);
  });

  it("leaves out what the workspace's packages do not provide", () => {
    const labels = areas({ equipment: false } as unknown as Features, 0).map((a) => a.label);
    expect(labels).toContain("Records");
    expect(labels).not.toContain("Map");
    expect(labels).not.toContain("Beam model");
  });

  it("is a labelled navigation that marks the current area, also on its sub-pages", () => {
    renderWith(<SideNav items={areas(ALL, 3)} />, { path: "/tickets/board?type=x" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: /Tickets/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /Cockpit/ })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByLabelText("3 waiting")).toBeInTheDocument();
  });

  it("keeps Assets current on its tools and on object types", () => {
    renderWith(<SideNav items={areas(ALL, 0)} />, { path: "/labels" });
    expect(screen.getByRole("link", { name: /Assets/ })).toHaveAttribute("aria-current", "page");
  });
});
