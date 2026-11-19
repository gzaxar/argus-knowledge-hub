import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspacePicker } from "../auth/WorkspacePicker";
import { workspacesApi } from "../api/client";
import { addOidcProfile, clearSession, getActiveProfile, getRememberedWorkspaceId, updateProfile } from "../api/session";
import type { MyWorkspace } from "../api/types";

vi.mock("../api/firebase", () => ({ getFreshIdToken: vi.fn() }));
vi.mock("../api/infnAuth", () => ({ getInfnIdToken: vi.fn(), infnForgetSession: vi.fn() }));
vi.mock("../api/signOut", () => ({ signOut: vi.fn() }));
vi.mock("../api/client", () => ({ workspacesApi: { listMine: vi.fn(), me: vi.fn(), create: vi.fn() } }));
const identity = { issuer: "https://login.example", subject: "alice" };
const workspace = (id: string): MyWorkspace => ({
  id, name: id.toUpperCase(), created_at: "2026-11-19T00:00:00Z", is_global: false,
  can_read: true, can_create: true, can_modify: true, can_delete: true,
  can_read_tickets: true, can_create_tickets: true, can_modify_tickets: true, can_delete_tickets: true,
  can_read_documents: true, can_create_documents: true, can_modify_documents: true,
  can_delete_documents: true, can_approve_documents: true,
});
function returningUser(last = "eli") {
  const old = addOidcProfile("Alice", "https://api.example", "infn", identity);
  updateProfile(old.id, { activeWorkspaceId: last }); clearSession();
  return addOidcProfile("Alice", "https://api.example", "infn", identity);
}
afterEach(() => { vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe("restoring a workspace at login", () => {
  it("waits for current access before restoring the last workspace", async () => {
    const profile = returningUser();
    let resolve!: (ws: MyWorkspace[]) => void;
    vi.mocked(workspacesApi.listMine).mockReturnValue(new Promise((r) => { resolve = r; }));
    vi.mocked(workspacesApi.me).mockResolvedValue({ is_admin: false } as Awaited<ReturnType<typeof workspacesApi.me>>);
    const picked = vi.fn();
    render(<WorkspacePicker profile={profile} onPicked={picked} />);
    expect(screen.getByRole("heading", { name: "Returning to your last workspace…" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Please wait while we open your workspace.");
    expect(screen.queryByRole("heading", { name: "Choose a workspace" })).not.toBeInTheDocument();
    expect(getActiveProfile()?.activeWorkspaceId).toBeUndefined();
    expect(picked).not.toHaveBeenCalled();
    resolve([workspace("btf"), workspace("eli")]);
    await waitFor(() => expect(picked).toHaveBeenCalledTimes(1));
    expect(getActiveProfile()?.activeWorkspaceId).toBe("eli");
  });
  it("shows the picker if the remembered workspace is no longer accessible", async () => {
    const profile = returningUser();
    vi.mocked(workspacesApi.listMine).mockResolvedValue([workspace("btf"), workspace("sparc")]);
    vi.mocked(workspacesApi.me).mockResolvedValue({ is_admin: false } as Awaited<ReturnType<typeof workspacesApi.me>>);
    const picked = vi.fn(); render(<WorkspacePicker profile={profile} onPicked={picked} />);
    await screen.findByRole("button", { name: "BTF" });
    expect(screen.getByRole("heading", { name: "Choose a workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(picked).not.toHaveBeenCalled();
    expect(getActiveProfile()?.activeWorkspaceId).toBeUndefined();
    expect(getRememberedWorkspaceId(profile)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "SPARC" }));
    expect(getActiveProfile()?.activeWorkspaceId).toBe("sparc");
    expect(getRememberedWorkspaceId(profile)).toBe("sparc");
  });
  it("falls back to the only available workspace", async () => {
    const profile = returningUser();
    vi.mocked(workspacesApi.listMine).mockResolvedValue([workspace("btf")]);
    vi.mocked(workspacesApi.me).mockResolvedValue({ is_admin: false } as Awaited<ReturnType<typeof workspacesApi.me>>);
    const picked = vi.fn(); render(<WorkspacePicker profile={profile} onPicked={picked} />);
    await waitFor(() => expect(picked).toHaveBeenCalledTimes(1));
    expect(getActiveProfile()?.activeWorkspaceId).toBe("btf");
  });
  it("keeps the login screen usable when there is no accessible workspace", async () => {
    const profile = returningUser();
    vi.mocked(workspacesApi.listMine).mockResolvedValue([]);
    vi.mocked(workspacesApi.me).mockResolvedValue({ is_admin: false } as Awaited<ReturnType<typeof workspacesApi.me>>);
    const picked = vi.fn(); render(<WorkspacePicker profile={profile} onPicked={picked} />);
    await screen.findByText(/You don't have access to any workspace/);
    expect(picked).not.toHaveBeenCalled();
    expect(getRememberedWorkspaceId(profile)).toBeNull();
  });
});
