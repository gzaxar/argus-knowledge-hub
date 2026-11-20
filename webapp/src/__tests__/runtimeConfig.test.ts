import { afterEach, describe, expect, it, vi } from "vitest";
import { setting } from "../lib/runtimeConfig";

afterEach(() => { delete window.__ARGUS_CONFIG__; vi.unstubAllEnvs(); });

describe("an installation's addresses", () => {
  it("are the build's unless the installation sets its own", () => {
    expect(setting("apiBaseUrl", "https://built.example")).toBe("https://built.example");
    window.__ARGUS_CONFIG__ = { apiBaseUrl: "https://argus-hub-api.k8sda.lnf.infn.it" };
    expect(setting("apiBaseUrl", "https://built.example")).toBe("https://argus-hub-api.k8sda.lnf.infn.it");
  });

  it("an empty value set at deploy time clears the build's (no INFN login there)", () => {
    window.__ARGUS_CONFIG__ = { oidcTokenEndpoint: "" };
    expect(setting("oidcTokenEndpoint", "https://built.example/token")).toBeUndefined();
    expect(setting("oidcAuthority", undefined)).toBeUndefined();
  });
});
