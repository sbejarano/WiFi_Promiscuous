#!/usr/bin/env bash
# Start script for Wi-Fi Multi-Probe Mapper
# - Creates/uses a Python virtual environment at .wifienv
# - Installs requirements
# - Launches the aggregator with host/config.yaml

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

VENV_DIR=".wifienv"
REQS="host/requirements.txt"
CONFIG="host/config.yaml"
AGGREGATOR="host/aggregator.py"

# Ensure data directory exists
mkdir -p "data"

# Create venv if missing
if [[ ! -d "$VENV_DIR" ]]; then
  echo "[+] Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

# Activate venv
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

# Upgrade pip and install requirements (if file exists)
python -m pip install --upgrade pip
if [[ -f "$REQS" ]]; then
  pip install -r "$REQS"
else
  echo "[!] Requirements file not found at $REQS. Skipping dependency install."
fi

# Basic checks
if [[ ! -f "$CONFIG" ]]; then
  echo "[!] Config file not found at $CONFIG"
  echo "    Create it or copy the sample before running."
  exit 1
fi

if [[ ! -f "$AGGREGATOR" ]]; then
  echo "[!] Aggregator script not found at $AGGREGATOR"
  echo "    Add your aggregator implementation, then re-run:"
  echo "    python $AGGREGATOR --config $CONFIG"
  exit 1
fi

# Run the aggregator
echo "[+] Starting aggregator with $CONFIG"
exec python "$AGGREGATOR" --config "$CONFIG"
