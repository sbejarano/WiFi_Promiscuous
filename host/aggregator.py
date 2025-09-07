#!/usr/bin/env python3
"""
Aggregator: multi-serial ESP32 capture + GPS NMEA fusion → SQLite/CSV.

What it does:
- Loads YAML config (host/config.yaml)
- Opens GPS NMEA port (pynmea2) in a thread; keeps the latest fix in memory
- Opens 12 ESP32 ports (ttyACM0..11) in threads; reads line-delimited entries
- Accepts ESP lines as JSON or CSV:
    JSON example:
      {"node":3,"ch":3,"freq":2422,"bssid":"AA:BB:CC:DD:EE:FF","ssid":"Cafe","rssi":-63,"bint":102}
    CSV example (headerless, same order):
      node,ch,freq,bssid,ssid,rssi,bint
      3,3,2422,AA:BB:CC:DD:EE:FF,Cafe,-63,102
- Fuses each capture with the latest GPS fix and timestamp
- Writes to SQLite (default) or CSV (if configured) in batches
- Handles backpressure via an internal queue

Notes:
- PPS lock status is not read directly here; set gps.use_pps in config to inform pps_locked flag.
- If your ESP firmware does not send "freq", we compute it from channel.
- For CSV storage, the header is created if file doesn't exist.

Dependencies (see host/requirements.txt):
  pyserial, pynmea2, pyyaml, numpy, pandas, tqdm, geojson, pyproj, shapely, scipy

"""

import argparse
import csv as csvmod
import json
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import serial
import serial.tools.list_ports
import pynmea2
import yaml

# ------------------------------------------------------------
# Constants / CSV header
# ------------------------------------------------------------
CSV_HEADER = (
    "ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,beacon_interval_ms,"
    "gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_track_deg,gps_hdop,gps_vdop,pps_locked\n"
)

CHANNEL_TO_FREQ = {
    # 2.4 GHz (802.11b/g/n)
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
    7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484
}

# ------------------------------------------------------------
# Data classes
# ------------------------------------------------------------
@dataclass
class GPSFix:
    ts_utc: float            # epoch seconds of the fix
    lat: Optional[float]
    lon: Optional[float]
    alt_m: Optional[float]
    speed_mps: Optional[float]
    track_deg: Optional[float]
    hdop: Optional[float]
    vdop: Optional[float]
    pps_locked: bool

# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]  # ~/wifi_promiscuous

def load_config(path: Path) -> dict:
    with path.open("r") as f:
        return yaml.safe_load(f) or {}

def open_serial(port: str, baud: int = 115200, timeout: float = 0.2) -> serial.Serial:
    return serial.Serial(port=port, baudrate=baud, timeout=timeout)

def freq_from_channel(ch: int) -> int:
    return CHANNEL_TO_FREQ.get(ch, 2412 + 5 * (ch - 1))

# ------------------------------------------------------------
# GPS reader thread
# ------------------------------------------------------------
class GPSReader(threading.Thread):
    def __init__(self, port: str, baud: int, use_pps: bool, max_fix_age_ms: int):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.use_pps = use_pps
        self.max_fix_age_ms = max_fix_age_ms
        self._stop = threading.Event()
        self._ser = None
        self._lock = threading.Lock()
        self._fix: Optional[GPSFix] = None

    def run(self):
        try:
            self._ser = open_serial(self.port, self.baud, timeout=1.0)
        except Exception as e:
            print(f"[gps] Failed to open {self.port}: {e}", file=sys.stderr)
            return

        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(1024)
                if not chunk:
                    continue
                buf.extend(chunk)
                # process by lines
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    self._handle_line(line.decode(errors="ignore").strip())
            except Exception as e:
                print(f"[gps] Error: {e}", file=sys.stderr)
                time.sleep(0.5)

        try:
            self._ser.close()
        except Exception:
            pass

    def _handle_line(self, line: str):
        if not line.startswith("$"):
            return
        try:
            msg = pynmea2.parse(line, check=True)
        except Exception:
            return

        # We’ll gather fields from common sentences (RMC, GGA, GSA)
        lat = lon = alt = spd = trk = hdop = vdop = None
        ts = time.time()

        if isinstance(msg, pynmea2.types.talker.RMC):
            # Recommended Minimum data
            if msg.status == "A":
                lat = msg.latitude if msg.latitude else None
                lon = msg.longitude if msg.longitude else None
                # speed in knots → m/s
                try:
                    if msg.spd_over_grnd is not None:
                        spd = float(msg.spd_over_grnd) * 0.514444
                except Exception:
                    pass
                try:
                    if msg.true_course is not None:
                        trk = float(msg.true_course)
                except Exception:
                    pass

        elif isinstance(msg, pynmea2.types.talker.GGA):
            # Fix data
            try:
                lat = msg.latitude if msg.latitude else None
                lon = msg.longitude if msg.longitude else None
                alt = float(msg.altitude) if msg.altitude not in ("", None) else None
                hdop = float(msg.horizontal_dil) if msg.horizontal_dil not in ("", None) else None
            except Exception:
                pass

        elif isinstance(msg, pynmea2.types.talker.GSA):
            # DOP values
            try:
                hdop = float(msg.hdop) if msg.hdop not in ("", None) else None
                vdop = float(msg.vdop) if msg.vdop not in ("", None) else None
            except Exception:
                pass

        # Merge with previous fix if partial
        with self._lock:
            prev = self._fix
            if prev is not None:
                lat = lat if lat is not None else prev.lat
                lon = lon if lon is not None else prev.lon
                alt = alt if alt is not None else prev.alt_m
                spd = spd if spd is not None else prev.speed_mps
                trk = trk if trk is not None else prev.track_deg
                hdop = hdop if hdop is not None else prev.hdop
                vdop = vdop if vdop is not None else prev.vdop
            self._fix = GPSFix(
                ts_utc=ts,
                lat=lat, lon=lon, alt_m=alt,
                speed_mps=spd, track_deg=trk,
                hdop=hdop, vdop=vdop,
                pps_locked=bool(self.use_pps)
            )

    def latest_fix(self) -> Optional[GPSFix]:
        with self._lock:
            fix = self._fix
        if not fix:
            return None
        # Age filter
        if (time.time() - fix.ts_utc) * 1000.0 > self.max_fix_age_ms:
            return None
        return fix

    def stop(self):
        self._stop.set()

# ------------------------------------------------------------
# Probe reader thread
# ------------------------------------------------------------
class ProbeReader(threading.Thread):
    def __init__(self, node_id: int, port: str, out_queue: queue.Queue, baud: int = 115200):
        super().__init__(daemon=True)
        self.node_id = node_id
        self.port = port
        self.baud = baud
        self._stop = threading.Event()
        self._ser = None
        self._buf = bytearray()
        self._q = out_queue

    def run(self):
        try:
            self._ser = open_serial(self.port, self.baud, timeout=0.1)
            print(f"[probe {self.node_id}] opened {self.port}")
        except Exception as e:
            print(f"[probe {self.node_id}] failed to open {self.port}: {e}", file=sys.stderr)
            return

        while not self._stop.is_set():
            try:
                chunk = self._ser.read(1024)
                if not chunk:
                    continue
                self._buf.extend(chunk)
                while b"\n" in self._buf:
                    line, _, self._buf = self._buf.partition(b"\n")
                    s = line.decode(errors="ignore").strip()
                    if s:
                        rec = self._parse_line(s)
                        if rec:
                            self._q.put(rec, block=False)
            except queue.Full:
                # Drop to avoid backpressure explosion
                pass
            except Exception as e:
                print(f"[probe {self.node_id}] read error: {e}", file=sys.stderr)
                time.sleep(0.1)

        try:
            self._ser.close()
        except Exception:
            pass

    def _parse_line(self, s: str) -> Optional[Dict[str, Any]]:
        # Try JSON first
        try:
            obj = json.loads(s)
            # Normalize keys
            node = int(obj.get("node", self.node_id))
            ch = int(obj.get("ch") or obj.get("channel") or 0)
            freq = int(obj.get("freq") or obj.get("frequency_mhz") or 0) or freq_from_channel(ch)
            bssid = str(obj.get("bssid", "")).strip()
            ssid = obj.get("ssid", "")
            rssi = int(obj.get("rssi") or obj.get("rssi_dbm") or 0)
            bint = obj.get("bint") or obj.get("beacon_interval_ms") or None
            bint = int(bint) if bint not in (None, "") else None
            return dict(node_id=node, channel=ch, frequency_mhz=freq,
                        bssid=bssid, ssid=ssid, rssi_dbm=rssi,
                        beacon_interval_ms=bint)
        except Exception:
            pass

        # Try CSV: node,ch,freq,bssid,ssid,rssi,bint
        try:
            parts = [p.strip() for p in s.split(",")]
            if len(parts) >= 7:
                node = int(parts[0] or self.node_id)
                ch = int(parts[1])
                freq = int(parts[2]) if parts[2] else freq_from_channel(ch)
                bssid = parts[3]
                ssid = parts[4]
                rssi = int(parts[5])
                bint = int(parts[6]) if parts[6] else None
                return dict(node_id=node, channel=ch, frequency_mhz=freq,
                            bssid=bssid, ssid=ssid, rssi_dbm=rssi,
                            beacon_interval_ms=bint)
        except Exception:
            pass

        return None

    def stop(self):
        self._stop.set()

# ------------------------------------------------------------
# Storage writers
# ------------------------------------------------------------
class SQLiteWriter:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.lock = threading.Lock()

    def write_batch(self, rows):
        if not rows:
            return
        with self.lock:
            self.conn.executemany("""
                INSERT INTO wifi_captures
                (ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,
                 beacon_interval_ms,gps_lat,gps_lon,gps_alt_m,gps_speed_mps,
                 gps_track_deg,pps_locked)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

class CSVWriter:
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        ensure_dir(csv_path.parent)
        self.file = open(csv_path, "a", encoding="utf-8", newline="")
        self.writer = csvmod.writer(self.file)
        # Write header if empty
        if self.file.tell() == 0:
            self.file.write(CSV_HEADER)

    def write_batch(self, rows):
        # Convert tuples to list (without header; header already written)
        for r in rows:
            self.writer.writerow(r)

        self.file.flush()

    def close(self):
        try:
            self.file.close()
        except Exception:
            pass

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Wi-Fi Aggregator")
    parser.add_argument("--config", required=True, help="Path to host/config.yaml")
    args = parser.parse_args()

    root = repo_root()
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    cfg = load_config(cfg_path)

    gps_cfg = cfg.get("gps", {})
    probes_cfg = cfg.get("probes", {})
    storage_cfg = cfg.get("storage", {})
    runtime_cfg = cfg.get("runtime", {})

    # Storage setup
    mode = storage_cfg.get("mode", "sqlite").lower()
    if mode == "sqlite":
        sqlite_path = storage_cfg.get("sqlite_path", "data/captures.sqlite")
        sqlite_path = root / sqlite_path if not os.path.isabs(sqlite_path) else Path(sqlite_path)
        ensure_dir(sqlite_path.parent)
        # Ensure schema
        schema_path = root / "host" / "schemas" / "sqlite_schema.sql"
        if not sqlite_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(sqlite_path))
            with schema_path.open("r") as f:
                conn.executescript(f.read())
            conn.close()
        writer = SQLiteWriter(sqlite_path)
        print(f"[storage] SQLite → {sqlite_path}")
    elif mode == "csv":
        csv_path = storage_cfg.get("csv_path", "data/captures.csv")
        csv_path = root / csv_path if not os.path.isabs(csv_path) else Path(csv_path)
        writer = CSVWriter(csv_path)
        print(f"[storage] CSV → {csv_path}")
    else:
        print(f"[error] Unknown storage mode: {mode}")
        return 2

    # Queue for probe records
    q = queue.Queue(maxsize=int(runtime_cfg.get("queue_max", 10000)))

    # Start GPS thread
    gps_reader = GPSReader(
        port=gps_cfg.get("nmea_port", "/dev/ttyUSB0"),
        baud=int(gps_cfg.get("nmea_baud", 9600)),
        use_pps=bool(gps_cfg.get("use_pps", True)),
        max_fix_age_ms=int(gps_cfg.get("max_fix_age_ms", 500))
    )
    gps_reader.start()

    # Start probe threads
    probe_threads = []
    for node_str, port in sorted(probes_cfg.items(), key=lambda kv: int(kv[0])):
        t = ProbeReader(node_id=int(node_str), port=str(port), out_queue=q)
        t.start()
        probe_threads.append(t)

    batch = []
    batch_size = 200
    status_interval = int(runtime_cfg.get("status_interval_s", 5))
    last_status = time.time()

    # Graceful shutdown
    stopping = threading.Event()

    def handle_sigint(sig, frame):
        stopping.set()
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    print("[run] Aggregator running. Ctrl+C to stop.")
    try:
        while not stopping.is_set():
            try:
                rec = q.get(timeout=0.2)
            except queue.Empty:
                rec = None

            # Build output row(s)
            if rec:
                fix = gps_reader.latest_fix()
                ts = now_iso()
                row = (
                    ts,
                    int(rec.get("node_id", 0)),
                    int(rec.get("channel", 0)),
                    int(rec.get("frequency_mhz", 0)),
                    str(rec.get("bssid", "")),
                    str(rec.get("ssid", "")),
                    int(rec.get("rssi_dbm", 0)),
                    rec.get("beacon_interval_ms", None),
                    (fix.lat if fix else None),
                    (fix.lon if fix else None),
                    (fix.alt_m if fix else None),
                    (fix.speed_mps if fix else None),
                    (fix.track_deg if fix else None),
                    (fix.hdop if fix else None),
                    (fix.vdop if fix else None),
                    int(fix.pps_locked) if fix else int(bool(gps_cfg.get("use_pps", True))),
                )
                batch.append(row)

            # Flush batch
            if len(batch) >= batch_size or (rec is None and batch):
                try:
                    writer.write_batch(batch)
                except Exception as e:
                    print(f"[write] error: {e}", file=sys.stderr)
                batch.clear()

            # Periodic status
            if time.time() - last_status >= status_interval:
                last_status = time.time()
                qsize = q.qsize()
                print(f"[status] q={qsize} gps={'ok' if gps_reader.latest_fix() else 'stale'}")

    finally:
        print("\n[shutdown] stopping threads…")
        for t in probe_threads:
            t.stop()
        gps_reader.stop()
        for t in probe_threads:
            t.join(timeout=1.0)
        gps_reader.join(timeout=1.0)

        # Flush any remaining
        if batch:
            try:
                writer.write_batch(batch)
            except Exception as e:
                print(f"[write] final flush error: {e}", file=sys.stderr)

        try:
            writer.close()
        except Exception:
            pass

        print("[done] Aggregator stopped.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
