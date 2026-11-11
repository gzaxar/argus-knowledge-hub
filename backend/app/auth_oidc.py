"""Generic OIDC ID-token verification, independent of the identity provider.

Configured entirely via env vars (issuer, JWKS URL, audience) so switching from
Firebase to INFN's Keycloak is a config change, not a rewrite: only these
three values differ between providers, everything downstream (the User/Membership
model, permission checks) reads the same decoded claims regardless of issuer.

Firebase example values:
  OIDC_ISSUER   = https://securetoken.google.com/<firebase-project-id>
  OIDC_JWKS_URI = https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com
  OIDC_AUDIENCE = <firebase-project-id>

More than one provider can be trusted at once — Firebase for the accounts that
already exist and INFN's own IdP beside it, say. The three variables above name
the first; any others go in OIDC_EXTRA_PROVIDERS as a JSON list:

  OIDC_EXTRA_PROVIDERS='[{"issuer": "...", "jwks_uri": "...", "audience": "..."}]'

A token is checked against the provider whose issuer it names, never tried
against each in turn: a token signed by one provider must not be accepted
because another provider's key happened to verify it.

An audience may name several clients of the same provider, comma-separated
(or a list in OIDC_EXTRA_PROVIDERS): `argus-knowledge-hub,argus-librechat`
also accepts the access tokens INFN AAI issues to LibreChat, so an assistant
there calls ARGUS as the signed-in person. A token is accepted when its `aud`
names one of them or, for an access token issued to one of them, its `azp`
(Keycloak's access tokens carry the client in `azp`, and often only `account`
in `aud`). Clients not named stay refused.
"""
import json
import os
from functools import lru_cache

import jwt
from jwt import PyJWKClient

OIDC_ISSUER = os.environ.get("OIDC_ISSUER")
OIDC_JWKS_URI = os.environ.get("OIDC_JWKS_URI")
OIDC_AUDIENCE = os.environ.get("OIDC_AUDIENCE")


def load_providers() -> dict:
    """{issuer: {"jwks_uri", "audience"}} for every fully configured provider.
    A half-configured one (an issuer with no JWKS URL) is left out rather than
    trusted with whatever is missing."""
    found = {}
    candidates = [{"issuer": OIDC_ISSUER, "jwks_uri": OIDC_JWKS_URI, "audience": OIDC_AUDIENCE}]
    raw_extra = os.environ.get("OIDC_EXTRA_PROVIDERS")
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
        except ValueError:
            extra = []
        candidates += [p for p in extra if isinstance(p, dict)]
    for p in candidates:
        audiences = audiences_of(p.get("audience"))
        if p.get("issuer") and p.get("jwks_uri") and audiences:
            found[p["issuer"]] = {"jwks_uri": p["jwks_uri"], "audience": audiences}
    return found


def audiences_of(value) -> tuple:
    """The clients a provider's tokens may be for: "a,b", ["a", "b"] or "a"."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())


PROVIDERS = load_providers()


@lru_cache(maxsize=8)
def _jwk_client(jwks_uri: str) -> PyJWKClient:
    # A short timeout matters here: this runs inline while a request's DB
    # session is checked out (FastAPI dependency), so a slow/unreachable JWKS
    # endpoint would otherwise hold that connection for PyJWKClient's default
    # 30s timeout instead of failing fast.
    return PyJWKClient(jwks_uri, timeout=5)


def oidc_configured() -> bool:
    return bool(PROVIDERS)


def verify_oidc_token(raw_token: str) -> dict:
    """Returns the decoded claims, or raises jwt.PyJWTError if invalid."""
    # The issuer is read unverified only to choose whose keys to check the
    # signature against; nothing from these claims is trusted until it verifies.
    issuer = jwt.decode(raw_token, options={"verify_signature": False}).get("iss")
    provider = PROVIDERS.get(issuer)
    if provider is None:
        raise jwt.InvalidIssuerError("Token issuer is not a configured provider")
    signing_key = _jwk_client(provider["jwks_uri"]).get_signing_key_from_jwt(raw_token)
    claims = jwt.decode(
        raw_token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        options={"verify_aud": False, "require": ["exp", "iss"]},
    )
    # The audience by hand: one of the provider's clients in `aud`, or as the party the token was issued to.
    allowed = set(audiences_of(provider["audience"]))
    aud = claims.get("aud")
    auds = {aud} if isinstance(aud, str) else set(aud or [])
    if not (auds & allowed or claims.get("azp") in allowed):
        raise jwt.InvalidAudienceError("Token is not for this application")
    return claims
