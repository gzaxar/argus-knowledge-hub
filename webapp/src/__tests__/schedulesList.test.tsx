import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portabilityApi } from "../api/client";
import type { PortabilitySchedule } from "../api/portabilityTypes";
import { SchedulesList } from "../pages/admin/portability/Schedules";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const schedule: PortabilitySchedule = {
  id: "sch-1", source_export_id: "exp-20261014-6698e464", chain: "incremental", every_minutes: 1440,
  skip_unchanged: true, enabled: true, mode: "full", workspaces: [], repository: "baltig-infn-argus",
  next_run_at: "2026-11-04T15:53:46Z", running: false, last_run_at: "2026-11-03T15:53:46Z", last_outcome: "failed",
  last_message: "the export this schedule continues is no longer published (revoked)", last_export_id: null,
  last_published_export_id: "exp-20261015-43fea760", failures: 1, runs: 5, created_by: "a", updated_by: null,
  created_at: null,
};

describe("periodic exports", () => {
  it("say why the last run failed, in the row", async () => {
    vi.spyOn(portabilityApi, "schedules").mockResolvedValue([schedule]);
    renderWith(<SchedulesList />);
    expect(await screen.findByRole("status")).toHaveTextContent("no longer published (revoked)");
  });
});
