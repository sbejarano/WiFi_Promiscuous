#!/bin/bash
# ~/wifi_promiscuous/scripts/trilaterate.sh
# Run the trilateration tool and write GeoJSON into geojson/

set -euo pipefail

REPO_ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
VENV="$REPO_ROOT/.wifienv"
PY="$REPO_ROOT/scripts/trilaterate.py"

if [ ! -x "$PY" ]; then
  echo "[!] trilaterate.py not found or not executable at $PY"
  echo "    Run: chmod +x $PY"
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "[!] Virtual environment not found at $VENV"
  echo "    Run ./scripts/start.sh once to bootstrap it."
  exit 1
fi

source "$VENV/bin/activate"

# You can pass through any extra args, e.g.:
#   ./scripts/trilaterate.sh --minutes 30 --p0 -42 --n 2.0
exec "$PY" --minutes 60 "$@"
