#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENVDIR=".wifienv"
MONITOR="host/monitor.py"

log() { printf "\033[1;34m[+] %s\033[0m\n" "$*"; }

# Check virtualenv
if [[ ! -d "$VENVDIR" ]]; then
  log "Virtual environment not found. Creating..."
  python3 -m venv "$VENVDIR"
fi

# Activate venv and run monitor
source "$VENVDIR/bin/activate"

log "Launching monitor: $MONITOR"
exec python "$MONITOR"
