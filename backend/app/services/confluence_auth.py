"""Authentication for saved Confluence imports; tokens stay in encrypted_secret.

cloud_basic uses an Atlassian account API token WITHOUT scopes against the site
URL. Scoped tokens and OAuth gateway URLs are intentionally separate future work.
"""
import base64
from urllib.parse import urlparse


def configure_confluence_session(session, base_url: str, token: str,
                                 auth_mode: str = "pat", email: str = "") -> str:
    token = (token or "").strip()
    if not token:
        raise ValueError("A Confluence token is required.")
    if auth_mode not in ("pat", "cloud_basic"):
        raise ValueError("Unknown Confluence authentication method.")
    base_url = (base_url or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Enter the Confluence server URL without embedded credentials.")
    if parsed.query or parsed.fragment or any(part in parsed.path.split("/") for part in ("spaces", "pages", "display", "x")):
        raise ValueError("The server URL must name the site, not a page. Put the page address in A page link.")
    session.headers.update({"Accept": "application/json"})
    if auth_mode == "cloud_basic":
        email = (email or "").strip()
        if not email or "@" not in email or ":" in email or any(c.isspace() for c in email):
            raise ValueError("Confluence Cloud requires your Atlassian account email.")
        if parsed.scheme != "https":
            raise ValueError("Confluence Cloud requires an HTTPS site URL.")
        if parsed.hostname == "api.atlassian.com":
            raise ValueError("This Cloud mode uses a token without scopes and the site URL, not the API gateway.")
        if parsed.path.rstrip("/") not in ("", "/wiki"):
            raise ValueError("For Cloud, use https://your-site.atlassian.net/wiki as the server URL.")
        base_url = f"{parsed.scheme}://{parsed.netloc}/wiki"
        encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        session.headers.update({"Authorization": f"Basic {encoded}"})
    else:
        session.headers.update({"Authorization": f"Bearer {token}"})
    return base_url


def reject_confluence_login(response) -> None:
    """A browser login (including HTTP 200/202 HTML) is never an API result."""
    location = response.headers.get("Location", "")
    url = getattr(response, "url", "") or ""
    if any(urlparse(value).hostname == "id.atlassian.com" for value in (url, location)):
        raise RuntimeError("Confluence redirected to Atlassian login. Check the authentication method, email and token.")


def confluence_json(response) -> dict:
    reject_confluence_login(response)
    if response.status_code in (401, 403):
        raise RuntimeError("Confluence refused the credentials. Check the authentication method, token and account permissions.")
    if response.status_code != 200:
        raise RuntimeError(f"Confluence API returned HTTP {response.status_code}.")
    if "json" not in response.headers.get("Content-Type", "").lower():
        raise RuntimeError("Confluence returned a web page instead of API JSON. Check the server URL and authentication.")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Confluence returned invalid API JSON.") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Confluence returned an unexpected API response.")
    return payload
