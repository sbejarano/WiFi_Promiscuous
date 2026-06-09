#!/usr/bin/env python3
"""
Capture-only DB writer with safe schema initialization and runtime rotation.

- Reads /dev/shm/wifi_capture.json snapshots.
- Persists OMNI/fixed-node captures into SQLite wifi_captures.
- Uses LEFT/RIGHT nodes only as retained discriminator state.
- Retains LEFT/RIGHT discriminator data between scans.
- Applies latest valid discriminator state to later OMNI/fixed captures.
- Expires LEFT and RIGHT discriminator values independently.
- Rotates DB on UTC day change OR when size >= MAX_DB_BYTES.
- Maintains trilateration_data_latest.db symlink.
- HARD RULE: No GPS fix = no database insert.
"""

import glob
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone

BASE = "/home/sbejarano/wifi_promiscuous"
SRC = "/dev/shm/wifi_capture.json"
DB_DIR = f"{BASE}/data"
DB_BASENAME = "trilateration_data"

POLL_S = 0.25
MAX_DB_BYTES = 100 * 1024 * 1024
KEEP_FILES = 30

DIRECTIONAL_NODES = {"LEFT", "RIGHT"}

SIDE_THRESHOLD_DB = 4.0

# LEFT/RIGHT discriminator memory.
DISCRIMINATOR_TTL_S = 12.0

# Prevent duplicate writes from the rolling /dev/shm buffer.
SEEN_CACHE_LIMIT = 75000

UPSERT_SQL = """
INSERT INTO wifi_captures (
  ts_utc, bssid, ssid, sample_count, median_rssi, avg_rssi,
  dominant_channel, frequency_mhz,
  est_lat, est_lon, est_alt, accuracy_m,
  left_rssi, right_rssi, differential, side, side_confidence,
  gps_lat_min, gps_lat_max, gps_lon_min, gps_lon_max,
  last_seen_ts,
  gps_ts_utc, gps_track_deg, gps_speed_mps,
  gps_heading_deg, gps_heading_valid, gps_speed_knots,
  gps_stationary, gps_valid, gps_pdop, gps_hdop, gps_vdop,
  gps_monotonic_ts
) VALUES (
  :ts_utc, :bssid, :ssid, :sample_count, :median_rssi, :avg_rssi,
  :dominant_channel, :frequency_mhz,
  :est_lat, :est_lon, :est_alt, :accuracy_m,
  :left_rssi, :right_rssi, :differential, :side, :side_confidence,
  :gps_lat_min, :gps_lat_max, :gps_lon_min, :gps_lon_max,
  :last_seen_ts,
  :gps_ts_utc, :gps_track_deg, :gps_speed_mps,
  :gps_heading_deg, :gps_heading_valid, :gps_speed_knots,
  :gps_stationary, :gps_valid, :gps_pdop, :gps_hdop, :gps_vdop,
  :gps_monotonic_ts
);
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wifi_captures (
  id INTEGER PRIMARY KEY,
  ts_utc TEXT NOT NULL,
  bssid TEXT NOT NULL,
  ssid TEXT,
  sample_count INTEGER,
  median_rssi INTEGER,
  avg_rssi REAL,
  dominant_channel INTEGER,
  frequency_mhz INTEGER,
  est_lat REAL,
  est_lon REAL,
  est_alt REAL,
  accuracy_m REAL,
  left_rssi INTEGER,
  right_rssi INTEGER,
  differential INTEGER,
  side TEXT,
  side_confidence REAL,
  gps_lat_min REAL,
  gps_lat_max REAL,
  gps_lon_min REAL,
  gps_lon_max REAL,
  last_seen_ts TEXT,
  gps_ts_utc TEXT,
  gps_track_deg REAL,
  gps_speed_mps REAL,
  gps_heading_deg REAL,
  gps_heading_valid INTEGER,
  gps_speed_knots REAL,
  gps_stationary INTEGER,
  gps_valid INTEGER,
  gps_pdop REAL,
  gps_hdop REAL,
  gps_vdop REAL,
  gps_monotonic_ts REAL
);

CREATE INDEX IF NOT EXISTS idx_wificap_bssid ON wifi_captures(bssid);
CREATE INDEX IF NOT EXISTS idx_wificap_ts ON wifi_captures(ts_utc);
CREATE INDEX IF NOT EXISTS idx_wificap_gps_ts ON wifi_captures(gps_ts_utc);
CREATE INDEX IF NOT EXISTS idx_wificap_channel ON wifi_captures(dominant_channel);
CREATE INDEX IF NOT EXISTS idx_wificap_side ON wifi_captures(side);
"""


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def choose_db_path():
    os.makedirs(DB_DIR, exist_ok=True)
    return f"{DB_DIR}/{DB_BASENAME}_{db_stamp()}.db"


def set_latest_symlink(db_path):
    latest = f"{DB_DIR}/{DB_BASENAME}_latest.db"
    try:
        if os.path.islink(latest) or os.path.exists(latest):
            os.remove(latest)
        os.symlink(os.path.basename(db_path), latest)
    except Exception:
        pass


def cleanup_old_db_files(keep=KEEP_FILES):
    pattern = f"{DB_DIR}/{DB_BASENAME}_*.db"
    files = sorted(glob.glob(pattern))

    files = [
        p for p in files
        if not p.endswith("_latest.db")
    ]

    if len(files) <= keep:
        return

    for p in files[:-keep]:
        try:
            os.remove(p)

            for suffix in ("-wal", "-shm"):
                side = p + suffix
                if os.path.exists(side):
                    os.remove(side)

        except Exception:
            continue


def ensure_columns(con):
    existing = {
        row[1]
        for row in con.execute(
            "PRAGMA table_info(wifi_captures);"
        ).fetchall()
    }

    columns = {
        "frequency_mhz": "INTEGER",
        "est_lat": "REAL",
        "est_lon": "REAL",
        "est_alt": "REAL",
        "accuracy_m": "REAL",
        "gps_lat_min": "REAL",
        "gps_lat_max": "REAL",
        "gps_lon_min": "REAL",
        "gps_lon_max": "REAL",
        "gps_heading_deg": "REAL",
        "gps_heading_valid": "INTEGER",
        "gps_speed_knots": "REAL",
        "gps_stationary": "INTEGER",
        "gps_valid": "INTEGER",
        "gps_pdop": "REAL",
        "gps_hdop": "REAL",
        "gps_vdop": "REAL",
        "gps_monotonic_ts": "REAL",
    }

    for name, col_type in columns.items():
        if name not in existing:
            con.execute(
                f"ALTER TABLE wifi_captures "
                f"ADD COLUMN {name} {col_type};"
            )


def connect_db(db_path):
    con = sqlite3.connect(
        db_path,
        timeout=5.0,
        isolation_level=None
    )

    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    con.executescript(SCHEMA_SQL)
    ensure_columns(con)

    return con


def read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def median(vals):
    if not vals:
        return None

    s = sorted(vals)
    n = len(s)
    mid = n // 2

    return s[mid] if n % 2 else int((s[mid - 1] + s[mid]) / 2)


def to_bool_int(value):
    if value is None:
        return None

    return 1 if bool(value) else 0


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def normalize_bssid(value):
    return (value or "").strip().upper()


def normalize_node(value):
    return str(value or "").strip().upper()


def normalize_channel(value):
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return value


def obs_time(o, fallback=None):
    t = safe_float(o.get("ts"), fallback)

    if t is None:
        t = time.time()

    return t


def obs_seen_key(o):
    return (
        normalize_node(o.get("node")),
        normalize_bssid(o.get("bssid")),
        normalize_channel(o.get("channel")),
        safe_int(o.get("rssi")),
        round(obs_time(o), 3),
    )


def gps_value(gps, *names):
    for name in names:
        if name in gps and gps.get(name) is not None:
            return gps.get(name)

    return None


def side_from_lr(left_rssi, right_rssi, threshold_db=SIDE_THRESHOLD_DB):
    if left_rssi is None and right_rssi is None:
        return "OMNI", None, None, None, 0

    if left_rssi is None:
        return "RIGHT", None, right_rssi, None, 60

    if right_rssi is None:
        return "LEFT", left_rssi, None, None, 60

    diff = int(left_rssi - right_rssi)

    if diff > threshold_db:
        side = "LEFT"
    elif diff < -threshold_db:
        side = "RIGHT"
    else:
        side = "OMNI"

    conf = max(0, min(100, int(abs(diff) * 10)))

    return side, left_rssi, right_rssi, diff, conf


class DiscriminatorCache:
    def __init__(self, ttl_s=DISCRIMINATOR_TTL_S):
        self.ttl_s = ttl_s
        self.cache = {}

    def key(self, bssid, channel):
        return (normalize_bssid(bssid), normalize_channel(channel))

    def update(self, node, bssid, channel, rssi, ts):
        node = normalize_node(node)

        if node not in DIRECTIONAL_NODES:
            return

        bssid = normalize_bssid(bssid)

        if not bssid:
            return

        rssi = safe_int(rssi)

        if rssi is None:
            return

        ts = safe_float(ts, time.time())
        k = self.key(bssid, channel)

        item = self.cache.get(k)

        if not item:
            item = {
                "left_rssi": None,
                "right_rssi": None,
                "left_ts": None,
                "right_ts": None,
                "updated_ts": ts,
            }

        if node == "LEFT":
            item["left_rssi"] = rssi
            item["left_ts"] = ts

        elif node == "RIGHT":
            item["right_rssi"] = rssi
            item["right_ts"] = ts

        item["updated_ts"] = ts
        self.cache[k] = item

    def get(self, bssid, channel, ts):
        ts = safe_float(ts, time.time())

        candidates = []
        k_exact = self.key(bssid, channel)

        if k_exact in self.cache:
            candidates.append(self.cache[k_exact])

        bssid_norm = normalize_bssid(bssid)
        channel_norm = normalize_channel(channel)

        for (cached_bssid, cached_channel), item in self.cache.items():
            if cached_bssid == bssid_norm and cached_channel != channel_norm:
                candidates.append(item)

        if not candidates:
            return "OMNI", None, None, None, 0

        best = None
        best_age = None

        for item in candidates:
            left_ts = safe_float(item.get("left_ts"))
            right_ts = safe_float(item.get("right_ts"))

            valid_times = []

            if left_ts is not None:
                valid_times.append(left_ts)

            if right_ts is not None:
                valid_times.append(right_ts)

            if not valid_times:
                continue

            newest_ts = max(valid_times)
            age = ts - newest_ts

            if age < 0:
                age = 0

            if age <= self.ttl_s:
                if best is None or age < best_age:
                    best = item
                    best_age = age

        if not best:
            return "OMNI", None, None, None, 0

        left_rssi = best.get("left_rssi")
        right_rssi = best.get("right_rssi")

        left_ts = safe_float(best.get("left_ts"))
        right_ts = safe_float(best.get("right_ts"))

        left_age = None
        right_age = None

        if left_ts is not None:
            left_age = ts - left_ts
            if left_age < 0:
                left_age = 0
            if left_age > self.ttl_s:
                left_rssi = None

        if right_ts is not None:
            right_age = ts - right_ts
            if right_age < 0:
                right_age = 0
            if right_age > self.ttl_s:
                right_rssi = None

        side, l, r, diff, conf = side_from_lr(
            left_rssi,
            right_rssi,
            SIDE_THRESHOLD_DB
        )

        oldest_valid_age = 0

        valid_ages = []

        if left_rssi is not None and left_age is not None:
            valid_ages.append(left_age)

        if right_rssi is not None and right_age is not None:
            valid_ages.append(right_age)

        if valid_ages:
            oldest_valid_age = max(valid_ages)

        if oldest_valid_age > (self.ttl_s * 0.75):
            conf = int(conf * 0.75)

        return side, l, r, diff, conf

    def prune(self, now_ts):
        now_ts = safe_float(now_ts, time.time())
        expired = []

        for k, item in self.cache.items():
            left_ts = safe_float(item.get("left_ts"))
            right_ts = safe_float(item.get("right_ts"))

            valid_times = []

            if left_ts is not None:
                valid_times.append(left_ts)

            if right_ts is not None:
                valid_times.append(right_ts)

            if not valid_times:
                expired.append(k)
                continue

            newest_ts = max(valid_times)

            if now_ts - newest_ts > self.ttl_s * 3:
                expired.append(k)

        for k in expired:
            self.cache.pop(k, None)


def aggregate_rows(payload, seen_obs_keys, discriminator_cache):
    observations = payload.get("observations") or []
    gps = payload.get("gps") or {}

    gps_valid = gps_value(gps, "gps_valid")

    if not gps_valid:
        if observations:
            print(
                f"[db_writer] GPS BLOCK: "
                f"gps_valid={gps_valid}; "
                f"skipping {len(observations)} observations",
                flush=True
            )
        return []

    gps_lat = gps_value(gps, "lat", "latitude", "gps_lat")
    gps_lon = gps_value(gps, "lon", "longitude", "gps_lon")
    gps_alt = gps_value(gps, "alt", "altitude", "gps_alt")
    gps_accuracy = gps_value(gps, "accuracy_m", "accuracy")

    if gps_lat is None or gps_lon is None:
        if observations:
            print(
                f"[db_writer] GPS BLOCK: "
                f"gps_valid={gps_valid}; "
                f"lat={gps_lat}; lon={gps_lon}; "
                f"skipping {len(observations)} observations",
                flush=True
            )
        return []

    new_obs = []

    for o in observations:
        bssid = normalize_bssid(o.get("bssid"))
        rssi = safe_int(o.get("rssi"))

        if not bssid or rssi is None:
            continue

        key = obs_seen_key(o)

        if key in seen_obs_keys:
            continue

        seen_obs_keys.add(key)
        new_obs.append(o)

    if not new_obs:
        return []

    if len(seen_obs_keys) > SEEN_CACHE_LIMIT:
        trimmed = list(seen_obs_keys)[-int(SEEN_CACHE_LIMIT / 2):]
        seen_obs_keys.clear()
        seen_obs_keys.update(trimmed)

    for o in new_obs:
        node = normalize_node(o.get("node"))

        if node in DIRECTIONAL_NODES:
            discriminator_cache.update(
                node=node,
                bssid=o.get("bssid"),
                channel=o.get("channel"),
                rssi=o.get("rssi"),
                ts=obs_time(o, payload.get("ts")),
            )

    discriminator_cache.prune(payload.get("ts") or time.time())

    primary_groups = defaultdict(list)

    for o in new_obs:
        node = normalize_node(o.get("node"))

        if node in DIRECTIONAL_NODES:
            continue

        bssid = normalize_bssid(o.get("bssid"))
        ch = normalize_channel(o.get("channel"))

        if not bssid:
            continue

        primary_groups[(bssid, ch)].append(o)

    if not primary_groups:
        return []

    gps_ts_utc = gps_value(gps, "gps_time_utc", "gps_ts_utc")

    gps_heading_deg = gps_value(
        gps,
        "heading_deg",
        "gps_heading_deg"
    )

    gps_track_deg = gps_value(
        gps,
        "track_deg",
        "gps_track_deg"
    )

    if gps_track_deg is None:
        gps_track_deg = gps_heading_deg

    gps_speed_mps = gps_value(gps, "speed_mps", "gps_speed_mps")
    gps_speed_knots = gps_value(gps, "speed_knots", "gps_speed_knots")

    gps_heading_valid = gps_value(
        gps,
        "heading_valid",
        "gps_heading_valid"
    )

    gps_stationary = gps_value(
        gps,
        "vehicle_stationary",
        "gps_stationary"
    )

    gps_pdop = gps_value(gps, "pdop", "gps_pdop")
    gps_hdop = gps_value(gps, "hdop", "gps_hdop")
    gps_vdop = gps_value(gps, "vdop", "gps_vdop")

    gps_monotonic_ts = gps_value(
        gps,
        "monotonic_ts",
        "gps_monotonic_ts"
    )

    rows = []

    for (bssid, grouped_channel), primary_samples in primary_groups.items():
        rssis = [
            safe_int(s.get("rssi"))
            for s in primary_samples
            if safe_int(s.get("rssi")) is not None
        ]

        if not rssis:
            continue

        channels = [
            normalize_channel(s.get("channel"))
            for s in primary_samples
            if normalize_channel(s.get("channel")) is not None
        ]

        ch_counts = defaultdict(int)

        for ch in channels:
            ch_counts[ch] += 1

        dominant_channel = (
            max(ch_counts, key=ch_counts.get)
            if ch_counts else grouped_channel
        )

        frequency_mhz = next(
            (
                s.get("frequency_mhz") or s.get("frequency")
                for s in reversed(primary_samples)
                if s.get("frequency_mhz") is not None
                or s.get("frequency") is not None
            ),
            None
        )

        last_seen = max(
            obs_time(s, payload.get("ts"))
            for s in primary_samples
        )

        side, left_rssi, right_rssi, diff, side_conf = discriminator_cache.get(
            bssid=bssid,
            channel=dominant_channel,
            ts=last_seen,
        )

        ssid = next(
            (
                (s.get("ssid") or "").strip()
                for s in reversed(primary_samples)
                if (s.get("ssid") or "").strip()
            ),
            None
        )

        rows.append({
            "ts_utc": utc_now_iso(),
            "bssid": bssid,
            "ssid": ssid,
            "sample_count": len(rssis),
            "median_rssi": median(rssis),
            "avg_rssi": float(sum(rssis) / len(rssis)),
            "dominant_channel": dominant_channel,
            "frequency_mhz": frequency_mhz,

            "est_lat": gps_lat,
            "est_lon": gps_lon,
            "est_alt": gps_alt,
            "accuracy_m": gps_accuracy,

            "left_rssi": left_rssi,
            "right_rssi": right_rssi,
            "differential": diff,
            "side": side,
            "side_confidence": side_conf,

            "gps_lat_min": gps_lat,
            "gps_lat_max": gps_lat,
            "gps_lon_min": gps_lon,
            "gps_lon_max": gps_lon,

            "last_seen_ts": datetime.fromtimestamp(
                last_seen,
                tz=timezone.utc
            ).isoformat(timespec="seconds"),

            "gps_ts_utc": gps_ts_utc,
            "gps_track_deg": gps_track_deg,
            "gps_speed_mps": gps_speed_mps,

            "gps_heading_deg": gps_heading_deg,
            "gps_heading_valid": to_bool_int(gps_heading_valid),

            "gps_speed_knots": gps_speed_knots,
            "gps_stationary": to_bool_int(gps_stationary),
            "gps_valid": 1,

            "gps_pdop": gps_pdop,
            "gps_hdop": gps_hdop,
            "gps_vdop": gps_vdop,
            "gps_monotonic_ts": gps_monotonic_ts,
        })

    if rows:
        side_counts = defaultdict(int)

        for r in rows:
            side_counts[r["side"]] += 1

        print(
            "[db_writer] rows="
            f"{len(rows)} "
            f"LEFT={side_counts.get('LEFT', 0)} "
            f"RIGHT={side_counts.get('RIGHT', 0)} "
            f"OMNI={side_counts.get('OMNI', 0)} "
            f"disc_cache={len(discriminator_cache.cache)}",
            flush=True
        )

    return rows


def should_rotate(db_path, opened_day):
    now_day = datetime.now(timezone.utc).date()

    if now_day != opened_day:
        return True

    try:
        if os.path.exists(db_path) and os.path.getsize(db_path) >= MAX_DB_BYTES:
            return True
    except Exception:
        pass

    return False


def open_new_db():
    db_path = choose_db_path()
    con = connect_db(db_path)

    set_latest_symlink(db_path)
    cleanup_old_db_files()

    opened_day = datetime.now(timezone.utc).date()

    print(
        f"[db_writer] using database: {db_path}",
        flush=True
    )

    return con, db_path, opened_day


def main():
    con, db_path, opened_day = open_new_db()

    last_src_ts = None
    seen_obs_keys = set()
    discriminator_cache = DiscriminatorCache(DISCRIMINATOR_TTL_S)

    while True:
        try:
            if should_rotate(db_path, opened_day):
                try:
                    con.close()
                except Exception:
                    pass

                con, db_path, opened_day = open_new_db()
                seen_obs_keys.clear()
                discriminator_cache = DiscriminatorCache(DISCRIMINATOR_TTL_S)

            payload = read_json(SRC)

            if not payload:
                time.sleep(POLL_S)
                continue

            src_ts = payload.get("ts")

            if src_ts is not None and src_ts == last_src_ts:
                time.sleep(POLL_S)
                continue

            last_src_ts = src_ts

            rows = aggregate_rows(
                payload,
                seen_obs_keys,
                discriminator_cache
            )

            if rows:
                con.executemany(UPSERT_SQL, rows)

            time.sleep(POLL_S)

        except Exception as e:
            print(
                f"[db_writer] loop error: {e}",
                flush=True
            )
            time.sleep(1)


if __name__ == "__main__":
    main()
