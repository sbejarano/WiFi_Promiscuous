# Dashboard Data Flow (dashboard.js)

This document explains **exactly** how `dashboard.js` reads, aggregates, and displays system data in the Wi‑Fi Promiscuous project.

There is **no direct hardware access** from the dashboard. The dashboard is a **pure consumer** of JSON state files written by background services.

---

## High‑Level Architecture (Current)

```mermaid
flowchart TD

    subgraph Hardware
        GNSS["GNSS Receiver"]
        ESP["ESP32 Nodes"]
    end

    subgraph Services
        GPSD["gpsd.service"]
        PPS["gps-pps.service"]
        GPSSVC["gps_service.py"]
        CAP["wifi_capture.service"]
        TRI["trilateration.service"]
        DBW["ap_position_writer.service"]
        MON["system_monitor.service"]
    end

    subgraph StateFiles
        GPSJ["gps.json"]
        CAPJ["tmp/wifi_node_*.json + tmp/wifi_devices.json"]
        TRIJ["trilaterated.json"]
        SYSJ["system.json"]
    end

    subgraph Dashboard
        JS["dashboard.js"]
        UI["Browser UI"]
    end

    GNSS --> GPSD
    PPS --> GPSSVC
    GPSD --> GPSSVC
    GPSSVC --> GPSJ

    ESP --> CAP
    GPSJ --> CAP
    CAP --> CAPJ

    CAPJ --> TRI
    TRI --> TRIJ

    TRIJ --> DBW

    GPSJ --> MON
    CAPJ --> MON
    TRIJ --> MON
    MON --> SYSJ

    GPSJ --> JS
    CAPJ --> JS
    TRIJ --> JS
    SYSJ --> JS
    JS --> UI
```

---

## Key Design Principle

**dashboard.js never talks to services or devices.**

It only performs:

* `fetch()` over HTTP
* reads pre‑generated JSON files
* renders state already computed elsewhere

If a value is wrong on the dashboard, the **bug is always upstream**.

---

## Files Read by dashboard.js (Current)

| File                         | Written By               | Purpose                                        |
| ---------------------------- | ------------------------ | ---------------------------------------------- |
| `gps.json`                   | `gps_service.py`         | GNSS fix, PPS status, speed, bearing           |
| `wifi_node_1..12.json`       | `wifi_capture.service`   | Per-node omni observations (12 XIAO scanners)  |
| `wifi_node_LEFT/RIGHT.json`  | `wifi_capture.service`   | Directional discriminator observations          |
| `wifi_devices.json`          | `wifi_capture.service`   | Combined device view consumed by dashboard      |
| `trilaterated.json`          | `trilateration.service`  | Side, confidence, offset geometry              |
| `system.json`                | `system_monitor.service` | CPU, disk, heartbeats, ports                   |

---

## dashboard.js Read Cycle

```mermaid
flowchart TD

    GPSSVC["gps_service.py"] --> GPSJ["gps.json"]
    CAP["wifi_capture.service"] --> CAPJ["wifi_node_*.json + wifi_devices.json"]
    TRI["trilateration.service"] --> TRIJ["trilaterated.json"]
    MON["system_monitor.service"] --> SYSJ["system.json"]

    GPSJ --> JS["dashboard.js"]
    CAPJ --> JS
    TRIJ --> JS
    SYSJ --> JS

    JS --> UI["Browser UI"]
```

---

## Heartbeat Logic (Critical)

The dashboard **does not infer liveness**.

It trusts `system_monitor.service` to compute heartbeat ages.

Example from `system.json`:

```json
{
  "heartbeat": {
    "GPS": 1766698123.12,
    "PPS": 1766698123.12,
    "wifi-capture": 1766698122.88,
    "LEFT": 1766698123.01
  }
}
```

`dashboard.js` simply does:

* `now - heartbeat[key]`
* color‑codes based on age thresholds

---

## Why dashboard.js Cannot Break GPS

This is **provably impossible**:

* dashboard.js runs in the browser
* has no file write access
* has no serial access
* has no system calls

If GPS is stuck, the cause is always upstream:

* gpsd / gps‑pps / gps_service
* UART contention
* GNSS configuration
* antenna / RF

---

## Integration with udev + devices.yaml

`devices.yaml` and udev rules ensure:

* deterministic device naming
* no serial probing
* no race conditions

The dashboard remains **unchanged**, regardless of how hardware is wired.

---

## Summary

* dashboard.js is **read‑only**
* all logic happens in services
* JSON files are the contract (`gps.json`, `system.json`, `wifi_node_*.json`, `wifi_devices.json`)
* if data is wrong → fix the writer, not the dashboard
