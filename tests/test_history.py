import json
import pytest
import hearth
from hearth import load_history, save_to_history


SAMPLE_ENTRY = {
    "id": "abc123",
    "title": "Mozart Piano Concerto No. 9",
    "uploader": "Daniil Trifonov Fan",
    "duration": 2155,
    "played_at": "2026-04-22 20:00",
}


def test_load_history_missing_file(tmp_path, monkeypatch):
    """When no history file exists, load_history returns empty list without crashing."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    result = load_history()
    assert result == []


def test_load_history_corrupt_file(tmp_path, monkeypatch):
    """When history file contains invalid JSON, load_history returns empty list gracefully."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    history_file = tmp_path / ".hearth_history.json"
    history_file.write_text("this is not valid json {{{{")
    result = load_history()
    assert result == []


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    """Save an entry then load it back — data should be identical."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    save_to_history(SAMPLE_ENTRY)
    result = load_history()
    assert len(result) == 1
    assert result[0]["id"] == SAMPLE_ENTRY["id"]
    assert result[0]["title"] == SAMPLE_ENTRY["title"]


def test_history_capped_at_200(tmp_path, monkeypatch):
    """Saving 201 entries results in exactly 200 stored — oldest is dropped."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    for i in range(201):
        save_to_history({**SAMPLE_ENTRY, "id": f"id_{i}"})
    result = load_history()
    assert len(result) == 200


def test_dedup_consecutive_same_id(tmp_path, monkeypatch):
    """Playing the same track twice in a row only saves one entry."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    save_to_history(SAMPLE_ENTRY)
    save_to_history(SAMPLE_ENTRY)
    result = load_history()
    assert len(result) == 1


def test_dedup_allows_non_consecutive(tmp_path, monkeypatch):
    """Playing A, then B, then A again saves all three entries."""
    monkeypatch.setattr(hearth, "__file__", str(tmp_path / "hearth.py"))
    entry_a = {**SAMPLE_ENTRY, "id": "aaa"}
    entry_b = {**SAMPLE_ENTRY, "id": "bbb"}
    save_to_history(entry_a)
    save_to_history(entry_b)
    save_to_history(entry_a)
    result = load_history()
    assert len(result) == 3
    assert result[0]["id"] == "aaa"
    assert result[1]["id"] == "bbb"
    assert result[2]["id"] == "aaa"