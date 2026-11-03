/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The identity provider's issuer URL. Unset, and the "INFN login" button isn't offered. */
  readonly VITE_OIDC_AUTHORITY?: string;
  readonly VITE_OIDC_CLIENT_ID?: string;
  /** Optional API token mediation endpoint for a confidential client. Never a secret. */
  readonly VITE_OIDC_TOKEN_ENDPOINT?: string;
  /** What the button says. Defaults to "INFN login". */
  readonly VITE_OIDC_LABEL?: string;
  /** Where the API is, for a signed-in identity (a PAT is given its address by hand). */
  readonly VITE_API_BASE_URL?: string;
  /** The release, its commit and build time (the release workflow sets them; "dev" otherwise). */
  readonly VITE_APP_VERSION?: string;
  readonly VITE_APP_COMMIT?: string;
  readonly VITE_APP_BUILT_AT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
