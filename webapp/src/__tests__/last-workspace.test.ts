import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addOidcProfile, addProfile, clearSession, forgetRememberedWorkspace, getActiveProfile,
  getRememberedWorkspaceId, updateProfile,
} from "../api/session";

vi.mock("../api/firebase", () => ({ getFreshIdToken: vi.fn() }));
vi.mock("../api/infnAuth", () => ({ getInfnIdToken: vi.fn(), infnForgetSession: vi.fn() }));
const alice = { issuer: "https://login.example/realm", subject: "alice-subject" };
const bob = { issuer: "https://login.example/realm", subject: "bob-subject" };
const login = (identity = alice, baseUrl = "https://api.example", provider: "infn" | "firebase" = "infn") =>
  addOidcProfile("Same display name", baseUrl, provider, identity);

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe("remembering the last workspace", () => {
  it("survives logout and a new profile without using the workspace before access is checked", () => {
    const first = login();
    updateProfile(first.id, { activeWorkspaceId: "eli" });
    clearSession();
    expect(getActiveProfile()).toBeNull();
    const next = login();
    expect(next.id).not.toBe(first.id);
    expect(getRememberedWorkspaceId(next)).toBe("eli");
    expect(getActiveProfile()?.activeWorkspaceId).toBeUndefined();
  });
  it("keeps each account's last workspace separate even with identical display names", () => {
    const a = login(); updateProfile(a.id, { activeWorkspaceId: "eli" }); clearSession();
    const b = login(bob);
    expect(getRememberedWorkspaceId(b)).toBeNull();
    updateProfile(b.id, { activeWorkspaceId: "btf" }); clearSession();
    expect(getRememberedWorkspaceId(login())).toBe("eli");
    clearSession();
    expect(getRememberedWorkspaceId(login(bob))).toBe("btf");
  });
  it("isolates API servers, identity issuers and login providers", () => {
    const a = login(); updateProfile(a.id, { activeWorkspaceId: "eli" });
    expect(getRememberedWorkspaceId(login(alice, "https://other-api.example"))).toBeNull();
    expect(getRememberedWorkspaceId(login({ ...alice, issuer: "https://other-login.example" }))).toBeNull();
    expect(getRememberedWorkspaceId(login(alice, "https://api.example", "firebase"))).toBeNull();
    expect(getRememberedWorkspaceId(login(alice, "https://api.example/"))).toBe("eli");
  });
  it("remembers the workspace in the tab signing out while preserving other tabs' choices", () => {
    const a = login(); updateProfile(a.id, { activeWorkspaceId: "eli" });
    // Simulate another tab changing only the shared default.
    const profiles = JSON.parse(localStorage.getItem("assetmanagement.profiles")!);
    profiles[0].activeWorkspaceId = "btf";
    localStorage.setItem("assetmanagement.profiles", JSON.stringify(profiles));
    expect(getActiveProfile()?.activeWorkspaceId).toBe("eli");
    clearSession();
    expect(getRememberedWorkspaceId(login())).toBe("eli");
  });
  it("does not guess account identity for legacy profiles or PAT connections", () => {
    const legacy = addOidcProfile("Same display name", "https://api.example", "infn");
    updateProfile(legacy.id, { activeWorkspaceId: "eli" });
    expect(getRememberedWorkspaceId(legacy)).toBeNull();
    expect(getRememberedWorkspaceId(login())).toBeNull();
    expect(getRememberedWorkspaceId(addProfile("PAT", { baseUrl: "https://api.example", token: "test-token" }))).toBeNull();
  });
  it("can forget an inaccessible workspace", () => {
    const a = login(); updateProfile(a.id, { activeWorkspaceId: "eli" });
    forgetRememberedWorkspace(a);
    expect(getRememberedWorkspaceId(a)).toBeNull();
  });
  it("treats blocked preference storage as an optional feature", () => {
    const a = login();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(getRememberedWorkspaceId(a)).toBeNull();
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => forgetRememberedWorkspace(a)).not.toThrow();
  });
});
