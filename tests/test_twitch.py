"""
tests/test_twitch.py — unit + integration tests for twitch.py

Unit tests mock all HTTP; integration tests use real sockets but no network.
"""

import hashlib
import base64
import http.client
import json
import socket
import time
import threading
from unittest import mock

import pytest

import twitch


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestGeneratePkcePair:
    def test_verifier_is_url_safe(self):
        verifier, _ = twitch._generate_pkce_pair()
        # URL-safe base64 alphabet: A-Z a-z 0-9 - _
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert all(c in allowed for c in verifier)

    def test_challenge_is_sha256_of_verifier(self):
        verifier, challenge = twitch._generate_pkce_pair()
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = (
            base64.urlsafe_b64encode(expected_digest)
            .rstrip(b"=")
            .decode("ascii")
        )
        assert challenge == expected

    def test_pair_is_unique_across_calls(self):
        a = twitch._generate_pkce_pair()
        b = twitch._generate_pkce_pair()
        assert a[0] != b[0]


class TestIsTokenExpired:
    def test_not_expired(self):
        token = {"expires_at": time.time() + 3600}
        assert twitch.is_token_expired(token) is False

    def test_expired(self):
        token = {"expires_at": time.time() - 10}
        assert twitch.is_token_expired(token) is True

    def test_within_buffer(self):
        """Token expiring in 30s is treated as expired (60s buffer)."""
        token = {"expires_at": time.time() + 30}
        assert twitch.is_token_expired(token) is True

    def test_exactly_at_buffer_boundary(self):
        """Token expiring in exactly 60s is treated as expired (>= comparison)."""
        token = {"expires_at": time.time() + 60}
        assert twitch.is_token_expired(token) is True


class TestToEntry:
    def test_maps_helix_stream_to_entry(self):
        helix_stream = {
            "user_login": "shroud",
            "user_name": "shroud",
            "title": "just vibing",
            "game_name": "VALORANT",
            "viewer_count": 84201,
            "type": "live",
            "id": "99999999",
        }
        entry = twitch._to_entry(helix_stream)
        assert entry == {
            "id": "shroud",
            "title": "just vibing",
            "uploader": "shroud",
            "duration": None,
            "source": "twitch",
            "viewers": 84201,
            "game": "VALORANT",
        }

    def test_missing_optional_fields(self):
        helix_stream = {
            "user_login": "someone",
        }
        entry = twitch._to_entry(helix_stream)
        assert entry["id"] == "someone"
        assert entry["uploader"] == "someone"
        assert entry["title"] == ""
        assert entry["game"] == ""
        assert entry["viewers"] == 0
        assert entry["duration"] is None
        assert entry["source"] == "twitch"


class TestEnsureValidToken:
    """Three paths: valid token, expired→refresh, expired→refresh fails→re-auth."""

    def _make_token(self, expired=False):
        offset = -100 if expired else 3600
        return {
            "access_token": "tok123",
            "refresh_token": "ref456",
            "expires_at": time.time() + offset,
            "user_id": "789",
        }

    @mock.patch("twitch.save_token")
    @mock.patch("twitch.load_token")
    def test_valid_token_returned_as_is(self, mock_load, mock_save):
        token = self._make_token(expired=False)
        mock_load.return_value = token

        result = twitch.ensure_valid_token("cid", 8675)

        assert result is token
        mock_save.assert_not_called()

    @mock.patch("twitch.save_token")
    @mock.patch("twitch.refresh_access_token")
    @mock.patch("twitch.load_token")
    def test_expired_token_triggers_refresh(
        self, mock_load, mock_refresh, mock_save
    ):
        expired = self._make_token(expired=True)
        refreshed = self._make_token(expired=False)
        mock_load.return_value = expired
        mock_refresh.return_value = refreshed

        result = twitch.ensure_valid_token("cid", 8675)

        mock_refresh.assert_called_once_with(expired, "cid")
        assert result is refreshed
        mock_save.assert_called_once_with(refreshed)

    @mock.patch("twitch.save_token")
    @mock.patch("twitch.run_oauth_flow")
    @mock.patch("twitch.refresh_access_token")
    @mock.patch("twitch.load_token")
    def test_refresh_failure_triggers_reauth(
        self, mock_load, mock_refresh, mock_oauth, mock_save
    ):
        expired = self._make_token(expired=True)
        new_token = self._make_token(expired=False)
        mock_load.return_value = expired
        mock_refresh.side_effect = twitch.TwitchAuthError("refresh failed")
        mock_oauth.return_value = new_token

        result = twitch.ensure_valid_token("cid", 8675)

        mock_oauth.assert_called_once_with("cid", 8675)
        assert result is new_token
        mock_save.assert_called_once_with(new_token)

    @mock.patch("twitch.save_token")
    @mock.patch("twitch.run_oauth_flow")
    @mock.patch("twitch.load_token")
    def test_no_token_triggers_oauth(self, mock_load, mock_oauth, mock_save):
        new_token = self._make_token(expired=False)
        mock_load.return_value = None
        mock_oauth.return_value = new_token

        result = twitch.ensure_valid_token("cid", 8675)

        mock_oauth.assert_called_once_with("cid", 8675)
        assert result is new_token
        mock_save.assert_called_once_with(new_token)


class TestIsAvailable:
    @mock.patch("twitch.urllib.request.urlopen")
    @mock.patch("twitch.load_config")
    def test_not_configured(self, mock_config, mock_urlopen):
        mock_config.side_effect = twitch.TwitchConfigError("missing")

        ok, reason = twitch.is_available()

        assert ok is False
        assert reason == "not configured"
        mock_urlopen.assert_not_called()

    @mock.patch("twitch.urllib.request.urlopen")
    @mock.patch("twitch.load_config")
    def test_service_unreachable(self, mock_config, mock_urlopen):
        mock_config.return_value = {"client_id": "x", "redirect_port": 8675}
        mock_urlopen.side_effect = OSError("network down")

        ok, reason = twitch.is_available()

        assert ok is False
        assert reason == "service unreachable"

    @mock.patch("twitch.urllib.request.urlopen")
    @mock.patch("twitch.load_config")
    def test_reachable_via_401(self, mock_config, mock_urlopen):
        """A 401 from the validate endpoint means the server is reachable."""
        mock_config.return_value = {"client_id": "x", "redirect_port": 8675}
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None
        )

        ok, reason = twitch.is_available()

        assert ok is True
        assert reason == ""

    @mock.patch("twitch.urllib.request.urlopen")
    @mock.patch("twitch.load_config")
    def test_reachable_via_200(self, mock_config, mock_urlopen):
        mock_config.return_value = {"client_id": "x", "redirect_port": 8675}
        mock_urlopen.return_value.__enter__ = mock.Mock()
        mock_urlopen.return_value.__exit__ = mock.Mock(return_value=False)

        ok, reason = twitch.is_available()

        assert ok is True
        assert reason == ""


# ---------------------------------------------------------------------------
# Integration tests (real sockets, no network)
# ---------------------------------------------------------------------------

# Use a high port unlikely to conflict
_TEST_PORT = 18675


class TestCallbackServerReleasesPort:
    def test_returns_code_and_releases_port(self):
        """Start callback server in a thread, send a fake callback,
        verify code is returned and port is freed."""
        result = {}

        def run_server():
            try:
                # We need to pass an auth_url but we won't actually open a
                # browser — mock webbrowser.open to no-op.
                code = twitch._start_callback_server(
                    _TEST_PORT, "http://example.com"
                )
                result["code"] = code
            except Exception as exc:
                result["error"] = exc

        with mock.patch("twitch.webbrowser.open"):
            server_thread = threading.Thread(target=run_server)
            server_thread.start()

            # Give the server a moment to bind
            time.sleep(0.3)

            # Send fake callback
            conn = http.client.HTTPConnection("127.0.0.1", _TEST_PORT)
            conn.request("GET", "/callback?code=test123")
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()

            server_thread.join(timeout=5)

        assert "error" not in result, f"Server raised: {result.get('error')}"
        assert result["code"] == "test123"

        # Verify port is released
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(1)
            with pytest.raises(ConnectionRefusedError):
                sock.connect(("127.0.0.1", _TEST_PORT))
        finally:
            sock.close()


class TestCallbackServerTimeout:
    def test_timeout_raises_and_releases_port(self):
        """Start server, send nothing, assert TwitchAuthError and port freed."""
        result = {}

        # Use a very short timeout to keep the test fast
        original_timeout = twitch._AUTH_TIMEOUT

        def run_server():
            try:
                code = twitch._start_callback_server(
                    _TEST_PORT, "http://example.com"
                )
                result["code"] = code
            except twitch.TwitchAuthError as exc:
                result["error"] = exc
            except Exception as exc:
                result["unexpected"] = exc

        try:
            twitch._AUTH_TIMEOUT = 2  # 2 seconds for test speed

            with mock.patch("twitch.webbrowser.open"):
                # Patch HTTPServer to use our short timeout
                original_init = twitch.HTTPServer.__init__

                server_thread = threading.Thread(target=run_server)
                server_thread.start()
                server_thread.join(timeout=10)

            assert "unexpected" not in result, (
                f"Unexpected error: {result.get('unexpected')}"
            )
            assert "error" in result
            assert isinstance(result["error"], twitch.TwitchAuthError)

            # Verify port is released
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(1)
                with pytest.raises(ConnectionRefusedError):
                    sock.connect(("127.0.0.1", _TEST_PORT))
            finally:
                sock.close()

        finally:
            twitch._AUTH_TIMEOUT = original_timeout
