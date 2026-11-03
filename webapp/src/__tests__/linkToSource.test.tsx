import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { catalogueCollectionsApi } from "../api/client";
import { LinkToSource } from "../pages/catalogue/LinkToSource";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

describe("a model made by hand, linked to its source", () => {
  it("searches the sources with its code and links the one chosen, saying what was filled", async () => {
    const search = vi.spyOn(catalogueCollectionsApi, "searchSources").mockResolvedValue({ installed: [], more: false, library: [
      { catalogue_id: "cisco/c9200-24t", name: "Cisco Catalyst 9200-24T", vendor: "Cisco", model_code: "Catalyst 9200-24T",
        part_number: "C9200-24T", collection: "it-devices", source: "netbox" }] });
    const link = vi.spyOn(catalogueCollectionsApi, "link").mockResolvedValue(
      { uid: "m1", name: "Our C9200", installed: true, filled: ["components", "part_number"], kept: ["name"] });
    renderWith(<LinkToSource uid="m1" initial="C9200-24T" />);
    fireEvent.click(await screen.findByRole("button", { name: "Link to this one" }));
    expect(search).toHaveBeenCalledWith("C9200-24T");
    expect(await screen.findByRole("status")).toHaveTextContent("filled components, part_number");
    expect(link).toHaveBeenCalledWith("cisco/c9200-24t", "m1");
    expect(screen.getByText(/C9200-24T · NetBox/)).toBeInTheDocument();
  });
});
