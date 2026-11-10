import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { directoryApi, workspacesApi } from "../api/client";
import type { Me } from "../api/types";
import { AdminShell } from "../layout/AdminShell";
import { renderWith } from "../test/render";

let current: string | null = "btf";
vi.mock("../api/useCurrentWorkspaceId", () => ({ useCurrentWorkspaceId: () => current }));
afterEach(() => vi.restoreAllMocks());

const person = (over: Partial<Me>): Me => ({ auth_type: "oidc", workspace_id: null, user_id: "u", email: "a@infn.it",
  name: "A", is_admin: false, administered_sites: [], ...over });

function shell(me: Me, path = "/workspaces/btf/access") {
  vi.spyOn(workspacesApi, "me").mockResolvedValue(me);
  vi.spyOn(workspacesApi, "listMine").mockResolvedValue([
    { id: "lnf", name: "LNF", role: "site", site_id: null }, { id: "btf", name: "BTF", role: null, site_id: "lnf" },
    { id: "sparc", name: "SPARC", role: null, site_id: null }] as never);
  vi.spyOn(directoryApi, "myGroups").mockResolvedValue([]);
  renderWith(<AdminShell />, { path });
}

describe("the administration sidebar", () => {
  it("has one section per scope, and the workspace's pages grouped", async () => {
    shell(person({ is_admin: true, administered_sites: [{ id: "lnf", name: "LNF" }, { id: "lnl", name: "LNL" }] }));
    const workspace = await screen.findByRole("group", { name: "Workspace" });
    for (const label of ["People & access", "Content", "Integrations", "Area permissions", "Access reviews", "Data integrity"]) {
      expect(within(workspace).getByText(label)).toBeInTheDocument();
    }
    expect(within(workspace).queryByText("Members")).not.toBeInTheDocument();
    const installation = await screen.findByRole("group", { name: "Installation" });
    expect(within(installation).getByRole("link", { name: "Packages (all workspaces)" })).toBeInTheDocument();
    expect(within(installation).getByRole("link", { name: "All tokens" })).toBeInTheDocument();
    // An administrator sees the site of the workspace in hand, not every site.
    expect(screen.getByRole("group", { name: "Site LNF" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Site LNL" })).not.toBeInTheDocument();
  });

  it("gives a site administrator their site whatever workspace is current, and nothing of the installation", async () => {
    current = "sparc";
    shell(person({ administered_sites: [{ id: "lnf", name: "LNF" }] }), "/workspaces/sparc/access");
    const site = await screen.findByRole("group", { name: "Site LNF" });
    expect(within(site).getByRole("link", { name: "Site-wide group access" })).toHaveAttribute("href", "/sites/lnf/group-access");
    expect(within(site).getByRole("link", { name: "Facilities" })).toHaveAttribute("href", "/sites/lnf/facilities");
    expect(screen.queryByRole("group", { name: "Installation" })).not.toBeInTheDocument();
    current = "btf";
  });

  it("shows no site to someone who administers none", async () => {
    shell(person({ catalogue_maintainer: true }));
    // Once /me has answered (the catalogue link comes from it), still no site.
    await screen.findByRole("link", { name: "Catalogue" });
    expect(screen.queryByRole("group", { name: /^Site / })).not.toBeInTheDocument();
  });

  it("says a site page applies to every facility at the site", async () => {
    shell(person({ administered_sites: [{ id: "lnf", name: "LNF" }] }), "/sites/lnf/administrators");
    expect(await screen.findByText(/applies to every facility at this site/)).toBeInTheDocument();
  });
});
