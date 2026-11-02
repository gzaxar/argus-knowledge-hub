import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assetsApi, intakeApi, schemasApi, workspacesApi } from "../api/client";
import type { AppSchema, Asset, MyWorkspace } from "../api/types";
import { AssetForm } from "../pages/assets/Form";
import { AssetSearch } from "../pages/assets/Search";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const schema = (uid: string, name: string, ws = "lnf") =>
  ({ uid, name, workspace_id: ws, applies_to: "objects", is_concrete: true, is_global: false, attributes: [],
     parent_schema_uid: null, metadata: {}, version: 1, icon_uid: null, description: null, created_at: "", updated_at: "" }) as AppSchema;
const asset = (uid: string, name: string, ws: string, schemaUid: string, type = "Area") =>
  ({ uid, key: uid.toUpperCase(), name, workspace_id: ws, schema_uid: schemaUid, type, attributes: {}, is_global: false,
     created_at: "2026-11-02", updated_at: "2026-11-02" }) as unknown as Asset;
const me = { auth_type: "oidc", workspace_id: null, user_id: "u", email: "u", name: null, is_admin: true };
const ws = (id: string, over: Partial<MyWorkspace> = {}) => ({ id, name: id.toUpperCase(), is_global: false,
  created_at: "", can_read: true, can_create: true, can_modify: true, can_delete: true, ...over }) as MyWorkspace;

describe("a record moved here with another workspace's type", () => {
  it("has its type chosen again, the same-named one here suggested, and sends it", async () => {
    vi.spyOn(schemasApi, "list").mockResolvedValue([schema("lnf:area", "Area"), schema("lnf:building", "Building")]);
    vi.spyOn(assetsApi, "get").mockResolvedValue(asset("e6a", "Edificio 6a", "lnf", "sparc:area"));
    vi.spyOn(intakeApi, "guide").mockResolvedValue({ kind: "asset", ready: false, checks: [], steps: [], next: null });
    const update = vi.spyOn(assetsApi, "update").mockResolvedValue(asset("e6a", "Edificio 6a", "lnf", "lnf:area"));
    renderWith(<Routes><Route path="/assets/:uid/edit" element={<AssetForm />} /></Routes>,
               { path: "/assets/e6a/edit", cache: { '["me"]': me } });
    expect(await screen.findByText(/belongs to the workspace it came from/)).toBeInTheDocument();
    const picker = screen.getByPlaceholderText(/Type to search/);
    expect(picker).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Save asset/ }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("e6a", expect.objectContaining({ schema_uid: "lnf:area" }), "lnf"));
  });

  it("keeps a usable type locked, and sends no type", async () => {
    vi.spyOn(schemasApi, "list").mockResolvedValue([schema("lnf:area", "Area")]);
    vi.spyOn(assetsApi, "get").mockResolvedValue(asset("e2", "Edificio 2", "lnf", "lnf:area"));
    vi.spyOn(intakeApi, "guide").mockResolvedValue({ kind: "asset", ready: false, checks: [], steps: [], next: null });
    const update = vi.spyOn(assetsApi, "update").mockResolvedValue(asset("e2", "Edificio 2", "lnf", "lnf:area"));
    renderWith(<Routes><Route path="/assets/:uid/edit" element={<AssetForm />} /></Routes>,
               { path: "/assets/e2/edit", cache: { '["me"]': me } });
    expect(await screen.findByDisplayValue("Edificio 2")).toBeInTheDocument();       // the record has loaded
    expect(screen.getByPlaceholderText(/Type to search/)).toBeDisabled();
    expect(screen.queryByText(/belongs to the workspace it came from/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Save asset/ }));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][1]).not.toHaveProperty("schema_uid");
  });
});

describe("a facility's asset list", () => {
  it("shows its own records and its site's places by default", async () => {
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([ws("sparc", { site_id: "lnf" }), ws("lnf", { role: "site" })]);
    vi.spyOn(schemasApi, "list").mockResolvedValue([schema("lnf:area", "Area")]);
    vi.spyOn(assetsApi, "list").mockResolvedValue([
      asset("mine", "SPARC pump", "sparc", "lnf:area", "Vacuum Pump"), asset("e6a", "Edificio 6a", "lnf", "lnf:area"),
      asset("pm", "Some model", "catalogue", "lnf:area", "Product Model")]);
    renderWith(<AssetSearch />, { cache: { '["me"]': { ...me, workspace_id: "sparc" } } });
    expect(await screen.findByText("Edificio 6a")).toBeInTheDocument();
    expect(screen.getByText("SPARC pump")).toBeInTheDocument();
    expect(screen.queryByText("Some model")).not.toBeInTheDocument();       // shared by the catalogue, not the site
    expect(screen.getByLabelText("Whose records")).toHaveValue("site");
    expect(screen.getByRole("option", { name: "This workspace + LNF's places" })).toBeInTheDocument();
  });
});
