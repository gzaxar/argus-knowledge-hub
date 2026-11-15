import { describe, expect, it } from "vitest";
import { clipLine, drawn } from "../pages/map/PlanLayersPage";
import type { PlanLayersView } from "../api/client";

describe("a cable on a plan drawn by ARGUS", () => {
  const box: [number, number, number, number] = [20, 20, 200, 100];

  it("is drawn from the wall it comes through, inside the building only", () => {
    expect(clipLine([[0, 50], [100, 50]], box)).toEqual([[[20, 50], [100, 50]]]);
    expect(clipLine([[50, 0], [50, 200]], box)).toEqual([[[50, 20], [50, 120]]]);
    expect(clipLine([[0, 0], [10, 10]], box)).toEqual([]);                          // outside: nothing
    // In, out and in again: two pieces.
    expect(clipLine([[50, 50], [50, 200], [100, 200], [100, 50]], box)).toEqual([
      [[50, 50], [50, 120]], [[100, 120], [100, 50]]]);
    // Wholly inside: as it was.
    expect(clipLine([[30, 30], [60, 30], [60, 90]], box)).toEqual([[[30, 30], [60, 30], [60, 90]]]);
  });

  it("is clipped to the building's walls when the drawing knows them", () => {
    const v = {
      uid: "pl", width_px: 300, height_px: 200, building: box, items: [], outlines: [], held: {},
      routes: [{ uid: "c1", key: "C1", name: "Fibre", type: "Cable", layer: "paths", points: [[0, 50], [300, 50]] }],
      layers: [], tickets: [], activities: [], in_racks: 0,
    } as unknown as PlanLayersView;
    const { shapes } = drawn(v, new Set(["paths"]), new Set(), () => {}, () => {});
    expect(shapes.map((s) => s.points)).toEqual([[[20, 50], [220, 50]]]);
  });
});
