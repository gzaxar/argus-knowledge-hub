"""Trusting more than one identity provider at once.

What matters: a token is checked against the provider whose issuer it names and
no other, so adding INFN's IdP beside Firebase cannot let one provider's signing
key vouch for a token the other issued.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth_oidc

FIREBASE = {"issuer": "https://securetoken.example/firebase", "jwks_uri": "https://fb/jwks", "audience": "fb-project"}
INFN = {"issuer": "https://idp.example/realms/infn", "jwks_uri": "https://infn/jwks", "audience": "argus-webapp"}


class Key:
    def __init__(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, provider, **claims):
        body = {"iss": provider["issuer"], "aud": provider["audience"], "sub": "u1",
                "email": "a@b.test", "exp": int(time.time()) + 300, **claims}
        return jwt.encode(body, self.private, algorithm="RS256")


class FakeClient:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _raw):
        class Signing:
            key = self.key.private.public_key()
        return Signing()


@pytest.fixture()
def two_providers(monkeypatch):
    firebase_key, infn_key = Key(), Key()
    monkeypatch.setattr(auth_oidc, "PROVIDERS", {
        FIREBASE["issuer"]: {"jwks_uri": FIREBASE["jwks_uri"], "audience": FIREBASE["audience"]},
        INFN["issuer"]: {"jwks_uri": INFN["jwks_uri"], "audience": INFN["audience"]},
    })
    clients = {FIREBASE["jwks_uri"]: FakeClient(firebase_key), INFN["jwks_uri"]: FakeClient(infn_key)}
    monkeypatch.setattr(auth_oidc, "_jwk_client", lambda uri: clients[uri])
    return firebase_key, infn_key


def test_each_provider_verifies_its_own_tokens(two_providers):
    firebase_key, infn_key = two_providers
    assert auth_oidc.verify_oidc_token(firebase_key.token(FIREBASE))["email"] == "a@b.test"
    assert auth_oidc.verify_oidc_token(infn_key.token(INFN))["iss"] == INFN["issuer"]


def test_one_providers_key_cannot_vouch_for_the_others_issuer(two_providers):
    firebase_key, infn_key = two_providers
    forged = firebase_key.token(INFN)          # names INFN as issuer, signed with Firebase's key
    with pytest.raises(jwt.PyJWTError):
        auth_oidc.verify_oidc_token(forged)


def test_an_unknown_issuer_is_refused(two_providers):
    firebase_key, _ = two_providers
    other = {"issuer": "https://evil.example", "audience": "x"}
    with pytest.raises(jwt.InvalidIssuerError):
        auth_oidc.verify_oidc_token(firebase_key.token(other))


def test_the_audience_must_be_the_providers_own(two_providers):
    _, infn_key = two_providers
    with pytest.raises(jwt.PyJWTError):
        auth_oidc.verify_oidc_token(infn_key.token(INFN, aud="someone-elses-client"))


def test_an_expired_token_is_refused(two_providers):
    _, infn_key = two_providers
    with pytest.raises(jwt.ExpiredSignatureError):
        auth_oidc.verify_oidc_token(infn_key.token(INFN, exp=int(time.time()) - 10))


def test_providers_come_from_the_primary_variables_and_the_extra_list(monkeypatch):
    monkeypatch.setattr(auth_oidc, "OIDC_ISSUER", FIREBASE["issuer"])
    monkeypatch.setattr(auth_oidc, "OIDC_JWKS_URI", FIREBASE["jwks_uri"])
    monkeypatch.setattr(auth_oidc, "OIDC_AUDIENCE", FIREBASE["audience"])
    monkeypatch.setenv("OIDC_EXTRA_PROVIDERS", '[{"issuer": "%s", "jwks_uri": "%s", "audience": "%s"}, '
                       '{"issuer": "half-configured"}]' % (INFN["issuer"], INFN["jwks_uri"], INFN["audience"]))
    assert set(auth_oidc.load_providers()) == {FIREBASE["issuer"], INFN["issuer"]}      # half-configured is left out


def test_nothing_configured_means_oidc_is_off(monkeypatch):
    monkeypatch.setattr(auth_oidc, "PROVIDERS", {})
    assert auth_oidc.oidc_configured() is False


def test_a_malformed_extra_list_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setattr(auth_oidc, "OIDC_ISSUER", None)
    monkeypatch.setenv("OIDC_EXTRA_PROVIDERS", "not json")
    assert auth_oidc.load_providers() == {}


def test_one_provider_may_name_several_clients_and_only_those(monkeypatch):
    """INFN AAI's tokens for LibreChat call ARGUS as the person: accepted when the client is named, by aud or azp."""
    key = Key()
    monkeypatch.setattr(auth_oidc, "PROVIDERS", {INFN["issuer"]: {
        "jwks_uri": INFN["jwks_uri"], "audience": auth_oidc.audiences_of("argus-webapp, argus-librechat")}})
    monkeypatch.setattr(auth_oidc, "_jwk_client", lambda uri: FakeClient(key))
    assert auth_oidc.verify_oidc_token(key.token(INFN, aud="argus-librechat"))["sub"] == "u1"
    # Keycloak's access token: the client in azp, only "account" in aud.
    assert auth_oidc.verify_oidc_token(key.token(INFN, aud="account", azp="argus-librechat"))["sub"] == "u1"
    assert auth_oidc.verify_oidc_token(key.token(INFN, aud=["account", "argus-webapp"]))["sub"] == "u1"
    for claims in ({"aud": "account", "azp": "someone-else"}, {"aud": "account"}, {"aud": "other", "azp": None}):
        with pytest.raises(jwt.InvalidAudienceError):
            auth_oidc.verify_oidc_token(key.token(INFN, **claims))


def test_audiences_are_read_from_a_comma_list_or_a_json_list(monkeypatch):
    monkeypatch.setattr(auth_oidc, "OIDC_ISSUER", INFN["issuer"])
    monkeypatch.setattr(auth_oidc, "OIDC_JWKS_URI", INFN["jwks_uri"])
    monkeypatch.setattr(auth_oidc, "OIDC_AUDIENCE", "argus-knowledge-hub, argus-librechat")
    monkeypatch.setenv("OIDC_EXTRA_PROVIDERS", '[{"issuer": "x", "jwks_uri": "y", "audience": ["a", "b"]}]')
    found = auth_oidc.load_providers()
    assert found[INFN["issuer"]]["audience"] == ("argus-knowledge-hub", "argus-librechat")
    assert found["x"]["audience"] == ("a", "b")
