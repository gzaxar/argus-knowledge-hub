import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  settings: vi.fn(), redirect: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("oidc-client-ts", () => ({
  UserManager: class {
    constructor(settings: unknown) { mocks.settings(settings); }
    signinRedirect = mocks.redirect;
  },
  WebStorageStateStore: class {},
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  vi.resetModules();
});

describe("direct INFN authentication", () => {
  async function configured() {
    vi.stubEnv("VITE_OIDC_AUTHORITY", "https://idp-test.app.infn.it/auth/realms/aai");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "argus-knowledge-hub");
    vi.stubEnv("VITE_OIDC_TOKEN_ENDPOINT", "");
    return import("../api/infnAuth");
  }

  it("uses the INFN realm and registered client for login and step-up", async () => {
    const auth = await configured();
    await auth.startInfnLogin();
    expect(mocks.settings).toHaveBeenCalledWith(expect.objectContaining({
      authority: "https://idp-test.app.infn.it/auth/realms/aai",
      client_id: "argus-knowledge-hub", response_type: "code",
    }));
    const settings = mocks.settings.mock.calls[0][0];
    expect(settings).not.toHaveProperty("client_secret");
    expect(settings).not.toHaveProperty("metadataSeed");
    expect(settings.disablePKCE).not.toBe(true);
    await auth.startStepUp("/admin");
    expect(mocks.redirect).toHaveBeenLastCalledWith({
      prompt: "login", max_age: 0, state: { stepUp: true, returnTo: "/admin" },
    });
  });

  it("does not send an intermediate broker hint", async () => {
    const auth = await configured();
    await auth.startInfnLogin();
    expect(mocks.settings.mock.calls[0][0]).not.toHaveProperty("extraQueryParams");
  });

  it("routes code exchange and refresh through the API without a browser secret", async () => {
    vi.stubEnv("VITE_OIDC_AUTHORITY", "https://idp-test.app.infn.it/auth/realms/aai");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "argus-librechat");
    vi.stubEnv("VITE_OIDC_TOKEN_ENDPOINT", "http://localhost:8080/v1/auth/oidc/token");
    const auth = await import("../api/infnAuth");
    await auth.startInfnLogin();
    const settings = mocks.settings.mock.calls[0][0];
    expect(settings.metadataSeed).toEqual({ token_endpoint: "http://localhost:8080/v1/auth/oidc/token" });
    expect(settings).not.toHaveProperty("client_secret");
    expect(settings.refreshTokenAllowedScope).toBe("openid email profile");
    expect(settings.authority).toBe("https://idp-test.app.infn.it/auth/realms/aai");
  });

  it("keeps login disabled unless authority and client ID are configured", async () => {
    vi.stubEnv("VITE_OIDC_AUTHORITY", "");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "");
    const auth = await import("../api/infnAuth");
    expect(auth.infnLoginEnabled).toBe(false);
    await expect(auth.startInfnLogin()).rejects.toThrow("not configured");
    expect(mocks.redirect).not.toHaveBeenCalled();
  });
});
