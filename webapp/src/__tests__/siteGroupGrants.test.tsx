import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { directoryApi, membersApi, rolesApi, sitesApi, workspacesApi } from "../api/client";
import type { DirectoryGroup, SiteGroupGrant } from "../api/types";
import { WorkspaceAccess } from "../pages/workspace/Access";
import { SiteGroupAccessPage } from "../pages/site/SiteAdministration";
import { renderWith } from "../test/render";

let here = "lnf";
vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ workspaceId: here, siteId: here }),
}));
afterEach(() => vi.restoreAllMocks());

const ops: DirectoryGroup = { uid: "ops", dn: null, name: "Operations", description: null, email: null, source: "local",
  active: true, member_count: 2, workspaces: [], home_site_id: "lnf", site_grants: [] };
const granted: SiteGroupGrant = { id: 7, site_id: "lnf", group_uid: "ops", group_name: "Operations", group_active: true,
  group_source: "local", role_id: "reporter", role_name: "Reporter", created_by: null, created_at: null };

function page() {
  vi.spyOn(rolesApi, "listBindings").mockResolvedValue([]);
  vi.spyOn(rolesApi, "list").mockResolvedValue([{ id: "viewer", name: "Viewer" }, { id: "reporter", name: "Reporter" },
                                                { id: "owner", name: "Owner" }] as never);
  vi.spyOn(directoryApi, "groups").mockResolvedValue([ops, { ...ops, uid: "lnl", name: "LNL crew", home_site_id: "lnl" }]);
  vi.spyOn(directoryApi, "status").mockResolvedValue({ provider: "none", is_test_data: false, groups: 1, active_groups: 1,
                                                       users: 1, last_synced_at: null } as never);
  vi.spyOn(membersApi, "directory").mockResolvedValue([]);
  vi.spyOn(workspacesApi, "listMine").mockResolvedValue([
    { id: "lnf", name: "LNF", role: "site", site_id: null }, { id: "btf", name: "BTF", role: null, site_id: "lnf" }] as never);
  vi.spyOn(sitesApi, "administrators").mockResolvedValue([]);
  vi.spyOn(workspacesApi, "me").mockResolvedValue({ auth_type: "oidc", is_admin: true, workspace_id: null, user_id: "u",
    email: null, name: null, administered_sites: [{ id: "lnf", name: "LNF" }] });
}

describe("site-wide group access", () => {
  it("is on the site's own page, and the site's Access page points there", async () => {
    here = "lnf";
    page();
    renderWith(<WorkspaceAccess />);
    expect(await screen.findByText(/This workspace is a site/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "site-wide group access" })).toHaveAttribute("href", "/sites/lnf/group-access");
    expect(screen.queryByLabelText("Group for the site")).not.toBeInTheDocument();
  });

  it("previews who and where, then gives the role once for the site", async () => {
    here = "lnf";
    page();
    vi.spyOn(sitesApi, "groupGrants").mockResolvedValue({ site_id: "lnf", workspaces: ["lnf", "sparc", "btf"],
                                                          roles: ["viewer", "reporter"], grants: [] });
    vi.spyOn(sitesApi, "previewGroupGrant").mockResolvedValue({ site_id: "lnf", group_uid: "ops", group_name: "Operations",
      group_active: true, role_id: "reporter", role_name: "Reporter", workspaces: ["lnf", "sparc", "btf"],
      people: [{ user_id: "u", email: "ann@infn.it", name: null }] });
    const give = vi.spyOn(sitesApi, "grantGroup").mockResolvedValue(granted);
    renderWith(<SiteGroupAccessPage />);
    expect(await screen.findByRole("heading", { name: /Site-wide group access/ })).toBeInTheDocument();
    const groupSelect = screen.getByLabelText("Group for the site");
    expect(screen.queryByRole("option", { name: "LNL crew" })).not.toBeInTheDocument();   // another site's group
    const roleSelect = screen.getByLabelText("Site-wide role");
    await waitFor(() => expect(roleSelect.querySelectorAll("option")).toHaveLength(2));   // no Owner site-wide
    fireEvent.change(groupSelect, { target: { value: "ops" } });
    fireEvent.change(roleSelect, { target: { value: "reporter" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/1 person in Operations would have Reporter in lnf, sparc, btf/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Give Reporter site-wide" }));
    await waitFor(() => expect(give).toHaveBeenCalledWith("lnf", { group_uid: "ops", role_id: "reporter" }));
  });

  it("is listed on a facility as inherited, and not removable there", async () => {
    here = "btf";
    page();
    vi.spyOn(rolesApi, "inherited").mockResolvedValue([granted]);
    renderWith(<WorkspaceAccess />);
    expect(await screen.findByText("Inherited from the site lnf")).toBeInTheDocument();
    expect(screen.getByText(/from lnf/)).toBeInTheDocument();
    expect(screen.queryByText("Site-wide group access")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });
});

describe("second part of #26", () => {
  it("says in words where a role comes from", async () => {
    const { viaText } = await import("../pages/account/Account");
    expect(viaText("group:Operations")).toBe("via Operations");
    expect(viaText("site:lnf:Operations")).toBe("site-wide at lnf, via Operations");
    expect(viaText("site:lnf")).toBe("as administrator of the site lnf");
  });

  it("shows who loses access before a facility moves, and holds the move while grants block it", async () => {
    const { AdminWorkspaces } = await import("../pages/admin/Workspaces");
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([
      { id: "lnf", name: "LNF", role: "site", site_id: null }, { id: "lnl", name: "LNL", role: "site", site_id: null },
      { id: "btf", name: "BTF", role: null, site_id: "lnf" }] as never);
    const move = vi.spyOn(sitesApi, "setSite").mockResolvedValue({ workspace_id: "btf", site_id: "lnf", preview: true,
      would_end: [], access: { workspace_id: "btf", from_site: "lnf", to_site: "lnl",
        loses: [{ ...granted, people: ["ann@infn.it", "bob@infn.it"] }], gains: [],
        blocked: [{ binding_id: 1, group_uid: "ops", group_name: "Operations", home_site_id: "lnf", role_id: "viewer" }] } });
    renderWith(<AdminWorkspaces />);
    fireEvent.change(await screen.findByLabelText("Site of BTF"), { target: { value: "lnl" } });
    await waitFor(() => expect(move).toHaveBeenCalledWith("btf", "lnl", false));
    expect(await screen.findByText(/stops inheriting from lnf: Operations \(Reporter\): 2 people/)).toBeInTheDocument();
    expect(screen.getByText(/Settle first/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move it" })).toBeDisabled();
  });

  it("lists the recorded changes to access", async () => {
    here = "btf";
    page();
    vi.spyOn(rolesApi, "inherited").mockResolvedValue([]);
    vi.spyOn(rolesApi, "accessEvents").mockResolvedValue([{ id: 1, at: "2026-11-10T10:00:00Z", actor: "Ada", kind: "site_role.granted",
      workspace_id: null, site_id: "lnf", group_uid: "ops", subject_type: "group", subject: "Operations", role_id: "reporter",
      detail: {} }]);
    renderWith(<WorkspaceAccess />);
    fireEvent.click(await screen.findByRole("button", { name: /Changes to access/ }));
    expect(await screen.findByText(/given site-wide · reporter · lnf/)).toBeInTheDocument();
    expect(screen.getByText(/by Ada/)).toBeInTheDocument();
  });
});
