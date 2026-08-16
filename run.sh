#!/bin/bash
# run.sh — launch hearth (assumes setup.sh has been run)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/hearth.py"
