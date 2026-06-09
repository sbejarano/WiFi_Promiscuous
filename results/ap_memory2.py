#!/usr/bin/env python3
import glob
import json
import math
import os
import sqlite3
from datetime import datetime, timezone

RESULTS_DIR = "/home/sbejarano/wifi_promiscuous/results"
MEMORY_DB = os.path.join(RESULTS_DIR, "ap_memory.db")
MEMORY_GEOJSON = os.path.join(RESULTS_DIR, "ap_memory.geojson")
MEMORY_AP_GEOJSON = os.path.join(RESULTS_DIR, "ap_memory_aps.geojson")
MEMORY_MOBILE_GEOJSON = os.path.join(RESULTS_DIR, "ap_memory_mobile_candidates.geojson")

BATCH_PATTERN = os.path.join(RESULTS_DIR, "ap_trilateration_*.db")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def scalar(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row else None


def create_schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS ap_state (
        bssid TEXT PRIMARY KEY,
        ssid TEXT,
        channel TEXT,

        est_lat REAL NOT NULL,
        est_lon REAL NOT NULL,
        est_alt REAL,

        confidence REAL NOT NULL,

        observation_count INTEGER NOT NULL,
        batch_count INTEGER NOT NULL,

        avg_rssi REAL,
        strongest_rssi REAL,
        weakest_rssi REAL,
        spread_m REAL,

        left_count INTEGER NOT NULL DEFAULT 0,
        right_count INTEGER NOT NULL DEFAULT 0,
        omni_count INTEGER NOT NULL DEFAULT 0,

        directional_observation_count INTEGER NOT NULL DEFAULT 0,
        heading_observation_count INTEGER NOT NULL DEFAULT 0,

        first_seen TEXT,
        last_seen TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ap_source_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bssid TEXT NOT NULL,
        source_db TEXT NOT NULL,

        ssid TEXT,
        channel TEXT,

        est_lat REAL NOT NULL,
        est_lon REAL NOT NULL,
        est_alt REAL,

        confidence REAL,
        observation_count INTEGER,
        avg_rssi REAL,
        strongest_rssi REAL,
        weakest_rssi REAL,
        spread_m REAL,
        dominant_side TEXT,

        first_seen TEXT,
        last_seen TEXT,
        processed_at TEXT NOT NULL,

        UNIQUE (bssid, source_db)
    );

    CREATE TABLE IF NOT EXISTS processed_batches (
        source_db TEXT PRIMARY KEY,
        processed_at TEXT NOT NULL,
        row_count INTEGER NOT NULL DEFAULT 0
    );
    """)
    con.commit()


def has_required_table(con):
    row = con.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='ap_trilateration_results'
    """).fetchone()
    return row is not None


def batch_already_processed(con, source_db):
    return scalar(
        con,
        "SELECT 1 FROM processed_batches WHERE source_db = ?",
        (source_db,)
    ) is not None


def mark_batch_processed(con, source_db, row_count):
    con.execute("""
        INSERT OR REPLACE INTO processed_batches (
            source_db,
            processed_at,
            row_count
        )
        VALUES (?, ?, ?)
    """, (source_db, utc_now(), row_count))


def side_counts(side):
    side = (side or "OMNI").upper()

    if side == "LEFT":
        return 1, 0, 0
    if side == "RIGHT":
        return 0, 1, 0

    return 0, 0, 1


def evidence_weight(row):
    confidence = max(1.0, float(row["confidence"] or 1.0))
    observations = max(1.0, float(row["observation_count"] or 1.0))
    spread = max(1.0, float(row["spread_m"] or 1.0))

    return max(
        0.001,
        confidence * math.log1p(observations) / (1.0 + spread)
    )


def merge_value(old_value, old_weight, new_value, new_weight):
    if old_value is None:
        return new_value
    if new_value is None:
        return old_value

    total = old_weight + new_weight
    if total <= 0:
        return new_value

    return ((old_value * old_weight) + (new_value * new_weight)) / total


def min_time(a, b):
    if not a:
        return b
    if not b:
        return a
    return min(a, b)


def max_time(a, b):
    if not a:
        return b
    if not b:
        return a
    return max(a, b)


def insert_source_history(con, source_db, row):
    con.execute("""
        INSERT OR IGNORE INTO ap_source_history (
            bssid,
            source_db,
            ssid,
            channel,
            est_lat,
            est_lon,
            est_alt,
            confidence,
            observation_count,
            avg_rssi,
            strongest_rssi,
            weakest_rssi,
            spread_m,
            dominant_side,
            first_seen,
            last_seen,
            processed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["bssid"],
        source_db,
        row["ssid"],
        str(row["channel"]) if row["channel"] is not None else None,
        row["est_lat"],
        row["est_lon"],
        row["est_alt"],
        row["confidence"],
        row["observation_count"],
        row["avg_rssi"],
        row["strongest_rssi"],
        row["weakest_rssi"],
        row["spread_m"],
        row["dominant_side"],
        row["first_seen"],
        row["last_seen"],
        utc_now(),
    ))


def update_ap_state(con, source_db, row):
    bssid = row["bssid"]
    left_add, right_add, omni_add = side_counts(row["dominant_side"])

    existing = con.execute("""
        SELECT *
        FROM ap_state
        WHERE bssid = ?
    """, (bssid,)).fetchone()

    new_weight = evidence_weight(row)

    if existing is None:
        con.execute("""
            INSERT INTO ap_state (
                bssid,
                ssid,
                channel,
                est_lat,
                est_lon,
                est_alt,
                confidence,
                observation_count,
                batch_count,
                avg_rssi,
                strongest_rssi,
                weakest_rssi,
                spread_m,
                left_count,
                right_count,
                omni_count,
                directional_observation_count,
                heading_observation_count,
                first_seen,
                last_seen,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bssid,
            row["ssid"],
            str(row["channel"]) if row["channel"] is not None else None,
            row["est_lat"],
            row["est_lon"],
            row["est_alt"],
            row["confidence"] or 1.0,
            row["observation_count"] or 0,
            1,
            row["avg_rssi"],
            row["strongest_rssi"],
            row["weakest_rssi"],
            row["spread_m"],
            left_add,
            right_add,
            omni_add,
            row["directional_observation_count"] or 0,
            row["heading_observation_count"] or 0,
            row["first_seen"],
            row["last_seen"],
            utc_now(),
        ))

    else:
        old_weight = evidence_weight(existing)

        merged_lat = merge_value(existing["est_lat"], old_weight, row["est_lat"], new_weight)
        merged_lon = merge_value(existing["est_lon"], old_weight, row["est_lon"], new_weight)
        merged_alt = merge_value(existing["est_alt"], old_weight, row["est_alt"], new_weight)

        merged_confidence = min(
            100.0,
            merge_value(existing["confidence"], old_weight, row["confidence"], new_weight)
        )

        merged_avg_rssi = merge_value(existing["avg_rssi"], old_weight, row["avg_rssi"], new_weight)
        merged_strongest = max(
            existing["strongest_rssi"] if existing["strongest_rssi"] is not None else -999,
            row["strongest_rssi"] if row["strongest_rssi"] is not None else -999,
        )
        merged_weakest = min(
            existing["weakest_rssi"] if existing["weakest_rssi"] is not None else 999,
            row["weakest_rssi"] if row["weakest_rssi"] is not None else 999,
        )
        merged_spread = merge_value(existing["spread_m"], old_weight, row["spread_m"], new_weight)

        con.execute("""
            UPDATE ap_state
            SET
                ssid = ?,
                channel = ?,
                est_lat = ?,
                est_lon = ?,
                est_alt = ?,
                confidence = ?,
                observation_count = ?,
                batch_count = ?,
                avg_rssi = ?,
                strongest_rssi = ?,
                weakest_rssi = ?,
                spread_m = ?,
                left_count = ?,
                right_count = ?,
                omni_count = ?,
                directional_observation_count = ?,
                heading_observation_count = ?,
                first_seen = ?,
                last_seen = ?,
                updated_at = ?
            WHERE bssid = ?
        """, (
            row["ssid"] or existing["ssid"],
            str(row["channel"]) if row["channel"] is not None else existing["channel"],
            merged_lat,
            merged_lon,
            merged_alt,
            merged_confidence,
            existing["observation_count"] + (row["observation_count"] or 0),
            existing["batch_count"] + 1,
            merged_avg_rssi,
            merged_strongest,
            merged_weakest,
            merged_spread,
            existing["left_count"] + left_add,
            existing["right_count"] + right_add,
            existing["omni_count"] + omni_add,
            existing["directional_observation_count"] + (row["directional_observation_count"] or 0),
            existing["heading_observation_count"] + (row["heading_observation_count"] or 0),
            min_time(existing["first_seen"], row["first_seen"]),
            max_time(existing["last_seen"], row["last_seen"]),
            utc_now(),
            bssid,
        ))

    insert_source_history(con, source_db, row)


def process_batch(memory_con, batch_path):
    source_db = os.path.basename(batch_path)

    if source_db == os.path.basename(MEMORY_DB):
        return 0

    if batch_already_processed(memory_con, source_db):
        print(f"[SKIP] Already processed: {source_db}")
        return 0

    print(f"[INFO] Processing: {source_db}")

    batch_con = open_db(batch_path)

    try:
        if not has_required_table(batch_con):
            print(f"[WARN] Missing ap_trilateration_results: {source_db}")
            mark_batch_processed(memory_con, source_db, 0)
            memory_con.commit()
            return 0

        rows = batch_con.execute("""
            SELECT *
            FROM ap_trilateration_results
            WHERE bssid IS NOT NULL
              AND est_lat IS NOT NULL
              AND est_lon IS NOT NULL
            ORDER BY confidence DESC, observation_count DESC
        """).fetchall()

        if not rows:
            print(f"[WARN] No AP rows: {source_db}")
            mark_batch_processed(memory_con, source_db, 0)
            memory_con.commit()
            return 0

        count = 0

        for row in rows:
            update_ap_state(memory_con, source_db, row)
            count += 1

        mark_batch_processed(memory_con, source_db, count)
        memory_con.commit()

        print(f"[DONE] {source_db}: {count} APs merged")
        return count

    finally:
        batch_con.close()


def is_mobile_candidate(ssid):
    if not ssid:
        return False

    s = str(ssid).lower().strip()

    mobile_keywords = [
        "iphone",
        "ipad",
        "android",
        "galaxy",
        "pixel",
        "moto",
        "motorola",
        "oneplus",
        "xiaomi",
        "redmi",
        "poco",
        "huawei",
        "honor",
        "oppo",
        "vivo",
        "samsung",
        "phone",
        "mobile",
        "hotspot",
        "personal hotspot",
        "tether",
    ]

    return any(k in s for k in mobile_keywords)


def export_geojson(con):
    rows = con.execute("""
        SELECT *
        FROM ap_state
        ORDER BY confidence DESC, observation_count DESC
    """).fetchall()

    ap_features = []
    mobile_features = []

    for row in rows:
        coords = [row["est_lon"], row["est_lat"]]

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": coords,
            },
            "properties": {
                "bssid": row["bssid"],
                "ssid": row["ssid"],
                "channel": row["channel"],
                "confidence": row["confidence"],
                "observation_count": row["observation_count"],
                "batch_count": row["batch_count"],
                "avg_rssi": row["avg_rssi"],
                "strongest_rssi": row["strongest_rssi"],
                "weakest_rssi": row["weakest_rssi"],
                "spread_m": row["spread_m"],
                "left_count": row["left_count"],
                "right_count": row["right_count"],
                "omni_count": row["omni_count"],
                "directional_observation_count": row["directional_observation_count"],
                "heading_observation_count": row["heading_observation_count"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "updated_at": row["updated_at"],
                "category": "mobile_candidate" if is_mobile_candidate(row["ssid"]) else "ap",
            }
        }

        if is_mobile_candidate(row["ssid"]):
            mobile_features.append(feature)
        else:
            ap_features.append(feature)

    ap_obj = {
        "type": "FeatureCollection",
        "features": ap_features
    }

    mobile_obj = {
        "type": "FeatureCollection",
        "features": mobile_features
    }

    with open(MEMORY_AP_GEOJSON, "w") as f:
        json.dump(ap_obj, f, indent=2)

    with open(MEMORY_MOBILE_GEOJSON, "w") as f:
        json.dump(mobile_obj, f, indent=2)

    print(f"[DONE] AP GeoJSON written: {MEMORY_AP_GEOJSON}")
    print(f"[DONE] AP GeoJSON count: {len(ap_features)}")
    print(f"[DONE] Mobile candidate GeoJSON written: {MEMORY_MOBILE_GEOJSON}")
    print(f"[DONE] Mobile candidate GeoJSON count: {len(mobile_features)}")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    batch_files = sorted(glob.glob(BATCH_PATTERN))

    batch_files = [
        f for f in batch_files
        if os.path.basename(f) != os.path.basename(MEMORY_DB)
    ]

    print(f"[INFO] Found {len(batch_files)} batch DBs")

    memory_con = open_db(MEMORY_DB)
    create_schema(memory_con)

    total = 0

    for batch_path in batch_files:
        total += process_batch(memory_con, batch_path)

    export_geojson(memory_con)

    memory_con.close()

    print()
    print("[DONE] AP memory fusion complete")
    print(f"[DONE] Total AP rows merged this run: {total}")
    print(f"[DONE] Memory DB: {MEMORY_DB}")
    print(f"[DONE] AP map: {MEMORY_AP_GEOJSON}")
    print(f"[DONE] Mobile candidate map: {MEMORY_MOBILE_GEOJSON}")


if __name__ == "__main__":
    main()
