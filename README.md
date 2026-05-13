# hearth

A lightweight CLI tool to search and listen to YouTube audio and live Twitch streams directly in the terminal. No browser, no GUI.

## Requirements

- Python 3.10+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) — `brew install yt-dlp`
- An audio player: [mpv](https://mpv.io) (recommended), [VLC](https://www.videolan.org), or ffplay
- [`streamlink`](https://streamlink.github.io) — installed automatically by `setup.sh` for Twitch stream resolution

## Setup

```bash
chmod +x setup.sh
./setup.sh
```

Run `./setup.sh` every time to launch. It checks dependencies and drops you into the platform menu.

## Usage

On launch you pick a platform:

```
  hearth
  ───────────────────────────────────────────────
  [1] YouTube
  [2] Twitch  (3 live)
  ───────────────────────────────────────────────
  1-2=select  q=quit
```

**YouTube** — search for audio, browse results, and listen:

| Key | Action |
|---|---|
| `1-5` | Listen to result |
| `h` | View play history |
| `n` / `p` | Next / previous page |
| `s` | New search |
| `q` | Back to platform menu |
| `Ctrl+C` | Stop playback |

**Twitch** — browse followed live channels and listen:

| Key | Action |
|---|---|
| `1-N` | Listen to channel |
| `q` | Back to platform menu |

## History

Play history is stored locally in `.hearth_history.json` (capped at 200 entries, gitignored). The 5 most recent plays appear on startup in the YouTube flow. From the history view you can page through all entries, listen directly from history, or delete all history.

If you're upgrading from the old `yt-search` name, the existing `.yt_search_history.json` file is migrated automatically on first run.

## Twitch setup

Twitch integration shows live channels you follow. It requires a Twitch application for OAuth — no client secret is needed (Device Code Grant flow).

### 1. Register a Twitch app

1. Go to [dev.twitch.tv/console/apps/create](https://dev.twitch.tv/console/apps/create) and create a new application
2. Set the category to any value (e.g. "Other")
3. Set the **Client Type** to **Public**
4. Copy the **Client ID** from the app's manage page

### 2. Create `.twitch_config`

In the repo root:

```json
{
  "client_id": "your_client_id_here"
}
```

### 3. Authorize

On first launch, selecting Twitch displays a code and a URL. Open the URL in any browser, enter the code, and authorize the app. The token is saved to `.twitch_token` and refreshed automatically on future runs.

Both `.twitch_config` and `.twitch_token` are gitignored.

## How it works

**YouTube:** Fetches 25 results in a single `yt-dlp` call using `ytsearch25:`, ranks them locally with a fuzzy scorer (`difflib.SequenceMatcher`) to avoid repeat network requests, then resolves the stream URL on demand when you pick a track. Audio plays via your configured player in headless mode — no window, no browser.

**Twitch:** Queries the Helix API for followed live channels, then resolves the stream URL via `streamlink` when you pick a channel.

## Benchmark

Baseline measured 2026-05-13 on macOS 12.7.6, Python 3.14.3, yt-dlp 2026.03.17, streamlink 8.4.0.

Run `.venv/bin/python benchmark.py` to reproduce or capture a new snapshot.

### Stream URL resolution (3-run average)

| Source | Avg | Runs |
|---|---|---|
| YouTube (yt-dlp) | 1.89s | 2.18, 1.77, 1.73 |
| Twitch (streamlink) | 1.18s | 1.39, 1.07, 1.07 |

### Memory (peak RSS)

| State | RSS |
|---|---|
| Idle (post-import) | 22.2 MB |
| Post-resolution | 22.2 MB |

### Startup

Import time (loading `hearth`, `youtube`, `twitch` modules): **0.122s**

### Historical: CLI vs API (yt-dlp)

The original benchmark compared shelling out to yt-dlp (current approach) vs using its Python API (removed in `legacy-yt-dlp-api` branch). The CLI approach traded ~0.5-0.7s of latency per call for an 82% reduction in Python memory usage (44 MB → 8 MB). Importing `yt_dlp` alone cost 14.8 MB of peak memory — eliminated entirely in the current version.

## Files

| File | Purpose |
|---|---|
| `hearth.py` | CLI entry point — platform menu, search interaction, playback, history |
| `youtube.py` | YouTube data adapter — search, fuzzy ranking, stream URL resolution |
| `twitch.py` | Twitch data adapter — Device Code Grant OAuth, Helix API, followed channels |
| `setup.sh` | Dependency check (including streamlink) and launcher |
| `benchmark.py` | Baseline performance snapshot (resolution latency, memory, startup) |
