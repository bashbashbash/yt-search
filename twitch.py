"""
twitch.py — Twitch followed-channels integration via Helix API + Device Code OAuth

Public interface:
    is_available()      → (bool, str)   — config + API reachability check
    get_live_channels() → list[dict]    — live followed channels as entry dicts
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent
_CONFIG_PATH = _BASE_DIR / ".twitch_config"
_TOKEN_PATH = _BASE_DIR / ".twitch_token"

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
    """Read .twitch_config. Raises TwitchConfigError if absent or malformed."""
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
# Device Code OAuth flow
# ---------------------------------------------------------------------------

def _request_device_code(client_id: str) -> dict:
    """Request a device code from Twitch. Returns the full response dict
    containing device_code, user_code, verification_uri, interval, expires_in."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scopes": "user:read:follows",
    }).encode()

    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/device",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        raise TwitchAuthError(
            f"Device code request failed: {exc} — {error_body}"
        ) from exc
    except Exception as exc:
        raise TwitchAuthError(
            f"Device code request failed: {exc}"
        ) from exc


def _poll_for_token(
    client_id: str, device_code: str, interval: int, expires_in: int
) -> dict:
    """Poll the token endpoint until the user authorizes or the code expires.
    Returns the token dict on success."""
    deadline = time.time() + expires_in

    while time.time() < deadline:
        time.sleep(interval)

        data = urllib.parse.urlencode({
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode()

        req = urllib.request.Request(
            "https://id.twitch.tv/oauth2/token",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
                body["expires_at"] = (
                    int(time.time()) + body.get("expires_in", 0)
                )
                return body
        except urllib.error.HTTPError as exc:
            error_body = json.loads(exc.read().decode())
            status = error_body.get("status", exc.code)
            message = error_body.get("message", "")

            if status == 400 and "authorization_pending" in message.lower():
                continue
            raise TwitchAuthError(
                f"Token poll failed: {message}"
            ) from exc

    raise TwitchAuthError(
        "Device code expired — user did not authorize in time."
    )


def run_oauth_flow(client_id: str) -> dict:
    """Device Code OAuth orchestration.
    Requests device code, prompts user, polls until authorized."""
    device = _request_device_code(client_id)

    print(f"\n  Go to: {device['verification_uri']}")
    print(f"  Enter code: {device['user_code']}")
    print("  Waiting for authorization...\n")

    token = _poll_for_token(
        client_id,
        device["device_code"],
        device.get("interval", 5),
        device.get("expires_in", 1800),
    )
    return token


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------

def refresh_access_token(token: dict, client_id: str) -> dict:
    """Refresh an expired access token using the refresh_token grant.
    Device Code refresh tokens are single-use — the new token is saved
    immediately to avoid losing it."""
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
    save_token(body)
    return body


def ensure_valid_token(client_id: str) -> dict:
    """Load, refresh, or re-authorize as needed. Returns a valid token."""
    token = load_token()

    if token is None:
        token = run_oauth_flow(client_id)
        save_token(token)
        return token

    if not is_token_expired(token):
        return token

    # token is expired — try refresh
    try:
        token = refresh_access_token(token, client_id)
    except TwitchAuthError:
        logger.info("Refresh failed, starting full OAuth flow.")
        token = run_oauth_flow(client_id)

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

def _check_reachable() -> bool:
    """Lightweight reachability check — hit the Twitch OAuth validate endpoint."""
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate")
    try:
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError:
        # 401 is expected without a token — server is reachable
        return True
    except Exception:
        return False
    return True


def get_menu_status() -> tuple[str, list[dict]]:
    """Return (status_label, channels) for the platform menu.
    Does NOT trigger the Device Code auth flow — returns 'not authorized'
    if there is no valid token.

    Status labels: 'not configured', 'service unreachable', 'not authorized',
    'no one live', or 'N live'."""
    try:
        config = load_config()
    except TwitchConfigError:
        return ("not configured", [])

    if not _check_reachable():
        return ("service unreachable", [])

    client_id = config["client_id"]
    token = load_token()

    if token is None:
        return ("not authorized", [])

    # try to ensure a valid (non-expired) token without triggering auth
    if is_token_expired(token):
        try:
            token = refresh_access_token(token, client_id)
        except TwitchAuthError:
            return ("not authorized", [])

    try:
        user_id = get_user_id(token, client_id)
        channels = fetch_live_followed(token, client_id, user_id)
    except (TwitchAPIError, TwitchAuthError):
        return ("not authorized", [])

    if not channels:
        return ("no one live", [])
    count = len(channels)
    return (f"{count} live", channels)


def get_live_channels() -> list[dict]:
    """Full orchestration: config → auth → fetch followed live streams.
    Triggers Device Code auth if needed.
    Returns [] on any failure (logs reason, never raises)."""
    try:
        config = load_config()
        client_id = config["client_id"]

        token = ensure_valid_token(client_id)
        user_id = get_user_id(token, client_id)
        return fetch_live_followed(token, client_id, user_id)
    except Exception:
        logger.exception("get_live_channels failed")
        return []
