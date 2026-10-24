import { describe, expect, it } from "vitest";
import { groupActivities } from "../pages/Dashboard";

const occ = (id: string, series: string | null, title: string, overdue = true, status = "planned") =>
  ({ id, series_uid: series, title, overdue, status }) as never;

describe("the cockpit's activities", () => {
  it("shows one line a series, with how many of its occurrences are overdue", () => {
    const groups = groupActivities([
      occ("w1", "weekly", "Weekly restore test"), occ("w2", "weekly", "Weekly restore test"),
      occ("w3", "weekly", "Weekly restore test"), occ("once", null, "Replace fan", false, "in_progress"),
      occ("m1", "monthly", "UPS self-test"),
    ]);
    expect(groups.map((g) => [g.title, g.items.length, g.overdue, g.underWay])).toEqual([
      ["Replace fan", 1, 0, 1],
      ["Weekly restore test", 3, 3, 0],
      ["UPS self-test", 1, 1, 0],
    ]);
    // Every occurrence is still there to open.
    expect(groups[1].items.map((a: { id: string }) => a.id)).toEqual(["w1", "w2", "w3"]);
  });
});
