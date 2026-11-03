"""Validate direct external OIDC configuration by rendering the actual Helm chart."""
from pathlib import Path
import subprocess
import unittest

CHART = Path(__file__).resolve().parents[1] / "argus-knowledge-hub"
BASE = "https://idp-test.app.infn.it/auth/realms/aai"


def render(*args):
    return subprocess.run(["helm", "template", "test", str(CHART), *args], text=True, capture_output=True)


class DirectOidcTests(unittest.TestCase):
    def test_default_keeps_local_keycloak(self):
        result = render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('name: OIDC_ISSUER, value: "https://keycloak.example.org/realms/argus"', result.stdout)
        self.assertIn("name: argus-keycloak-realm", result.stdout)

    def test_infn_overlay_trusts_infn_and_does_not_deploy_a_broker(self):
        result = render("-f", str(CHART / "values-production.yaml"),
                        "-f", str(CHART / "values-infn-test.yaml"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'name: OIDC_ISSUER, value: "{BASE}"', result.stdout)
        self.assertIn(f'name: OIDC_JWKS_URI, value: "{BASE}/protocol/openid-connect/certs"', result.stdout)
        self.assertIn('name: OIDC_AUDIENCE, value: "argus-knowledge-hub"', result.stdout)
        self.assertNotIn("name: argus-keycloak", result.stdout)
        self.assertNotIn("CORPORATE_CLIENT_SECRET", result.stdout)
        self.assertNotIn("name: OIDC_CLIENT_SECRET", result.stdout)
        self.assertNotIn("name: OIDC_TOKEN_ENDPOINT", result.stdout)
        # Existing secondary providers are retained when the environment enables them.
        self.assertIn("securetoken.google.com", result.stdout)

    def test_incomplete_external_provider_fails_closed(self):
        for field in ["issuer", "jwksUri", "audience"]:
            result = render("--set", f"api.oidc.{field}=configured")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("is required", result.stderr)

    def test_external_provider_can_coexist_with_local_keycloak_during_migration(self):
        result = render("-f", str(CHART / "values-infn-test.yaml"),
                        "--set", "keycloak.enabled=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'name: OIDC_ISSUER, value: "{BASE}"', result.stdout)
        self.assertNotIn('name: OIDC_ISSUER, value: "https://keycloak.example.org', result.stdout)
        self.assertIn("name: argus-keycloak-realm", result.stdout)


if __name__ == "__main__":
    unittest.main()
