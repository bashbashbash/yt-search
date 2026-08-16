import subprocess
import pytest
from hearth import play, search_loop
from unittest.mock import patch, MagicMock


# ─── video_id extraction ──────────────────────────────────────────────────────
# These are regression tests for the bug where history entries used "video_id"
# instead of "id", causing playback to fail silently with an empty ID.

def test_video_id_from_search_entry():
    """Entry with 'id' key (yt-dlp search result format) returns correct video ID."""
    entry = {"id": "abc123", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("youtube.get_stream_url", return_value="https://stream.url") as mock_stream, \
         patch("hearth.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("hearth.save_to_history"), \
         patch("subprocess.run"):
        play(entry)
        mock_stream.assert_called_once_with("abc123")


def test_video_id_from_history_entry():
    """Entry saved by save_to_history also uses 'id' key — regression test for key mismatch bug."""
    entry = {"id": "xyz789", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("youtube.get_stream_url", return_value="https://stream.url") as mock_stream, \
         patch("hearth.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("hearth.save_to_history"), \
         patch("subprocess.run"):
        play(entry)
        mock_stream.assert_called_once_with("xyz789")


def test_video_id_missing_returns_none_stream():
    """Entry with no 'id' field passes None to get_stream_url, which returns None, play exits cleanly."""
    entry = {"title": "Test", "uploader": "Someone", "duration": 100}
    with patch("youtube.get_stream_url", return_value=None) as mock_stream, \
         patch("hearth.save_to_history"):
        play(entry)
        mock_stream.assert_called_once_with(None)


def test_play_does_not_save_history_on_failed_stream():
    """If stream URL resolution fails, history is not saved."""
    entry = {"id": "abc123", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("youtube.get_stream_url", return_value=None), \
         patch("hearth.save_to_history") as mock_save:
        play(entry)
        mock_save.assert_not_called()


# ─── Twitch playback via streamlink ──────────────────────────────────────────

def _twitch_entry(**overrides):
    base = {"id": "somechannel", "title": "Live Stream", "uploader": "SomeChannel",
            "duration": None, "source": "twitch"}
    base.update(overrides)
    return base


def test_twitch_play_calls_streamlink():
    """Twitch entry resolves stream URL via streamlink, then passes to player."""
    entry = _twitch_entry()
    fake_url = "https://video-weaver.fra02.hls.ttvnw.net/v1/playlist/abc.m3u8"
    streamlink_result = MagicMock(stdout=fake_url + "\n", returncode=0)

    with patch("subprocess.run", side_effect=[streamlink_result, None]) as mock_run, \
         patch("hearth.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("hearth.save_to_history"):
        play(entry)
        # First call: streamlink resolution
        sl_call = mock_run.call_args_list[0]
        assert "streamlink" in sl_call[0][0][0]
        assert "https://twitch.tv/somechannel" in sl_call[0][0]
        assert "best" in sl_call[0][0]
        # Second call: player launch with resolved URL
        player_call = mock_run.call_args_list[1]
        assert fake_url in player_call[0][0]


def test_twitch_play_fails_gracefully_on_empty_stream():
    """If streamlink returns empty output, play exits without launching player."""
    entry = _twitch_entry()
    streamlink_result = MagicMock(stdout="", returncode=1)

    with patch("subprocess.run", return_value=streamlink_result) as mock_run, \
         patch("hearth.save_to_history") as mock_save:
        play(entry)
        # Only one subprocess call (streamlink), no player launch
        assert mock_run.call_count == 1
        mock_save.assert_not_called()


def test_twitch_play_does_not_call_ytdlp():
    """Twitch entries must not call youtube.get_stream_url."""
    entry = _twitch_entry()
    streamlink_result = MagicMock(stdout="https://stream.url\n", returncode=0)

    with patch("subprocess.run", side_effect=[streamlink_result, None]), \
         patch("youtube.get_stream_url") as mock_yt, \
         patch("hearth.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("hearth.save_to_history"):
        play(entry)
        mock_yt.assert_not_called()


# ─── YouTube timeout + retry ─────────────────────────────────────────────────

def _yt_entry(**overrides):
    base = {"id": "abc123", "title": "Test Video", "uploader": "Someone",
            "duration": 100, "source": "youtube"}
    base.update(overrides)
    return base


def test_search_timeout_user_declines_retry(capsys):
    """First search times out, user declines retry, search_loop returns."""
    with patch("youtube.search", side_effect=subprocess.TimeoutExpired("yt-dlp", 5)), \
         patch("builtins.input", return_value="n"):
        search_loop("mozart")
    output = capsys.readouterr().out
    assert "taking longer than expected" in output


def test_search_timeout_user_retries_and_succeeds(capsys):
    """First search times out, user retries, second attempt returns results."""
    results = [{"id": "a", "title": "Mozart", "uploader": "X", "duration": 100}]
    with patch("youtube.search", side_effect=[subprocess.TimeoutExpired("yt-dlp", 5), results]), \
         patch("builtins.input", side_effect=["y", "q"]):
        search_loop("mozart")
    output = capsys.readouterr().out
    assert "taking longer than expected" in output
    assert "Results" in output


def test_search_timeout_both_attempts_fail(capsys):
    """Both search attempts time out, user sees 'not responding' message."""
    with patch("youtube.search", side_effect=subprocess.TimeoutExpired("yt-dlp", 5)), \
         patch("builtins.input", return_value="y"):
        search_loop("mozart")
    output = capsys.readouterr().out
    assert "not responding" in output


def test_play_stream_timeout_user_declines_retry(capsys):
    """Stream URL resolution times out, user declines, play returns without launching player."""
    entry = _yt_entry()
    with patch("youtube.get_stream_url", side_effect=subprocess.TimeoutExpired("yt-dlp", 5)), \
         patch("builtins.input", return_value="n"), \
         patch("hearth.save_to_history") as mock_save:
        play(entry)
    mock_save.assert_not_called()
    output = capsys.readouterr().out
    assert "taking longer than expected" in output


def test_play_stream_timeout_both_attempts_fail(capsys):
    """Both stream URL attempts time out, user sees 'not responding' message."""
    entry = _yt_entry()
    with patch("youtube.get_stream_url", side_effect=subprocess.TimeoutExpired("yt-dlp", 5)), \
         patch("builtins.input", return_value="y"), \
         patch("hearth.save_to_history") as mock_save:
        play(entry)
    mock_save.assert_not_called()
    output = capsys.readouterr().out
    assert "not responding" in output
