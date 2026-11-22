import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HubStartStep } from "../api/hubTypes";
import { StartHere } from "../components/hub/StartHere";

vi.mock("../api/useCurrentWorkspaceId", () => ({ useCurrentWorkspaceId: () => "lab" }));

const step = (key: HubStartStep["key"], count = 0, extra: Partial<HubStartStep> = {}): HubStartStep =>
  ({ key, count, done: count > 0, ...extra });

const show = (steps: HubStartStep[]) => render(<MemoryRouter><StartHere steps={steps} /></MemoryRouter>);

describe("Start here", () => {
  beforeEach(() => localStorage.clear());

  it("lists the steps in order, ticks what is done and points at the next one", () => {
    show([step("places", 2, { type_uid: "lab:argus-object:building" }), step("equipment"), step("people"),
          step("document"), step("ticket")]);
    expect(screen.getByRole("heading", { name: "Start here" })).toBeInTheDocument();
    expect(screen.getByText("1 of 5 done")).toBeInTheDocument();
    expect(screen.getByText("Done — 2")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add a building" })).toBeNull();
    expect(screen.getByRole("link", { name: "Import a spreadsheet" })).toHaveAttribute("href", "/assets/import");
    expect(screen.getByRole("link", { name: "Invite people" })).toHaveAttribute("href", "/workspaces/lab/access");
  });

  it("opens the form on the Building type for the places", () => {
    show([step("places", 0, { type_uid: "lab:argus-object:building" }), step("people")]);
    expect(screen.getByRole("link", { name: "Add a building" }))
      .toHaveAttribute("href", "/assets/new?schema_uid=lab%3Aargus-object%3Abuilding");
  });

  it("goes away once every step is done, or when hidden", () => {
    const { container, unmount } = show([step("places", 1), step("people", 1)]);
    expect(container).toBeEmptyDOMElement();
    unmount();
    show([step("places"), step("people")]);
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByRole("heading", { name: "Start here" })).toBeNull();
    expect(localStorage.getItem("argus.start-here.hidden.lab")).toBe("1");
  });
});
