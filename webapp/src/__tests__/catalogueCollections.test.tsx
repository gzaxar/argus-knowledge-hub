import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  catalogueCollectionsApi, type CatalogueCollection, type CataloguePlan, type CataloguePlanItem, type CatalogueRecord,
} from "../api/client";
import { CatalogueCollectionsPage, linkAllVendors, openVendorLinks, stillOpen } from "../pages/catalogue/CatalogueCollections";
import { CatalogueModelPage } from "../pages/catalogue/CatalogueModel";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const collection = (id: string, over: Partial<CatalogueCollection> = {}): CatalogueCollection => ({
  id, name: id, description: "", version: "0.1.0", domain: "it", owner: "INFN ARGUS", license: "CC-BY-4.0",
  checksum: "abc", summary: "2 models", vendors: 0, models: 2, requires: { packages: {}, collections: {} }, problems: [],
  installed_version: null, installed_at: null, upgrade_available: false, ...over,
});

const link: CataloguePlanItem = {
  catalogue_id: "moxa/nport-5450", kind: "model", collection: "it-network", category: "link",
  record_uid: "r1", record_name: "NPort 5450", needs_decision: true, notes: [],
  fields: [{ field: "model_code", record: null, release: "NPort 5450", action: "managed" },
           { field: "name", record: "NPort 5450", release: "Moxa NPort 5450", action: null }],
};

const plan: CataloguePlan = {
  workspace_id: "cat", counts: { link: 1, add: 1 }, undecided: ["moxa/nport-5450"], trial: null,
  releases: [{ collection: "it-network", from_version: null, version: "0.1.0", checksum: "abc", already_installed: false,
               counts: { link: 1, add: 1 }, not_stored: { specifications: 1 },
               items: [link, { ...link, catalogue_id: "cisco/c9200-24t", category: "add", record_uid: null,
                               record_name: null, needs_decision: false, fields: [] }] }],
};

describe("a link waits for a person", () => {
  it("needs link or create, and a choice for every field that differs", () => {
    expect(stillOpen(link, undefined)).toBe(true);
    expect(stillOpen(link, { action: "create" })).toBe(false);
    expect(stillOpen(link, { action: "link" })).toBe(true);                          // the name differs
    expect(stillOpen(link, { action: "link", fields: { name: "local" } })).toBe(false);
  });
});

describe("catalogue collections", () => {
  it("previews, asks for the decisions, and installs with them", async () => {
    vi.spyOn(catalogueCollectionsApi, "list").mockResolvedValue({
      workspace_id: "cat", history: [],
      sources: [{ id: "argus", kind: "argus-collections", repo: "https://github.com/infn-argus/argus-catalogue.git",
                  ref: "v0.1.0", commit: "63a81dded8c09c500ee8ffb7cffa69f5a705f75f", select: null }],
      collections: [collection("it-network"), collection("vacuum", { problems: ["vacuum: models › x: needs a model_code"] })],
    });
    vi.spyOn(catalogueCollectionsApi, "review").mockResolvedValue([]);
    vi.spyOn(catalogueCollectionsApi, "preview").mockResolvedValue(plan);
    const install = vi.spyOn(catalogueCollectionsApi, "install").mockResolvedValue({ ...plan, undecided: [] });
    renderWith(<CatalogueCollectionsPage />);

    expect(await screen.findByLabelText("Choose vacuum")).toBeDisabled();             // invalid: not offered
    expect(screen.getByText("infn-argus/argus-catalogue")).toBeInTheDocument();
    expect(screen.getByText("v0.1.0 @ 63a81dded8c0")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Choose it-network"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/NPort 5450/, { selector: "b" })).toBeInTheDocument();
    expect(screen.getByText(/specifications \(1\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install" })).toBeDisabled();
    expect(screen.getByText("1 entry needs a decision before installing.")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/link it/));
    fireEvent.click(screen.getByLabelText("keep this record's"));
    const button = screen.getByRole("button", { name: "Install" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(install).toHaveBeenCalledWith(["it-network"], {
      "moxa/nport-5450": { action: "link", fields: { name: "local" } } }, undefined));
  });

  it("sends a migration manifest, and leaves what it decided alone", async () => {
    vi.spyOn(catalogueCollectionsApi, "list").mockResolvedValue({
      workspace_id: "cat", history: [], sources: [], collections: [collection("it-network")] });
    vi.spyOn(catalogueCollectionsApi, "review").mockResolvedValue([]);
    const preview = vi.spyOn(catalogueCollectionsApi, "preview").mockResolvedValue({ ...plan, undecided: [] });
    const install = vi.spyOn(catalogueCollectionsApi, "install").mockResolvedValue({ ...plan, undecided: [] });
    renderWith(<CatalogueCollectionsPage />);
    fireEvent.click(await screen.findByLabelText("Choose it-network"));
    const file = new File(["workspace: cat\nlinks: {}\n"], "migration-cat.yaml", { type: "application/yaml" });
    fireEvent.change(screen.getByLabelText("Migration manifest"), { target: { files: [file] } });
    expect(await screen.findByText("migration-cat.yaml")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/linked as the migration manifest says/)).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith(["it-network"], {}, "workspace: cat\nlinks: {}\n");
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() => expect(install).toHaveBeenCalledWith(["it-network"], {}, "workspace: cat\nlinks: {}\n"));
  });
});

describe("linking every matching vendor at once", () => {
  const vendor = (id: string, name: string, fields = [{ field: "name", record: name, release: id, action: null }]) =>
    ({ ...link, catalogue_id: id, kind: "vendor" as const, collection: "vendors", record_uid: `u-${id}`,
       record_name: name, fields: fields as CataloguePlanItem["fields"] });
  const vendorsPlan: CataloguePlan = {
    ...plan, undecided: ["agilent", "pfeiffer-vacuum", "moxa", "moxa/nport-5450"],
    releases: [{ ...plan.releases[0], collection: "vendors",
                 items: [vendor("agilent", "Agilent Technologies"), vendor("pfeiffer-vacuum", "Pfeiffer Vacuum", []),
                         vendor("moxa", "MOXA"), link] }],
  };

  it("takes the vendors still waiting, and links each keeping this record's differing fields", () => {
    const open = openVendorLinks(vendorsPlan, { moxa: { action: "create" } }, false);
    expect(open.map((i) => i.catalogue_id)).toEqual(["agilent", "pfeiffer-vacuum"]);   // not decided, not a model
    expect(linkAllVendors(open)).toEqual({
      agilent: { action: "link", fields: { name: "local" } },
      "pfeiffer-vacuum": { action: "link", fields: {} },
    });
    expect(openVendorLinks(vendorsPlan, {}, true).map((i) => i.catalogue_id)).toEqual(["agilent", "pfeiffer-vacuum", "moxa"]);
    expect(openVendorLinks({ ...vendorsPlan, undecided: ["moxa/nport-5450"] }, {}, true)).toEqual([]);  // the manifest decided
  });

  it("is a button in the preview; a choice made by hand stays, and models wait for a person", async () => {
    vi.spyOn(catalogueCollectionsApi, "list").mockResolvedValue({
      workspace_id: "cat", history: [], sources: [], collections: [collection("vendors")] });
    vi.spyOn(catalogueCollectionsApi, "review").mockResolvedValue([]);
    vi.spyOn(catalogueCollectionsApi, "preview").mockResolvedValue(vendorsPlan);
    const install = vi.spyOn(catalogueCollectionsApi, "install").mockResolvedValue({ ...vendorsPlan, undecided: [] });
    renderWith(<CatalogueCollectionsPage />);
    fireEvent.click(await screen.findByLabelText("Choose vendors"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    fireEvent.click((await screen.findAllByLabelText(/create a separate one/))[2]);       // MOXA: by hand
    fireEvent.click(screen.getByRole("button", { name: "Link all matching vendors (2)" }));
    expect(screen.queryByRole("button", { name: /Link all matching vendors/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Install" })).toBeDisabled();              // the model still waits
    fireEvent.click(screen.getAllByLabelText(/create a separate one/)[3]);               // the NPort: by hand
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() => expect(install).toHaveBeenCalledWith(["vendors"], {
      agilent: { action: "link", fields: { name: "local" } },
      "pfeiffer-vacuum": { action: "link", fields: {} },
      moxa: { action: "create" },
      "moxa/nport-5450": { action: "create" },
    }, undefined));
  });
});

describe("a catalogue model's page", () => {
  it("shows where each value comes from and asks about an edited one", async () => {
    const record: CatalogueRecord = {
      uid: "r1", key: "PM-1", name: "Moxa NPort 5450", type: "Product Model", kind: "model", record_status: "Active",
      is_global: true, stated_only: { specifications: { serial_ports: 4 } }, relations: [], sources: [], retired: null,
      units: [{ workspace_id: "sparc", name: "SPARC", count: 3 }, { workspace_id: null, name: "other workspaces", count: 2 }],
      releases: [{ version: "0.1.0", from_version: null, installed_at: null, installed_by: "u" }],
      entry: { catalogue_id: "moxa/nport-5450", collection_id: "it-network", collection_version: "0.1.0", status: "active",
               adopted_at: null, adopted_by: null, managed_fields: ["name", "datasheet_url"] },
      fields: [
        { field: "name", label: "Name", value: "Moxa NPort 5450", ref: null, source: "collection",
          collection_value: "Moxa NPort 5450", conflict: null, correction: null },
        { field: "datasheet_url", label: "Datasheet", value: "https://local/x.pdf", ref: null, source: "edited",
          collection_value: "https://moxa/x.pdf", conflict: null, correction: null },
      ],
    };
    vi.spyOn(catalogueCollectionsApi, "record").mockResolvedValue(record);
    const decide = vi.spyOn(catalogueCollectionsApi, "decideField").mockResolvedValue({});
    renderWith(<Routes><Route path="/catalogue/models/:uid" element={<CatalogueModelPage />} /></Routes>,
               { path: "/catalogue/models/r1" });

    expect(await screen.findByText("edited here")).toBeInTheDocument();
    expect(screen.getByText("from the collection")).toBeInTheDocument();
    expect(screen.getByText("The collection says: https://moxa/x.pdf")).toBeInTheDocument();
    expect(screen.getByText("serial ports")).toBeInTheDocument();
    expect(screen.getByText("other workspaces: 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Propose this value to Git" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("moxa/nport-5450", "datasheet_url", "propose"));
  });
});

describe("GLPI devices", () => {
  it("proposes models for review and lists what nothing matches", async () => {
    const { GlpiMatches } = await import("../pages/catalogue/ProductCatalogue");
    const { glpiMatchesApi } = await import("../api/client");
    vi.spyOn(glpiMatchesApi, "run").mockResolvedValue({
      status: "ran", proposals: 3, exact: 2, near: 1,
      ambiguous: [{ manufacturer: "Cisco", model: "C9200-24T", candidates: ["a", "b"] }],
      unmatched: [{ manufacturer: "Acme", model: "Thing 9", units: 2 }] });
    renderWith(<GlpiMatches />);
    fireEvent.click(screen.getByRole("button", { name: "Propose models" }));
    expect(await screen.findByText(/3 proposals \(2 exact, 1 near\)/)).toBeInTheDocument();
    expect(screen.getByText(/Cisco C9200-24T \(a or b\)/)).toBeInTheDocument();
    expect(screen.getByText("Acme Thing 9: 2 units")).toBeInTheDocument();
  });
});

describe("corrections back to Git", () => {
  it("downloads a patch per repository and says what could not go", async () => {
    const { CorrectionPatches } = await import("../pages/catalogue/CatalogueCollections");
    vi.spyOn(catalogueCollectionsApi, "corrections").mockResolvedValue({
      patches: [{ repo: "argus-catalogue", diff: "--- a/x\n+++ b/x\n" }],
      items: [{ catalogue_id: "moxa/nport-5450", field: "datasheet_url", from: null, to: "u", by: "me", reason: null,
                status: "skipped", why: "no place in the NetBox device type format" }] });
    const created = vi.fn(() => "blob:x");
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    renderWith(<CorrectionPatches />);
    fireEvent.click(screen.getByRole("button", { name: "Download the corrections as patches" }));
    expect(await screen.findByText(/argus-catalogue-corrections.patch: apply on a branch/)).toBeInTheDocument();
    expect(screen.getByText(/datasheet_url: no place in the NetBox/)).toBeInTheDocument();
    expect(created).toHaveBeenCalledTimes(1);
  });
});
