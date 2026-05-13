# hearth — project instructions for Claude Code

---

## Project state

**Repo:** yt-search (rename to `hearth` is planned but not yet done)
**Primary files:** `ytsearch.py` (CLI entry point), `youtube.py` (YouTube adapter), `twitch.py` (Twitch adapter)
**Tests:** `tests/` — pytest, run via `.venv/bin/python -m pytest tests/`
**CI:** GitHub Actions (`test.yml`) — must pass before merge to `main`
**Rule:** never push directly to `main`

---

## Git conventions

- **No `Co-Authored-By` trailers in commits.** Do not append co-author lines. This is a project-wide rule.
- Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes: `feat:`, `fix:`, `chore:`, `ci:`, `docs:`, `refactor:`, `test:`.
- Commit messages should explain *why*, not just *what*.

---

## Architecture

- `ytsearch.py` — CLI entry point: platform menu, search interaction, playback (mpv/VLC/ffplay), flat JSON play history
- `youtube.py` — YouTube data adapter with narrow public interface: `is_available()`, `search(query)`, `get_stream_url(video_id)`
- `twitch.py` — Twitch data adapter with narrow public interface: `is_available()` and `get_live_channels()`
- Platform adapters share an **entry dict contract** (see below) so `play()` and history work across sources
- Playback and history are platform-agnostic — do not add platform-specific logic to them

### Entry dict contract

All platform adapters must produce entries in this shape:

```python
{
    "id": str,          # platform-specific ID (YouTube video ID or Twitch login)
    "title": str,
    "uploader": str,
    "duration": int | None,   # None for live streams
    "source": str,            # "youtube" or "twitch"
}
```

Twitch entries additionally carry `viewers` (int) and `game` (str), ignored by `play()`.

URL construction in `play()` is gated on `source`:
- `"twitch"` → `https://twitch.tv/{id}`
- otherwise → resolve via `yt-dlp`

---

## Credentials & secrets

- `.twitch_config` and `.twitch_token` are gitignored — never commit credentials
- No hardcoded client IDs or secrets anywhere
- Twitch uses Device Code Grant OAuth — no client_secret, no redirect URI needed

---

## Testing

- Run tests: `.venv/bin/python -m pytest tests/ -v`
- All tests must pass before committing
- Twitch Device Code tests mock all HTTP — no real network or sockets needed

---

## Planned future work (out of scope for current sessions unless explicitly requested)

- Rename project from `yt-search` to `hearth` (touches imports, CI, README, repo name)
- Twitch VOD or clip support
