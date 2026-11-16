import { afterEach, describe, expect, it } from "vitest";
import { getActiveProfile, updateProfile } from "../api/session";

const PROFILES = "assetmanagement.profiles";
const ACTIVE = "assetmanagement.activeProfileId";

function signedIn(workspace: string) {
  localStorage.setItem(PROFILES, JSON.stringify([{ id: "p1", name: "me", baseUrl: "http://x", token: "", authType: "oidc",
                                                   activeWorkspaceId: workspace }]));
  localStorage.setItem(ACTIVE, "p1");
}

/** Another tab choosing a workspace: it writes the shared choice, not this tab's. */
function otherTabChooses(workspace: string) {
  const profiles = JSON.parse(localStorage.getItem(PROFILES)!);
  profiles[0].activeWorkspaceId = workspace;
  localStorage.setItem(PROFILES, JSON.stringify(profiles));
}

afterEach(() => { localStorage.clear(); sessionStorage.clear(); });

describe("each tab keeps its own workspace", () => {
  it("is not moved when another tab switches, and starts from the last choice when it has none", () => {
    signedIn("medium-linac");
    expect(getActiveProfile()?.activeWorkspaceId).toBe("medium-linac");     // a new tab: the last choice
    updateProfile("p1", { activeWorkspaceId: "medium-linac" });              // this tab chooses
    otherTabChooses("it-services");
    expect(getActiveProfile()?.activeWorkspaceId).toBe("medium-linac");     // still where it was
    updateProfile("p1", { activeWorkspaceId: "eupraxia" });                  // this tab moves on
    expect(getActiveProfile()?.activeWorkspaceId).toBe("eupraxia");
    sessionStorage.clear();                                                  // a tab opened later
    expect(getActiveProfile()?.activeWorkspaceId).toBe("eupraxia");
  });
});
