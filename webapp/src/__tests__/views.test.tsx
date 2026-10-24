import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useBrowseParams, useSelection, ViewSwitch } from "../components/browse/Browse";
import { ticketMatches } from "../pages/issues/List";
import { renderWith } from "../test/render";

describe("switching between list, board and map", () => {
  it("carries the filters, and starts the other view on its first page", () => {
    renderWith(<ViewSwitch views={[{ label: "List", to: "/tickets", current: true }, { label: "Board", to: "/tickets/board", current: false }]} />,
               { path: "/tickets?q=pump&type=inc&page=3" });
    expect(screen.getByRole("link", { name: "List" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Board" })).toHaveAttribute("href", "/tickets/board?q=pump&type=inc");
  });

  it("adds the view's own parameters (the map's type filter)", () => {
    renderWith(<ViewSwitch views={[{ label: "Map", to: "/map?types=srv", current: false }]} />, { path: "/assets/search?q=rack" });
    expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute("href", "/map?q=rack&types=srv");
  });

  it("keeps the filters in the address; a new filter goes back to page 1", async () => {
    function Probe() {
      const { get, set } = useBrowseParams();
      return <button type="button" onClick={() => set({ type: "chg" })}>{get("q")}|{get("page")}</button>;
    }
    const r = renderWith(<Probe />, { path: "/tickets?q=pump&page=2" });
    expect(screen.getByRole("button")).toHaveTextContent("pump|2");
    await userEvent.click(screen.getByRole("button"));
    expect(r.location()).toBe("/tickets?q=pump&type=chg");
  });

  it("keeps the selection when the list is left and opened again", () => {
    function Probe() {
      const s = useSelection("tickets");
      return <button type="button" onClick={() => s.toggle("a")}>{[...s.selected].join(",") || "none"}</button>;
    }
    const first = renderWith(<Probe />);
    act(() => screen.getByRole("button").click());
    first.unmount();
    renderWith(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("a");
  });

  it("the board and the list filter tickets alike", () => {
    const t = { title: "Pump fault", state: "closed", schema_uid: "inc", assignee: null } as never;
    const f = { q: "pump", family: new Set(["inc"]), state: "all", assignee: "" };
    expect(ticketMatches(t, f)).toBe(true);
    expect(ticketMatches(t, { ...f, state: "open" })).toBe(false);
    expect(ticketMatches(t, { ...f, assignee: "none" })).toBe(true);
    expect(ticketMatches(t, { ...f, family: new Set(["chg"]) })).toBe(false);
  });
});
