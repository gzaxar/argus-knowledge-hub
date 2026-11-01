import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { catalogueCollectionsApi, workspacesApi, type CatalogueBrowse } from "../api/client";
import { ProductCataloguePage } from "../pages/catalogue/ProductCatalogue";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const browse: CatalogueBrowse = {
  workspace_id: "cat", total: 2,
  models: [
    { uid: "m1", key: "PM-1", name: "NPort 5450", vendor: "Moxa", vendor_ref: null, model_code: "NPort 5450",
      device_class: "serial server", catalogue_id: "moxa/nport-5450", collection: "it-devices", version: "0.1.1",
      status: "catalogue", review: false, units: 4, domains: ["it"] },
    { uid: "m2", key: "PM-2", name: "PKR 251", vendor: "Pfeiffer", vendor_ref: null, model_code: "PKR 251",
      device_class: "vacuum gauge", catalogue_id: null, collection: null, version: null, status: "local",
      review: false, units: 17, domains: ["local"] },
  ] as never,
  facets: { device_class: {}, vendor: {}, collection: {}, status: {}, domain: { it: 1, local: 1 } },
  domain_names: { it: "IT", local: "Made here (local)" },
  navigator: [
    { domain: "it", name: "IT", count: 1, classes: [
      { device_class: "serial server", count: 1, vendors: [{ vendor: "Moxa", count: 1 }] }] },
    { domain: "local", name: "Made here (local)", count: 1, classes: [
      { device_class: "vacuum gauge", count: 1, vendors: [{ vendor: "Pfeiffer", count: 1 }] }] },
  ],
};

describe("the model navigator", () => {
  it("browses domain › device class › vendor, filtering the list", async () => {
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ auth_type: "oidc", workspace_id: null, user_id: "u", email: "u",
                                                      name: null, is_admin: false });
    const models = vi.spyOn(catalogueCollectionsApi, "models").mockResolvedValue(browse);
    renderWith(<ProductCataloguePage />);
    const nav = await screen.findByRole("navigation", { name: "Models by domain" });
    expect(within(nav).getByRole("button", { name: /^IT\s*1$/ })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /^Made here \(local\)/ })).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole("button", { name: /^IT\s*1$/ }));
    await waitFor(() => expect(models).toHaveBeenLastCalledWith(expect.objectContaining({ domain: "it", device_class: "", vendor: "" })));
    fireEvent.click(await within(nav).findByRole("button", { name: /serial server/ }));
    await waitFor(() => expect(models).toHaveBeenLastCalledWith(expect.objectContaining({ domain: "it", device_class: "serial server" })));
    fireEvent.click(await within(nav).findByRole("button", { name: /Moxa/ }));
    await waitFor(() => expect(models).toHaveBeenLastCalledWith(expect.objectContaining({ domain: "it", device_class: "serial server", vendor: "Moxa" })));
    expect(screen.getByLabelText("Domain")).toHaveValue("it");
    fireEvent.click(within(nav).getByRole("button", { name: "Every model" }));
    // Back to the first question (answered from the cache): every filter cleared.
    await waitFor(() => expect(screen.getByLabelText("Domain")).toHaveValue(""));
    expect(screen.getByLabelText("Device class")).toHaveValue("");
    expect(screen.getByLabelText("Vendor")).toHaveValue("");
  });
});
