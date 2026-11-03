# Direct INFN Keycloak sign-in

## INFN AAI and Google, side by side

ARGUS keeps both: the web's **INFN login** signs in with INFN AAI (below), and its **Google** button with Google
(Firebase), as before. The API trusts every issuer it is given — `OIDC_ISSUER` and the `OIDC_EXTRA_PROVIDERS` list:

| | Production | Development (`docker compose`) |
|---|---|---|
| Web *INFN login* | INFN AAI (`release.yml`: `WEB_OIDC_AUTHORITY`, client `argus-knowledge-hub`) | the local Keycloak; INFN AAI with `--env-file deploy/infn-test.env` (or `.env.infn-local`) |
| Web *Google* | Google (Firebase), trusted as an extra provider | the same: compose trusts Google by default |
| Mobile app | ARGUS's Keycloak (and its Google sign-in), trusted beside INFN AAI while `keycloak.enabled` | the local Keycloak, trusted beside INFN AAI by `deploy/infn-test.env` |

The chart adds the bundled Keycloak to the trusted issuers by itself when `api.oidc` names another provider and
`keycloak.enabled` is on. The mobile app moves to INFN AAI once the client accepts its redirect
`it.infn.argus.field:/oauthredirect` (and the app is built with that issuer). People are matched by e-mail, so an
account keeps its roles whichever provider it signs in with, as long as the e-mail is the same.

ARGUS signs in directly to the INFN test realm using public client **`argus-knowledge-hub`** and
Authorization Code with PKCE S256. The browser exchanges and refreshes tokens directly with INFN;
there is no client secret and no token mediation through the ARGUS API. The API verifies ID tokens
with INFN's public keys and the `argus-knowledge-hub` audience. Workspace roles remain managed by ARGUS.

## INFN client registration

Use authority `https://idp-test.app.infn.it/auth/realms/aai`. The OIDC library obtains authorization,
token, JWKS and logout endpoints from its
[discovery document](https://idp-test.app.infn.it/auth/realms/aai/.well-known/openid-configuration).

On client `argus-knowledge-hub`, configure:

- Client authentication: off (public client).
- Standard Flow: on; PKCE method: S256.
- Local Valid Redirect URI: `http://localhost:5173/auth/callback`.
- Local Web Origin: `http://localhost:5173` (an origin has no trailing slash or callback path).
- Local Valid Post Logout Redirect URI: `http://localhost:5173/`.

For the current cloud deployment, separately authorize callback
`https://argus-hub.90.147.174.30.myip.cloud.infn.it/auth/callback`, Web Origin
`https://argus-hub.90.147.174.30.myip.cloud.infn.it` and post-logout redirect to that origin's `/`.

The old `argus-librechat` client and `/broker/corporate/endpoint` callback are not used.

## Local startup

`deploy/infn-test.env` contains the public frontend and API configuration. Copy it into the ignored
`.env.infn-local` file if you need a local administrator setting, then add:

```dotenv
ARGUS_BOOTSTRAP_ADMINS=your-account@lnf.infn.it
```

Start with:

```sh
docker compose --env-file .env.infn-local up -d --build --wait db api web
```

Or use `--env-file deploy/infn-test.env` for the shared defaults. Open `http://localhost:5173` and
start a fresh **INFN login**: sessions belonging to the former client cannot be reused by this client.

`OIDC_AUDIENCE` and `VITE_OIDC_CLIENT_ID` must both be `argus-knowledge-hub`. Keep
`OIDC_CLIENT_SECRET`, `OIDC_TOKEN_ENDPOINT`, `OIDC_REDIRECT_URIS` and `VITE_OIDC_TOKEN_ENDPOINT`
unset. No secret is needed. For Vite development, copy public `VITE_*` settings into
`webapp/.env.development` and set `VITE_API_BASE_URL=http://localhost:8080`.

## Kubernetes / release builds

Preview the INFN configuration after the environment values:

```sh
helm template argus charts/argus-knowledge-hub \
  -f charts/argus-knowledge-hub/values-production.yaml \
  -f charts/argus-knowledge-hub/values-infn-test.yaml
```

The overlay configures external token verification, requires no client secret and disables the
bundled Keycloak. Migrate any remaining clients using that Keycloak before applying it, including
mobile clients. Rendering does not change the cluster or the static web image.

For release web builds, set GitHub repository variables:

```text
OIDC_AUTHORITY=https://idp-test.app.infn.it/auth/realms/aai
OIDC_CLIENT_ID=argus-knowledge-hub
OIDC_LABEL=INFN login
```

Clear the optional `OIDC_TOKEN_ENDPOINT` repository variable if it was set for the confidential
client. For custom Docker builds, pass matching public `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`,
`VITE_OIDC_LABEL` and the deployment's `VITE_API_BASE_URL`; leave `VITE_OIDC_TOKEN_ENDPOINT` unset.

## Troubleshooting

- `Invalid parameter: redirect_uri`: authorize the exact callback above on the new client.
- `Failed to fetch` during token exchange: check Web Origins on the new client and verify Client
  Authentication is off. The old confidential client required a secret; this client does not.
- Old session or invalid state: start a new login from `/`, not a previous callback URL.
- Workspace access: the account and roles are identified by the INFN subject, so changing clients
  within the same realm should preserve the existing ARGUS account.

Verify login, refresh, logout and step-up against the actual new client. This is the INFN **test**
realm; obtain production realm and client settings before production use.

The optional confidential-client token mediation implementation remains available for other
installations, but is disabled in this configuration.
