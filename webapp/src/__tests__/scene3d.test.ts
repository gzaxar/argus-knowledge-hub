import { describe, expect, it } from "vitest";
import type { PlanSceneView } from "../api/client";
import { RACK, U_M, anchors, arc, drawnRelations, relationColour, unitBox } from "../lib/scene3d";

const v = {
  metres_per_px: 0.1,
  items: [
    { uid: "rk", key: "RK", name: "Rack", type: "Rack", x: 100, y: 50, layer: "racks", tickets: 0, activities: 0 },
    { uid: "ups", key: "UPS", name: "UPS", type: "UPS", x: 300, y: 50, layer: "fixed", tickets: 0, activities: 0 },
  ],
  units: [
    { uid: "srv", key: null, name: "Server", type: "Server", rack_uid: "rk", start_u: 10, height_u: 2, face: "front", kind: "device" },
    { uid: "pdu", key: null, name: "PDU", type: "PDU", rack_uid: "rk", start_u: null, height_u: 0, face: "rear", kind: "zero_u" },
  ],
  outlines: [], routes: [],
  relations: [{ from: "ups", to: "srv", type: "powers" }, { from: "srv", to: "ups", type: "monitors" }, { from: "ups", to: "rk", type: "powers" }],
} as unknown as PlanSceneView;

describe("the 3D view's geometry", () => {
  it("puts a unit at its units in its rack, on its face", () => {
    const b = unitBox(v.units[0]);
    expect(b.h).toBeCloseTo(2 * U_M);
    expect(b.y).toBeCloseTo(RACK.base + 9 * U_M + U_M);      // U10–U11: nine units up, then half its height
    expect(b.dz).toBeLessThan(0);                             // the front
    expect(unitBox(v.units[1]).dz).toBeGreaterThan(0);        // a 0U strip on the rear
  });

  it("anchors relations on records in metres, and units inside their rack", () => {
    const at = anchors(v);
    expect(at.get("ups")![0]).toBeCloseTo(30);
    const srv = at.get("srv")!;
    expect(srv[0]).toBeCloseTo(10);
    expect(srv[2]).toBeLessThan(5);
  });

  it("draws an arc between the ends, higher when they are farther apart", () => {
    const near = arc([0, 1, 0], [1, 1, 0]);
    const far = arc([0, 1, 0], [20, 1, 0]);
    expect(near[0]).toEqual([0, 1, 0]);
    expect(far[far.length - 1]).toEqual([20, 1, 0]);
    expect(Math.max(...far.map((p) => p[1]))).toBeGreaterThan(Math.max(...near.map((p) => p[1])));
  });

  it("keeps the relation types chosen, and with a record selected only its own", () => {
    expect(drawnRelations(v, new Set(["powers"]), null, true)).toHaveLength(2);
    expect(drawnRelations(v, new Set(["powers", "monitors"]), "srv", true)).toHaveLength(2);
    expect(drawnRelations(v, new Set(["powers", "monitors"]), "srv", false)).toHaveLength(3);
    expect(relationColour("powers")).toBe(relationColour("powers"));
  });
});
