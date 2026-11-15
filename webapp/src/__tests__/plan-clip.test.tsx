import { describe, expect, it } from "vitest";
import { clipLine, drawn, routeEnds } from "../pages/map/PlanLayersPage";
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

  it("is named along its longest stretch, and a dot marks where it arrives", () => {
    // In through the right wall, along a level run, up into a room: the name over the level run.
    expect(routeEnds([[220, 60], [150, 60], [150, 40]], "Cooling water main", box)).toEqual({
      tag: { x: 185, y: 60, text: "Cooling water main", direction: "center" }, end: [150, 40] });
    // Drawn from inside out through the top wall, upright: the name beside it, the dot where it starts.
    expect(routeEnds([[100, 80], [100, 20]], "Fibre", box)).toEqual({
      tag: { x: 100, y: 50, text: "Fibre", direction: "right" }, end: [100, 80] });
    // Across the building, wall to wall: named, no dot. Wholly inside: neither.
    expect(routeEnds([[20, 50], [220, 50]], "Feeder", box).end).toBeUndefined();
    expect(routeEnds([[30, 30], [60, 30]], "Inside", box)).toEqual({});
  });
});
