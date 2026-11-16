import { describe, expect, it } from "vitest";
import type { MapFeature } from "../api/client";
import { findOnMap, siteOf } from "../pages/map/MapPage";

const f = (uid: string, name: string, key: string, type: string, role: "position" | "outline" = "position"): MapFeature => ({
  type: "Feature", id: `${uid}-${role}`, geometry: { type: "Point", coordinates: [11.95, 44.62] } as never,
  properties: { uid, key, name, type, workspace_id: "w", status: "Active", map_layer: null, role, base_m: null,
                top_m: null, accuracy_m: null, source: "manual" },
});

describe("the map's workspaces and search", () => {
  it("knows a workspace's site: itself for a site, its site for a facility, none otherwise", () => {
    expect(siteOf({ id: "lnf", role: "site" })).toBe("lnf");
    expect(siteOf({ id: "sparc", site_id: "lnf" })).toBe("lnf");
    expect(siteOf({ id: "alone" })).toBeNull();
  });

  it("finds a located record by name, key or type, once, the names that start with it first", () => {
    const all = [f("b", "Accelerator Building", "VL-BLD-ACC", "Building"),
                 f("b", "Accelerator Building", "VL-BLD-ACC", "Building", "outline"),
                 f("r", "Rack A12-1", "VL-RK-A12-1", "Rack"), f("k", "Klystron K-2", "VL-KLY-2", "Klystron"),
                 f("s", "Shielded accelerator hall", "VL-HALL", "Building")];
    expect(findOnMap(all, "accel").map((x) => x.properties.uid)).toEqual(["b", "s"]);
    expect(findOnMap(all, "vl-rk").map((x) => x.properties.uid)).toEqual(["r"]);
    expect(findOnMap(all, "klystron").map((x) => x.properties.uid)).toEqual(["k"]);
    expect(findOnMap(all, "  ")).toEqual([]);
  });
});
