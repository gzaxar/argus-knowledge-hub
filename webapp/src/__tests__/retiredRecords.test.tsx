import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assetsApi, schemasApi, workspacesApi } from "../api/client";
import type { Asset } from "../api/types";
import { isLive } from "../lib/liveRecords";
import { AssetSearch } from "../pages/assets/Search";
import { ImportReports } from "../pages/beam/BeamModelEditor";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const record = (name: string, extra: Partial<Asset> = {}) => ({
  uid: name, workspace_id: "btf", schema_uid: "s", key: `btf/${name}`, name, type: "Dipole", avatar_icon_uid: null,
  attributes: {}, inbound_relations: [], outbound_relations: [], is_global: false, record_status: "Active",
  deleted_at: null, created_at: "2026-11-06T00:00:00Z", updated_at: "2026-11-06T00:00:00Z", ...extra,
}) as Asset;

describe("records no longer in use", () => {
  it("are not live when deleted, retired or merged", () => {
    expect(isLive(record("a"))).toBe(true);
    expect(isLive(record("a", { record_status: "Provisional" }))).toBe(true);
    expect(isLive(record("a", { record_status: "Retired" }))).toBe(false);
    expect(isLive(record("a", { record_status: "Merged" }))).toBe(false);
    expect(isLive(record("a", { deleted_at: "2026-11-06T00:00:00Z" }))).toBe(false);
  });

  it("stay off the Assets page until asked for, and deleted ones never appear", async () => {
    vi.spyOn(assetsApi, "list").mockResolvedValue([
      record("DHSA11"), record("DIPA11", { record_status: "Retired" }),
      record("GONE01", { deleted_at: "2026-11-06T00:00:00Z" }),
    ]);
    vi.spyOn(schemasApi, "list").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    renderWith(<AssetSearch />);
    expect(await screen.findByText("DHSA11")).toBeInTheDocument();
    expect(screen.queryByText("DIPA11")).not.toBeInTheDocument();
    expect(screen.queryByText("GONE01")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show retired"));
    expect(await screen.findByText("DIPA11")).toBeInTheDocument();
    expect(screen.getByText("Retired")).toBeInTheDocument();
    expect(screen.queryByText("GONE01")).not.toBeInTheDocument();
  });

  it("a save the ledger holds is not reported as done", () => {
    const report = { model: "accumulator_pa", systems: 1, paths: 1, elements: 59, datasets: 1, values: 40,
                     awaiting_policy: false };
    renderWith(<ImportReports reports={[{ ...report, state: "held" }]} />);
    expect(screen.getByText(/not applied yet/)).toBeInTheDocument();
    expect(screen.queryByText(/59 elements/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review queue/ })).toHaveAttribute("href", "/review");
  });
});
