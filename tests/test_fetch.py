import json
import pytest
from unittest.mock import patch, MagicMock
from youtube import fetch_results, get_stream_url


def make_mock_result(stdout: str, returncode: int = 0):
    """Helper — creates a mock subprocess.CompletedProcess with given stdout."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


# ─── fetch_results ────────────────────────────────────────────────────────────

def test_fetch_results_parses_json_lines():
    """fetch_results correctly parses newline-delimited JSON from subprocess output."""
    entries = [
        {"id": "abc", "title": "Mozart Concerto", "uploader": "Someone"},
        {"id": "def", "title": "Beethoven Symphony", "uploader": "Someone"},
    ]
    stdout = "\n".join(json.dumps(e) for e in entries)
    with patch("subprocess.run", return_value=make_mock_result(stdout)):
        result = fetch_results("mozart")
    assert len(result) == 2
    assert result[0]["id"] == "abc"
    assert result[1]["id"] == "def"


def test_fetch_results_skips_invalid_lines():
    """Malformed JSON lines in subprocess output are skipped, valid ones returned."""
    valid = json.dumps({"id": "abc", "title": "Mozart", "uploader": "Someone"})
    stdout = f"{valid}\nnot valid json {{{{\n{valid}"
    with patch("subprocess.run", return_value=make_mock_result(stdout)):
        result = fetch_results("mozart")
    assert len(result) == 2


def test_fetch_results_empty_output():
    """Empty subprocess output returns empty list without crashing."""
    with patch("subprocess.run", return_value=make_mock_result("")):
        result = fetch_results("mozart")
    assert result == []


# ─── get_stream_url ───────────────────────────────────────────────────────────

def test_get_stream_url_returns_url():
    """Mocked subprocess returns a URL string, get_stream_url returns it stripped."""
    fake_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=xyz"
    with patch("subprocess.run", return_value=make_mock_result(f"  {fake_url}  \n")):
        result = get_stream_url("abc123")
    assert result == fake_url


def test_get_stream_url_empty_returns_none():
    """Empty subprocess output returns None."""
    with patch("subprocess.run", return_value=make_mock_result("")):
        result = get_stream_url("abc123")
    assert result is None


def test_get_stream_url_whitespace_only_returns_none():
    """Whitespace-only subprocess output returns None."""
    with patch("subprocess.run", return_value=make_mock_result("   \n  ")):
        result = get_stream_url("abc123")
    assert result is None
