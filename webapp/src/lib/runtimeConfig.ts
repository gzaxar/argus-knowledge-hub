/** An installation's addresses, set when it is deployed (config.js, from the Helm chart's web.runtimeConfig),
 * over those built into the image: one image serves every installation. */
export interface RuntimeConfig {
  apiBaseUrl?: string;
  oidcAuthority?: string;
  oidcClientId?: string;
  oidcTokenEndpoint?: string;
  oidcLabel?: string;
}

declare global {
  interface Window { __ARGUS_CONFIG__?: RuntimeConfig }
}

/** The installation's value, else the build's. An empty string set at deploy time clears the build's. */
export function setting(key: keyof RuntimeConfig, built: string | undefined): string | undefined {
  const deployed = typeof window !== "undefined" ? window.__ARGUS_CONFIG__?.[key] : undefined;
  return deployed !== undefined ? deployed || undefined : built || undefined;
}
