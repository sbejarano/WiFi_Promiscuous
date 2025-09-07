#!/usr/bin/env python3
"""
Minimal Aggregator Stub for Wi-Fi Multi-Probe Mapper
- Reads config.yaml
- Prints which ports it *would* open
- Verifies SQLite or CSV target path
"""

import argparse
import yaml
import os
import sys
from datetime import datetime

def load_config(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def main():
    parser = argparse.ArgumentParser(description="Wi-Fi Aggregator Stub")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    print("=== Wi-Fi Multi-Probe Aggregator (Stub) ===")
    print(f"Config loaded from: {args.config}")
    print()

    # Show GPS config
    gps = cfg.get("gps", {})
    print("GPS Configuration:")
    for k, v in gps.items():
        print(f"  {k}: {v}")
    print()

    # Show probes
    probes = cfg.get("probes", {})
    print("Probes:")
    for node, port in probes.items():
        print(f"  Node {node}: {port}")
    print()

    # Storage config
    storage = cfg.get("storage", {})
    mode = storage.get("mode", "sqlite")
    print("Storage:")
    print(f"  Mode: {mode}")
    if mode == "sqlite":
        path = storage.get("sqlite_path", "data/captures.sqlite")
    else:
        path = storage.get("csv_path", "data/captures.csv")
    print(f"  Path: {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Print runtime info
    runtime = cfg.get("runtime", {})
    print()
    print("Runtime:")
    for k, v in runtime.items():
        print(f"  {k}: {v}")

    # Fake loop (placeholder for real capture logic)
    print()
    print("Aggregator started (stub mode).")
    print("Press Ctrl+C to exit.")
    try:
        while True:
            # For now, just show a timestamp every few seconds
            sys.stdout.write(f"\rHeartbeat: {datetime.utcnow().isoformat()} UTC")
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nAggregator stopped.")

if __name__ == "__main__":
    main()
