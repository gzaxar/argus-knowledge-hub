import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sitesApi, transfersApi, workspacesApi, type TransferPreview } from "../api/client";
import type { MyWorkspace } from "../api/types";
import { SiteSharing } from "../components/IndoorCard";
import { TransferItemAction } from "../components/TransferItemAction";
import { AdminWorkspaces } from "../pages/admin/Workspaces";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const ws = (id: string, over: Partial<MyWorkspace> = {}) => ({ id, name: id.toUpperCase(), is_global: false,
  created_at: "2026-11-01", can_read: true, can_create: true, can_modify: true, can_delete: true, ...over }) as MyWorkspace;

describe("sites on Administration › Workspaces", () => {
  it("shows the site and its facilities, and previews a facility leaving it", async () => {
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([
      ws("lnf", { role: "site" }), ws("sparc", { site_id: "lnf" }), ws("btf", { site_id: "lnf" }), ws("other")]);
    const setSite = vi.spyOn(sitesApi, "setSite")
      .mockResolvedValueOnce({ workspace_id: "sparc", site_id: "lnf", preview: true, would_end: [
        { workspace_id: "sparc", record: { uid: "p", key: "SP-1", name: "SPARC pump" }, place_uid: "h", plan_uid: "pl" }] })
      .mockResolvedValueOnce({ workspace_id: "sparc", site_id: null, ended: ["x"] });
    const setRole = vi.spyOn(sitesApi, "setRole").mockResolvedValue({ workspace_id: "other", role: "site", ended: [] });
    renderWith(<AdminWorkspaces />);

    expect(await screen.findByText("Site", { selector: "span" })).toBeInTheDocument();      // LNF's badge
    expect(screen.getByText("2 facilities")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop being a site" })).toBeDisabled();   // facilities are at it
    fireEvent.change(screen.getByLabelText("Site of SPARC"), { target: { value: "" } });
    expect(await screen.findByText(/ends 1 placement of its records/)).toHaveTextContent("SPARC pump");
    fireEvent.click(screen.getByRole("button", { name: "Leave the site" }));
    await waitFor(() => expect(setSite).toHaveBeenLastCalledWith("sparc", null, true));
    const other = screen.getByLabelText("Site of OTHER").closest("div")!;
    fireEvent.click(within(other).getByRole("button", { name: "Make it a site" }));
    await waitFor(() => expect(setRole).toHaveBeenCalledWith("other", true));
  });
});

describe("a site's place, shared with the facilities", () => {
  it("previews what withholding it ends, then withholds it", async () => {
    vi.spyOn(sitesApi, "sharing").mockResolvedValue({ uid: "b", site: "lnf", facilities: ["sparc", "btf"], shared: true,
                                                      withheld: false, withheld_by: null, inside: 2 });
    const set = vi.spyOn(sitesApi, "setSharing")
      .mockResolvedValueOnce({ uid: "b", site: "lnf", facilities: ["sparc", "btf"], shared: true, withheld: false,
                               withheld_by: null, inside: 2, preview: true, would_withhold: 3, would_end: [
          { workspace_id: "sparc", record: { uid: "p1", key: "S1", name: "SPARC pump" }, place_uid: "h", plan_uid: null },
          { workspace_id: "btf", record: { uid: "p2", key: "B1", name: "BTF pump" }, place_uid: "h", plan_uid: null }] })
      .mockResolvedValueOnce({ uid: "b", site: "lnf", facilities: ["sparc", "btf"], shared: false, withheld: true,
                               withheld_by: null, inside: 2, ended: ["a", "b"] });
    renderWith(<SiteSharing uid="b" />);

    expect(await screen.findByText(/sparc, btf see it and the 2 places inside it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop sharing it" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Stops sharing 3 places");
    expect(alert).toHaveTextContent("sparc: SPARC pump");
    expect(alert).toHaveTextContent("btf: BTF pump");
    expect(set).toHaveBeenLastCalledWith("b", false, false);                 // nothing changed yet
    fireEvent.click(within(alert).getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith("b", false, true));
  });

  it("is not shown for a place that is not a site's", async () => {
    vi.spyOn(sitesApi, "sharing").mockRejectedValue(new Error("not a site"));
    const { container } = renderWith(<SiteSharing uid="b" />);
    await waitFor(() => expect(sitesApi.sharing).toHaveBeenCalled());
    expect(container).not.toHaveTextContent("Shared with the facilities");
  });
});

describe("moving a record", () => {
  it("is previewed first, with its reconciliation report", async () => {
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([ws("lnf", { role: "site" }), ws("catalogue")]);
    const report: TransferPreview = {
      source: "catalogue", target: "lnf", mode: "move",
      records: [{ uid: "e2", key: "ACC-ARE-1", name: "Edificio 2", type: "Area", is_global: true, site_shared_after: true }],
      indoors: { levels: [{ uid: "l", place_uid: "e2", name: "Ground floor" }],
                 plans: [{ uid: "p", place_uid: "e2", name: "Ground floor", files_present: true, placed_on_map: true, residual_m: 0.4 }] },
      placements: [], placed_inside: [{ record: { uid: "s", key: "S1", name: "SPARC pump", workspace_id: "sparc" }, keeps_placement: true, why: null }],
      references: [{ kind: "attribute", attributes: ["installed_in"], to: "e2", resolves_after: true, resolves_if_not_global: false, why: null,
                     from: { uid: "x", key: "X1", name: "Pump elsewhere", workspace_id: "euaps" } }],
      labels_carried: 1, problems: [], clean: true,
    };
    const preview = vi.spyOn(transfersApi, "preview").mockResolvedValue(report);
    const create = vi.spyOn(transfersApi, "create").mockResolvedValue({ uid: "job" } as never);
    renderWith(<TransferItemAction kind="asset" uid="e2" />, { cache: { '["me"]': { workspace_id: "catalogue" } } });

    fireEvent.click(screen.getByRole("button", { name: "Copy/Move…" }));
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "move" } });
    const target = await screen.findByRole("option", { name: /LNF/ });
    fireEvent.change(target.closest("select")!, { target: { value: "lnf" } });
    expect(screen.getByRole("button", { name: "Move" })).toBeDisabled();          // not before the preview
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const shown = await screen.findByRole("region", { name: "Transfer report" });
    expect(preview).toHaveBeenCalledWith(expect.objectContaining({ mode: "move", target_workspace_id: "lnf", asset_uids: ["e2"] }));
    expect(shown).toHaveTextContent("Nothing would break.");
    expect(shown).toHaveTextContent("same ids and keys");
    expect(shown).toHaveTextContent("SPARC pump (sparc) — stays placed");
    expect(shown).toHaveTextContent("If they stopped being global, Pump elsewhere (euaps) would no longer reach them.");
    fireEvent.click(screen.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
  });
});
