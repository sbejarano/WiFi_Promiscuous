#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENVDIR=".wifienv"
REQS="host/requirements.txt"
CONFIG="host/config.yaml"
AGG="host/aggregator.py"
SCHEMA="host/schemas/sqlite_schema.sql"
DB="data/captures.sqlite"

log() { printf "[+] %s\n" "$*"; }
err() { printf "[x] %s\n" "$*" >&2; exit 1; }

# venv & deps
if [[ ! -d "$VENVDIR" ]]; then
  log "Creating virtual environment at $VENVDIR"
  python3 -m venv "$VENVDIR"
fi
# shellcheck disable=SC1091
source "$VENVDIR/bin/activate"
pip -q install --upgrade pip
pip -q install -r "$REQS"

# data dir & DB
mkdir -p data
if [[ ! -f "$DB" ]]; then
  log "Initializing SQLite at $DB"
  sqlite3 "$DB" < "$SCHEMA"
fi

# run
log "Starting aggregator with $CONFIG"
python "$AGG" --config "$CONFIG"
