# Wi-Fi Multi-Probe Mapper (12× ESP32 XIAO + GPS/PPS)

A reproducible pipeline to capture 2.4 GHz Wi-Fi beacons simultaneously across channels 1–12 using **twelve ESP32 XIAO** probes connected through a **USB hub/power bar**, time-synchronized by a **GPS receiver with PPS**, and fused on a **Linux workstation**. The workstation associates **every single Wi-Fi capture** with **Date, Time, Lat, Lon, Alt, Heading, Speed** and stores it to **SQLite** (or **CSV**) for downstream **trilateration** that estimates access-point (AP) positions and exports **GeoJSON** for mapping.

---

## Key Goals

- 12 dedicated probes, each fixed to a specific Wi-Fi channel (1–12) in promiscuous mode.
- USB hub → single host computer ingesting all probe streams **and** GPS NMEA+PPS.
- GPS acts as the **clock and sync beacon** (timestamps & phase alignment via PPS).
- Each capture → `BSSID, SSID, RSSI, BeaconInterval, NodeId, Channel, Frequency` **plus** `UTC Date/Time, Lat, Lon, Alt, Heading, Speed`.
- High-rate logging to **SQLite** (preferred) or **CSV** (fastest append).
- A second script performs **trilateration to GeoJSON**, accounting for **receiver motion** (speed/heading/altitude) at capture time.
- Turn-key **virtualenv** (`.wifienv`) and a **start script** to bootstrap the stack.

---

## System Architecture (High Level)

[12× ESP32 XIAO] --USB--> [Powered USB Hub] --USB--> [Linux Host]
                                           \--USB--> [GPS (NMEA + PPS)]

ESP32 XIAO (Ch 1..12):
  • Promiscuous mode
  • Parses beacon frames
  • Sends: NodeId, Channel, Freq, BSSID, SSID, RSSI, BeaconInterval

Linux Host:
  • gpsd/pps (NMEA+PPS) for disciplined time
  • aggregator.py (Python):
      - Reads 12 serial streams + GPS stream
      - PPS-disciplined timestamping
      - Associates GPS fix (lat/lon/alt/speed/track) to each Wi-Fi capture
      - Writes to SQLite or CSV (configurable)
  • trilaterate_to_geojson.py (Python):
      - Motion-aware trilateration of AP positions
      - Emits GeoJSON for GIS tools / web maps

---

## Repository Layout

.
├─ firmware/
│  └─ esp32_xiao_probe/           
├─ host/
│  ├─ aggregator.py                
│  ├─ trilaterate_to_geojson.py    
│  ├─ schemas/
│  │  ├─ sqlite_schema.sql         
│  │  └─ csv_headers.txt           
│  ├─ config.yaml                  
│  └─ requirements.txt             
├─ scripts/
│  ├─ start.sh                     
│  └─ udev/99-esp32-xiao.rules     
├─ data/
│  ├─ captures.sqlite              
│  ├─ captures_YYYYMMDD.csv        
│  └─ output.geojson               
└─ README.md

---

## Hardware

- **12 × Seeed XIAO ESP32** (each locked to channel 1–12).
- **Powered USB Hub** with current for all nodes.
- **GPS Receiver** with NMEA + PPS (USB).
- Linux workstation (Ubuntu 22.04/24.04).

> Your ESP-32 nodes are available as `/dev/ttyACM0`–`/dev/ttyACM11`.

---

## 📡 Probe Data Model

Wi-Fi fields:
- `node_id` (1–12)
- `channel`
- `frequency_mhz`
- `bssid`
- `ssid`
- `rssi_dbm`
- `beacon_interval_ms`

GPS fields:
- `ts_utc`
- `lat`, `lon`, `alt`
- `speed`, `track`
- `pps_locked`

---

## Storage

SQLite schema:

CREATE TABLE IF NOT EXISTS wifi_captures (
  id INTEGER PRIMARY KEY,
  ts_utc TEXT NOT NULL,
  node_id INTEGER NOT NULL,
  channel INTEGER NOT NULL,
  frequency_mhz INTEGER NOT NULL,
  bssid TEXT NOT NULL,
  ssid TEXT,
  rssi_dbm INTEGER NOT NULL,
  beacon_interval_ms INTEGER,
  gps_lat REAL, gps_lon REAL, gps_alt_m REAL,
  gps_speed_mps REAL, gps_track_deg REAL,
  pps_locked INTEGER DEFAULT 0
);

---

## Installation

sudo apt update
sudo apt install -y python3-venv gpsd gpsd-clients pps-tools chrony git
git clone <your-repo-url> wifi-multi-probe
cd wifi-multi-probe
python3 -m venv .wifienv
source .wifienv/bin/activate
pip install -U pip
pip install -r host/requirements.txt

---

## Configuration

`host/config.yaml` already maps:

probes:
  1: "/dev/ttyACM0"
  2: "/dev/ttyACM1"
  ...
  12: "/dev/ttyACM11"

Set `gps.nmea_port` to your GPS device (`/dev/ttyUSB0` or `/dev/ttyACM12`).

---

## ▶Start Script

chmod +x scripts/start.sh
./scripts/start.sh

This activates `.wifienv`, installs requirements, and launches aggregator.

---

## Usage

Capture:
./scripts/start.sh

Trilaterate to GeoJSON:
source .wifienv/bin/activate
python host/trilaterate_to_geojson.py \
  --input-sqlite data/captures.sqlite \
  --output data/output.geojson

---

## Output Example

{
  "type": "Feature",
  "properties": {
    "bssid": "AA:BB:CC:DD:EE:FF",
    "ssid": "Cafe",
    "channel": 6,
    "samples_used": 142,
    "est_error_m": 7.8
  },
  "geometry": { "type": "Point", "coordinates": [-79.940, 37.270] }
}

---

## License

MIT or Apache-2.0 (choose and place LICENSE file).
