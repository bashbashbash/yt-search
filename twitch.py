"""
twitch.py — Twitch followed-channels integration via Helix API + PKCE OAuth

Public interface:
    is_available()      → (bool, str)   — config + API reachability check
    get_live_channels() → list[dict]    — live followed channels as entry dicts
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent
_CONFIG_PATH = _BASE_DIR / ".twitch_config"
_TOKEN_PATH = _BASE_DIR / ".twitch_token"

_DEFAULT_PORT = 8675
_AUTH_TIMEOUT = 60  # seconds to wait for browser callback
_EXPIRY_BUFFER = 60  # seconds before actual expiry to consider token expired


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------

class TwitchConfigError(Exception):
    """Raised when .twitch_config is missing or malformed."""


class TwitchAuthError(Exception):
    """Raised when OAuth flow fails or token cannot be refreshed."""


class TwitchAPIError(Exception):
    """Raised when a Helix API call returns a non-200 response."""


# ---------------------------------------------------------------------------
# Config & token I/O
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Read .twitch_config. Raises TwitchConfigError if absent or malformed.
    Injects default redirect_port=8675 if not specified."""
    if not _CONFIG_PATH.exists():
        raise TwitchConfigError(
            f"{_CONFIG_PATH} not found. "
            "Create it with your Twitch app client_id."
        )
    try:
        config = json.loads(_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise TwitchConfigError(f"Malformed {_CONFIG_PATH}: {exc}") from exc

    if "client_id" not in config:
        raise TwitchConfigError(
            f"{_CONFIG_PATH} must contain a 'client_id' field."
        )

    config.setdefault("redirect_port", _DEFAULT_PORT)
    return config


def load_token() -> dict | None:
    """Read .twitch_token. Returns None if file absent."""
    if not _TOKEN_PATH.exists():
        return None
    try:
        return json.loads(_TOKEN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_token(token: dict) -> None:
    """Write token dict to .twitch_token atomically."""
    tmp = _TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(token, indent=2))
    os.replace(tmp, _TOKEN_PATH)


def is_token_expired(token: dict) -> bool:
    """Return True if token is expired or within 60s of expiry."""
    expires_at = token.get("expires_at", 0)
    return time.time() >= (expires_at - _EXPIRY_BUFFER)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_pkce_pair() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for PKCE.
    verifier: 64 URL-safe random bytes
    challenge: base64url(sha256(verifier)) with padding stripped"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _build_auth_url(client_id: str, port: int, code_challenge: str) -> str:
    """Construct the Twitch OAuth2 authorize URL with PKCE params."""
    params = {
        "client_id": client_id,
        "redirect_uri": f"http://127.0.0.1:{port}/callback",
        "response_type": "code",
        "scope": "user:read:follows",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return (
        "https://id.twitch.tv/oauth2/authorize?"
        + urllib.parse.urlencode(params)
    )


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures a single OAuth callback."""

    def do_GET(self):  # noqa: N802 — required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if "error" in qs:
            self.server.auth_error = qs["error"][0]
            self.server.auth_code = None
        else:
            self.server.auth_code = qs.get("code", [None])[0]
            self.server.auth_error = None

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><p>Authorization complete. "
            b"You can close this tab.</p></body></html>"
        )

    def log_message(self, format, *args):  # noqa: A002
        pass  # suppress default stderr logging


def _start_callback_server(port: int, auth_url: str) -> str:
    """Bind localhost callback server, open browser, wait for code.
    Returns the authorization code. Raises TwitchAuthError on timeout
    or if the callback carries an error parameter."""
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = _AUTH_TIMEOUT
    server.auth_code = None
    server.auth_error = None

    webbrowser.open(auth_url)
    server.handle_request()  # blocks until one request or timeout
    server.server_close()

    if server.auth_error:
        raise TwitchAuthError(
            f"Twitch authorization denied: {server.auth_error}"
        )
    if server.auth_code is None:
        raise TwitchAuthError(
            "Timed out waiting for Twitch authorization callback."
        )
    return server.auth_code


def _exchange_code(
    client_id: str, code: str, code_verifier: str, port: int
) -> dict:
    """Exchange authorization code for tokens via Twitch token endpoint."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": f"http://127.0.0.1:{port}/callback",
    }).encode()

    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/token",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except Exception as exc:
        raise TwitchAuthError(f"Token exchange failed: {exc}") from exc

    body["expires_at"] = int(time.time()) + body.get("expires_in", 0)
    return body


def run_oauth_flow(client_id: str, port: int) -> dict:
    """Full PKCE OAuth orchestration.
    Generates PKCE pair, opens browser, waits for callback, exchanges code."""
    print("  Opening browser for Twitch authorization...")
    verifier, challenge = _generate_pkce_pair()
    auth_url = _build_auth_url(client_id, port, challenge)
    code = _start_callback_server(port, auth_url)
    token = _exchange_code(client_id, code, verifier, port)
    return token


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------

def refresh_access_token(token: dict, client_id: str) -> dict:
    """Refresh an expired access token using the refresh_token grant."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
    }).encode()

    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/token",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except Exception as exc:
        raise TwitchAuthError(f"Token refresh failed: {exc}") from exc

    body["expires_at"] = int(time.time()) + body.get("expires_in", 0)
    # preserve user_id if it was cached
    if "user_id" in token and "user_id" not in body:
        body["user_id"] = token["user_id"]
    return body


def ensure_valid_token(client_id: str, port: int) -> dict:
    """Load, refresh, or re-authorize as needed. Returns a valid token."""
    token = load_token()

    if token is None:
        token = run_oauth_flow(client_id, port)
        save_token(token)
        return token

    if not is_token_expired(token):
        return token

    # token is expired — try refresh
    try:
        token = refresh_access_token(token, client_id)
    except TwitchAuthError:
        logger.info("Refresh failed, starting full OAuth flow.")
        token = run_oauth_flow(client_id, port)

    save_token(token)
    return token


# ---------------------------------------------------------------------------
# Helix API
# ---------------------------------------------------------------------------

def _helix_get(
    path: str, params: dict, token: dict, client_id: str
) -> dict:
    """GET https://api.twitch.tv/helix/{path} with auth headers."""
    qs = urllib.parse.urlencode(params) if params else ""
    url = f"https://api.twitch.tv/helix/{path}"
    if qs:
        url = f"{url}?{qs}"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token['access_token']}")
    req.add_header("Client-Id", client_id)

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status != 200:
                raise TwitchAPIError(
                    f"Helix {path} returned {resp.status}"
                )
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise TwitchAPIError(
            f"Helix {path} returned {exc.code}: {exc.reason}"
        ) from exc
    except Exception as exc:
        if isinstance(exc, TwitchAPIError):
            raise
        raise TwitchAPIError(f"Helix request failed: {exc}") from exc


def get_user_id(token: dict, client_id: str) -> str:
    """Return the authenticated user's Twitch ID, caching in token dict."""
    if "user_id" in token:
        return token["user_id"]

    data = _helix_get("users", {}, token, client_id)
    user_id = data["data"][0]["id"]
    token["user_id"] = user_id
    save_token(token)
    return user_id


def fetch_live_followed(
    token: dict, client_id: str, user_id: str
) -> list[dict]:
    """Fetch live streams from followed channels and map to entry dicts."""
    data = _helix_get(
        "streams/followed",
        {"user_id": user_id},
        token,
        client_id,
    )
    return [_to_entry(stream) for stream in data.get("data", [])]


def _to_entry(stream: dict) -> dict:
    """Map a Helix stream object to the shared entry contract."""
    return {
        "id": stream["user_login"],
        "title": stream.get("title", ""),
        "uploader": stream.get("user_name", stream["user_login"]),
        "duration": None,
        "source": "twitch",
        "viewers": stream.get("viewer_count", 0),
        "game": stream.get("game_name", ""),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def is_available() -> tuple[bool, str]:
    """Check whether Twitch integration is configured and reachable.
    Does NOT check whether any channels are live."""
    try:
        load_config()
    except TwitchConfigError:
        return (False, "not configured")

    # lightweight reachability check — hit the Twitch OAuth validate endpoint
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate")
    try:
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError:
        # 401 is expected without a token — server is reachable
        return (True, "")
    except Exception:
        return (False, "service unreachable")

    return (True, "")


def get_live_channels() -> list[dict]:
    """Full orchestration: config → auth → fetch followed live streams.
    Returns [] on any failure (logs reason, never raises)."""
    try:
        config = load_config()
        client_id = config["client_id"]
        port = config["redirect_port"]

        token = ensure_valid_token(client_id, port)
        user_id = get_user_id(token, client_id)
        return fetch_live_followed(token, client_id, user_id)
    except Exception:
        logger.exception("get_live_channels failed")
        return []
