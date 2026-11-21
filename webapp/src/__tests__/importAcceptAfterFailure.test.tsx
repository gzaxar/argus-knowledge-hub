import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portabilityApi, workspacesApi } from "../api/client";
import type { ImportView, ReconciliationReport } from "../api/portabilityTypes";
import { ImportDetailPage } from "../pages/admin/portability/ImportDetail";
import { renderWith } from "../test/render";

vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ id: "imp-1" }),
}));
afterEach(() => vi.restoreAllMocks());

const base = {
  id: "imp-1", mode: "restore", source: { repository: "baltig-cloud", ref: "export/full/x" }, decisions: {},
  requested_by: "a@lnf.infn.it", approved_by: null, commit: "c0ffee", verification: {}, manifest: null, labels: {},
  checkpoints: { done: 50 }, reconciliation_passed: null, reconciliation_sha256: null, error: null,
  staging: null, created_at: null, legal_hold: false, legal_hold_reason: null, purged_at: null,
};

function mocks(view: unknown) {
  vi.spyOn(workspacesApi, "me").mockResolvedValue({ auth_type: "oidc", is_admin: true, email: "b@lnf.infn.it" } as never);
  vi.spyOn(portabilityApi, "getImport").mockResolvedValue(view as ImportView);
  vi.spyOn(portabilityApi, "config").mockResolvedValue({ policy: { profile: "trusted", retention_days: 1 } } as never);
  vi.spyOn(portabilityApi, "provenance").mockResolvedValue({ events: [] } as never);
  vi.spyOn(portabilityApi, "originChain").mockResolvedValue(null as never);
  vi.spyOn(portabilityApi, "jobs").mockResolvedValue([]);
}

describe("an archive of another release", () => {
  it("is flagged in the dry run, with the decision a click away", async () => {
    mocks({ ...base, state: "awaiting_approval", dry_run: { ready: true, families: {}, advice: [{
      code: "projections_from_another_release", archive_release: "1.35.120", this_release: "1.35.134",
      decision: { projections: "accept_rebuilt" }, message: "This archive was exported by release 1.35.120" }] } });
    const dry = vi.spyOn(portabilityApi, "dryRunJob").mockResolvedValue({ job: { id: "j", state: "queued", action: "dry-run" } } as never);
    renderWith(<ImportDetailPage />);
    expect(await screen.findByText(/exported by release 1.35.120/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Accept what this release rebuilds and run the dry run again/ }));
    await waitFor(() => expect(dry).toHaveBeenCalledWith("imp-1", expect.objectContaining({ projections: "accept_rebuilt" })));
  });

  it("after a failed reconciliation takes the decision and reconciles again without loading", async () => {
    mocks({ ...base, state: "failed", reconciliation_passed: false, dry_run: null, staging: { database: "stg_imp_1" } });
    const report = {
      passed: false, staged: true, accepted: null,
      families: { assets: { rows: 1, expected_rows: 1, sha256: "", expected_sha256: "", ok: false, mismatch_count: 156, mismatches: [] } },
      projections: { p_conflicts: { exported: 4, rebuilt: 9, ok: false } },
      invariants: { ok: true, acceptable: true, failing: [] },
    } as unknown as ReconciliationReport;
    vi.spyOn(portabilityApi, "reconciliation").mockResolvedValue({ report, sha256: "abc" } as never);
    const set = vi.spyOn(portabilityApi, "reconcileDecisions").mockResolvedValue({} as never);
    const job = vi.spyOn(portabilityApi, "importJob").mockResolvedValue({ job: { id: "j", state: "queued", action: "resume" } } as never);
    renderWith(<ImportDetailPage />);
    expect(await screen.findByRole("button", { name: /Reconcile again in staging/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Accept what this release rebuilds and reconcile again/ }));
    await waitFor(() => expect(job).toHaveBeenCalledWith("imp-1", "resume"));
    expect(set).toHaveBeenCalledWith("imp-1", { projections: "accept_rebuilt" });
  });
});
