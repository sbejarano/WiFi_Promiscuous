# Wi‑Fi High Speed Scanning Rig

**(ESP32 XIAO Array + GPS/PPS‑Disciplined Linux Host)**

A deterministic, reproducible system for **simultaneous 2.4 GHz Wi‑Fi management‑frame capture** using multiple ESP32 XIAO probes, with **all timing, positioning, and fusion performed centrally on a Linux host disciplined by GPS + PPS**.

The system is designed for **mobile or stationary RF surveying**, directional inference, and later spatial analysis (GeoJSON / KML), while **explicitly avoiding distributed time synchronization** on microcontrollers.

This architecture mirrors professional **SDR, GNSS, and sensor‑fusion systems**.

---

## Core Principles (Non‑Negotiable)

* **ESP32 probes do not own time**

  * They emit **monotonic microsecond counters only**
* **Linux host is the sole time authority**

  * PPS‑disciplined kernel clock
  * GPS provides UTC + motion data
* **All absolute timestamps are assigned on the host**
* **Capture is UI‑controlled**

  * No background capture unless explicitly started
* **State is preserved**

  * Last‑known‑good GPS fix is retained
  * No resets on transient message loss
* **Directional inference is advisory**

  * LEFT / RIGHT probes bias interpretation, not geometry

---

## Operational Overview

At runtime:

1. ESP32 probes capture Wi‑Fi management frames
2. Frames are streamed over USB as JSON
3. Linux host:

   * assigns PPS‑disciplined UTC timestamps
   * fuses GPS position, speed, and heading
   * stores observations in SQLite
4. Optional post‑processing exports GeoJSON for mapping

Capture **does not run by default**.
It only runs when enabled from the HTML dashboard.

---

## High‑Level Data Flow

```mermaid
flowchart LR
    ESP[ESP32 Probes<br/>Ch 1–11 + LEFT/RIGHT] -->|USB JSON| HOST[Linux Host]

    GPS[GNSS NMEA] --> HOST
    PPS[PPS GPIO] --> HOST

    HOST --> DB[(trilateration_data.db)]
    DB --> GEO[GeoJSON / KML]
    HOST --> UI[HTML Dashboard]
```

---

## System Architecture

```mermaid
flowchart TB

    subgraph ESP[ESP32 Probe Array]
        N1[Node 1<br/>Ch 1]
        N2[Node 2<br/>Ch 2]
        N3[Node 3<br/>Ch 3]
        N4[Node 4<br/>Ch 4]
        N5[Node 5<br/>Ch 5]
        N6[Node 6<br/>Ch 6]
        N7[Node 7<br/>Ch 7]
        N8[Node 8<br/>Ch 8]
        N9[Node 9<br/>Ch 9]
        N10[Node 10<br/>Ch 10]
        N11[Node 11<br/>Ch 11]
        L[LEFT Directional]
        R[RIGHT Directional]
    end

    HUB[Powered USB Hub]
    HOST[Linux Host]

    ESP --> HUB --> HOST

    subgraph Time[Time Authority]
        PPSK[PPS Kernel Clock]
        CHRONY[chrony]
        GPSD[gpsd]
    end

    PPS --> PPSK --> CHRONY
    GPS --> GPSD --> HOST
```

---

## Capture Control Model

The **database worker always runs**, but **ingestion is gated** by a shared state file.

* `capture.state = STOP` → no database writes
* `capture.state = START` → active ingestion

The HTML UI controls this state.

This avoids:

* restarting services
* corrupting WAL
* losing in‑memory buffers

---

## Repository Layout (Actual)

```text
wifi_promiscuous/
├── data/
│   ├── trilateration_data.db
│   └── wifi.db                # legacy / optional
│
├── host/
│   ├── wifi_capture_service.py
│   ├── broker.py
│   ├── db-worker.py           # main ingestion & fusion
│   ├── gps_service.py         # GPS + PPS → gps.json
│   ├── system_monitor.py
│   └── schema/
│       └── aggregator_schema.sql
│
├── tmp/
│   ├── gps.json
│   ├── capture.state
│   ├── wifi_node_1.json
│   ├── ...
│   ├── wifi_node_11.json
│   ├── wifi_node_LEFT.json
│   └── wifi_node_RIGHT.json
│
├── scripts/
│   ├── start.sh
│   ├── stop.sh
│   └── restart_stack.sh
│
└── /var/www/html/wifi/
    ├── index.html
    ├── db_ctl.php
    ├── css/
    │   └── dashboard.css
    ├── js/
    │   └── dashboard.js
    └── data/ (symlinks to tmp/)
```

---

## Database Model (Operational)

* **wifi_observations** – raw per‑probe observations (append‑only)
* **side_observations** – LEFT / RIGHT burst comparisons
* **wifi_captures** – per‑BSSID aggregated state
* **resolved_locations** – optional derived estimates

---

## Directional LEFT / RIGHT Logic

```mermaid
flowchart TD
    A[Fixed‑Channel Observations] --> B[Aggregator]
    L[LEFT Directional] --> B
    R[RIGHT Directional] --> B

    B --> C[Group by BSSID + Time Window]

    C --> D{LEFT & RIGHT RSSI?}

    D -->|Yes| E[Compare RSSI]
    D -->|No| F[Side Unknown]

    E -->|LEFT > RIGHT + Δ| G[Side = LEFT]
    E -->|RIGHT > LEFT + Δ| H[Side = RIGHT]
    E -->|≈ Equal| I[Side = CENTER]

    G --> J[Annotate Capture]
    H --> J
    I --> J
    F --> J

    J --> DB[(wifi_captures)]
```

* Directional probes are advisory only
* Δ avoids noise‑based flipping

---

## Services & systemd Architecture

The system is composed of **long-running systemd services** that remain active at all times, with **runtime behavior gated by state files**, not service restarts.

This design avoids:

* service churn
* WAL corruption
* loss of in-memory buffers
* race conditions

### Service Responsibilities

| Service                  | Purpose                                    |
| ------------------------ | ------------------------------------------ |
| `gpsd.service`           | Reads GNSS NMEA from `/dev/serial0`        |
| `gps-pps.service`        | Generates `gps.json`, validates PPS & fix  |
| `wifi_capture.service`   | Reads ESP32 USB JSON streams               |
| `broker.service`         | Normalizes and fans out capture data       |
| `wifi-db.service`        | Ingests, fuses, and stores data (UI-gated) |
| `system_monitor.service` | Health & telemetry export                  |

### Service Interaction Diagram

```mermaid
flowchart TB

    subgraph systemd[systemd Services]
        GPSD[gpsd.service]
        GPSPPS[gps-pps.service]
        WIFICAP[wifi_capture.service]
        BROKER[broker.service]
        DB[wifi-db.service]
        MON[system_monitor.service]
    end

    GPSD --> GPSPPS
    GPSPPS -->|gps.json| DB

    WIFICAP -->|USB JSON| BROKER
    BROKER -->|normalized JSON| DB

    MON -->|status JSON| UI[HTML Dashboard]

    UI -->|START / STOP| STATE[capture.state]
    STATE --> DB
```

**Key points**:

* Services remain running continuously
* `wifi-db.service` checks `capture.state` before every ingest cycle
* UI never restarts services
* GPS remains authoritative even when capture is stopped

---

## GPS & Time Discipline

* GPS NMEA via `/dev/serial0`
* PPS via `/dev/pps0`
* `chrony` disciplines the kernel clock
* `gps_service.py` preserves last‑known‑good fixes

Verified state:

* PPS active
* Mode = 3 (3D fix)
* Valid lat / lon / alt (MSL)
* Reliable timestamps

---

## Dependencies

### System

* Linux (Debian / Ubuntu)
* gpsd
* chrony
* SQLite3
* systemd
* Apache + PHP

### Python

* Python ≥ 3.9
* sqlite3
* json
* statistics
* collections

### Hardware

* 11–13 × ESP32 XIAO
* Directional antennas (LEFT / RIGHT)
* Powered USB hub
* GNSS module with PPS (REYAX RYS352A)
* Raspberry Pi 4/5 or equivalent

---

## Legal / RF Notice

Only **IEEE 802.11 management frames** are captured.
No payloads, no decryption, no association.

Operate only where lawful.

---

## Status

✔ PPS‑disciplined
✔ Centralized time authority
✔ Deterministic ingestion
✔ UI‑controlled capture
✔ Directional inference
✔ Ready for spatial analysis

