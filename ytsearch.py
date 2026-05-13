#!/usr/bin/env python3
"""
ytsearch.py — CLI interface: platform menu, search interaction, playback, history
Requires: yt-dlp (brew install yt-dlp or standalone binary)
Requires: brew install mpv (or VLC app bundle)
"""

import datetime
import json
import sys
import subprocess
import shutil
import time
from pathlib import Path

import twitch
import youtube

PAGE_SIZE = 5
_TWITCH_CACHE_TTL = 300  # 5 minutes
_twitch_cache = {"status": "", "channels": [], "fetched_at": 0.0}


def _get_twitch_status() -> tuple[str, list[dict]]:
    """Return cached Twitch menu status, refreshing if stale (>5 min)."""
    if time.time() - _twitch_cache["fetched_at"] < _TWITCH_CACHE_TTL:
        return (_twitch_cache["status"], _twitch_cache["channels"])
    status, channels = twitch.get_menu_status()
    _twitch_cache["status"] = status
    _twitch_cache["channels"] = channels
    _twitch_cache["fetched_at"] = time.time()
    return (status, channels)


def _invalidate_twitch_cache():
    """Force next _get_twitch_status() call to re-fetch."""
    _twitch_cache["fetched_at"] = 0.0


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
    if history and history[0].get("id") == entry.get("id"):
        return  # don't save duplicate of most recent entry
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
    video_id = entry.get("id")
    title = entry.get("title", "Unknown")
    source = entry.get("source", "youtube")

    if source == "twitch":
        print(f"\n  ▶ Listening live: {title}")
        print(f"  ▶ twitch.tv/{video_id}")
        print("  ▶ Resolving stream via streamlink...")
        streamlink_bin = str(Path(sys.executable).parent / "streamlink")
        try:
            result = subprocess.run(
                [streamlink_bin, "--stream-url",
                 f"https://twitch.tv/{video_id}", "best"],
                capture_output=True, text=True, timeout=30,
            )
            stream_url = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            stream_url = None
        if not stream_url:
            print("  ✗ Could not resolve Twitch stream. Is the channel live?")
            return
    else:
        print(f"\n  ▶ Fetching stream for: {title}")
        print(f"  ▶ ID: {video_id}")
        stream_url = youtube.get_stream_url(video_id)
        if not stream_url:
            print("  ✗ Could not resolve stream URL.")
            return

    save_to_history({
        "title": title,
        "uploader": entry.get("uploader") or entry.get("channel") or "?",
        "duration": entry.get("duration"),
        "id": video_id,
        "source": source,
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
    ranked = youtube.search(query)
    if not ranked:
        print("  No results found.")
        return

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

def recent_prompt(history: list[dict]) -> str:
    """Returns 'quit', 'continue', or 'search'."""
    try:
        choice = input("\n  Play recent (1-5) or Enter to search: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Bye.")
        return "quit"
    if choice.lower() == "q":
        print("  Bye.")
        return "quit"
    elif choice.lower() == "h":
        history_loop(history)
        return "continue"
    elif choice.isdigit() and 1 <= int(choice) <= len(history[:5]):
        play(history[int(choice) - 1])
        return "continue"
    elif choice == "":
        return "search"
    else:
        search_loop(choice)
        return "continue"

def search_prompt(history: list[dict]) -> bool:
    """Handle search prompt interaction. Returns False to quit, True to continue."""
    try:
        query = input("\n  Search (or 'h' for history): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Bye.")
        return False
    if not query:
        return True
    if query.lower() == "q":
        print("  Bye.")
        return False
    elif query.lower() == "h":
        history_loop(history)
        return True
    else:
        search_loop(query)
        return True

def twitch_channel_menu(channels: list[dict]):
    """Display live Twitch channels and let user pick one to listen to."""
    print(f"\n{'─' * 55}")
    print(f"  Live channels  ({len(channels)})")
    print(f"{'─' * 55}")
    for i, ch in enumerate(channels, 1):
        title = ch.get("title", "")[:40]
        game = ch.get("game", "")
        viewers = ch.get("viewers", 0)
        uploader = ch.get("uploader", ch.get("id", "?"))
        print(f"  [{i}] {uploader}")
        print(f"      {title}")
        print(f"      {game}  •  {viewers:,} viewers")
    print(f"{'─' * 55}")
    print("  1-{}=listen  q=back".format(len(channels)))
    print(f"{'─' * 55}\n")

    choice = input("  > ").strip().lower()
    if choice == "q":
        return
    if choice.isdigit() and 1 <= int(choice) <= len(channels):
        play(channels[int(choice) - 1])


def platform_menu() -> str | None:
    """Show platform selection menu. Returns 'youtube', 'twitch', or None to quit."""
    yt_ok, yt_reason = youtube.is_available()
    twitch_status, _twitch_channels = _get_twitch_status()

    print(f"\n{'─' * 55}")
    print("  hearth")
    print(f"{'─' * 55}")
    if yt_ok:
        print("  [1] YouTube")
    else:
        print(f"  [1] YouTube  ({yt_reason})")
    if twitch_status:
        print(f"  [2] Twitch  ({twitch_status})")
    else:
        print("  [2] Twitch")
    print(f"{'─' * 55}")
    print("  1-2=select  q=quit")
    print(f"{'─' * 55}\n")

    choice = input("  > ").strip().lower()
    if choice == "q":
        return None
    elif choice == "1":
        if not yt_ok:
            print(f"\n  YouTube: {yt_reason}")
            return "back"
        return "youtube"
    elif choice == "2":
        if twitch_status == "not configured":
            print("\n  Twitch is not configured.")
            print("  Create .twitch_config with your client_id.")
            print("  See README for setup instructions.")
            return "back"
        elif twitch_status == "service unreachable":
            print(f"\n  Twitch: {twitch_status}")
            return "back"
        return "twitch"
    return "back"


def youtube_flow():
    """The original YouTube search/history loop."""
    while True:
        history = load_history()
        show_recent(history)
        if history:
            signal = recent_prompt(history)
            if signal == "quit":
                return
            elif signal == "search":
                if not search_prompt(history):
                    return
        else:
            if not search_prompt(history):
                return


def twitch_flow():
    """Fetch followed live channels and display selection menu."""
    status, channels = _get_twitch_status()
    if not channels:
        # not authorized or no one live — try full flow (triggers auth if needed)
        print("\n  Fetching live channels...")
        channels = twitch.get_live_channels()
        _invalidate_twitch_cache()
    if not channels:
        print("  No followed channels are live.")
        return
    twitch_channel_menu(channels)


def main():
    while True:
        choice = platform_menu()
        if choice is None:
            print("  Bye.")
            return
        elif choice == "youtube":
            youtube_flow()
        elif choice == "twitch":
            twitch_flow()
        # "back" loops to platform menu

if __name__ == "__main__":
    main()