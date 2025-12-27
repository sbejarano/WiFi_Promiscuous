#!/usr/bin/env python3
import sqlite3, time, math, json, os, sys
from datetime import datetime, timezone

DB_PATH = "/media/sbejarano/Developer1/wifi_promiscuous/tmp/wifi_logs.db"  # adjust
SRC_JSON = "/dev/shm/trilaterated.json"  # adjust to your output
POLL_S = 1.0

UPSERT_SQL = """
INSERT INTO wifi_ap_position (
  bssid, lat, lon, err_m, confidence, best_score,
  last_seen_utc, best_seen_utc, last_rssi, last_channel, side, updates
) VALUES (
  :bssid, :lat, :lon, :err_m, :confidence, :best_score,
  :last_seen_utc, :best_seen_utc, :last_rssi, :last_channel, :side, 1
)
ON CONFLICT(bssid) DO UPDATE SET
  last_seen_utc = excluded.last_seen_utc,
  last_rssi     = excluded.last_rssi,
  last_channel  = excluded.last_channel,
  side          = excluded.side,

  lat           = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.lat ELSE wifi_ap_position.lat END,
  lon           = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.lon ELSE wifi_ap_position.lon END,
  err_m         = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.err_m ELSE wifi_ap_position.err_m END,
  confidence    = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.confidence ELSE wifi_ap_position.confidence END,
  best_score    = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.best_score ELSE wifi_ap_position.best_score END,
  best_seen_utc = CASE WHEN excluded.best_score > wifi_ap_position.best_score THEN excluded.best_seen_utc ELSE wifi_ap_position.best_seen_utc END,

  updates       = wifi_ap_position.updates + 1;
"""

def utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def best_score(confidence: float, err_m: float) -> float:
    # monotonic comparator: higher is better
    e = max(float(err_m), 1.0)
    c = float(confidence)
    return c / e

def connect_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=5.0, isolation_level=None)  # autocommit
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con

def ensure_schema(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS wifi_ap_position (
      bssid           TEXT PRIMARY KEY,
      lat             REAL NOT NULL,
      lon             REAL NOT NULL,
      err_m           REAL NOT NULL,
      confidence      REAL NOT NULL,
      best_score      REAL NOT NULL,
      last_seen_utc   TEXT NOT NULL,
      best_seen_utc   TEXT NOT NULL,
      last_rssi       REAL,
      last_channel    INTEGER,
      side            TEXT,
      updates         INTEGER NOT NULL DEFAULT 0
    );
    """)

def read_json(path: str):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[writer] JSON read error: {e}", file=sys.stderr)
        return None

def write_one(con: sqlite3.Connection, row: dict):
    # Required fields from your trilateration output:
    # bssid, lat, lon, err_m, confidence, rssi, channel, side
    bssid = row.get("bssid")
    if not bssid:
        return

    lat = row.get("lat"); lon = row.get("lon")
    err_m = row.get("err_m"); conf = row.get("confidence")

    # Reject obviously bad points, but LOG them if needed
    if lat is None or lon is None or err_m is None or conf is None:
        return
    if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
        return
    if float(err_m) <= 0:
        return

    now = utc_iso()
    score = best_score(conf, err_m)

    params = {
        "bssid": bssid,
        "lat": float(lat),
        "lon": float(lon),
        "err_m": float(err_m),
        "confidence": float(conf),
        "best_score": float(score),
        "last_seen_utc": now,
        "best_seen_utc": now,
        "last_rssi": row.get("avg_rssi") if "avg_rssi" in row else row.get("rssi"),
        "last_channel": row.get("dominant_channel") if "dominant_channel" in row else row.get("channel"),
        "side": row.get("side", "UNKNOWN"),
    }

    # Retry on lock without killing the loop
    for attempt in range(1, 6):
        try:
            con.execute("BEGIN;")
            con.execute(UPSERT_SQL, params)
            con.execute("COMMIT;")
            return
        except sqlite3.OperationalError as e:
            con.execute("ROLLBACK;")
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                time.sleep(0.1 * attempt)
                continue
            print(f"[writer] OperationalError bssid={bssid} err={e}", file=sys.stderr)
            return
        except Exception as e:
            try: con.execute("ROLLBACK;")
            except Exception: pass
            print(f"[writer] Write error bssid={bssid} err_m={err_m} conf={conf} score={score} err={e}", file=sys.stderr)
            return

def main():
    con = connect_db(DB_PATH)
    ensure_schema(con)

    last_ts = None

    while True:
        data = read_json(SRC_JSON)
        if not data:
            time.sleep(POLL_S)
            continue

        # If your json includes a timestamp, use it to avoid reprocessing duplicates
        ts = data.get("ts") or data.get("_ts")
        if ts is not None and ts == last_ts:
            time.sleep(POLL_S)
            continue
        last_ts = ts

        rows = data.get("aps") or data.get("results") or []
        if isinstance(rows, dict):
            rows = [rows]

        for r in rows:
            write_one(con, r)

        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
