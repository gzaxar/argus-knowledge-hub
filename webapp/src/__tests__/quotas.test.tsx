import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { quotasApi, workspacesApi } from "../api/client";
import type { QuotasOverview, QuotaStatus } from "../api/types";
import { AdminQuotasPage } from "../pages/admin/Quotas";
import { QuotaBanner } from "../pages/workspace/Quotas";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const GiB = 2 ** 30;
const row = (key: string, label: string, unit: QuotaStatus["unit"], limit: number | null, used: number | null,
             level: QuotaStatus["level"] = "ok"): QuotaStatus =>
  ({ key, label, unit, what: "", limit, used, ratio: limit && used !== null ? used / limit : null, source: "default", level });

const overview: QuotasOverview = {
  quotas: [
    { key: "storage_bytes", label: "Storage", unit: "bytes", what: "files", builtin: 50 * GiB, default: 50 * GiB, scope: "workspace" },
    { key: "assets", label: "Records", unit: "count", what: "records", builtin: null, default: null, scope: "workspace" },
    { key: "imports_at_once", label: "Imports at once", unit: "count", what: "imports", builtin: 1, default: 1, scope: "installation" },
  ],
  workspaces: [{ id: "lnf", name: "LNF", overrides: {}, level: "warn",
                 quotas: [row("storage_bytes", "Storage", "bytes", 50 * GiB, 45 * GiB, "warn"), row("assets", "Records", "count", null, 9302)] }],
  installation: { imports_at_once: { limit: 1, used: 1, imports: ["imp-1"] } },
};

describe("quotas", () => {
  it("shows the defaults in GB, empty as unlimited, and saves them", async () => {
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ is_admin: true } as never);
    vi.spyOn(quotasApi, "all").mockResolvedValue(overview);
    const save = vi.spyOn(quotasApi, "setDefaults").mockResolvedValue({ quotas: overview.quotas });
    renderWith(<AdminQuotasPage />);
    const storage = await screen.findByLabelText("Default for Storage, in GB");
    expect(storage).toHaveValue("50");
    expect(screen.getByLabelText("Default for Records")).toHaveValue("");
    expect(screen.getByText(/a quota is near/)).toBeInTheDocument();
    fireEvent.change(storage, { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("Default for Records"), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save the defaults" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ storage_bytes: 20 * GiB, assets: 5000, imports_at_once: 1 }, []));
  });

  it("warns a workspace's administrators at 80% and says when one is reached", async () => {
    vi.spyOn(quotasApi, "workspace").mockResolvedValue({ workspace_id: "lnf", quotas: [
      row("storage_bytes", "Storage", "bytes", 50 * GiB, 45 * GiB, "warn"), row("assets", "Records", "count", 100, 100, "over")] });
    renderWith(<QuotaBanner workspaceId="lnf" />);
    expect(await screen.findByText(/A quota of this workspace is reached/)).toBeInTheDocument();
    expect(screen.getByText(/Records 100 of 100/)).toBeInTheDocument();
  });
});
