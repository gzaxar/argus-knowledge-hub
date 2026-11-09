import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { directoryApi, membersApi, rolesApi, workspacesApi } from "../api/client";
import type { DirectoryGroup } from "../api/types";
import { WorkspaceAccess } from "../pages/workspace/Access";
import { WorkspaceGroups } from "../pages/workspace/Groups";
import { renderWith } from "../test/render";

// The pages read the workspace from the route; the test router matches any path.
vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ workspaceId: "btf" }),
}));

afterEach(() => vi.restoreAllMocks());

const group = (name: string, extra: Partial<DirectoryGroup> = {}): DirectoryGroup => ({
  uid: name, dn: null, name, description: null, email: null, source: "local", active: true, member_count: 0,
  workspaces: [], ...extra,
});

function access() {
  vi.spyOn(rolesApi, "listBindings").mockResolvedValue([]);
  vi.spyOn(rolesApi, "list").mockResolvedValue([{ id: "viewer", name: "Viewer" }, { id: "reporter", name: "Reporter" }] as never);
  vi.spyOn(directoryApi, "groups").mockResolvedValue([group("Shift crew")]);
  vi.spyOn(directoryApi, "status").mockResolvedValue({ provider: "none", is_test_data: false, groups: 1, active_groups: 1,
                                                       users: 1, last_synced_at: null } as never);
  vi.spyOn(membersApi, "directory").mockResolvedValue([]);
}

describe("inviting by e-mail", () => {
  it("sends the addresses, the role and, when chosen, a new group", async () => {
    access();
    const invite = vi.spyOn(rolesApi, "invite").mockResolvedValue({
      workspace_id: "btf", role_id: "reporter", role_name: "Reporter", group_uid: "g", group_name: "Night shift",
      group_granted: true, not_addresses: [],
      people: [{ email: "a@infn.it", user_id: "u", added: true, granted: true, joined: true, signed_in: false,
                 emailed: true, error: null }],
    });
    renderWith(<WorkspaceAccess />, { path: "/workspaces/btf/access" });
    fireEvent.change(await screen.findByLabelText("E-mail addresses"), { target: { value: "a@infn.it, b@infn.it" } });
    await screen.findAllByRole("option", { name: "Reporter" });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "reporter" } });
    fireEvent.change(await screen.findByDisplayValue("each person"), { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("New group name"), { target: { value: "Night shift" } });
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));
    await waitFor(() => expect(invite).toHaveBeenCalledWith("btf", expect.objectContaining({
      emails: "a@infn.it, b@infn.it", role_id: "reporter", send_email: true, new_group: "Night shift" })));
    expect(await screen.findByText(/now has Reporter here/)).toBeInTheDocument();
    expect(screen.getByText(/joined Night shift/)).toBeInTheDocument();
  });
});

describe("groups", () => {
  it("are made here, filled by e-mail, and the directory's are read only", async () => {
    vi.spyOn(directoryApi, "allGroups").mockResolvedValue([
      group("Shift crew", { member_count: 1, workspaces: ["btf"] }), group("LDAP staff", { source: "ldap" })]);
    vi.spyOn(directoryApi, "groupMembers").mockResolvedValue([
      { user_id: "u1", email: "ann@infn.it", name: "Ann", username: null, active: true, source: "local" }]);
    const add = vi.spyOn(directoryApi, "addGroupMembers").mockResolvedValue({
      workspace_id: "btf", role_id: null, role_name: null, people: [], not_addresses: [] });
    const create = vi.spyOn(directoryApi, "createGroup").mockResolvedValue(group("Vacuum"));
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ user_id: "me", email: "me@infn.it", is_admin: false } as never);
    vi.spyOn(rolesApi, "myPermissions").mockResolvedValue({ workspace: ["manage_members"] } as never);
    vi.spyOn(directoryApi, "groupAdministrators").mockResolvedValue([]);
    renderWith(<WorkspaceGroups />, { path: "/workspaces/btf/groups" });
    fireEvent.click(await screen.findByText("Shift crew"));
    expect(await screen.findByText("ann@infn.it")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Addresses to add"), { target: { value: "bob@infn.it" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("Shift crew", { emails: "bob@infn.it", send_email: true }));
    fireEvent.click(screen.getByText("LDAP staff"));            // one open at a time: now the directory's
    await screen.findByText("ann@infn.it");
    expect(screen.queryByLabelText("Addresses to add")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New group name"), { target: { value: "Vacuum" } });
    fireEvent.click(screen.getByRole("button", { name: "Create group" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "Vacuum" }));
  });
});
