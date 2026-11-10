import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { catalogueCollectionsApi, type CatalogueProposalDraft } from "../api/client";
import { CatalogueProposals, ProposeModel, SourceReleases } from "../pages/catalogue/CatalogueGit";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const draft: CatalogueProposalDraft = {
  record_uid: "m-1",
  entry: { id: "keysight/34465a", vendor: "keysight", model_code: "34465A", name: "Keysight 34465A", device_class: "multimeter" },
  vendor: { id: "keysight", name: "Keysight", new: true, record_uid: "v-1", entry: { id: "keysight", name: "Keysight" } },
  collections: [{ id: "vacuum", name: "Vacuum", version: "0.1.1", domains: ["vacuum-cryo"] }],
  device_classes: ["multimeter", "vacuum"], source_kinds: ["datasheet", "manufacturer-page", "other"],
  repository: "infn-argus/argus-catalogue", enabled: true,
};

describe("proposing a model to the catalogue", () => {
  it("checks the files first, then opens the pull request with what the person completed", async () => {
    vi.spyOn(catalogueCollectionsApi, "proposalDraft").mockResolvedValue(draft);
    const preview = vi.spyOn(catalogueCollectionsApi, "proposalPreview").mockResolvedValue(
      { title: "Add Keysight 34465A (keysight/34465a)", base: "main", repository: "infn-argus/argus-catalogue",
        files: { "collections/test-measurement/models.yaml": "models:\n- id: keysight/34465a\n" } });
    const propose = vi.spyOn(catalogueCollectionsApi, "propose").mockResolvedValue({
      id: 1, record_uid: "m-1", record_name: "Keysight 34465A", catalogue_id: "keysight/34465a", vendor_id: "keysight",
      collection_id: "test-measurement", repository: "infn-argus/argus-catalogue", number: 7,
      url: "https://github.com/infn-argus/argus-catalogue/pull/7", state: "open", proposed_by: "m", proposed_at: "2026-11-05",
      files: [] });
    renderWith(<ProposeModel uid="m-1" />);
    fireEvent.click(screen.getByRole("button", { name: /propose for the catalogue/i }));
    expect(await screen.findByText(/has no vendor Keysight/)).toBeInTheDocument();
    const open = screen.getByRole("button", { name: "Open the pull request" });
    expect(open).toBeDisabled();                                      // the source is still missing

    fireEvent.click(screen.getByLabelText("a new one"));
    fireEvent.change(screen.getByPlaceholderText("test-measurement"), { target: { value: "test-measurement" } });
    fireEvent.change(screen.getByPlaceholderText(/datasheet's link/), { target: { value: "https://keysight.com/ds.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Show the files" }));          // to read them: not a step
    expect(await screen.findByText(/validator accepts it/)).toBeInTheDocument();
    expect(preview.mock.calls[0][0]).toMatchObject({ collection: { id: "test-measurement" },
                                                      source: { kind: "datasheet", ref: "https://keysight.com/ds.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Open the pull request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("pull request #7");
    expect(propose).toHaveBeenCalledOnce();
  });

  it("opens the pull request without showing the files first, and says how it read the device class", async () => {
    vi.spyOn(catalogueCollectionsApi, "proposalDraft").mockResolvedValue(
      { ...draft, entry: { ...draft.entry, device_class: "multimeter" }, device_class_written: "digital multimeter" });
    const preview = vi.spyOn(catalogueCollectionsApi, "proposalPreview");
    const propose = vi.spyOn(catalogueCollectionsApi, "propose").mockRejectedValue(new Error("no"));
    renderWith(<ProposeModel uid="m-1" />);
    fireEvent.click(screen.getByRole("button", { name: /propose for the catalogue/i }));
    expect(await screen.findByText(/says “digital multimeter”: read as multimeter/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("a new one"));
    fireEvent.change(screen.getByPlaceholderText("test-measurement"), { target: { value: "test-measurement" } });
    fireEvent.change(screen.getByPlaceholderText(/datasheet's link/), { target: { value: "https://keysight.com/ds.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Open the pull request" }));
    await waitFor(() => expect(propose).toHaveBeenCalledOnce());
    expect(preview).not.toHaveBeenCalled();
  });

  it("lists what was proposed and how far it got", async () => {
    vi.spyOn(catalogueCollectionsApi, "proposals").mockResolvedValue({ enabled: true, repository: "r", proposals: [
      { id: 1, record_uid: "m-1", record_name: "Keysight 34465A", catalogue_id: "keysight/34465a", vendor_id: null,
        collection_id: "test-measurement", repository: "r", number: 7, url: "u", state: "merged", proposed_by: "m",
        proposed_at: "2026-11-05", files: [] }] });
    renderWith(<CatalogueProposals />);
    expect(await screen.findByText(/merged: waiting for a release/)).toBeInTheDocument();
  });
});

describe("a newer catalogue release", () => {
  it("is pinned from the list of releases, and the pin says who moved it", async () => {
    vi.spyOn(catalogueCollectionsApi, "releases").mockResolvedValue({
      source: "argus", repo: "r", ref: "v0.2.0", commit: "a".repeat(40), shipped_ref: "v0.2.0", shipped_commit: "a".repeat(40),
      releases: [{ tag: "v0.3.0", commit: "b".repeat(40), current: false, newer: true }] });
    const pin = vi.spyOn(catalogueCollectionsApi, "pin").mockResolvedValue(
      { source: "argus", ref: "v0.3.0", commit: "b".repeat(40), previous_ref: "v0.2.0" });
    renderWith(<SourceReleases source={{ id: "argus", kind: "argus-collections", repo: "r", ref: "v0.2.0",
                                         commit: "a".repeat(40), select: null, releasable: true, pinned_in: "lock" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Check for newer releases" }));
    fireEvent.click(await screen.findByRole("button", { name: "Check and pin v0.3.0" }));
    await waitFor(() => expect(pin).toHaveBeenCalledWith("argus", "v0.3.0"));
    expect(await screen.findByRole("status")).toHaveTextContent("v0.3.0 is pinned");
  });
});
