import { fireEvent, screen } from "@testing-library/react";
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

const failed = {
  id: "imp-1", mode: "clone", state: "failed", source: { repository: "baltig-cloud", ref: "export/full/x" }, decisions: {},
  requested_by: "a@lnf.infn.it", approved_by: "a@lnf.infn.it", commit: "c0ffee", verification: {}, manifest: null, labels: {},
  checkpoints: { done: 10 }, reconciliation_passed: false, reconciliation_sha256: null, dry_run: null, error: null,
  staging: null, created_at: null, legal_hold: false, legal_hold_reason: null, purged_at: null,
} as unknown as ImportView;

const report = {
  passed: false, export_id: "exp-1",
  families: {
    groups: { rows: 6, expected_rows: 6, sha256: "", expected_sha256: "", ok: true, mismatch_count: 0, mismatches: [] },
    assets: { rows: 9302, expected_rows: 9302, sha256: "", expected_sha256: "", ok: false, mismatch_count: 157,
              mismatches: [{ key: "epik8s-015a", missing: false, fields: ["attributes.argus_source"] }] },
  },
  projections: { p_conflicts: { exported: 4, rebuilt: 9, ok: false, only_in_export: [], only_rebuilt: [{ conflict_id: "37816c" }] } },
  invariants: { ok: false, exported_ok: null, acceptable: false, failing: ["uniqueness"],
                examples: { uniqueness: [{ message: "qrcode DEMO-QR-QF-01 is held by 2 records" }] } },
  accepted: null,
} as unknown as ReconciliationReport;

describe("a failed reconciliation", () => {
  it("folds the details away and explains each red item when clicked", async () => {
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ auth_type: "oidc", is_admin: true } as never);
    vi.spyOn(portabilityApi, "getImport").mockResolvedValue(failed);
    vi.spyOn(portabilityApi, "config").mockResolvedValue({ policy: { profile: "trusted", retention_days: 1 } } as never);
    vi.spyOn(portabilityApi, "reconciliation").mockResolvedValue({ report, sha256: "abc" } as never);
    vi.spyOn(portabilityApi, "provenance").mockResolvedValue({ events: [] } as never);
    vi.spyOn(portabilityApi, "originChain").mockResolvedValue(null as never);
    vi.spyOn(portabilityApi, "jobs").mockResolvedValue([]);
    renderWith(<ImportDetailPage />);

    const assets = await screen.findByRole("button", { name: /assets: 157 row\(s\) differ/ });
    expect(screen.queryByText("Authoritative, row by row")).not.toBeInTheDocument();     // folded away
    expect(screen.queryByText("Source and signature")).not.toBeInTheDocument();

    fireEvent.click(assets);
    expect(screen.getByText(/fields the ledger projects onto a record/)).toBeInTheDocument();
    expect(screen.getByText(/accept what this release rebuilds/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /invariant uniqueness fails/ }));
    expect(screen.getByText(/held by one record only/)).toBeInTheDocument();
    expect(screen.getByText(/DEMO-QR-QF-01/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Show details: signature, every family/ }));
    expect(screen.getByText("Authoritative, row by row")).toBeInTheDocument();
  });
});
