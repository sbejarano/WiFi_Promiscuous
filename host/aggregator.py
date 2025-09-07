#!/usr/bin/env python3
"""
Aggregator bootstrap with automatic storage initialization.

Features:
- Loads YAML config (host/config.yaml).
- Ensures data directory exists.
- If storage.mode == "sqlite":
    * Creates SQLite file if missing.
    * Applies schema from host/schemas/sqlite_schema.sql (idempotent).
    * Verifies main table exists.
- If storage.mode == "csv":
    * Creates CSV file if missing and writes canonical header.
- Prints a heartbeat loop (stub) so you can confirm it runs.

This is a scaffold; replace the loop with real serial/GPS ingestion later.
"""

import argparse
import os
import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

# Canonical CSV header (must match your README/schema)
CSV_HEADER = (
    "ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,beacon_interval_ms,"
    "gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_track_deg,gps_hdop,gps_vdop,pps_locked\n"
)

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]  # ~/wifi_promiscuous

def load_config(path: Path) -> dict:
    with path.open("r") as f:
        return yaml.safe_load(f) or {}

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def sqlite_run_schema(db_path: Path, schema_path: Path) -> None:
    """Run schema SQL (idempotent) and verify main table exists."""
    # Connect; sqlite will create file if missing
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        if not schema_path.is_file():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with schema_path.open("r") as f:
            sql = f.read()
        conn.executescript(sql)

        # Verify main table exists
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wifi_captures';"
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Expected table 'wifi_captures' not created by schema.")

        conn.commit()
    finally:
        conn.close()

def ensure_sqlite_initialized(sqlite_path: Path, schema_path: Path) -> None:
    """Create DB directory and apply schema if needed."""
    ensure_dir(sqlite_path.parent)

    needs_schema = False
    if not sqlite_path.exists():
        needs_schema = True
    else:
        # Quick check: does main table exist?
        try:
            conn = sqlite3.connect(str(sqlite_path))
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wifi_captures';"
            )
            if cur.fetchone() is None:
                needs_schema = True
        finally:
            conn.close()

    if needs_schema:
        print(f"[init] Initializing SQLite at {sqlite_path} using schema …")
        sqlite_run_schema(sqlite_path, schema_path)
    else:
        print(f"[ok] SQLite ready at {sqlite_path}")

def ensure_csv_ready(csv_path: Path) -> None:
    """Create CSV file with header if missing."""
    ensure_dir(csv_path.parent)
    if not csv_path.exists():
        print(f"[init] Creating CSV log at {csv_path}")
        with csv_path.open("w", encoding="utf-8") as f:
            f.write(CSV_HEADER)
    else:
        print(f"[ok] CSV ready at {csv_path}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Wi-Fi Aggregator (storage bootstrap)")
    parser.add_argument("--config", required=True, help="Path to host/config.yaml")
    args = parser.parse_args()

    root = repo_root()
    config_path = (Path(args.config).resolve()
                   if not args.config.startswith("host/")
                   else root / args.config)
    cfg = load_config(config_path)

    # Basic paths
    data_dir = root / "data"
    ensure_dir(data_dir)

    # Show basic config summary
    print("=== Wi-Fi Multi-Probe Aggregator (Bootstrap) ===")
    print(f"Repo root: {root}")
    print(f"Config:    {config_path}")
    print()

    gps = cfg.get("gps", {})
    probes = cfg.get("probes", {})
    storage = cfg.get("storage", {})
    runtime = cfg.get("runtime", {})

    print("GPS:")
    for k in ("nmea_port", "nmea_baud", "use_pps", "max_fix_age_ms"):
        if k in gps:
            print(f"  {k}: {gps[k]}")
    print()

    print("Probes:")
    for node_id in sorted(probes, key=lambda x: int(x)):
        print(f"  Node {node_id}: {probes[node_id]}")
    print()

    mode = storage.get("mode", "sqlite").lower()
    print("Storage:")
    print(f"  mode: {mode}")

    # Initialize chosen storage
    if mode == "sqlite":
        sqlite_path = storage.get("sqlite_path", "data/captures.sqlite")
        sqlite_path = (root / sqlite_path) if not os.path.isabs(sqlite_path) else Path(sqlite_path)
        schema_path = root / "host" / "schemas" / "sqlite_schema.sql"
        ensure_sqlite_initialized(sqlite_path, schema_path)
        active_target = sqlite_path
    elif mode == "csv":
        csv_path = storage.get("csv_path", "data/captures.csv")
        csv_path = (root / csv_path) if not os.path.isabs(csv_path) else Path(csv_path)
        ensure_csv_ready(csv_path)
        active_target = csv_path
    else:
        print(f"[err] Unknown storage mode: {mode}")
        return 2

    print(f"Active target: {active_target}")
    print()

    print("Runtime:")
    for k, v in runtime.items():
        print(f"  {k}: {v}")
    print()

    # Stub heartbeat loop (replace with real ingestion)
    print("Bootstrap complete. Running heartbeat (Ctrl+C to exit)…")
    try:
        while True:
            ts = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
            sys.stdout.write(f"\rHeartbeat: {ts}")
            sys.stdout.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
