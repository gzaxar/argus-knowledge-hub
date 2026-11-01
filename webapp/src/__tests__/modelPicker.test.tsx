import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, assetsApi, catalogueCollectionsApi, type ModelSearch } from "../api/client";
import type { Asset, SchemaAttribute } from "../api/types";
import { AttributeInput } from "../components/AttributeInput";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const attribute = { key: "product_model", name: "Product model", type: "reference", referenceType: "Product Model",
                    referenceSchemaUid: "pm" } as SchemaAttribute;
const results: ModelSearch = {
  installed: [{ uid: "m1", key: "PM-1", name: "Cisco C9200-24T", vendor: "Cisco", model_code: "C9200-24T", catalogue_id: "cisco/c9200-24t" }],
  library: [{ catalogue_id: "cisco/c9200-48t", name: "Cisco C9200-48T", vendor: "Cisco", model_code: "C9200-48T",
              part_number: "C9200-48T-E", collection: "it-devices", source: "netbox" }],
  more: false,
};

function typeIn(text: string) {
  fireEvent.change(screen.getByLabelText("Search a product model"), { target: { value: text } });
}

describe("the product model picker", () => {
  it("searches as one types, the catalogue's models first, then the library's", async () => {
    const search = vi.spyOn(catalogueCollectionsApi, "searchModels").mockResolvedValue(results);
    const list = vi.spyOn(assetsApi, "list");
    const onChange = vi.fn();
    renderWith(<AttributeInput attribute={attribute} value={null} onChange={onChange} />);
    typeIn("c9200");
    const options = await screen.findAllByRole("option");
    expect(search).toHaveBeenLastCalledWith("c9200", false);
    expect(list).not.toHaveBeenCalled();                               // no list of every model
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("in the catalogue"), expect.stringContaining("NetBox · add")]);
    fireEvent.click(options[0]);
    expect(onChange).toHaveBeenCalledWith("m1");
    fireEvent.click(screen.getByLabelText(/every model/));
    typeIn("c9200x");
    await waitFor(() => expect(search).toHaveBeenLastCalledWith("c9200x", true));
  });

  it("adds a library model to the catalogue when it is chosen", async () => {
    vi.spyOn(catalogueCollectionsApi, "searchModels").mockResolvedValue(results);
    const install = vi.spyOn(catalogueCollectionsApi, "installOne").mockResolvedValue({ uid: "m2", key: "PM-2", name: "Cisco C9200-48T", installed: true });
    const onChange = vi.fn();
    renderWith(<AttributeInput attribute={attribute} value={null} onChange={onChange} />);
    typeIn("c9200");
    fireEvent.click(await screen.findByRole("option", { name: /C9200-48T/ }));
    await waitFor(() => expect(install).toHaveBeenCalledWith("cisco/c9200-48t"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("m2"));
  });

  it("offers the record already here when the library model looks like it", async () => {
    vi.spyOn(catalogueCollectionsApi, "searchModels").mockResolvedValue(results);
    vi.spyOn(catalogueCollectionsApi, "installOne").mockRejectedValue(new ApiError(409, {
      detail: { error: "Our C9200-48T is already here and looks like Cisco C9200-48T: choose it instead",
                candidate: { uid: "mine", name: "Our C9200-48T" } } }));
    const onChange = vi.fn();
    renderWith(<AttributeInput attribute={attribute} value={null} onChange={onChange} />);
    typeIn("c9200");
    fireEvent.click(await screen.findByRole("option", { name: /C9200-48T/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Use Our C9200-48T" }));
    expect(onChange).toHaveBeenCalledWith("mine");
  });

  it("shows the model chosen, and leaves other references alone", async () => {
    vi.spyOn(assetsApi, "get").mockResolvedValue({ uid: "m1", key: "PM-1", name: "Cisco C9200-24T" } as Asset);
    renderWith(<AttributeInput attribute={attribute} value="m1" onChange={() => {}} />);
    expect(await screen.findByText("Cisco C9200-24T")).toBeInTheDocument();
  });

  it("is not used for other references", async () => {
    vi.spyOn(assetsApi, "list").mockResolvedValue([{ uid: "r1", key: "R1", name: "Rack 1", schema_uid: "pm" } as Asset]);
    const search = vi.spyOn(catalogueCollectionsApi, "searchModels");
    renderWith(<AttributeInput attribute={{ ...attribute, key: "rack", referenceType: "Rack" }} value={null} onChange={() => {}} />);
    fireEvent.focus(await screen.findByRole("textbox"));
    expect(await screen.findByText(/Rack 1/)).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });
});
