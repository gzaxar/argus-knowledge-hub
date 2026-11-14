import { describe, expect, it, vi } from "vitest";
import type { PlanLayersView, TunnelElement } from "../api/client";
import { drawn, initialLayers } from "../pages/map/PlanLayersPage";
import { spreadOut, stateOf } from "../pages/beam/TunnelPage";

const layer = (id: string, on: boolean) => ({ id, label: id, on, count: 1 }) as PlanLayersView["layers"][number];

const view = {
  uid: "p", name: "Hall", width_px: 100, height_px: 50,
  layers: [layer("places", true), layer("racks", true), layer("devices", false), layer("tickets", false), layer("zones", false)],
  items: [
    { uid: "rk", key: "RK-1", name: "Rack 1", type: "Rack", x: 10, y: 10, layer: "racks", tickets: 2, activities: 0, rack: { holds: 3, mounted: true } },
    { uid: "cam", key: "CAM-1", name: "Camera", type: "Camera", x: 50, y: 20, layer: "devices", tickets: 0, activities: 0 },
  ],
  outlines: [{ uid: "z", key: null, name: "Controlled area", type: "Radiation Area", layer: "zones", points: [[0, 0], [10, 0], [10, 10]] }],
  routes: [], tickets: [], activities: [], in_racks: 3, held: { srv: "rk" },
} as unknown as PlanLayersView;

describe("a plan's layers", () => {
  it("starts from the plan's defaults, then from what the person chose", () => {
    expect([...initialLayers(view, {})]).toEqual(["places", "racks"]);
    expect([...initialLayers(view, { devices: true, racks: false })]).toEqual(["places", "devices"]);
  });

  it("draws only the layers that are on; a rack is one square that opens its elevation", () => {
    const open = vi.fn();
    const { pins, shapes } = drawn(view, new Set(["racks"]), new Set(), open, () => {});
    expect(pins.map((p) => p.id)).toEqual(["rk"]);
    expect(pins[0].square).toBe(true);
    expect(pins[0].label).toContain("3 units");
    expect(pins[0].badges).toEqual([]);                  // tickets off: no counter
    pins[0].onClick!();
    expect(open).toHaveBeenCalledWith(view.items[0]);
    expect(shapes).toEqual([]);
  });

  it("shows ticket counters and zones when asked, and a unit looked for is shown as its rack", () => {
    const { pins, shapes, wanted } = drawn(view, new Set(["tickets", "zones"]), new Set(["srv"]), () => {}, () => {});
    expect(pins.map((p) => [p.id, p.highlight])).toEqual([["rk", true]]);    // racks off, but the one looked for is shown
    expect(pins[0].badges![0].n).toBe(2);
    expect(shapes.map((s) => [s.id, s.closed, s.dashed])).toEqual([["z", true, true]]);
    expect([...wanted]).toEqual(["rk"]);
  });
});

describe("the tunnel", () => {
  const el = (hardware: Partial<TunnelElement["hardware"][number]>[]) => ({ hardware } as unknown as TunnelElement);
  it("says what each element's hardware is: none, without a room, placed, with open tickets", () => {
    expect(stateOf(el([]))).toBe("none");
    expect(stateOf(el([{ room: null, spot: null, tickets: [] }]))).toBe("unplaced");
    expect(stateOf(el([{ room: { uid: "r", key: null, name: "Hall", type: "Room" }, spot: null, tickets: [] }]))).toBe("placed");
    expect(stateOf(el([{ room: null, spot: null, tickets: [{ uid: "t", key: null, title: "x", state: "new" }] }]))).toBe("tickets");
  });

  it("keeps labels apart without moving them out of order", () => {
    expect(spreadOut([10, 12, 50, 11], 5)).toEqual([10, 20, 50, 15]);
  });
});
