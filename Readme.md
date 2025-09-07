# Wi-Fi Multi-Probe Mapper (12× ESP32 XIAO + GPS/PPS)

A reproducible pipeline to capture 2.4 GHz Wi-Fi management frames simultaneously across channels 1–12 using twelve ESP32 probes connected through a powered USB hub, time-disciplined by GPS with PPS, and fused on a Linux host. Every Wi-Fi capture is annotated with UTC timestamp, latitude, longitude, altitude, speed, and heading, and stored in SQLite or CSV. A downstream script performs motion-aware trilateration and exports GeoJSON.

## Goals

- Twelve probes, each fixed to a specific Wi-Fi channel (1–12) in promiscuous mode.
- Host ingests all probe streams over USB and GPS NMEA (+ optional PPS).
- GPS is the synchronization beacon: timestamps and alignment reference.
- Each capture includes: BSSID, SSID, RSSI, BeaconInterval, NodeId, Channel, Frequency, UTC, Lat/Lon/Alt, Speed, Heading.
- Storage in SQLite (default) or CSV for high-throughput logging.
- Trilateration script produces GeoJSON of AP estimates, accounting for receiver motion.

## Repository Layout

```
wifi_promiscuous/
├─ README.md
├─ data/
│  ├─ captures.sqlite
│  ├─ captures_YYYYMMDD.csv
│  └─ gps_raw.log
├─ host/
│  ├─ aggregator.py
│  ├─ trilaterate_to_geojson.py        # (planned)
│  ├─ requirements.txt
│  ├─ config.yaml                      # uses /dev/serial/by-id/* stable paths
│  ├─ channel_map.yaml                 # NodeId → Channel/Frequency/Device
│  └─ schemas/
│     └─ sqlite_schema.sql
├─ scripts/
│  └─ start.sh
└─ firmware/
   └─ esp32_xiao_probe/                # (planned) promiscuous + channel lock + serial out
```

## System Operation (Mermaid)

```mermaid
flowchart TB
    %% --- Probes ---
    subgraph ESP32_Probes[12× ESP32 Probes (Channels 1–12)]
        P1["Node 1<br/>Ch 1"]
        P2["Node 2<br/>Ch 2"]
        P3["Node 3<br/>Ch 3"]
        P4["Node 4<br/>Ch 4"]
        P5["Node 5<br/>Ch 5"]
        P6["Node 6<br/>Ch 6"]
        P7["Node 7<br/>Ch 7"]
        P8["Node 8<br/>Ch 8"]
        P9["Node 9<br/>Ch 9"]
        P10["Node 10<br/>Ch 10"]
        P11["Node 11<br/>Ch 11"]
        P12["Node 12<br/>Ch 12"]
    end

    HUB[Powered USB Hub / Power Bar]
    HOST[Linux Host]
    GPS[USB GPS (NMEA) + PPS]

    P1 --> HUB
    P2 --> HUB
    P3 --> HUB
    P4 --> HUB
    P5 --> HUB
    P6 --> HUB
    P7 --> HUB
    P8 --> HUB
    P9 --> HUB
    P10 --> HUB
    P11 --> HUB
    P12 --> HUB
    HUB --> HOST
    GPS --> HOST

    %% --- Aggregator internals ---
    subgraph Aggregator["host/aggregator.py"]
        S1["Serial Readers<br/>(12 ESP32 + GPS NMEA)"]
        S2["GPS Fix Buffer<br/>(lat/lon/alt/speed/track, PPS flag)"]
        S3["Fusion<br/>Attach GPS + UTC to each Wi‑Fi capture"]
        S4["Backpressure Queue"]
        S5["Storage Writer<br/>SQLite or CSV"]
        S6["Raw NMEA Log (optional)<br/>(data/gps_raw.log)"]
        S7["Channel Map Validation<br/>(host/channel_map.yaml)"]
    end

    HOST --> S1
    S1 --> S2
    S2 --> S3
    S3 --> S4
    S4 --> S5
    S2 --> S6
    S1 --> S7

    DB[(data/captures.sqlite)]
    CSV[(data/captures_YYYYMMDD.csv)]
    T[Trilateration Script<br/>host/trilaterate_to_geojson.py]
    GEO[GeoJSON Output]

    S5 --> DB
    S5 --> CSV
    DB --> T
    CSV --> T
    T --> GEO
```

## Hardware

- 12 × Seeed XIAO ESP32 (or ESP32 variants), each fixed to one channel (1–12).
- Powered USB hub with sufficient current for all probes plus GPS.
- GPS receiver providing NMEA (USB) and PPS.
- Linux host (Debian/Ubuntu/Raspberry Pi OS).

Tip: Use `/dev/serial/by-id/*` stable device IDs to avoid ttyACM renumbering. These are configured in `host/config.yaml`.

## Configuration

`host/config.yaml` drives everything. Example:

```
gps:
  nmea_port: "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
  nmea_baud: 9600
  use_pps: true
  max_fix_age_ms: 500
  raw_log_enable: true
  raw_log_path: "data/gps_raw.log"

probes:
  1: "/dev/serial/by-id/usb-Espressif_...57:74-if00"
  2: "/dev/serial/by-id/usb-Espressif_...0C:70-if00"
  3: "/dev/serial/by-id/usb-Espressif_...56:2C-if00"
  4: "/dev/serial/by-id/usb-Espressif_...D8:10-if00"
  5: "/dev/serial/by-id/usb-Espressif_...12:2C-if00"
  6: "/dev/serial/by-id/usb-Espressif_...50:9C-if00"
  7: "/dev/serial/by-id/usb-Espressif_...4F:04-if00"
  8: "/dev/serial/by-id/usb-Espressif_...D8:08-if00"
  9: "/dev/serial/by-id/usb-Espressif_...D7:AC-if00"
  10: "/dev/serial/by-id/usb-Espressif_...50:A8-if00"
  11: "/dev/serial/by-id/usb-Espressif_...12:1C-if00"
  12: "/dev/serial/by-id/usb-Espressif_...5E:54-if00"

storage:
  mode: "sqlite"                 # "sqlite" or "csv"
  sqlite_path: "data/captures.sqlite"
  csv_path: "data/captures_{{date}}.csv"

runtime:
  status_interval_s: 5
  queue_max: 10000
  drop_on_backpressure: true
```

Channel ground truth is documented in `host/channel_map.yaml` and validated on startup. Example:

```
channels:
  1: { channel: 1,  frequency_mhz: 2412, device: "/dev/serial/by-id/usb-Espressif_...57:74-if00" }
  2: { channel: 2,  frequency_mhz: 2417, device: "/dev/serial/by-id/usb-Espressif_...0C:70-if00" }
  ...
  12:{ channel: 12, frequency_mhz: 2467, device: "/dev/serial/by-id/usb-Espressif_...5E:54-if00" }
```

## Installation

```
sudo apt update
sudo apt install -y python3-venv gpsd gpsd-clients pps-tools chrony git sqlite3
cd ~/wifi_promiscuous
python3 -m venv .wifienv
source .wifienv/bin/activate
pip install -U pip
pip install -r host/requirements.txt
```

Enable serial access for your user if needed:

```
sudo usermod -a -G dialout $USER
# log out/in or reboot for group change to apply
```

## Start

```
chmod +x scripts/start.sh
./scripts/start.sh
```

You should see:
- Channel-map validation summary.
- Probe open messages for each `/dev/serial/by-id/*` device.
- Status lines like `[status] q=… gps=ok`.
- `data/gps_raw.log` containing timestamped NMEA sentences.

## Storage Schema

SQLite table `wifi_captures`:

```
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
CREATE INDEX IF NOT EXISTS idx_bssid ON wifi_captures(bssid);
CREATE INDEX IF NOT EXISTS idx_ts ON wifi_captures(ts_utc);
CREATE INDEX IF NOT EXISTS idx_node_ts ON wifi_captures(node_id, ts_utc);
```

CSV header (if `storage.mode: "csv"`):

```
ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,beacon_interval_ms,gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_track_deg,gps_hdop,gps_vdop,pps_locked
```

## Trilateration

`host/trilaterate_to_geojson.py` (planned) will:
- Group rows by BSSID.
- Convert RSSI to range hypotheses with robust loss.
- Use receiver trajectory (position/speed/heading/altitude at capture time).
- Estimate AP positions in 3D (down-weight Z if needed).
- Export GeoJSON Points with metadata (samples_used, estimated error).

## Sanity Checks

- Devices:
  - `ls -l /dev/serial/by-id/`
- GPS live view:
  - `sudo gpsd -n -D 2 -F /var/run/gpsd.sock /dev/serial/by-id/usb-u-blox_...-if00`
  - `cgps -s`
- PPS:
  - `sudo ppstest /dev/pps0`
- Database row count:
  - `sqlite3 data/captures.sqlite 'SELECT COUNT(*) FROM wifi_captures;'`

## Notes

- Use only lawful capture methods; stick to management frames for RF mapping.
- Keep the hub powered and use short, quality cables to minimize serial errors.
