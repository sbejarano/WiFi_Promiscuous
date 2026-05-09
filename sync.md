
# Synced Project Notes

_Last updated: 2026-05-06 (UTC)_

## Purpose
This file is the persistent, cross-device project memory for this repository.
It records project intent, architecture, operating constraints, and agreed changes
so work can continue from any device/session.

## Current Baseline (agreed in chat)
- The project must keep continuity across sessions and devices.
- No code changes should be made unless the task is explicitly agreed first.
- Before making any new change, previous changes should be evaluated.
- Keep agreements and change decisions in a synced note inside the repository.

## Project Purpose (current understanding)
This project is a Raspberry Pi based WiFi promiscuous capture platform that:
1. Ingests WiFi observations from multiple scanner nodes.
2. Combines radio data with GPS and system telemetry.
3. Stores and processes data in SQLite for capture history and AP positioning.
4. Exposes near-real-time operational state to a local dashboard website.

Primary intent:
- Continuous situational awareness of nearby WiFi access points.
- Signal-side analysis (LEFT/RIGHT/OMNI) and trilateration outputs.
- Operational resilience through watchdog, power, and system monitors.

## Confirmed Runtime Layout (from user-provided host machine data)
- Repo root on host: `~/wifi_promiscuous`
- Key directories:
  - `host/` services and control scripts
  - `data/` SQLite databases (rotated snapshots + latest symlink)
  - `tmp/` JSON state exchange files
  - `/var/www/html` dashboard consuming symlinked JSON

### Host services/scripts (15 files)
- `wifi_capture_service.py`
- `broker.py`
- `db_writer.py`
- `db_writer_gate.py`
- `gps_service.py`
- `trilateration_service.py`
- `ap_position_writer.py`
- `ap_position_geojson.py`
- `ap_position_geojson.sh`
- `esp_usb_watchdog.py`
- `system_monitor.py`
- `power.py`
- `devices.yaml`
- `denied_ssi.yaml`
- `battery.yaml`

## Data and dashboard integration (confirmed)
Dashboard path: `/var/www/html`
- `data/gps.json` -> `~/wifi_promiscuous/tmp/gps.json`
- `data/power.json` -> `~/wifi_promiscuous/tmp/power.json`
- `data/system.json` -> `~/wifi_promiscuous/tmp/system.json`
- `data/trilaterated.json` -> `~/wifi_promiscuous/tmp/trilaterated.json`
- `data/usb_watchdog.json` -> `~/wifi_promiscuous/tmp/usb_watchdog.json`
- `data/wifi_devices.json` -> `~/wifi_promiscuous/tmp/wifi_devices.json`
- `data/wifi_capture.json` -> `/dev/shm/wifi_capture.json`

This confirms website status is directly tied to live JSON feeds from both
`/tmp` and `/dev/shm`.

## Database policy requested by user (critical requirement)
Historical baseline:
- Previously used single `trilateration_data.db`.

Requested policy (Kismet style):
- Use timestamped DB files.
- Rotate database per day OR when file reaches 100 MB.
- Maintain usable latest-pointer behavior for tools/dashboard.

## Current behavior gap identified during review
Current `db_writer.py` behavior (from user-provided file):
- Creates timestamped DB on process start when `ROTATE_PER_START=True`.
- Updates `trilateration_data_latest.db` symlink.
- Cleans up older rotated DB files.
- Does NOT implement active runtime daily rotation checks.
- Does NOT implement active runtime max-size (100 MB) rotation checks.

Current `db_writer_gate.py` behavior:
- Starts `db_writer.service` only after GPS lock condition persists.
- Lock requires `mode >= 2` and FIX status logic.
- If GPS lock is absent, writer may remain unstarted.

Resulting gap:
- Rotation currently tied to service start timing, not explicit daily/100 MB policy.

## Input contract observations (important)
Two live data shapes were observed:
1. `wifi_capture.json` (under `/dev/shm`) consumed by current `db_writer.py`.
2. `wifi_devices.json` (under `/tmp`) with schema:
   - top-level `ts`
   - top-level `devices[]`
   - each device has `bssid`, `ssid`, `rssi`, `channel`, `side`, `last_seen`

Potential mismatch risk:
- Writer currently expects `observations` style payload from capture feed.
- Dashboard also consumes `wifi_devices.json` directly.

## Operational snapshots received in chat
- `gps.json` sample showed coordinates present but `mode=0`, `fix="NO FIX"`.
- `usb_watchdog.json` sample showed multiple devices recently seen and no resets.
- `power_state.json` / `power.json` showed stable battery and no low-voltage alarm.

Interpretation captured:
- System instability is less likely from power/USB at that moment.
- Main concerns remain DB rotation policy implementation and feed contract alignment.


## Device-layer evidence (USB/serial stability)
User-provided `/dev` and `dmesg` snapshots confirm:
- Multiple ACM serial endpoints are present (`ttyACM0` through `ttyACM13`).
- Persistent custom aliases exist for scanners (`esp-left`, `esp-right`, `esp-node1`..`esp-node12`).
- Kernel logs show repeated USB disconnect/re-enumeration waves, followed by
  reattachment into ACM device nodes.

Implication:
- Serial mapping can churn over time due to bus resets/disconnect events.
- Stability logic should continue to rely on persistent aliases and watchdog
  telemetry instead of fixed `/dev/ttyACM*` assumptions.


## Device identity source of truth
From user-provided `host/devices.yaml`:
- `devices.yaml` is declared as the single source of truth for all serial devices.
- Runtime serial auto-discovery is explicitly disallowed.
- GPS is pinned to `/dev/serial0` and `/dev/pps0`.
- Directional nodes are pinned to `/dev/esp-left` and `/dev/esp-right`.
- Fixed scanners are pinned to `/dev/esp-node1` through `/dev/esp-node12`.

Operational rule captured:
- Any writer/capture/gate logic should treat alias-based device paths as canonical
  identity, not dynamic `ttyACM*` numbering.

## USB serial mapping evidence
User-provided `udevadm` mapping (`/dev/ttyACM*` -> `ID_SERIAL_SHORT`) confirms:
- Stable per-device serial identities exist even when ACM index assignment changes.
- `ttyACM` numbering should be considered ephemeral across reconnect/reset events.

Implication:
- Persistent aliases (`/dev/esp-*`) and serial identifiers should be preferred for
  node identity continuity across USB churn.

## Session Log

### 2026-05-06
#### Context recovered
- Current branch in this environment: `work`.
- No recoverable "yesterday" work was found in local git history on this machine.
- Prior work was stated to be from another machine/session.

#### Agreement captured
- Create and maintain a synced note so agreements are available next time from any device.
- Persist project-purpose and architecture notes in synced form.

## Operating Workflow (for next sessions)
1. Read this file first.
2. Confirm the latest agreed task with the user.
3. Evaluate current repository and recent changes before editing.
4. Apply only approved changes.
5. Append dated decisions, architecture updates, and runtime observations.

## Pending Items
- [ ] Paste/record any explicit inline review comments from prior PR for line-by-line closure.
- [ ] If approved, implement DB rotation policy: daily OR >=100 MB with timestamped files.
- [ ] If approved, reconcile writer input contract with active `/tmp` and `/dev/shm` feeds.

## Latest information checkpoint (explicit)
Added to ensure visibility of the most recent user-provided runtime details.

### Latest shared details now recorded
- `/dev` inventory includes scanner aliases (`/dev/esp-left`, `/dev/esp-right`, `/dev/esp-node1..12`) and ACM devices (`/dev/ttyACM0..13`).
- Kernel `dmesg` logs show repeated USB disconnect and reconnect/re-enumeration cycles across multiple ACM devices.
- `host/devices.yaml` states: single source of truth for serial devices; runtime discovery not allowed.
- `host/devices.yaml` pinning captured:
  - GPS: `/dev/serial0`, `/dev/pps0`
  - Directional: `/dev/esp-left`, `/dev/esp-right`
  - Scanners: `/dev/esp-node1` through `/dev/esp-node12`
- `udevadm` evidence captured: each `/dev/ttyACM*` has an `ID_SERIAL_SHORT` value, confirming stable device identity independent of ACM index ordering.

### Visibility note
If this section is missing in your local copy, your working tree may be behind the latest commit on branch `work`.

## Directional discriminator model (critical)
User clarified a core algorithmic requirement:
- LEFT and RIGHT nodes are discriminators, not redundant scanners.
- Their role is to infer on which side of the road an AP is located.
- Side discrimination is then combined with trilateration logic.

Trilateration intent captured:
- Use RSSI-derived distance estimates relative to GPS-referenced omnidirectional captures.
- Apply this per specific channel to improve AP localization quality.

Sampling constraint captured:
- Vehicle speed is high during capture runs.
- Reliable AP positioning requires collecting more than one scan for a BSSID.
- System behavior should favor repeated/individual captures per AP before final position resolution.

## Discriminator/promiscuous synchronization caveat (critical)
User clarified capture-timing behavior:
- Discriminator nodes perform regular scan cycles (discrete scan events).
- ESP32 promiscuous nodes listen continuously on a single fixed channel.

Fusion rule captured:
- Synchronization windows must be anchored on discriminator scan boundaries.
- All promiscuous captures observed after one discriminator scan should be
  grouped/weighted under that discriminator scan context.
- Grouping window closes when the next discriminator scan arrives.

Practical implication:
- Capture weighting/validation should be time-windowed by discriminator events,
  not treated as globally uniform over continuous promiscuous traffic.

## Opposite-direction pass strategy (critical)
User clarified a localization goal:
- AP location quality should improve by combining captures from both travel
  directions on the same road (outbound and return passes).

Persistence requirement captured:
- BSSID records must remain permanently available in the database to accumulate
  multi-pass evidence over time.

Trilateration implication:
- Opposite-direction observations should be fused for the same BSSID to reduce
  directional bias and improve final AP position estimates after turns.

## Authoritative project objective (user clarification)
Core objective:
- Capture and store WiFi/GPS telemetry so it can be used later for trilateration
  and GeoJSON production of AP location records containing:
  `lat`, `lon`, `alt`, `rssi`, `ssid`, `bssid`.

Accuracy strategy:
- As the vehicle revisits the same roads repeatedly, accumulated capture points
  for each BSSID should improve localization accuracy over time.

Processing policy:
- Trilateration must run as a post-process and should not consume CPU during
  live capture collection.

Dashboard policy:
- Data presentation is for monitoring operations (satellite/GPS status, DB size,
  node activity), not for performing heavy localization computation inline.

## Timing source-of-truth (critical)
User clarified timing architecture:
- PPS is used as a timing reference.
- A monotonic timer is used for sequencing/stability.
- GPS time is used as a timing source for captured data.

Timestamping implication:
- Capture records should preserve timing lineage so downstream fusion/trilateration
  can rely on consistent temporal alignment across nodes and passes.

## Latest runtime validation snapshot (2026-05-09 UTC)
Purpose: preserve a rollback-safe operational checkpoint before new changes.

### Service state validated
- `db_writer.service` is active/running and stable (no restart loop observed at validation time).
- `db_writer_gate.service` is active/running.
- Related services active: `wifi_capture.service`, `gps_service.service`, `trilateration.service`, `broker.service`, `esp_usb_watchdog.service`.

### Writer path currently in production
- Systemd `ExecStart` currently launches:
  - `/home/sbejarano/wifi_promiscuous/host/db_writer.py`
- Note: production service path is not yet pointed at `db_writer_fixed.py` in this repository snapshot.

### Database write proof captured
- Query result at validation:
  - `select count(*), min(ts_utc), max(ts_utc) from wifi_captures;`
  - Result: `369207 | 2026-05-09T00:00:00+00:00 | 2026-05-09T00:33:39+00:00`
- Top-BSSID recency check also showed fresh writes up to `2026-05-09T00:34:13+00:00`.
- `trilateration_data_latest.db` contains table `wifi_captures`.

### Active DB file snapshot
- `trilateration_data_latest.db -> trilateration_data_20260509_000000.db`
- Active DB size observed near threshold: ~85 MB (+ WAL/SHM present).
- Prior tiny 4KB rotated files from earlier crash-loop period remain in directory as historical artifacts.

### Input/GPS snapshot captured
- `/dev/shm/wifi_capture.json` populated with live observations and GPS block.
- GPS at validation showed `gps_mode=3`, `gps_fix="3D FIX"`.
- PPS discipline was previously confirmed in `gps.json` (`pps_ok=true`).

### Rollback anchors
- Git checkpoint before introducing new upcoming changes:
  - `1fac7ee Add SYNC_NOTES and rotation-aware DB writer with schema/init and symlink management`
- Recommended operational rollback references on host before edits:
  1. `/etc/systemd/system/db_writer.service`
  2. `/home/sbejarano/wifi_promiscuous/host/db_writer.py`
  3. `/home/sbejarano/wifi_promiscuous/host/trilateration_service.py`
  4. Current symlink target: `/home/sbejarano/wifi_promiscuous/data/trilateration_data_latest.db`
