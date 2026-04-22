#!/usr/bin/env python3
"""
ytsearch.py — fuzzy YouTube audio search & stream in the CLI
Requires: yt-dlp (brew install yt-dlp or standalone binary)
Requires: brew install mpv (or VLC app bundle)
"""

import datetime
import json
import sys
import subprocess
import shutil
from pathlib import Path
from difflib import SequenceMatcher

PAGE_SIZE = 5
FETCH_COUNT = 25  # fetch once, rank locally — avoids repeat requests


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


def format_duration(seconds) -> str:
    if not seconds:
        return "?:??"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"

def load_history() -> list[dict]:
    history_file = Path(__file__).parent / ".yt_search_history.json"
    if not history_file.exists():
        return []
    try:
        return json.loads(history_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    
def save_to_history(entry: dict):
    history_file = Path(__file__).parent / ".yt_search_history.json"
    history = load_history()
    history.insert(0, entry)
    history = history[:200]
    try:
        history_file.write_text(json.dumps(history, indent=2))
    except OSError:
        pass

def show_recent(history: list[dict]):
    if not history:
        return
    recent = history[:5]
    print(f"\n  {'─' * 55}")
    print("  Recent plays:")
    for i, entry in enumerate(recent, 1):
        title = entry.get("title", "Unknown")[:45]
        uploader = entry.get("uploader", "?")[:30]
        print(f"  [{i}] {title}")
        print(f"      {uploader}")
    print(f"  {'─' * 55}")

def print_page(entries: list[dict], page: int, total_pages: int):
    start = page * PAGE_SIZE
    page_entries = entries[start : start + PAGE_SIZE]
    print(f"\n{'─' * 55}")
    print(f"  Results  (page {page + 1}/{total_pages})")
    print(f"{'─' * 55}")
    for i, entry in enumerate(page_entries, 1):
        title = entry.get("title", "Unknown")[:50]
        uploader = entry.get("uploader") or entry.get("channel") or "?"
        duration = format_duration(entry.get("duration"))
        print(f"  [{i}] {title}")
        print(f"      {uploader}  •  {duration}")
    print(f"{'─' * 55}")
    print("  n=next  p=prev  1-5=play  q=quit  s=new search")
    print(f"{'─' * 55}\n")
    return page_entries


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


def get_player() -> tuple[str, str] | None:
    """Read player from .player config, fall back to PATH detection."""
    config = Path(__file__).parent / ".player"
    if config.exists():
        name = config.read_text().strip()
        if name == "vlc":
            return ("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")
        path = shutil.which(name)
        if path:
            return (name, path)
    # fallback
    for name in ("mpv", "ffplay"):
        path = shutil.which(name)
        if path:
            return (name, path)
    if Path("/Applications/VLC.app/Contents/MacOS/VLC").exists():
        return ("vlc", "/Applications/VLC.app/Contents/MacOS/VLC")
    return None


def play(entry: dict):
    video_id = entry.get("id") or entry.get("url", "").split("v=")[-1]
    title = entry.get("title", "Unknown")
    print(f"\n  ▶ Fetching stream for: {title}")
    print(f"  ▶ ID: {video_id}")

    stream_url = get_stream_url(video_id)
    if not stream_url:
        print("  ✗ Could not resolve stream URL.")
        return
    save_to_history({
        "title": title,
        "uploader": entry.get("uploader") or entry.get("channel") or "?",
        "duration": format_duration(entry.get("duration")),
        "video_id": video_id,
    "played_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    player = get_player()
    if not player:
        sys.exit("No player found. Re-run setup.sh for instructions.")

    name, path = player
    print(f"  ▶ Playing via {name} — Ctrl+C to stop\n")
    try:
        if name == "mpv":
            subprocess.run([path, "--no-video", "--really-quiet", stream_url])
        elif name == "vlc":
            subprocess.run([path, "--intf", "dummy", "--play-and-exit",
                            "--no-video", stream_url])
        else:  # ffplay
            subprocess.run([path, "-nodisp", "-autoexit", "-i", stream_url])
    except KeyboardInterrupt:
        print("\n  ■ Stopped.")


def search_loop(query: str):
    print(f"\n  Searching for: {query!r} ...")
    raw = fetch_results(query)
    if not raw:
        print("  No results found.")
        return

    ranked = rank_results(query, raw)
    total_pages = (len(ranked) + PAGE_SIZE - 1) // PAGE_SIZE
    page = 0

    while True:
        page_entries = print_page(ranked, page, total_pages)
        choice = input("  > ").strip().lower()

        if choice == "q":
            return
        elif choice == "s":
            return  # back to outer search prompt
        elif choice == "n":
            page = min(page + 1, total_pages - 1)
        elif choice == "p":
            page = max(page - 1, 0)
        elif choice.isdigit() and 1 <= int(choice) <= len(page_entries):
            play(page_entries[int(choice) - 1])
        else:
            print("  Invalid input.")

def history_loop(history: list[dict]):
    if not history:
        print("\n  No history yet.")
        return

    PAGE = 10
    total_pages = (len(history) + PAGE - 1) // PAGE
    page = 0

    while True:
        start = page * PAGE
        page_entries = history[start : start + PAGE]
        print(f"\n  {'─' * 55}")
        print(f"  History  (page {page + 1}/{total_pages})")
        print(f"  {'─' * 55}")
        for i, entry in enumerate(page_entries, 1):
            title = entry.get("title", "Unknown")[:45]
            uploader = entry.get("uploader", "?")
            duration = entry.get("duration", "?:??")
            played_at = entry.get("played_at", "")
            print(f"  [{i:2}] {title}")
            print(f"       {uploader}  •  {duration}  •  {played_at}")
        print(f"  {'─' * 55}")
        print("  n=next  p=prev  1-10=play  d=delete all  q=back")
        print(f"  {'─' * 55}\n")

        choice = input("  > ").strip().lower()

        if choice == "q":
            return
        elif choice == "n":
            page = min(page + 1, total_pages - 1)
        elif choice == "p":
            page = max(page - 1, 0)
        elif choice == "d":
            delete_history()
            return
        elif choice.isdigit() and 1 <= int(choice) <= len(page_entries):
            play(page_entries[int(choice) - 1])
        else:
            print("  Invalid input.")

def delete_history():
    history_file = Path(__file__).parent / ".yt_search_history.json"
    confirm = input("\n  Delete all history? (y/n): ").strip().lower()
    if confirm == "y":
        try:
            history_file.unlink()
            print("  ✓ History deleted.")
        except OSError:
            print("  ✗ Could not delete history file.")
    else:
        print("  Cancelled.")

def main():
    print("\n  yt audio search  (yt-dlp + mpv)")
    history = load_history()
    show_recent(history)
    while True:
        try:
            query = input("\n  Search (or 'h' for history): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye.")
            break
        if not query:
            continue
        if query.lower() == "h":
            history = load_history()
            history_loop(history)
        elif query.lower() == "q":
            print("  Bye.")
            break
        else:
            search_loop(query)


if __name__ == "__main__":
    main()