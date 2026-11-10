"""Credential and API-response checks that need no database or live Atlassian site.

Run from the repository root:
    python -m unittest discover -s backend/tests -p test_confluence_auth.py
with PYTHONPATH=backend, or use pytest inside the usual backend test environment.
"""
import base64
import unittest
from types import SimpleNamespace

from app.services.confluence_auth import (
    configure_confluence_session, confluence_json, reject_confluence_login,
)


def response(status=200, payload=None, content_type="application/json", url="https://site.atlassian.net/wiki/rest/api/space", location=""):
    return SimpleNamespace(status_code=status, url=url,
                           headers={"Content-Type": content_type, "Location": location},
                           json=lambda: {"results": []} if payload is None else payload)


class ConfluenceAuthTests(unittest.TestCase):
    def setUp(self):
        self.session = SimpleNamespace(headers={})

    def test_existing_pat_default_is_unchanged(self):
        base = configure_confluence_session(self.session, "https://wiki.example.org/confluence/", "secret")
        self.assertEqual(base, "https://wiki.example.org/confluence")
        self.assertEqual(self.session.headers["Authorization"], "Bearer secret")

    def test_cloud_uses_email_and_token_and_adds_wiki(self):
        base = configure_confluence_session(self.session, "https://site.atlassian.net", "token", "cloud_basic", " user@example.org ")
        self.assertEqual(base, "https://site.atlassian.net/wiki")
        encoded = self.session.headers["Authorization"].removeprefix("Basic ")
        self.assertEqual(base64.b64decode(encoded).decode(), "user@example.org:token")

    def test_cloud_keeps_single_wiki_prefix(self):
        self.assertEqual(configure_confluence_session(self.session, "https://site.atlassian.net/wiki/", "token", "cloud_basic", "u@example.org"), "https://site.atlassian.net/wiki")

    def test_cloud_requires_email(self):
        for email in ("", "invalid", "a:b@example.org", "user @example.org"):
            with self.subTest(email=email), self.assertRaisesRegex(ValueError, "email"):
                configure_confluence_session(self.session, "https://site.atlassian.net/wiki", "token", "cloud_basic", email)

    def test_empty_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "token is required"):
            configure_confluence_session(self.session, "https://wiki.example.org", "  ")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            configure_confluence_session(self.session, "https://wiki.example.org", "token", "unknown")

    def test_cloud_requires_https(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            configure_confluence_session(self.session, "http://site.atlassian.net", "token", "cloud_basic", "u@example.org")

    def test_server_field_cannot_contain_page_address(self):
        with self.assertRaisesRegex(ValueError, "not a page"):
            configure_confluence_session(self.session, "https://site.atlassian.net/wiki/spaces/ELI/overview", "token")

    def test_embedded_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "embedded credentials"):
            configure_confluence_session(self.session, "https://user:secret@site.atlassian.net", "token")

    def test_scoped_gateway_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "without scopes"):
            configure_confluence_session(self.session, "https://api.atlassian.com/ex/confluence/id", "token", "cloud_basic", "u@example.org")

    def test_json_is_returned(self):
        self.assertEqual(confluence_json(response(payload={"id": "123"})), {"id": "123"})

    def test_html_success_is_not_an_api_response(self):
        with self.assertRaisesRegex(RuntimeError, "web page"):
            confluence_json(response(content_type="text/html"))

    def test_atlassian_login_202_is_authentication_error(self):
        with self.assertRaisesRegex(RuntimeError, "Atlassian login"):
            confluence_json(response(status=202, url="https://id.atlassian.com/login", content_type="text/html"))

    def test_login_redirect_is_not_followed_as_api_success(self):
        with self.assertRaisesRegex(RuntimeError, "Atlassian login"):
            reject_confluence_login(response(status=302, location="https://id.atlassian.com/login"))

    def test_credential_refusal_is_clear(self):
        for status in (401, 403):
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, "credentials"):
                confluence_json(response(status=status))

    def test_json_array_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            confluence_json(response(payload=[]))

    def test_malformed_json_is_rejected(self):
        def invalid():
            raise ValueError("bad JSON")
        resp = response()
        resp.json = invalid
        with self.assertRaisesRegex(RuntimeError, "invalid API JSON"):
            confluence_json(resp)


if __name__ == "__main__":
    unittest.main()
