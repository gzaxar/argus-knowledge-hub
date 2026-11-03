"""Token mediation for a confidential OIDC client; the client secret stays on the API.

The SPA retains its existing state/nonce/PKCE handling and token storage. This is
not a cookie session or a general-purpose OAuth proxy. Only code + PKCE and
refresh grants for one configured client, origin and upstream are accepted.
"""
import base64
import hashlib
import json
import os
import re
from urllib.parse import parse_qsl, urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/v1/auth/oidc", tags=["auth"])
HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
MAX_BODY = 32768
TOKEN_FIELDS = {"access_token", "id_token", "refresh_token", "token_type", "expires_in",
                "refresh_expires_in", "scope", "session_state", "not-before-policy"}
ERRORS = {"invalid_grant": "The sign-in code or refresh token is invalid or expired. Sign in again.",
          "invalid_client": "The identity provider rejected the server's client credentials.",
          "unauthorized_client": "The identity provider refused this client or grant.",
          "invalid_scope": "The identity provider refused the requested scopes.",
          "access_denied": "The identity provider denied access.",
          "temporarily_unavailable": "The identity provider is temporarily unavailable."}


def failure(status, code, message):
    return JSONResponse({"error": code, "error_description": message}, status_code=status, headers=HEADERS)


def refresh_cipher(secret):
    # Separate key purpose from any other use of the client credential.
    key = hashlib.sha256(b"argus-oidc-refresh-v1:" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def wrap_refresh(raw, secret, client, origin):
    return refresh_cipher(secret).encrypt(json.dumps({
        "token": raw, "client": client, "origin": origin,
    }).encode()).decode()


def exchange(endpoint, data):
    # Never follow redirects with credentials, and never log request/response bodies.
    return requests.post(endpoint, data=data, timeout=(5, 15), allow_redirects=False)


@router.post("/token")
async def token(request: Request):
    endpoint = os.environ.get("OIDC_TOKEN_ENDPOINT", "")
    client = os.environ.get("OIDC_CLIENT_ID") or os.environ.get("OIDC_AUDIENCE", "")
    secret = os.environ.get("OIDC_CLIENT_SECRET", "")
    redirects = {uri.strip() for uri in os.environ.get("OIDC_REDIRECT_URIS", "").split(",") if uri.strip()}
    if not (endpoint and client and secret and redirects):
        return failure(503, "server_error", "Server-side OIDC login is not fully configured.")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query):
        return failure(503, "server_error", "The configured OIDC token endpoint must use HTTPS.")
    origin = request.headers.get("origin")
    origins = {f"{urlsplit(uri).scheme}://{urlsplit(uri).netloc}" for uri in redirects}
    if not origin or origin not in origins:
        return failure(403, "access_denied", "This web origin is not allowed to sign in.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
        return failure(415, "invalid_request", "Expected a form-encoded token request.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return failure(413, "invalid_request", "The token request is too large.")
    try:
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=10)
    except (ValueError, UnicodeDecodeError):
        return failure(400, "invalid_request", "Invalid token request.")
    fields = dict(pairs)
    if len(fields) != len(pairs):
        return failure(400, "invalid_request", "Duplicate token parameters are not allowed.")
    if fields.get("client_id") != client:
        return failure(400, "invalid_client", "This client is not configured for server-side sign-in.")
    grant = fields.get("grant_type")
    if grant == "authorization_code":
        allowed = {"grant_type", "client_id", "code", "redirect_uri", "code_verifier"}
        uri = fields.get("redirect_uri", "")
        if uri not in redirects or f"{urlsplit(uri).scheme}://{urlsplit(uri).netloc}" != origin:
            return failure(400, "invalid_request", "This sign-in callback is not allowed.")
        if not fields.get("code") or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", fields.get("code_verifier", "")):
            return failure(400, "invalid_request", "An authorization code and PKCE verifier are required.")
    elif grant == "refresh_token":
        allowed = {"grant_type", "client_id", "refresh_token", "scope"}
        if not fields.get("refresh_token"):
            return failure(400, "invalid_request", "A refresh token is required.")
        if not set(fields.get("scope", "").split()) <= {"openid", "email", "profile"}:
            return failure(400, "invalid_scope", "Only the configured sign-in scopes are allowed.")
    else:
        return failure(400, "unsupported_grant_type", "Only authorization code and refresh grants are supported.")
    if fields.keys() - allowed:
        return failure(400, "invalid_request", "Unsupported token parameters.")
    if grant == "refresh_token":
        try:
            saved = json.loads(refresh_cipher(secret).decrypt(fields["refresh_token"].encode()))
            if saved["client"] != client or saved["origin"] != origin or not saved["token"]:
                raise ValueError("Refresh binding mismatch")
            fields["refresh_token"] = saved["token"]
        except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
            return failure(400, "invalid_grant", "The refresh session is invalid. Sign in again.")
    fields["client_secret"] = secret
    try:
        response = await run_in_threadpool(exchange, endpoint, fields)
        payload = response.json()
    except (requests.RequestException, ValueError):
        return failure(502, "server_error", "The identity provider could not be reached or returned an invalid response.")
    if not isinstance(payload, dict):
        return failure(502, "server_error", "The identity provider returned an invalid response.")
    if response.status_code != 200:
        # Do not reflect arbitrary upstream bodies, error descriptions or credentials.
        error = payload.get("error")
        if not isinstance(error, str) or error not in ERRORS:
            error = "server_error"
        return failure(400 if response.status_code < 500 else 502, error,
                       ERRORS.get(error, "The identity provider refused the token request."))
    if not payload.get("access_token") or (grant == "authorization_code" and not payload.get("id_token")):
        return failure(502, "server_error", "The identity provider returned an incomplete token response.")
    result = {key: value for key, value in payload.items() if key in TOKEN_FIELDS}
    if result.get("refresh_token"):
        # Only sessions created here may refresh through this endpoint. An unrelated
        # refresh token from another app sharing this client cannot use our secret.
        result["refresh_token"] = wrap_refresh(result["refresh_token"], secret, client, origin)
    return JSONResponse(result, headers=HEADERS)
