"""
youtube.py — YouTube data adapter: search, rank, stream URL resolution
Public interface: is_available(), search(query), get_stream_url(video_id)
"""

import json
import shutil
import subprocess
from difflib import SequenceMatcher

FETCH_COUNT = 25  # fetch once, rank locally — avoids repeat requests


def is_available() -> tuple[bool, str]:
    """Check whether yt-dlp is on PATH."""
    if shutil.which("yt-dlp"):
        return (True, "ok")
    return (False, "yt-dlp not found")


def fetch_results(query: str) -> list[dict]:
    result = subprocess.run(
        [
            "yt-dlp",
            f"ytsearch{FETCH_COUNT}:{query}",
            "--dump-json",
            "--flat-playlist",
            "--no-warnings",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    entries = []
    for line in result.stdout.strip().splitlines():
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def fuzzy_score(query: str, entry: dict) -> float:
    title = (entry.get("title") or "").lower()
    uploader = (entry.get("uploader") or "").lower()
    q = query.lower()
    title_score = SequenceMatcher(None, q, title).ratio()
    # boost if all query words appear in title
    word_bonus = sum(w in title for w in q.split()) / max(len(q.split()), 1)
    uploader_score = SequenceMatcher(None, q, uploader).ratio() * 0.3
    return title_score * 0.6 + word_bonus * 0.3 + uploader_score


def rank_results(query: str, entries: list[dict]) -> list[dict]:
    scored = [(fuzzy_score(query, e), e) for e in entries if e.get("title")]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored]


def search(query: str) -> list[dict]:
    """Fetch YouTube results and return them ranked by relevance."""
    raw = fetch_results(query)
    return rank_results(query, raw)


def get_stream_url(video_id: str) -> str | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    result = subprocess.run(
        [
            "yt-dlp",
            url,
            "--get-url",
            "-f", "bestaudio",
            "--no-warnings",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    stream = result.stdout.strip()
    return stream if stream else None
