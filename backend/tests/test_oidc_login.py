"""The confidential-client endpoint must never become an unrestricted token proxy."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import requests
from starlette.requests import Request

from app.routers import oidc_login

REAL_EXCHANGE = oidc_login.exchange

ENV = {
    "OIDC_TOKEN_ENDPOINT": "https://idp.example/realms/aai/protocol/openid-connect/token",
    "OIDC_AUDIENCE": "argus-librechat", "OIDC_CLIENT_SECRET": "server-only-test-secret",
    "OIDC_REDIRECT_URIS": "http://localhost:5173/auth/callback",
}
FORM = {"grant_type": "authorization_code", "client_id": "argus-librechat", "code": "one-time-code",
        "redirect_uri": "http://localhost:5173/auth/callback", "code_verifier": "A" * 64}


class Upstream:
    status_code = 200

    def json(self):
        return {"access_token": "access", "id_token": "identity", "refresh_token": "refresh",
                "expires_in": 300, "token_type": "Bearer", "debug": ENV["OIDC_CLIENT_SECRET"]}


class TokenMediationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.upstream = patch.object(oidc_login, "exchange", return_value=Upstream()).start()
        self.addCleanup(patch.stopall)

    async def call(self, form=None, origin="http://localhost:5173", body=None, content_type=None):
        body = body if body is not None else urlencode(form if form is not None else FORM).encode()
        headers = [(b"content-type", (content_type or "application/x-www-form-urlencoded").encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return await oidc_login.token(Request({"type": "http", "headers": headers}, receive))

    async def test_code_exchange_adds_secret_only_upstream_and_never_caches(self):
        result = await self.call()
        self.assertEqual(result.status_code, 200)
        endpoint, data = self.upstream.call_args.args
        self.assertEqual(endpoint, ENV["OIDC_TOKEN_ENDPOINT"])
        self.assertEqual(data, {**FORM, "client_secret": ENV["OIDC_CLIENT_SECRET"]})
        self.assertNotIn(ENV["OIDC_CLIENT_SECRET"], result.body.decode())
        self.assertNotIn("debug", json.loads(result.body))
        self.assertNotEqual(json.loads(result.body)["refresh_token"], "refresh")
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(result.headers["pragma"], "no-cache")

    async def test_refresh_uses_same_server_credentials(self):
        result = await self.call({"grant_type": "refresh_token", "client_id": "argus-librechat",
                                  "refresh_token": oidc_login.wrap_refresh("refresh", ENV["OIDC_CLIENT_SECRET"], "argus-librechat", "http://localhost:5173"), "scope": "openid email profile"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.upstream.call_args.args[1]["client_secret"], ENV["OIDC_CLIENT_SECRET"])
        self.assertEqual(self.upstream.call_args.args[1]["refresh_token"], "refresh")

    async def test_only_refresh_tokens_issued_here_for_this_origin_may_refresh(self):
        for refresh in ["raw-upstream-token", "malformed", oidc_login.wrap_refresh(
                "refresh", ENV["OIDC_CLIENT_SECRET"], "argus-librechat", "https://other.example")]:
            result = await self.call({"grant_type": "refresh_token", "client_id": "argus-librechat",
                                      "refresh_token": refresh})
            self.assertEqual(result.status_code, 400)
            self.assertEqual(json.loads(result.body)["error"], "invalid_grant")
        self.upstream.assert_not_called()

    async def test_token_responses_bypass_persistent_idempotency(self):
        from app import idempotency
        async def handler(request):
            return "not persisted"
        request = Request({"type": "http", "method": "POST", "path": "/v1/auth/oidc/token",
                           "headers": [(b"idempotency-key", b"test"), (b"authorization", b"Bearer test")]})
        self.assertEqual(await idempotency.run(request, handler), "not persisted")

    async def test_unknown_or_missing_origin_is_refused(self):
        for origin in [None, "null", "https://attacker.example", "http://localhost:5173.attacker.example"]:
            with self.subTest(origin=origin):
                self.assertEqual((await self.call(origin=origin)).status_code, 403)
        self.upstream.assert_not_called()

    async def test_wrong_client_callback_or_missing_pkce_is_refused(self):
        for changes in [{"client_id": "other"}, {"redirect_uri": "https://attacker.example/callback"},
                        {"code_verifier": ""}, {"code_verifier": "short"}, {"code": ""},
                        {"client_secret": "browser-secret"}, {"token_endpoint": "https://attacker.example"}]:
            with self.subTest(fields=list(changes)):
                self.assertEqual((await self.call({**FORM, **changes})).status_code, 400)
        self.upstream.assert_not_called()

    async def test_origin_must_match_the_requested_callback(self):
        with patch.dict("os.environ", {"OIDC_REDIRECT_URIS": ENV["OIDC_REDIRECT_URIS"] + ",https://other.example/auth/callback"}):
            self.assertEqual((await self.call(origin="https://other.example")).status_code, 400)
        self.upstream.assert_not_called()

    async def test_password_and_client_credentials_grants_are_refused(self):
        for grant in ["password", "client_credentials", "urn:ietf:params:oauth:grant-type:token-exchange"]:
            self.assertEqual((await self.call({**FORM, "grant_type": grant})).status_code, 400)
        self.upstream.assert_not_called()

    async def test_refresh_scope_cannot_be_expanded(self):
        result = await self.call({"grant_type": "refresh_token", "client_id": "argus-librechat",
                                  "refresh_token": "refresh", "scope": "openid admin"})
        self.assertEqual(result.status_code, 400)
        self.upstream.assert_not_called()

    async def test_duplicate_parameters_and_large_or_wrong_content_are_refused(self):
        self.assertEqual((await self.call(body=urlencode(FORM).encode()+b"&client_id=other")).status_code, 400)
        self.assertEqual((await self.call(body=b"x" * (oidc_login.MAX_BODY + 1))).status_code, 413)
        self.assertEqual((await self.call(content_type="application/json")).status_code, 415)
        self.upstream.assert_not_called()

    async def test_incomplete_configuration_and_insecure_endpoint_fail_closed(self):
        for change in [{"OIDC_CLIENT_SECRET": ""}, {"OIDC_REDIRECT_URIS": ""},
                       {"OIDC_TOKEN_ENDPOINT": "http://idp.example/token"}]:
            with patch.dict("os.environ", change):
                result = await self.call()
                self.assertEqual(result.status_code, 503)
                self.assertNotIn(ENV["OIDC_CLIENT_SECRET"], result.body.decode())
        self.upstream.assert_not_called()

    async def test_provider_errors_are_sanitized(self):
        upstream = Upstream()
        upstream.status_code = 400
        upstream.json = lambda: {"error": "invalid_client", "error_description": ENV["OIDC_CLIENT_SECRET"]}
        self.upstream.return_value = upstream
        result = await self.call()
        self.assertEqual(result.status_code, 400)
        self.assertEqual(json.loads(result.body)["error"], "invalid_client")
        self.assertNotIn(ENV["OIDC_CLIENT_SECRET"], result.body.decode())

    async def test_network_and_invalid_provider_responses_are_sanitized(self):
        for exc in [requests.Timeout(ENV["OIDC_CLIENT_SECRET"]), ValueError(ENV["OIDC_CLIENT_SECRET"])]:
            self.upstream.side_effect = exc
            result = await self.call()
            self.assertEqual(result.status_code, 502)
            self.assertNotIn(ENV["OIDC_CLIENT_SECRET"], result.body.decode())

    def test_requests_does_not_forward_credentials_to_redirects(self):
        with patch.object(oidc_login.requests, "post") as post:
            REAL_EXCHANGE(ENV["OIDC_TOKEN_ENDPOINT"], {"client_secret": "test"})
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
            self.assertEqual(post.call_args.kwargs["timeout"], (5, 15))


class SeveralAudiencesTests(TokenMediationTests):
    """OIDC_AUDIENCE naming other trusted clients too: the login stays the first one's, and only it."""

    def setUp(self):
        super().setUp()
        patch.dict("os.environ", {"OIDC_AUDIENCE": "argus-librechat, another-trusted-client"}).start()

    async def test_the_first_audience_is_the_login_client(self):
        self.assertEqual((await self.call()).status_code, 200)
        self.assertEqual((await self.call({**FORM, "client_id": "another-trusted-client"})).status_code, 400)



if __name__ == "__main__":
    unittest.main()
