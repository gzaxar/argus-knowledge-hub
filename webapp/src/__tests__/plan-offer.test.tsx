import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { indoorApi, placesApi, type IndoorView } from "../api/client";
import { IndoorCard } from "../components/IndoorCard";
import { DialogHost } from "../lib/dialogs";
import { renderWith } from "../test/render";

vi.mock("../components/PlanView", () => ({
  PlanView: () => <div data-testid="plan" />,
  usePlanImage: () => ({ data: null }),
  NorthArrow: () => null,
}));

afterEach(() => vi.restoreAllMocks());

const offer = {
  place: { uid: "room", key: "R-1", name: "Network Room (MDF)", type: "Room" },
  plans: [{ uid: "pl", name: "Hub Building — ground floor", level: "Ground floor", place: { uid: "hub", name: "Hub Building" } }],
};
const view: IndoorView = { uid: "sw", placement: null, in: [], contents: [], history: [], spot: null, plan_offer: offer };

function mocks() {
  vi.spyOn(placesApi, "location").mockResolvedValue({ uid: "sw", hidden: false } as never);
  vi.spyOn(indoorApi, "indoors").mockResolvedValue(view);
  vi.spyOn(indoorApi, "levels").mockResolvedValue({ levels: [], plans: [{ uid: "pl", name: "Hub Building — ground floor",
    width_px: 600, height_px: 360, level: null, place: { uid: "hub", name: "Hub Building" } } as never] });
}

describe("a record said to be in a place that has a floor plan", () => {
  it("is offered that plan, and putting it there starts in that place on that plan", async () => {
    mocks();
    renderWith(<IndoorCard uid="sw" editable />);
    const banner = await screen.findByText(/which has a floor plan/);
    expect(banner).toHaveTextContent("Network Room (MDF)");
    fireEvent.click(screen.getByRole("button", { name: "Put it on the plan" }));
    const dialog = await screen.findByRole("dialog", { name: "Place it inside" });
    expect(dialog).toHaveTextContent("Network Room (MDF)");
    await waitFor(() => expect(screen.getAllByRole("combobox").map((c) => (c as HTMLSelectElement).value)).toContain("pl"));
  });

  it("is asked about it right after it is created", async () => {
    mocks();
    renderWith(<><DialogHost /><IndoorCard uid="sw" editable /></>, { path: "/assets/sw?onplan=ask" });
    expect(await screen.findByText(/Network Room \(MDF\) has a floor plan\. Put it on the floor plan Hub Building — ground floor now\?/))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByRole("dialog", { name: "Place it inside" })).toBeInTheDocument();
  });

  it("is not offered it on a page that only reads", async () => {
    mocks();
    renderWith(<IndoorCard uid="sw" editable={false} />);
    await screen.findByText("Indoors");
    expect(screen.queryByText(/which has a floor plan/)).toBeNull();
  });
});
