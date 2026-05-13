"""
tests/test_twitch.py — unit tests for twitch.py (Device Code OAuth flow)

All HTTP calls are mocked — no network required.
"""

import json
import time
from unittest import mock
from urllib.error import HTTPError
from io import BytesIO

import pytest

import twitch


# ---------------------------------------------------------------------------
# Unit tests — token expiry
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Unit tests — entry mapping
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Unit tests — Device Code flow
# ---------------------------------------------------------------------------

def _mock_urlopen_response(body: dict):
    """Create a mock context manager that returns body as JSON."""
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(body).encode()
    resp.status = 200
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _mock_http_error(status: int, body: dict):
    """Create an HTTPError with a JSON body."""
    fp = BytesIO(json.dumps(body).encode())
    return HTTPError(
        url="", code=status, msg="Bad Request", hdrs=None, fp=fp
    )


class TestRequestDeviceCode:
    @mock.patch("twitch.urllib.request.urlopen")
    def test_returns_device_code_response(self, mock_urlopen):
        expected = {
            "device_code": "dev123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://www.twitch.tv/activate",
            "interval": 5,
            "expires_in": 1800,
        }
        mock_urlopen.return_value = _mock_urlopen_response(expected)

        result = twitch._request_device_code("my_client_id")

        assert result == expected

    @mock.patch("twitch.urllib.request.urlopen")
    def test_raises_on_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_http_error(
            400, {"status": 400, "message": "invalid client"}
        )

        with pytest.raises(twitch.TwitchAuthError, match="invalid client"):
            twitch._request_device_code("bad_client_id")


class TestPollForToken:
    @mock.patch("twitch.time.sleep")
    @mock.patch("twitch.urllib.request.urlopen")
    def test_returns_token_after_pending(self, mock_urlopen, mock_sleep):
        """First poll returns authorization_pending, second returns token."""
        pending_error = _mock_http_error(
            400, {"status": 400, "message": "authorization_pending"}
        )
        token_body = {
            "access_token": "tok123",
            "refresh_token": "ref456",
            "expires_in": 3600,
            "scope": ["user:read:follows"],
            "token_type": "bearer",
        }
        mock_urlopen.side_effect = [
            pending_error,
            _mock_urlopen_response(token_body),
        ]

        result = twitch._poll_for_token("cid", "dev123", 5, 1800)

        assert result["access_token"] == "tok123"
        assert result["refresh_token"] == "ref456"
        assert "expires_at" in result
        assert mock_sleep.call_count == 2

    @mock.patch("twitch.time.sleep")
    @mock.patch("twitch.urllib.request.urlopen")
    def test_raises_on_non_pending_error(self, mock_urlopen, mock_sleep):
        """A non-pending error (e.g. access_denied) raises immediately."""
        mock_urlopen.side_effect = _mock_http_error(
            400, {"status": 400, "message": "access_denied"}
        )

        with pytest.raises(twitch.TwitchAuthError, match="access_denied"):
            twitch._poll_for_token("cid", "dev123", 5, 1800)

    @mock.patch("twitch.time.time")
    @mock.patch("twitch.time.sleep")
    @mock.patch("twitch.urllib.request.urlopen")
    def test_raises_on_expiry(self, mock_urlopen, mock_sleep, mock_time):
        """Raises TwitchAuthError when device code expires."""
        # First call to time.time() sets deadline, second exceeds it
        mock_time.side_effect = [100.0, 2000.0]

        with pytest.raises(twitch.TwitchAuthError, match="expired"):
            twitch._poll_for_token("cid", "dev123", 5, 1800)

        mock_urlopen.assert_not_called()


class TestRunOauthFlow:
    @mock.patch("twitch._poll_for_token")
    @mock.patch("twitch._request_device_code")
    @mock.patch("builtins.print")
    def test_orchestrates_device_code_flow(
        self, mock_print, mock_request, mock_poll
    ):
        mock_request.return_value = {
            "device_code": "dev123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://www.twitch.tv/activate",
            "interval": 5,
            "expires_in": 1800,
        }
        expected_token = {"access_token": "tok", "expires_at": 9999}
        mock_poll.return_value = expected_token

        result = twitch.run_oauth_flow("my_cid")

        assert result is expected_token
        mock_request.assert_called_once_with("my_cid")
        mock_poll.assert_called_once_with("my_cid", "dev123", 5, 1800)


# ---------------------------------------------------------------------------
# Unit tests — token lifecycle
# ---------------------------------------------------------------------------

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

        result = twitch.ensure_valid_token("cid")

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

        result = twitch.ensure_valid_token("cid")

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

        result = twitch.ensure_valid_token("cid")

        mock_oauth.assert_called_once_with("cid")
        assert result is new_token
        mock_save.assert_called_once_with(new_token)

    @mock.patch("twitch.save_token")
    @mock.patch("twitch.run_oauth_flow")
    @mock.patch("twitch.load_token")
    def test_no_token_triggers_oauth(self, mock_load, mock_oauth, mock_save):
        new_token = self._make_token(expired=False)
        mock_load.return_value = None
        mock_oauth.return_value = new_token

        result = twitch.ensure_valid_token("cid")

        mock_oauth.assert_called_once_with("cid")
        assert result is new_token
        mock_save.assert_called_once_with(new_token)


# ---------------------------------------------------------------------------
# Unit tests — get_menu_status
# ---------------------------------------------------------------------------

class TestGetMenuStatus:
    def _make_token(self, expired=False):
        offset = -100 if expired else 3600
        return {
            "access_token": "tok123",
            "refresh_token": "ref456",
            "expires_at": time.time() + offset,
            "user_id": "789",
        }

    @mock.patch("twitch.load_config")
    def test_not_configured(self, mock_config):
        mock_config.side_effect = twitch.TwitchConfigError("missing")

        status, channels = twitch.get_menu_status()

        assert status == "not configured"
        assert channels == []

    @mock.patch("twitch._check_reachable", return_value=False)
    @mock.patch("twitch.load_config", return_value={"client_id": "x"})
    def test_service_unreachable(self, mock_config, mock_reachable):
        status, channels = twitch.get_menu_status()

        assert status == "service unreachable"
        assert channels == []

    @mock.patch("twitch._check_reachable", return_value=True)
    @mock.patch("twitch.load_token", return_value=None)
    @mock.patch("twitch.load_config", return_value={"client_id": "x"})
    def test_not_authorized(self, mock_config, mock_token, mock_reachable):
        status, channels = twitch.get_menu_status()

        assert status == "not authorized"
        assert channels == []

    @mock.patch("twitch._check_reachable", return_value=True)
    @mock.patch("twitch.fetch_live_followed", return_value=[])
    @mock.patch("twitch.get_user_id", return_value="789")
    @mock.patch("twitch.load_token")
    @mock.patch("twitch.load_config", return_value={"client_id": "x"})
    def test_no_one_live(
        self, mock_config, mock_token, mock_uid, mock_fetch, mock_reachable
    ):
        mock_token.return_value = self._make_token(expired=False)

        status, channels = twitch.get_menu_status()

        assert status == "no one live"
        assert channels == []

    @mock.patch("twitch._check_reachable", return_value=True)
    @mock.patch("twitch.fetch_live_followed")
    @mock.patch("twitch.get_user_id", return_value="789")
    @mock.patch("twitch.load_token")
    @mock.patch("twitch.load_config", return_value={"client_id": "x"})
    def test_channels_live(
        self, mock_config, mock_token, mock_uid, mock_fetch, mock_reachable
    ):
        mock_token.return_value = self._make_token(expired=False)
        live = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        mock_fetch.return_value = live

        status, channels = twitch.get_menu_status()

        assert status == "3 live"
        assert channels == live

    @mock.patch("twitch._check_reachable", return_value=True)
    @mock.patch("twitch.save_token")
    @mock.patch("twitch.refresh_access_token")
    @mock.patch("twitch.load_token")
    @mock.patch("twitch.load_config", return_value={"client_id": "x"})
    def test_expired_token_refresh_fails_returns_not_authorized(
        self, mock_config, mock_token, mock_refresh, mock_save, mock_reachable
    ):
        mock_token.return_value = self._make_token(expired=True)
        mock_refresh.side_effect = twitch.TwitchAuthError("refresh failed")

        status, channels = twitch.get_menu_status()

        assert status == "not authorized"
        assert channels == []
