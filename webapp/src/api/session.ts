import { getFreshIdToken } from "./firebase";
import { getInfnIdToken, infnForgetSession } from "./infnAuth";

const LEGACY_KEY = "assetmanagement.session";
const PROFILES_KEY = "assetmanagement.profiles";
const ACTIVE_KEY = "assetmanagement.activeProfileId";

export type AuthType = "pat" | "oidc";
/** Who signed an "oidc" profile in. A profile saved before there was a choice has none, and is Firebase's. */
export type OidcProvider = "firebase" | "infn";

/** A saved way to connect: a PAT tied to one workspace, or a signed-in identity
 * that can act as any workspace it has membership in (activeWorkspaceId picks
 * which one, since one OIDC identity can span many workspaces unlike a PAT's
 * fixed 1:1 mapping). */
export interface Profile {
  id: string;
  name: string;
  baseUrl: string;
  authType: AuthType;
  token?: string; // "pat" only — a stored bearer token
  activeWorkspaceId?: string; // "oidc" only — which workspace this profile currently acts as
  provider?: OidcProvider; // "oidc" only — whose token this is; absent means "firebase"
}

/** What a request actually needs: a base URL, a bearer token (fetched fresh for
 * "oidc"), and — for "oidc" — the X-Workspace-Id header value. */
export interface ResolvedSession {
  baseUrl: string;
  authType: AuthType;
  token: string;
  workspaceId?: string;
}

function readProfiles(): Profile[] {
  try {
    const raw = localStorage.getItem(PROFILES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeProfiles(profiles: Profile[]): void {
  localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles));
}

/** One-time migration from the old single-session format. */
function migrateLegacy(): void {
  const raw = localStorage.getItem(LEGACY_KEY);
  if (!raw) return;
  try {
    const legacy = JSON.parse(raw) as { baseUrl: string; token: string };
    if (legacy.baseUrl && legacy.token) {
      const profile: Profile = {
        id: crypto.randomUUID(),
        name: "Default",
        baseUrl: legacy.baseUrl,
        token: legacy.token,
        authType: "pat",
      };
      writeProfiles([profile]);
      localStorage.setItem(ACTIVE_KEY, profile.id);
    }
  } catch {
    // ignore malformed legacy data
  }
  localStorage.removeItem(LEGACY_KEY);
}

export function listProfiles(): Profile[] {
  migrateLegacy();
  return readProfiles();
}

export function getActiveProfileId(): string | null {
  migrateLegacy();
  return localStorage.getItem(ACTIVE_KEY);
}

export function setActiveProfileId(id: string): void {
  localStorage.setItem(ACTIVE_KEY, id);
}

export function getActiveProfile(): Profile | null {
  const id = getActiveProfileId();
  const profiles = readProfiles();
  return profiles.find((p) => p.id === id) ?? profiles[0] ?? null;
}

export function updateProfile(id: string, patch: Partial<Profile>): void {
  const profiles = readProfiles().map((p) => (p.id === id ? { ...p, ...patch } : p));
  writeProfiles(profiles);
}

/** Used throughout api/client.ts — resolves the active profile into what a
 * request actually needs, fetching a fresh ID token from whichever provider
 * signed an "oidc" profile in. */
export async function loadSession(): Promise<ResolvedSession | null> {
  const profile = getActiveProfile();
  if (!profile) return null;

  if (profile.authType === "oidc") {
    const token = profile.provider === "infn" ? await getInfnIdToken() : await getFreshIdToken();
    if (!token) {
      // The provider ended the session (its idle timeout, or the person was
      // signed out elsewhere) and the refresh token went with it. Left alone
      // this is an app that shows nothing and says nothing; the sign-in screen
      // is the only useful place to be.
      if (profile.provider === "infn") {
        await infnForgetSession().catch(() => {});
        removeProfile(profile.id);
        window.location.reload();
      }
      return null;
    }
    return { baseUrl: profile.baseUrl, authType: "oidc", token, workspaceId: profile.activeWorkspaceId };
  }

  if (!profile.token) return null;
  return { baseUrl: profile.baseUrl, authType: "pat", token: profile.token };
}

export function addProfile(name: string, session: { baseUrl: string; token: string }): Profile {
  const profiles = readProfiles();
  const profile: Profile = { id: crypto.randomUUID(), name, authType: "pat", ...session };
  writeProfiles([...profiles, profile]);
  setActiveProfileId(profile.id);
  return profile;
}

/** Where the API is, for an identity that signed in rather than being handed a
 * token: set at build time for a deployment that knows, else a guess by host. */
export function defaultApiBaseUrl(): string {
  return (
    import.meta.env.VITE_API_BASE_URL ||
    (window.location.hostname.includes("localhost")
      ? "http://localhost:8000"
      : "https://argus-hub-api.90.147.174.30.myip.cloud.infn.it")
  );
}

export function addOidcProfile(name: string, baseUrl: string, provider: OidcProvider = "firebase"): Profile {
  const profiles = readProfiles();
  const profile: Profile = { id: crypto.randomUUID(), name, authType: "oidc", baseUrl, provider };
  writeProfiles([...profiles, profile]);
  setActiveProfileId(profile.id);
  return profile;
}

export function removeProfile(id: string): void {
  const profiles = readProfiles().filter((p) => p.id !== id);
  writeProfiles(profiles);
  if (getActiveProfileId() === id) {
    if (profiles.length > 0) {
      setActiveProfileId(profiles[0].id);
    } else {
      localStorage.removeItem(ACTIVE_KEY);
    }
  }
}

/** Forgets every saved workspace profile — back to the sign-in screen. */
export function clearSession(): void {
  localStorage.removeItem(LEGACY_KEY);
  localStorage.removeItem(PROFILES_KEY);
  localStorage.removeItem(ACTIVE_KEY);
}


/** Opens a page of another workspace: the profile moves there first (as the workspace switcher does). */
export function openInWorkspace(workspaceId: string | null | undefined, path: string, current: string | null): boolean {
  const profile = getActiveProfile();
  if (!workspaceId || workspaceId === current || profile?.authType !== "oidc") return false;
  updateProfile(profile.id, { activeWorkspaceId: workspaceId });
  window.location.assign(path);
  return true;
}

/** A link from an e-mail names its workspace (`?ws=…`): a signed-in profile moves there before the page loads,
 * and the parameter leaves the address. */
export function adoptWorkspaceFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    const ws = url.searchParams.get("ws");
    const profile = getActiveProfile();
    if (!ws || profile?.authType !== "oidc") return;
    if (profile.activeWorkspaceId !== ws) updateProfile(profile.id, { activeWorkspaceId: ws });
    url.searchParams.delete("ws");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  } catch {
    // Storage unavailable: the page opens in the workspace already chosen.
  }
}
