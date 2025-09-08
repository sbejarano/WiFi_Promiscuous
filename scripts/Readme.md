# Wi-Fi Promiscuous Capture – Scripts

This directory contains helper shell scripts that manage the Wi-Fi multi-probe system, monitoring, and trilateration export.

## Available Scripts

### 1. start.sh
Bootstrap and start the Wi-Fi Multi-Probe Aggregator.

- Creates/updates the local Python virtual environment (.wifienv).
- Installs all dependencies from host/requirements.txt.
- Initializes the SQLite database (data/captures.sqlite) if not present.
- Stops gpsd to free the GPS serial device.
- Launches aggregator.py with configuration from host/config.yaml.
- Captured data is written into the database.

Run:
    ./start.sh

Stop:
    Press Ctrl+C to terminate the aggregator.

---

### 2. monitor.sh
Monitor the live ingestion rate per probe node.

- Wraps monitor_nodes.py.
- Shows how many lines (captures) per node are being received every second.
- Useful to verify all ESP32 probes are working.

Run:
    ./monitor.sh

Press Ctrl+C to exit.

---

### 3. trilaterate.sh
Perform multilateration of observed BSSIDs and export to GeoJSON.

- Reads from data/captures.sqlite.
- Groups observations by BSSID.
- Applies weighted least-squares trilateration (RSSI → range, GPS weighting).
- Produces a timestamped GeoJSON in geojson/.

Run with defaults (last 60 minutes of data):
    ./trilaterate.sh

Options (pass-through to trilaterate.py):
    --minutes N        look back N minutes (default 60)
    --since ISO        start time, e.g. 2025-09-08T00:00:00Z
    --bssid XX:XX:XX:XX:XX:XX  process only this BSSID (repeatable)
    --p0 -40           RSSI at 1 m (default -40 dBm)
    --n 2.2            path loss exponent (default 2.2)
    --max-range 2000   clamp max range in meters
    --conf-scale 100   confidence scaling in meters
    --quiet            suppress progress logs
    --outfile PATH     write to specific file instead of auto-naming

Examples:
    # Last 30 minutes, quieter output
    ./trilaterate.sh --minutes 30 --quiet

    # Process only a given BSSID
    ./trilaterate.sh --minutes 120 --bssid 1C:8B:76:8F:89:DB

    # Use a custom path-loss model
    ./trilaterate.sh --p0 -42 --n 2.0

---

## Output Locations
- Database: ../data/captures.sqlite
- GeoJSON results: ../geojson/trilateration_<UTC-TIMESTAMP>.geojson

---

## Notes
- Always run start.sh first to ensure the environment and database exist.
- Use monitor.sh during a session to verify all probes are contributing data.
- Run trilaterate.sh after sufficient data has been collected to export estimated AP positions.
