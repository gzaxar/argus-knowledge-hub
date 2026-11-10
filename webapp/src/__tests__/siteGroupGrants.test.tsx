import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { directoryApi, membersApi, rolesApi, sitesApi, workspacesApi } from "../api/client";
import type { DirectoryGroup, SiteGroupGrant } from "../api/types";
import { WorkspaceAccess } from "../pages/workspace/Access";
import { renderWith } from "../test/render";

let here = "lnf";
vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ workspaceId: here }),
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
}

describe("site-wide group access", () => {
  it("previews who and where, then gives the role once for the site", async () => {
    here = "lnf";
    page();
    vi.spyOn(sitesApi, "groupGrants").mockResolvedValue({ site_id: "lnf", workspaces: ["lnf", "sparc", "btf"],
                                                          roles: ["viewer", "reporter"], grants: [] });
    vi.spyOn(sitesApi, "previewGroupGrant").mockResolvedValue({ site_id: "lnf", group_uid: "ops", group_name: "Operations",
      group_active: true, role_id: "reporter", role_name: "Reporter", workspaces: ["lnf", "sparc", "btf"],
      people: [{ user_id: "u", email: "ann@infn.it", name: null }] });
    const give = vi.spyOn(sitesApi, "grantGroup").mockResolvedValue(granted);
    renderWith(<WorkspaceAccess />);
    expect(await screen.findByText("Site-wide group access")).toBeInTheDocument();
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
