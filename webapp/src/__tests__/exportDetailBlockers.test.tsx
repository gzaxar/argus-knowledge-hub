import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portabilityApi, workspacesApi } from "../api/client";
import type { ExportView } from "../api/portabilityTypes";
import { ExportDetailPage } from "../pages/admin/portability/ExportDetail";
import { renderWith } from "../test/render";

vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ id: "exp-1" }),
}));
afterEach(() => vi.restoreAllMocks());

const waiting = {
  id: "exp-1", mode: "incremental", state: "awaiting_approval", risk: "normal", workspaces: ["lnf"], classifications: [],
  base_export_id: "exp-0", destination: { repository: "git" }, decisions: {}, requested_by: "schedule", approved_by: null,
  analysis: {
    ready: false, warnings: [],
    policy: { profile: "trusted", retention_days: 1, blob_readers: ["text"], relaxations: [] },
    closure: { dependencies: [{ id: "claim_subject:missing", rule: "claim_subject", count: 54, examples: [], outcome: "external_reference", options: ["block", "external_reference"] }],
               automatic: [], unresolved: [], blocked: [] },
    blobs: { inspected: 3, secrets: [], needs_decision: [], excluded: [], ready: false, missing_count: 5541,
             missing: [{ family: "icons", key: "0049fa96", file: "0049fa96" }] },
  },
  watermark: null, manifest_sha256: null, git: {}, error: null, labels: { complete: false, selective: false, full: false, incremental: true, signed: false,
  encrypted: false, artifact_complete: false, evidence_only: false, git_published: false, verified: false, restorable: false },
  created_at: null, legal_hold: false,
  legal_hold_reason: null, purged_at: null,
} as unknown as ExportView;

describe("an export that is not ready", () => {
  it("says it is the missing files, not the settled dependencies, and analyses again on request", async () => {
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ auth_type: "oidc", is_admin: true } as never);
    vi.spyOn(portabilityApi, "getExport").mockResolvedValue(waiting);
    vi.spyOn(portabilityApi, "config").mockResolvedValue({ policy: { profile: "trusted", retention_days: 1, blob_readers: [],
      relaxations: [] } } as never);
    vi.spyOn(portabilityApi, "manifest").mockResolvedValue(null as never);
    const again = vi.spyOn(portabilityApi, "decideExport").mockResolvedValue({ ...waiting, analysis: { ...waiting.analysis, ready: true } });
    renderWith(<ExportDetailPage />);
    expect(await screen.findByText(/5541 attachment file\(s\) are missing from storage \(listed/)).toBeInTheDocument();
    expect(screen.queryByText(/need an outcome/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Analyse again" }));
    await waitFor(() => expect(again).toHaveBeenCalledWith("exp-1", {}));
  });
});
