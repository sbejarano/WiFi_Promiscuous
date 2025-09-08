# Wi-Fi Promiscuous Capture - Scripts

This directory (`scripts/`) contains helper shell and Python scripts to manage,
monitor, and process data for the Wi-Fi Promiscuous Capture project.

## Scripts Overview

### 1. start.sh
Bootstraps the entire system:
- Activates the `.wifienv` virtual environment.
- Installs dependencies from `host/requirements.txt`.
- Initializes or migrates the SQLite database at `../data/captures.sqlite`.
- Stops conflicting GPS services (gpsd).
- Launches the main aggregator (`host/aggregator.py`) using `../host/config.yaml`.

**Run:**
```bash
./start.sh
```

---

### 2. monitor.sh
Launches the monitoring utility to track per-node capture counts in real time.

**Run:**
```bash
./monitor.sh
```

This calls `monitor_nodes.py` which prints statistics for each ESP32 node (1–12).

---

### 3. trilaterate.sh
Runs trilateration on captured Wi-Fi data:
- Reads from `../data/captures.sqlite`.
- Estimates Access Point positions based on RSSI, speed, heading, and altitude.
- Outputs a GeoJSON file into `../geojson/` with timestamped filename.
- Each AP is annotated with a confidence percentage.

**Run:**
```bash
./trilaterate.sh
```

Result: `../geojson/trilateration-YYYYMMDD-HHMMSS.geojson`

---

### 4. calibrate.sh
Calibrates RSSI model parameters (`p0`, `n`) using anchors defined in
`../scripts/calibration.yaml`. Anchors are APs with known locations.

**Run:**
```bash
./calibrate.sh
```

This updates the calibration file with corrected values.

---

## File Layout

```
scripts/
├── start.sh         # Start aggregator, setup env, stop gpsd, manage DB
├── monitor.sh       # Launch node monitor (monitor_nodes.py)
├── trilaterate.sh   # Run trilateration, export GeoJSON
├── calibrate.sh     # Run calibration with known anchors
├── monitor_nodes.py # Python script for node stats
├── trilaterate.py   # Trilateration algorithm
├── calibrate.py     # Calibration routine
└── calibration.yaml # Anchor definitions and calibration params
```

## Notes
- Run all scripts from inside the `scripts/` directory.
- Ensure ESP32 devices appear under `/dev/serial/by-id/` and GPS is not occupied by `gpsd` before running.
- GeoJSON exports can be loaded directly into GIS tools or Google Earth.sitions.
