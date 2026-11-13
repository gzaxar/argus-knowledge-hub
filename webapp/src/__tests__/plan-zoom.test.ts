import { describe, expect, it } from "vitest";
import { span } from "../components/PlanView";

describe("the plan's zoom around the records shown", () => {
  it("keeps at least half the plan each way, inside the plan", () => {
    expect(span(450, 530, 1000)).toEqual([240, 740]);    // one access point: half the plan around it
    expect(span(-40, 60, 1000)).toEqual([0, 500]);       // near an edge: moved inside
    expect(span(100, 900, 1000)).toEqual([100, 900]);    // already wide: as it is
    expect(span(-50, 1100, 1000)).toEqual([0, 1000]);    // wider than the plan: the plan
  });
});
