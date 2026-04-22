#!/bin/bash
# setup.sh — sets up and runs ytsearch.py
# Run once to set up, then again anytime to launch

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"

# ─── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✔ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
err()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }
info() { echo -e "  → $1"; }

echo ""
echo "  yt audio search — setup"
echo "  ─────────────────────────────────"

# ─── 1. Python ────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  err "python3 not found. Install via: brew install python"
fi
ok "python3 found: $(python3 --version)"

# ─── 2. venv ──────────────────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  info "Creating virtual environment..."
  python3 -m venv "$VENV"
  ok "venv created at .venv"
else
  ok "venv already exists"
fi

# ─── 3. yt-dlp ────────────────────────────────────────────────────────────────
if ! command -v yt-dlp &>/dev/null; then
  err "yt-dlp not found. Install it: brew install yt-dlp"
fi
ok "yt-dlp found: $(yt-dlp --version)"

# ─── 4. Audio player ──────────────────────────────────────────────────────────
PLAYER=""

# Check mpv (system or symlinked from app)
if command -v mpv &>/dev/null; then
  PLAYER="mpv"
  ok "player: mpv ($(which mpv))"

# Check VLC app bundle
elif [ -f "/Applications/VLC.app/Contents/MacOS/VLC" ]; then
  PLAYER="vlc"
  ok "player: VLC (app bundle)"

# Check ffplay
elif command -v ffplay &>/dev/null; then
  PLAYER="ffplay"
  ok "player: ffplay"

else
  echo ""
  warn "No audio player found. Choose an option:"
  echo ""
  echo "  [1] Download mpv from GitHub (recommended, no compilation)"
  echo "      After install, symlink it:"
  echo "      ln -s /Applications/mpv.app/Contents/MacOS/mpv /usr/local/bin/mpv"
  echo ""
  echo "  [2] Download VLC from https://www.videolan.org"
  echo "      No extra steps needed after install."
  echo ""
  echo "  Then re-run this script."
  echo ""
  exit 1
fi

# ─── 5. Patch player into script ──────────────────────────────────────────────
# Write a small player config file the python script can read
cat > "$SCRIPT_DIR/.player" <<EOF
$PLAYER
EOF
ok "player config written"

# ─── 6. Run ───────────────────────────────────────────────────────────────────
echo ""
echo "  ─────────────────────────────────"
echo "  Setup complete. Launching..."
echo "  ─────────────────────────────────"
echo ""

"$PYTHON" "$SCRIPT_DIR/ytsearch.py"