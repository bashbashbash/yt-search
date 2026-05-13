#!/usr/bin/env python3
"""
benchmark.py — baseline performance snapshot for hearth
Run: .venv/bin/python benchmark.py
"""
import datetime
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

# ─── Test targets ────────────────────────────────────────────────────────────
YOUTUBE_VIDEO_ID = "BeZ5QxP4m2Y"  # Mozart Piano Concerto No. 17
TWITCH_CHANNEL = "loaboratory"     # 24/7 lo-fi beats
RUNS = 3

STREAMLINK_BIN = str(Path(sys.executable).parent / "streamlink")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_rss_mb() -> float:
    """Current max RSS in MB. macOS reports bytes, Linux reports KB."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return raw / (1024 * 1024)
    return raw / 1024  # Linux


def get_version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        # streamlink prefixes its version with "streamlink " — strip it
        return out.removeprefix("streamlink ")
    except FileNotFoundError:
        return "not found"


def resolve_youtube(video_id: str) -> float:
    """Time a yt-dlp stream URL resolution. Returns seconds."""
    start = time.perf_counter()
    subprocess.run(
        ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
         "--get-url", "-f", "bestaudio", "--no-warnings", "--quiet"],
        capture_output=True, text=True,
    )
    return time.perf_counter() - start


def resolve_twitch(channel: str) -> float | None:
    """Time a streamlink stream URL resolution. Returns seconds, or None if offline."""
    start = time.perf_counter()
    result = subprocess.run(
        [STREAMLINK_BIN, "--stream-url",
         f"https://twitch.tv/{channel}", "best"],
        capture_output=True, text=True, timeout=30,
    )
    elapsed = time.perf_counter() - start
    if not result.stdout.strip():
        return None
    return elapsed


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    separator = "─" * 48

    # ── Environment ──
    py_version = platform.python_version()
    ytdlp_version = get_version(["yt-dlp", "--version"])
    sl_version = get_version([STREAMLINK_BIN, "--version"])
    os_version = f"{platform.system()} {platform.mac_ver()[0] or platform.release()}"

    print(f"\n  hearth baseline — {timestamp}")
    print(f"  {separator}\n")
    print(f"  Environment")
    print(f"    Python:     {py_version}")
    print(f"    yt-dlp:     {ytdlp_version}")
    print(f"    streamlink: {sl_version}")
    print(f"    OS:         {os_version}")

    results = {
        "timestamp": timestamp,
        "environment": {
            "python": py_version,
            "yt_dlp": ytdlp_version,
            "streamlink": sl_version,
            "os": os_version,
        },
    }

    # ── Startup (import time) ──
    print(f"\n  Startup")
    start = time.perf_counter()
    import hearth  # noqa: F401
    import_time = time.perf_counter() - start
    print(f"    import time: {import_time:.3f}s")
    results["startup_import_s"] = round(import_time, 3)

    # ── Memory: idle ──
    rss_idle = get_rss_mb()

    # ── Stream URL resolution ──
    print(f"\n  Stream URL resolution ({RUNS} runs)")

    yt_times = [resolve_youtube(YOUTUBE_VIDEO_ID) for _ in range(RUNS)]
    yt_avg = sum(yt_times) / RUNS
    print(f"    YouTube  avg: {yt_avg:.2f}s  runs: {[round(t, 2) for t in yt_times]}")

    twitch_times_raw = [resolve_twitch(TWITCH_CHANNEL) for _ in range(RUNS)]
    twitch_offline = any(t is None for t in twitch_times_raw)

    if twitch_offline:
        print(f"    Twitch   ⚠ SKIPPED — '{TWITCH_CHANNEL}' is offline or unreachable")
        print(f"             The 24/7 test channel may be temporarily down.")
        print(f"             To test with a different channel, edit TWITCH_CHANNEL in benchmark.py.")
        twitch_times = []
        tw_avg = None
    else:
        twitch_times = twitch_times_raw
        tw_avg = sum(twitch_times) / RUNS
        print(f"    Twitch   avg: {tw_avg:.2f}s  runs: {[round(t, 2) for t in twitch_times]}")

    results["resolution"] = {
        "youtube": {
            "avg_s": round(yt_avg, 2),
            "runs_s": [round(t, 2) for t in yt_times],
            "video_id": YOUTUBE_VIDEO_ID,
        },
        "twitch": {
            "avg_s": round(tw_avg, 2) if tw_avg else None,
            "runs_s": [round(t, 2) for t in twitch_times],
            "channel": TWITCH_CHANNEL,
            "skipped": twitch_offline,
        },
    }

    # ── Memory: post-resolution ──
    rss_post = get_rss_mb()
    print(f"\n  Memory (peak RSS)")
    print(f"    idle:            {rss_idle:.1f} MB")
    print(f"    post-resolution: {rss_post:.1f} MB")

    results["memory_mb"] = {
        "idle": round(rss_idle, 1),
        "post_resolution": round(rss_post, 1),
    }

    print(f"\n  {separator}\n")

    # ── Write JSON snapshot ──
    out = Path(__file__).parent / ".benchmark_results.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"  Snapshot saved to {out.name}\n")


if __name__ == "__main__":
    main()
