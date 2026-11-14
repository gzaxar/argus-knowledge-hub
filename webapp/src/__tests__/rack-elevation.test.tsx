import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RackElevationView } from "../api/client";
import { RackElevation, spanOf } from "../components/RackElevation";
import { renderWith } from "../test/render";

const view: RackElevationView = {
  rack: { uid: "r", key: "R-1", name: "Rack 1", units: 10, workspace_id: "ws" },
  mountings: [
    { uid: "m1", kind: "device", start_u: 3, height_u: 2, top_u: 4, face: "front", shelf_uid: null, label: null, note: null,
      source: "manual", evidence: null, asset: { uid: "a1", key: "SRV-1", name: "Server one", type: "Server" }, since: "2026-11-14T10:00:00Z" },
    { uid: "m2", kind: "reserved", start_u: 8, height_u: 2, top_u: 9, face: "both", shelf_uid: null, label: "Kept for a switch", note: null,
      source: "manual", evidence: null, asset: null, since: "2026-11-14T10:00:00Z" },
    { uid: "m3", kind: "zero_u", start_u: null, height_u: 0, top_u: null, face: "rear", shelf_uid: null, label: null, note: null,
      source: "manual", evidence: null, asset: { uid: "a2", key: "PDU-1", name: "PDU left", type: "Equipment" }, since: "2026-11-14T10:00:00Z" },
  ],
  free: { front: [], rear: [] },
  used_units: { front: 4, rear: 2 },
  problems: [],
};

describe("a rack elevation", () => {
  it("draws each face with what is on it and lists what takes no unit", () => {
    renderWith(<RackElevation view={view} />, {});
    expect(screen.getByRole("img", { name: /Rack 1, front: Server one U3–U4; Kept for a switch U8–U9/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Rack 1, rear: Kept for a switch U8–U9$/ })).toBeInTheDocument();
    expect(screen.getByText(/PDU left \(rear\)/)).toBeInTheDocument();
    expect(screen.getByText("4 of 10 U used")).toBeInTheDocument();
  });

  it("says where a mounting is in words", () => {
    expect(spanOf(view.mountings[0])).toBe("U3–U4");
    expect(spanOf(view.mountings[2])).toBe("0U");
  });

  it("opens what is clicked", () => {
    const pick = vi.fn();
    renderWith(<RackElevation view={view} onSelect={pick} />, {});
    screen.getAllByTitle(/Server one/)[0].click();
    expect(pick).toHaveBeenCalledWith(expect.objectContaining({ uid: "m1" }));
  });
});
