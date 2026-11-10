import { oneVendorField } from "../lib/schemaAttributes";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, catalogueCollectionsApi } from "../api/client";
import type { SchemaAttribute } from "../api/types";
import { AttributeFields, blocks, orderedFields } from "../components/AttributeFields";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const f = (key: string, name: string, extra: Partial<SchemaAttribute> = {}) => ({ key, name, type: "string", ...extra }) as SchemaAttribute;
const ATTRS = [
  f("argus_owner", "Owning service"),
  f("pbs_code", "PBS code", { group: "PBS" }), f("pbs_area", "PBS area", { group: "PBS", description: "The area segment of the PBS code" }),
  f("manufacturer", "Manufacturer (as recorded)", { group: "recorded" }), f("model", "Model (as recorded)", { group: "recorded" }),
  f("serial", "Serial number"),
  f("product_model", "Product model", { type: "reference", referenceType: "Product Model", referenceSchemaUid: "pm" }),
  f("argus_location", "Located in"),
];

describe("a record's fields on a form", () => {
  it("puts what was recorded about the model after the Product model, and groups consecutive fields", () => {
    const keys = orderedFields(ATTRS).map((a) => a.key);
    expect(keys).toEqual(["argus_owner", "pbs_code", "pbs_area", "serial", "product_model", "manufacturer", "model", "argus_location"]);
    expect(blocks(orderedFields(ATTRS)).map((b) => b.group)).toEqual([null, "PBS", null, "recorded", null]);
  });

  it("folds an empty group", () => {
    renderWith(<AttributeFields attrs={ATTRS} values={{}} onChange={() => {}} />);
    const pbs = screen.getByText("Product breakdown (PBS)").closest("details")!;
    expect(pbs).not.toHaveAttribute("open");
    expect(screen.getAllByText(/2 fields, empty/)).toHaveLength(2);
    expect(screen.getByText("The area segment of the PBS code")).toBeInTheDocument();      // described
  });

  it("opens a group with a value, and folds what was recorded once a model is chosen", () => {
    renderWith(<AttributeFields attrs={ATTRS} values={{ pbs_area: "LINAC", manufacturer: "MOXA", product_model: "m1" }}
                                onChange={() => {}} />);
    expect(screen.getByText("Product breakdown (PBS)").closest("details")).toHaveAttribute("open");
    expect(screen.getAllByText(/1 of 2 filled/)).toHaveLength(2);
    expect(screen.getByText(/As recorded/).closest("details")).not.toHaveAttribute("open");   // a model is chosen
  });
});

describe("adding a library model", () => {
  it("says why it could not be added", async () => {
    vi.spyOn(catalogueCollectionsApi, "searchModels").mockResolvedValue({ installed: [], more: false, library: [
      { catalogue_id: "moxa/nport-5650-8", name: "Moxa NPort 5650-8", vendor: "Moxa", model_code: "NPort 5650-8",
        part_number: null, collection: "it-devices", source: "netbox" }] });
    vi.spyOn(catalogueCollectionsApi, "installOne").mockRejectedValue(new ApiError(422, { detail: {
      error: "it-devices needs the package it (>=1.1,<2), and accelerator-infn does not have it", code: "catalogue_install_one" } }));
    renderWith(<AttributeFields attrs={[ATTRS[6]]} values={{}} onChange={() => {}} />);
    fireEvent.change(screen.getByLabelText("Search a product model"), { target: { value: "5650" } });
    fireEvent.click(await screen.findByRole("option", { name: /NPort 5650-8/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("needs the package it");
  });
});

describe("a Product Model's one vendor field", () => {
  const defs = [{ key: "vendor", name: "Vendor", type: "string" }, { key: "vendor_ref", name: "Supplied by", type: "reference" },
                { key: "model_code", name: "Model code", type: "string" }] as SchemaAttribute[];
  const names = (a: SchemaAttribute[]) => a.map((x) => `${x.key}:${x.name}`);

  it("offers only the reference, called Vendor, on a form", () => {
    expect(names(oneVendorField(defs, { vendor: "Keysight", vendor_ref: "u" }, "form")))
      .toEqual(["vendor_ref:Vendor", "model_code:Model code"]);
  });
  it("asks an older record for the vendor its text names", () => {
    const [field] = oneVendorField(defs, { vendor: "Keysight" }, "form");
    expect(field.key).toBe("vendor_ref");
    expect(field.description).toMatch(/“Keysight” is not linked/);
  });
  it("shows the one value on a page: the reference, or the text not linked yet", () => {
    expect(names(oneVendorField(defs, { vendor: "Keysight", vendor_ref: "u" }, "page"))[0]).toBe("vendor_ref:Vendor");
    expect(names(oneVendorField(defs, { vendor: "Keysight" }, "page"))).toEqual(["vendor:Vendor", "model_code:Model code"]);
  });
  it("leaves other types alone", () => {
    const others = [defs[0], defs[2]];
    expect(oneVendorField(others, { vendor: "x" }, "form")).toBe(others);
  });
});
