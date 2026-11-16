import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { directoryApi, rolesApi, workspacesApi } from "../api/client";
import type { DirectoryGroup, UserRemovalPreview } from "../api/types";
import { AdminUsers, removalText } from "../pages/admin/Users";
import { WorkspaceGroups } from "../pages/workspace/Groups";
import { DialogHost } from "../lib/dialogs";
import { renderWith } from "../test/render";

vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => ({ workspaceId: "btf" }),
}));

afterEach(() => vi.restoreAllMocks());

const preview: UserRemovalPreview = {
  user: { id: "u2", email: "Leaving@INFN.it", name: "Leaving", is_admin: false, removed_at: null },
  roles: ["btf"], memberships: [], site_administrator_of: [], group_administrator_of: [], groups_left: ["Shift crew"],
  directory_groups: [], personal_tokens: 1, open_tickets_count: 2, open_tickets_unassigned: [], activities_count: 0,
  activities_released: [], stays: { documents_owned: 3, robot_tokens_made: 0, history: "" }, blocked: null,
};

describe("removing a person from ARGUS", () => {
  it("says what it changes and what stays", () => {
    const text = removalText(preview);
    expect(text).toContain("Remove Leaving@INFN.it from ARGUS?");
    expect(text).toContain("can no longer sign in");
    expect(text).toContain("1 personal token stop working");
    expect(text).toContain("Their own roles go, in: btf.");
    expect(text).toContain("Taken out of the groups: Shift crew.");
    expect(text).toContain("2 open tickets assigned to them left unassigned.");
    expect(text).toContain("3 documents they own");
  });

  it("asks twice, the second time for their address, and sends it for the server to check", async () => {
    vi.spyOn(workspacesApi, "listUsers").mockResolvedValue([
      { id: "u2", email: "Leaving@INFN.it", name: "Leaving", is_admin: false, created_at: "2026-01-01T00:00:00Z",
        last_login_at: null },
      { id: "u3", email: "gone@infn.it", name: null, is_admin: false, created_at: "2026-01-01T00:00:00Z",
        last_login_at: null, removed_at: "2026-11-01T00:00:00Z" },
    ]);
    vi.spyOn(workspacesApi, "userRemoval").mockResolvedValue(preview);
    const remove = vi.spyOn(workspacesApi, "removeUser").mockResolvedValue(preview);
    renderWith(<><DialogHost /><AdminUsers /></>);
    expect(await screen.findByText(/removed/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove from ARGUS" })).toHaveLength(1);   // not twice
    fireEvent.click(screen.getByRole("button", { name: "Remove from ARGUS" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, go ahead" }));
    const field = await screen.findByLabelText("Their e-mail address");
    const go = screen.getByRole("button", { name: "I understand, do it" });
    fireEvent.change(field, { target: { value: "leaving@infn" } });
    expect(go).toBeDisabled();
    fireEvent.change(field, { target: { value: "leaving@infn.it" } });                     // any case
    expect(go).toBeEnabled();
    fireEvent.click(go);
    await waitFor(() => expect(remove).toHaveBeenCalledWith("u2", "Leaving@INFN.it"));
  });
});

const group = (name: string, extra: Partial<DirectoryGroup> = {}): DirectoryGroup => ({
  uid: name, dn: null, name, description: null, email: null, source: "local", active: true, member_count: 0,
  workspaces: [], ...extra,
});

describe("a group by e-mail domain", () => {
  it("is set by an administrator after a preview, and its members by address are not removed by hand", async () => {
    vi.spyOn(directoryApi, "allGroups").mockResolvedValue([group("INFN", { workspaces: ["btf"], email_domains: ["infn.it"] })]);
    vi.spyOn(directoryApi, "groupMembers").mockResolvedValue([
      { user_id: "u1", email: "ann@infn.it", name: "Ann", username: null, active: true, source: "domain" },
      { user_id: "u2", email: "bob@gmail.com", name: "Bob", username: null, active: true, source: "local" }]);
    vi.spyOn(directoryApi, "groupAdministrators").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ user_id: "me", email: "me@infn.it", is_admin: true } as never);
    vi.spyOn(rolesApi, "myPermissions").mockResolvedValue({ workspace: ["manage_members"] } as never);
    const set = vi.spyOn(directoryApi, "setGroupDomains").mockImplementation(async (_uid, domains, confirm) => ({
      domains, would_be_in_it: 12, examples: ["ann@infn.it"], unverified: 2, workspaces: ["btf"], preview: !confirm }));
    renderWith(<WorkspaceGroups />, { path: "/workspaces/btf/groups" });
    expect(await screen.findByText(/by address: infn.it/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("INFN"));
    await screen.findByText("ann@infn.it");
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);              // only Bob, added by hand
    fireEvent.change(screen.getByRole("textbox", { name: "E-mail domains" }), { target: { value: "infn.it, *.infn.it" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/would be in it/)).toHaveTextContent("12 people would be in it");
    expect(screen.getByText(/was not verified/)).toHaveTextContent("2 signed in");
    expect(set).toHaveBeenLastCalledWith("INFN", ["infn.it", "*.infn.it"], false);
    fireEvent.click(screen.getByRole("button", { name: "Apply these domains" }));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith("INFN", ["infn.it", "*.infn.it"], true));
  });

  it("is not offered to someone who is not an administrator of the installation", async () => {
    vi.spyOn(directoryApi, "allGroups").mockResolvedValue([group("Crew", { workspaces: ["btf"] })]);
    vi.spyOn(directoryApi, "groupMembers").mockResolvedValue([]);
    vi.spyOn(directoryApi, "groupAdministrators").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "me").mockResolvedValue({ user_id: "me", email: "me@infn.it", is_admin: false } as never);
    vi.spyOn(rolesApi, "myPermissions").mockResolvedValue({ workspace: ["manage_members"] } as never);
    renderWith(<WorkspaceGroups />, { path: "/workspaces/btf/groups" });
    fireEvent.click(await screen.findByText("Crew"));
    await screen.findByText("Nobody in it yet.");
    expect(screen.queryByRole("textbox", { name: "E-mail domains" })).toBeNull();
  });
});
