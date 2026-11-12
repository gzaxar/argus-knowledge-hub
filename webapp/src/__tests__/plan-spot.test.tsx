import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { indoorApi, placesApi, type IndoorView } from "../api/client";
import { IndoorCard } from "../components/IndoorCard";
import { FloorPlanPage } from "../pages/map/FloorPlanPage";
import { renderWith } from "../test/render";

// The plan itself is Leaflet on a picture; what matters here is where it is pinned and what it says.
vi.mock("../components/PlanView", () => ({
  PlanView: ({ pins, lines = [] }: { pins: { label: string; x: number; y: number; highlight?: boolean }[];
                                      lines?: { label?: string }[] }) => (
    <div data-testid="plan">{pins.map((p) => `${p.label}@${p.x},${p.y}${p.highlight ? "!" : ""}`).join(" ")}
      {lines.map((l) => ` —${l.label}`).join("")}</div>
  ),
  usePlanImage: () => ({ data: null }),
  NorthArrow: () => null,
}));

afterEach(() => vi.restoreAllMocks());

const rack = { uid: "nf-rack-a01", key: "NF-RACK-A01", name: "Rack R-A01", type: "Rack" };
const view: IndoorView = {
  uid: "nf-sc-dh1", placement: null, in: [], contents: [], history: [],
  spot: { plan: { uid: "pl", name: "Hub Building — ground floor", width_px: 600, height_px: 360 }, x: 60, y: 100,
          level: { uid: "l0", place_uid: "hub", name: "Ground floor", ordinal: 0, elevation_m: null, height_m: null },
          via: rack, path: [rack] },
};

describe("a device with no point of its own on a plan", () => {
  it("is shown where its rack is, and says so", async () => {
    vi.spyOn(placesApi, "location").mockResolvedValue({ uid: "nf-sc-dh1", hidden: false } as never);
    vi.spyOn(indoorApi, "indoors").mockResolvedValue(view);
    vi.spyOn(indoorApi, "levels").mockResolvedValue({ levels: [], plans: [] });
    renderWith(<IndoorCard uid="nf-sc-dh1" editable={false} />);

    expect(await screen.findByText(/Not placed itself, but it is in/)).toHaveTextContent("Rack R-A01");
    expect(screen.getByText(/No point of its own on a plan: shown where its rack/)).toHaveTextContent("NF-RACK-A01");
    expect(screen.getByTestId("plan")).toHaveTextContent("here, in NF-RACK-A01@60,100!");
    fireEvent.click(screen.getByRole("button", { name: "Show on the floor plan" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

describe("records on their floor plan, from a link in an answer", () => {
  it("shows the converter at its rack and the UPSs at theirs, with how far and which way", async () => {
    const plan = { uid: "pl", name: "Hub Building — ground floor", width_px: 600, height_px: 360, north_deg: 0,
                   level: { uid: "l0", place_uid: "hub", name: "Ground floor", ordinal: 0, elevation_m: null, height_m: null } };
    const show = vi.spyOn(indoorApi, "show").mockResolvedValue({
      plans: [plan as never],
      records: [
        { uid: "nf-sc-dh1", key: "NF-SC-DH1", name: "Serial converter SC-DH1", type: "Serial Converter", spot: view.spot! },
        { uid: "nf-ups-01", key: "NF-UPS-01", name: "UPS-01", type: "UPS", from_first: { metres: 50.3, direction: "east" },
          spot: { ...view.spot!, x: 540, y: 250, via: null, path: [] } },
      ],
    });
    renderWith(<FloorPlanPage />, { path: "/?show=nf-sc-dh1,nf-ups-01" });

    expect(await screen.findByText(/50.3 m east of NF-SC-DH1/)).toBeInTheDocument();
    expect(show).toHaveBeenCalledWith(["nf-sc-dh1", "nf-ups-01"]);
    expect(screen.getByText(/no point of its own: shown where its rack/)).toHaveTextContent("NF-RACK-A01");
    expect(screen.getByTestId("plan")).toHaveTextContent("NF-SC-DH1 (in NF-RACK-A01)@60,100! NF-UPS-01@540,250! —50.3 m");
  });
});
