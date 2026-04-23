import pytest
from ytsearch import play
from unittest.mock import patch, MagicMock


# ─── video_id extraction ──────────────────────────────────────────────────────
# These are regression tests for the bug where history entries used "video_id"
# instead of "id", causing playback to fail silently with an empty ID.

def test_video_id_from_search_entry():
    """Entry with 'id' key (yt-dlp search result format) returns correct video ID."""
    entry = {"id": "abc123", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("ytsearch.get_stream_url", return_value="https://stream.url") as mock_stream, \
         patch("ytsearch.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("ytsearch.save_to_history"), \
         patch("subprocess.run"):
        play(entry)
        mock_stream.assert_called_once_with("abc123")


def test_video_id_from_history_entry():
    """Entry saved by save_to_history also uses 'id' key — regression test for key mismatch bug."""
    entry = {"id": "xyz789", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("ytsearch.get_stream_url", return_value="https://stream.url") as mock_stream, \
         patch("ytsearch.get_player", return_value=("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")), \
         patch("ytsearch.save_to_history"), \
         patch("subprocess.run"):
        play(entry)
        mock_stream.assert_called_once_with("xyz789")


def test_video_id_missing_returns_none_stream():
    """Entry with no 'id' field passes None to get_stream_url, which returns None, play exits cleanly."""
    entry = {"title": "Test", "uploader": "Someone", "duration": 100}
    with patch("ytsearch.get_stream_url", return_value=None) as mock_stream, \
         patch("ytsearch.save_to_history"):
        play(entry)
        mock_stream.assert_called_once_with(None)


def test_play_does_not_save_history_on_failed_stream():
    """If stream URL resolution fails, history is not saved."""
    entry = {"id": "abc123", "title": "Test", "uploader": "Someone", "duration": 100}
    with patch("ytsearch.get_stream_url", return_value=None), \
         patch("ytsearch.save_to_history") as mock_save:
        play(entry)
        mock_save.assert_not_called()
