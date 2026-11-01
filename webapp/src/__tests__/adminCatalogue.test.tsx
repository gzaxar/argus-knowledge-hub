import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { catalogueCollectionsApi, directoryApi, glpiMatchesApi, rolesApi, systemCatalogueApi, workspacesApi } from "../api/client";
import type { MyWorkspace } from "../api/types";
import { AdminCataloguePage } from "../pages/admin/Catalogue";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const ws = (id: string, over: Partial<MyWorkspace> = {}) => ({ id, name: id, is_global: false, created_at: "",
  can_read: true, can_create: true, can_modify: true, can_delete: true, ...over }) as MyWorkspace;

const me = (admin: boolean, maintainer = admin) => vi.spyOn(workspacesApi, "me").mockResolvedValue({
  auth_type: "oidc", workspace_id: null, user_id: "u", email: "u@x", name: null, is_admin: admin,
  catalogue_maintainer: maintainer });

function collections() {
  vi.spyOn(catalogueCollectionsApi, "list").mockResolvedValue({ workspace_id: "acc", sources: [], collections: [], history: [] });
  vi.spyOn(catalogueCollectionsApi, "review").mockResolvedValue([]);
}

describe("Administration › Catalogue", () => {
  it("shows the catalogue workspace, what depends on it, its collections, and GLPI matching for a chosen workspace", async () => {
    vi.spyOn(systemCatalogueApi, "status").mockResolvedValue({
      designated: "acc", candidates: ["acc"], name: "Acceleratori-INFN",
      records: { "Product Model": 131, Vendor: 41 }, other_records: {}, not_shared: 0, shared_types: 144, own_types: 78,
      hanging: { btf: ["accelerator"], sparc: ["accelerator"] }, units: { euaps: 272 }, collections: {} });
    collections();
    me(false, true);                                       // a maintainer: no Maintainers section
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([ws("acc", { role: "catalogue" }), ws("it-services")]);
    const run = vi.spyOn(glpiMatchesApi, "run").mockResolvedValue({
      status: "ran", proposals: 1, exact: 1, near: 0, ambiguous: [], unmatched: [] });
    renderWith(<AdminCataloguePage />);

    expect(await screen.findByText("131 Product Models, 41 Vendors")).toBeInTheDocument();
    expect(screen.getByText("btf, sparc")).toBeInTheDocument();
    expect(screen.getByText("(euaps 272)")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Collections" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Catalogue collections" })).not.toBeInTheDocument();   // embedded

    const pick = await screen.findByLabelText("Workspace with GLPI devices");
    expect(screen.queryByRole("option", { name: /^acc / })).not.toBeInTheDocument();    // not the catalogue itself
    fireEvent.change(pick, { target: { value: "it-services" } });
    fireEvent.click(await screen.findByRole("button", { name: "Propose models" }));
    await waitFor(() => expect(run).toHaveBeenCalledWith("it-services"));
    expect(screen.queryByRole("region", { name: "Maintainers" })).not.toBeInTheDocument();
  });

  it("without a catalogue, offers to designate one", async () => {
    const status = vi.spyOn(systemCatalogueApi, "status").mockResolvedValue({ designated: null, candidates: ["acc"] });
    const designate = vi.spyOn(systemCatalogueApi, "designate").mockResolvedValue({
      designated: "acc", candidates: ["acc"], name: "Acc", records: {}, units: {}, hanging: {}, collections: {} });
    collections();
    me(true);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    vi.spyOn(rolesApi, "listBindings").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "listUsers").mockResolvedValue([]);
    vi.spyOn(directoryApi, "groups").mockResolvedValue([]);
    renderWith(<AdminCataloguePage />);

    expect(await screen.findByText("No catalogue workspace")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Collections" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Workspace to designate"), { target: { value: "acc" } });
    status.mockResolvedValue({ designated: "acc", candidates: ["acc"], name: "Acc", records: {}, units: {}, hanging: {}, collections: {} });
    fireEvent.click(screen.getByRole("button", { name: "Designate" }));
    await waitFor(() => expect(designate).toHaveBeenCalledWith("acc"));
    expect(await screen.findByRole("region", { name: "Collections" })).toBeInTheDocument();
  });

  it("administrators add and remove the catalogue's maintainers", async () => {
    vi.spyOn(systemCatalogueApi, "status").mockResolvedValue({ designated: "acc", candidates: ["acc"], name: "Acc",
      records: {}, units: {}, hanging: {}, collections: {} });
    collections();
    me(true);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    vi.spyOn(rolesApi, "listBindings").mockResolvedValue([
      { id: 7, workspace_id: "acc", subject_type: "user", subject_id: "p1", subject_label: "Paola", subject_active: true,
        role_id: "curator", role_name: "Curator", created_at: null },
      { id: 8, workspace_id: "acc", subject_type: "user", subject_id: "p2", subject_label: "Reader", subject_active: true,
        role_id: "viewer", role_name: "Viewer", created_at: null }]);
    vi.spyOn(workspacesApi, "listUsers").mockResolvedValue([
      { id: "p3", email: "luca@x", name: "Luca", is_admin: false, created_at: "", last_login_at: null } as never]);
    vi.spyOn(directoryApi, "groups").mockResolvedValue([]);
    const add = vi.spyOn(rolesApi, "createBinding").mockResolvedValue({} as never);
    const del = vi.spyOn(rolesApi, "deleteBinding").mockResolvedValue(undefined);
    renderWith(<AdminCataloguePage />);

    const section = await screen.findByRole("region", { name: "Maintainers" });
    expect(await within(section).findByText("Paola")).toBeInTheDocument();
    expect(within(section).queryByText("Reader")).not.toBeInTheDocument();      // a reader is not a maintainer
    fireEvent.change(within(section).getByLabelText("Who"), { target: { value: "p3" } });
    fireEvent.click(within(section).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("acc", { subject_type: "user", subject_id: "p3", role_id: "curator" }));
    fireEvent.click(within(section).getByRole("button", { name: "Remove Paola" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("acc", 7));
  });

  it("administrators rename the catalogue and see the records that do not belong in it", async () => {
    vi.spyOn(systemCatalogueApi, "status").mockResolvedValue({ designated: "accelerator-infn", candidates: [],
      name: "Acceleratori-INFN", records: { Area: 1, "Product Model": 131, Vendor: 41 }, other_records: { Area: 1 },
      other_record_list: [{ uid: "a1", key: "ACC-1", name: "Hall", type: "Area" }],
      not_shared: 0, units: {}, hanging: {}, collections: {} });
    collections();
    me(true);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    vi.spyOn(rolesApi, "listBindings").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "listUsers").mockResolvedValue([]);
    vi.spyOn(directoryApi, "groups").mockResolvedValue([]);
    const update = vi.spyOn(workspacesApi, "update").mockResolvedValue({} as never);
    renderWith(<AdminCataloguePage />);

    expect(await screen.findByText(/ACC-1 “Hall”/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "open the catalogue as a workspace" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Catalogue name"), { target: { value: "ARGUS catalogue" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("accelerator-infn", { name: "ARGUS catalogue" }));
  });
});
