#!/bin/bash
# ~/wifi_promiscuous/scripts/monitor.sh
# Wrapper to launch the live node monitor

set -e

REPO_ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
VENV="$REPO_ROOT/.wifienv"
MONITOR="$REPO_ROOT/scripts/monitor_nodes.py"

if [ ! -x "$MONITOR" ]; then
  echo "[!] monitor_nodes.py not found or not executable at $MONITOR"
  echo "    Run: chmod +x $MONITOR"
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "[!] Virtual environment not found at $VENV"
  echo "    Run ./start.sh once to bootstrap it."
  exit 1
fi

# Activate venv
source "$VENV/bin/activate"

# Launch monitor (defaults: 10s window, 1s interval, 12 nodes, clear screen)
exec "$MONITOR" --window 10 --interval 1 --nodes 12 --clear "$@"
