# yt-search

A lightweight CLI tool to search and stream YouTube audio directly in the terminal. No browser, no API key, no GUI.

## Branches

| Branch | Description |
|---|---|
| `main` | Current version — shells out to `yt-dlp` CLI, minimal memory footprint |
| `legacy-yt-dlp-api` | Original version — used `yt_dlp` Python API directly |

## Requirements

- Python 3.10+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) — `brew install yt-dlp`
- VLC — download from [videolan.org](https://www.videolan.org) and install to `/Applications`

## Setup

```bash
chmod +x setup.sh
./setup.sh
```

Run `./setup.sh` every time to launch. It checks dependencies and drops you into the search prompt.

## Usage

| Key | Action |
|---|---|
| `1-5` | Play result |
| `n` / `p` | Next / previous page |
| `s` | New search |
| `q` | Quit |
| `Ctrl+C` | Stop playback |

## How it works

Fetches 25 results in a single `yt-dlp` call using `ytsearch25:`, ranks them locally with a fuzzy scorer (`difflib.SequenceMatcher`) to avoid repeat network requests, then resolves the stream URL on demand when you pick a track. Audio plays via VLC in headless mode — no window, no browser.

## Benchmark

Measured on macOS 12, Python 3.14, yt-dlp 2026.03.17.

### Memory (while playing)

| Process | Legacy (API) | Current (CLI) |
|---|---|---|
| Python | 44 MB | 8 MB |
| VLC | 16 MB | 6.4 MB |

### Latency

| Operation | CLI | API |
|---|---|---|
| Search (25 results) | 2.67s avg | 1.95s avg |
| Stream URL resolution | 1.77s avg | 1.23s avg |

The CLI approach trades ~0.5–0.7s of latency per call for an 82% reduction in Python memory usage. For an interactive audio tool the latency difference is imperceptible.

### yt_dlp import cost
Importing `yt_dlp` into the Python process costs **14.8 MB** of peak memory — eliminated entirely in the current version.

## Files

| File | Purpose |
|---|---|
| `ytsearch.py` | Main script |
| `setup.sh` | Dependency check and launcher |
| `benchmark.py` | CLI vs API performance comparison |