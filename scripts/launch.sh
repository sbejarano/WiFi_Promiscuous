#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENVDIR=".wifienv"
REQS="host/requirements.txt"
CONFIG="host/config.yaml"
AGG="host/aggregator.py"
MON="host/monitor.py"
SCHEMA="host/schemas/sqlite_schema.sql"
DB="data/captures.sqlite"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

log() { printf "\033[1;34m[+] %s\033[0m\n" "$*"; }
err() { printf "\033[1;31m[!] %s\033[0m\n" "$*" >&2; exit 1; }

# --- 1. Setup venv ---
if [[ ! -d "$VENVDIR" ]]; then
  log "Creating virtual environment at $VENVDIR"
  python3 -m venv "$VENVDIR"
fi
source "$VENVDIR/bin/activate"
pip -q install --upgrade pip
pip -q install -r "$REQS"

# --- 2. Prepare DB if needed ---
mkdir -p data
if [[ ! -f "$DB" ]]; then
  log "Initializing SQLite DB at $DB"
  sqlite3 "$DB" < "$SCHEMA"
fi

# --- 3. Launch Aggregator + Monitor ---
log "Starting aggregator + monitor..."
log "Aggregator → $AGG"
log "Monitor    → $MON"

# Run both with logging to file
python "$AGG" --config "$CONFIG" > "$LOG_DIR/aggregator.log" 2>&1 &
AGG_PID=$!
log "Aggregator running as PID $AGG_PID"

sleep 2

python "$MON" > "$LOG_DIR/monitor.log" 2>&1 &
MON_PID=$!
log "Monitor running as PID $MON_PID"

# Trap cleanup
trap "log 'Stopping...'; kill $AGG_PID $MON_PID 2>/dev/null || true" SIGINT SIGTERM

# Wait for both to exit
wait $AGG_PID $MON_PID
