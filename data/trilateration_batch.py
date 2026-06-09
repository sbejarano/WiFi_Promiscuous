#!/usr/bin/env python3
import argparse
import glob
import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

BASE_DIR = "/home/sbejarano/wifi_promiscuous"
DATA_DIR = f"{BASE_DIR}/data"
OUT_DIR = f"{BASE_DIR}/results"

DEFAULT_MIN_OBS = 8
DEFAULT_MAX_HDOP = 8.0
DEFAULT_MIN_RSSI = -95
DEFAULT_TX_POWER = -45.0
DEFAULT_PATH_LOSS_N = 2.7

# Reduced from 2.8. Start conservative.
DEFAULT_SIDE_DISTANCE_SCALE = 1.0


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6378137.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def meters_to_latlon_offset(lat, lon, east_m, north_m):
    r = 6378137.0
    dlat = north_m / r
    dlon = east_m / (r * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def latlon_to_local_m(lat0, lon0, lat, lon):
    r = 6378137.0
    north = math.radians(lat - lat0) * r
    east = math.radians(lon - lon0) * r * math.cos(math.radians(lat0))
    return east, north


def rssi_to_distance_m(rssi, tx_power, path_loss_n):
    antenna_gain_dbi = 5.0
    corrected_rssi = rssi - antenna_gain_dbi
    return 10 ** ((tx_power - corrected_rssi) / (10 * path_loss_n))


def heading_side_unit(heading_deg, side):
    """
    Compass heading convention:
    - heading 0   = north
    - heading 90  = east
    - heading 180 = south
    - heading 270 = west

    Correct vehicle-relative side:
    - LEFT  = heading - 90 degrees
    - RIGHT = heading + 90 degrees

    This matches a normal compass bearing system where:
    - Driving north: LEFT west, RIGHT east
    - Driving south: LEFT east, RIGHT west
    - Driving east:  LEFT north, RIGHT south
    - Driving west:  LEFT south, RIGHT north
    """
    if heading_deg is None:
        return None

    side = (side or "OMNI").upper().strip()

    if side == "LEFT":
        bearing = heading_deg - 90.0
    elif side == "RIGHT":
        bearing = heading_deg + 90.0
    else:
        return None

    bearing = bearing % 360.0
    rad = math.radians(bearing)

    east = math.sin(rad)
    north = math.cos(rad)

    return east, north


def open_ro(path):
    uri = f"file:{path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def table_columns(con, table):
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def pick_column(columns, candidates):
    for c in candidates:
        if c in columns:
            return c
    return None


def build_select(columns):
    bssid_col = pick_column(columns, ["bssid"])
    ssid_col = pick_column(columns, ["ssid"])
    channel_col = pick_column(columns, ["dominant_channel", "channel"])
    rssi_col = pick_column(columns, ["avg_rssi", "median_rssi", "rssi"])

    lat_col = pick_column(columns, ["gps_lat", "latitude", "lat", "gps_lat_min", "est_lat"])
    lon_col = pick_column(columns, ["gps_lon", "longitude", "lon", "gps_lon_min", "est_lon"])
    alt_col = pick_column(columns, ["gps_alt", "altitude", "alt", "est_alt"])

    ts_col = pick_column(columns, ["ts_utc", "last_seen_ts"])
    hdop_col = pick_column(columns, ["gps_hdop", "hdop"])
    gps_valid_col = pick_column(columns, ["gps_valid"])
    speed_col = pick_column(columns, ["gps_speed_mps", "speed_mps"])
    heading_col = pick_column(columns, ["gps_heading_deg", "heading_deg", "gps_track_deg"])
    stationary_col = pick_column(columns, ["gps_stationary", "vehicle_stationary"])
    side_col = pick_column(columns, ["side"])

    required = {
        "bssid": bssid_col,
        "rssi": rssi_col,
        "lat": lat_col,
        "lon": lon_col,
    }

    missing = [k for k, v in required.items() if not v]

    if missing:
        raise RuntimeError(
            "Missing required usable columns: "
            + ", ".join(missing)
            + "\nCurrent table does not contain enough GPS/RSSI data for trilateration."
        )

    selected = {
        "bssid": bssid_col,
        "ssid": ssid_col,
        "channel": channel_col,
        "rssi": rssi_col,
        "lat": lat_col,
        "lon": lon_col,
        "alt": alt_col,
        "ts": ts_col,
        "hdop": hdop_col,
        "gps_valid": gps_valid_col,
        "speed_mps": speed_col,
        "heading_deg": heading_col,
        "stationary": stationary_col,
        "side": side_col,
    }

    sql_cols = []
    for alias, col in selected.items():
        if col:
            sql_cols.append(f"{col} AS {alias}")
        else:
            sql_cols.append(f"NULL AS {alias}")

    sql = f"""
        SELECT {", ".join(sql_cols)}
        FROM wifi_captures
        WHERE {bssid_col} IS NOT NULL
          AND {rssi_col} IS NOT NULL
          AND {lat_col} IS NOT NULL
          AND {lon_col} IS NOT NULL
    """

    return sql


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


def normalize_side(side):
    side = (side or "OMNI").upper().strip()

    if side in ("LEFT", "L"):
        return "LEFT"

    if side in ("RIGHT", "R"):
        return "RIGHT"

    return "OMNI"


def load_observations(db_path, args):
    observations = []

    try:
        con = open_ro(db_path)
        cols = table_columns(con, "wifi_captures")
        sql = build_select(cols)

        for row in con.execute(sql):
            (
                bssid,
                ssid,
                channel,
                rssi,
                lat,
                lon,
                alt,
                ts,
                hdop,
                gps_valid,
                speed_mps,
                heading_deg,
                stationary,
                side,
            ) = row

            if not bssid:
                continue

            rssi = safe_float(rssi)
            lat = safe_float(lat)
            lon = safe_float(lon)

            if rssi is None or lat is None or lon is None:
                continue

            if lat == 0 or lon == 0:
                continue

            if rssi < args.min_rssi:
                continue

            if gps_valid is not None and safe_int(gps_valid, 0) == 0:
                continue

            hdop = safe_float(hdop)

            if hdop is not None and hdop > args.max_hdop:
                continue

            alt = safe_float(alt)
            speed_mps = safe_float(speed_mps)
            heading_deg = safe_float(heading_deg)
            stationary = safe_int(stationary)

            observations.append({
                "db_file": os.path.basename(db_path),
                "bssid": str(bssid).upper(),
                "ssid": ssid or "",
                "channel": channel,
                "rssi": rssi,
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "ts": ts,
                "hdop": hdop,
                "speed_mps": speed_mps,
                "heading_deg": heading_deg,
                "stationary": stationary,
                "side": normalize_side(side),
            })

        con.close()

    except Exception as e:
        print(f"[WARN] Skipping {db_path}: {e}")

    return observations


def estimate_ap(group, args):
    if len(group) < args.min_observations:
        return None

    lat0 = sum(o["lat"] for o in group) / len(group)
    lon0 = sum(o["lon"] for o in group) / len(group)

    known_alts = [o["alt"] for o in group if o["alt"] is not None]
    alt0 = sum(known_alts) / len(known_alts) if known_alts else 0.0

    weighted_points = []
    directional_count = 0
    heading_count = 0

    for o in group:
        east, north = latlon_to_local_m(lat0, lon0, o["lat"], o["lon"])
        up = (o["alt"] - alt0) if o["alt"] is not None else 0.0

        distance = rssi_to_distance_m(o["rssi"], args.tx_power, args.path_loss_n)

        unit = heading_side_unit(o["heading_deg"], o["side"])

        if o["heading_deg"] is not None:
            heading_count += 1

        if unit:
            directional_count += 1
            side_distance = distance * args.side_distance_scale
            cand_east = east + unit[0] * side_distance
            cand_north = north + unit[1] * side_distance
        else:
            cand_east = east
            cand_north = north

        cand_up = up

        rssi_weight = max(1.0, 120.0 + o["rssi"])

        hdop_weight = 1.0
        if o["hdop"] and o["hdop"] > 0:
            hdop_weight = 1.0 / o["hdop"]

        side_weight = 1.35 if unit else 0.65

        weight = rssi_weight * hdop_weight * side_weight

        weighted_points.append({
            "east": cand_east,
            "north": cand_north,
            "up": cand_up,
            "weight": weight,
        })

    total_w = sum(p["weight"] for p in weighted_points)

    if total_w <= 0:
        return None

    est_east = sum(p["east"] * p["weight"] for p in weighted_points) / total_w
    est_north = sum(p["north"] * p["weight"] for p in weighted_points) / total_w
    est_up = sum(p["up"] * p["weight"] for p in weighted_points) / total_w

    est_lat, est_lon = meters_to_latlon_offset(lat0, lon0, est_east, est_north)
    est_alt = alt0 + est_up if known_alts else None

    strongest = max(group, key=lambda x: x["rssi"])
    weakest = min(group, key=lambda x: x["rssi"])

    spread_m = max(
        haversine_m(est_lat, est_lon, o["lat"], o["lon"])
        for o in group
    )

    avg_rssi = sum(o["rssi"] for o in group) / len(group)

    stationary_count = sum(1 for o in group if o["stationary"] == 1)
    moving_count = sum(1 for o in group if o["stationary"] == 0)

    if stationary_count >= max(3, len(group) * 0.8):
        mobility_state = "PARKED_CAPTURE"
    elif moving_count >= max(3, len(group) * 0.5):
        mobility_state = "MOVING_CAPTURE"
    else:
        mobility_state = "MIXED_CAPTURE"

    side_counts = defaultdict(int)
    for o in group:
        side_counts[o["side"] or "OMNI"] += 1

    dominant_side = max(side_counts, key=side_counts.get)

    confidence = 100

    if len(group) < 20:
        confidence -= 20
    elif len(group) < 50:
        confidence -= 10

    if spread_m > 500:
        confidence -= 30
    elif spread_m > 250:
        confidence -= 20
    elif spread_m > 100:
        confidence -= 10

    if avg_rssi < -85:
        confidence -= 20
    elif avg_rssi < -75:
        confidence -= 10

    if directional_count == 0:
        confidence -= 20

    if heading_count == 0:
        confidence -= 20

    confidence = max(5, min(100, confidence))

    return {
        "bssid": strongest["bssid"],
        "ssid": strongest["ssid"],
        "channel": strongest["channel"],
        "est_lat": est_lat,
        "est_lon": est_lon,
        "est_alt": est_alt,
        "observation_count": len(group),
        "avg_rssi": avg_rssi,
        "strongest_rssi": strongest["rssi"],
        "weakest_rssi": weakest["rssi"],
        "spread_m": spread_m,
        "confidence": confidence,
        "dominant_side": dominant_side,
        "directional_observation_count": directional_count,
        "heading_observation_count": heading_count,
        "mobility_state": mobility_state,
        "first_seen": min((o["ts"] for o in group if o["ts"]), default=None),
        "last_seen": max((o["ts"] for o in group if o["ts"]), default=None),
    }


def create_output_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    con = sqlite3.connect(path)
    con.executescript("""
    DROP TABLE IF EXISTS ap_trilateration_results;

    CREATE TABLE ap_trilateration_results (
        id INTEGER PRIMARY KEY,
        bssid TEXT NOT NULL,
        ssid TEXT,
        channel TEXT,
        est_lat REAL NOT NULL,
        est_lon REAL NOT NULL,
        est_alt REAL,
        observation_count INTEGER NOT NULL,
        avg_rssi REAL,
        strongest_rssi REAL,
        weakest_rssi REAL,
        spread_m REAL,
        confidence REAL,
        dominant_side TEXT,
        directional_observation_count INTEGER,
        heading_observation_count INTEGER,
        mobility_state TEXT,
        first_seen TEXT,
        last_seen TEXT,
        processed_at TEXT NOT NULL
    );
    """)
    return con


def write_results(con, results):
    processed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for r in results:
        rows.append((
            r["bssid"],
            r["ssid"],
            str(r["channel"]) if r["channel"] is not None else None,
            r["est_lat"],
            r["est_lon"],
            r["est_alt"],
            r["observation_count"],
            r["avg_rssi"],
            r["strongest_rssi"],
            r["weakest_rssi"],
            r["spread_m"],
            r["confidence"],
            r["dominant_side"],
            r["directional_observation_count"],
            r["heading_observation_count"],
            r["mobility_state"],
            r["first_seen"],
            r["last_seen"],
            processed_at,
        ))

    con.executemany("""
        INSERT INTO ap_trilateration_results (
            bssid, ssid, channel, est_lat, est_lon, est_alt,
            observation_count, avg_rssi, strongest_rssi, weakest_rssi,
            spread_m, confidence, dominant_side,
            directional_observation_count, heading_observation_count,
            mobility_state, first_seen, last_seen, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

    con.commit()


def write_geojson(path, results):
    features = []

    for r in results:
        coords = [r["est_lon"], r["est_lat"]]

        if r["est_alt"] is not None:
            coords.append(r["est_alt"])

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": coords,
            },
            "properties": {
                "bssid": r["bssid"],
                "ssid": r["ssid"],
                "channel": r["channel"],
                "est_lat": r["est_lat"],
                "est_lon": r["est_lon"],
                "est_alt": r["est_alt"],
                "observation_count": r["observation_count"],
                "avg_rssi": r["avg_rssi"],
                "strongest_rssi": r["strongest_rssi"],
                "weakest_rssi": r["weakest_rssi"],
                "spread_m": r["spread_m"],
                "confidence": r["confidence"],
                "dominant_side": r["dominant_side"],
                "directional_observation_count": r["directional_observation_count"],
                "heading_observation_count": r["heading_observation_count"],
                "mobility_state": r["mobility_state"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            }
        })

    obj = {
        "type": "FeatureCollection",
        "features": features
    }

    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def find_day_dbs(data_dir, day):
    pattern = os.path.join(data_dir, f"trilateration_data_{day}_*.db")
    files = sorted(glob.glob(pattern))

    files = [
        f for f in files
        if not f.endswith("-wal")
        and not f.endswith("-shm")
        and not os.path.islink(f)
    ]

    return files


def print_input_summary(all_obs):
    side_counts = defaultdict(int)
    heading_count = 0

    for o in all_obs:
        side_counts[o["side"]] += 1
        if o["heading_deg"] is not None:
            heading_count += 1

    print("[INFO] Input side summary:")
    for side in sorted(side_counts.keys()):
        print(f"[INFO]   {side}: {side_counts[side]}")

    print(f"[INFO]   heading present: {heading_count}")
    print(f"[INFO]   total observations: {len(all_obs)}")


def main():
    parser = argparse.ArgumentParser(
        description="Directional AP trilateration processor."
    )

    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--min-observations", type=int, default=DEFAULT_MIN_OBS)
    parser.add_argument("--max-hdop", type=float, default=DEFAULT_MAX_HDOP)
    parser.add_argument("--min-rssi", type=float, default=DEFAULT_MIN_RSSI)
    parser.add_argument("--tx-power", type=float, default=DEFAULT_TX_POWER)
    parser.add_argument("--path-loss-n", type=float, default=DEFAULT_PATH_LOSS_N)
    parser.add_argument("--side-distance-scale", type=float, default=DEFAULT_SIDE_DISTANCE_SCALE)

    args = parser.parse_args()

    db_files = find_day_dbs(args.data_dir, args.date)

    print(f"[INFO] Found {len(db_files)} DB files for {args.date}")

    all_obs = []

    for db in db_files:
        obs = load_observations(db, args)
        print(f"[INFO] {os.path.basename(db)}: {len(obs)} usable observations")
        all_obs.extend(obs)

    print_input_summary(all_obs)

    grouped = defaultdict(list)

    for o in all_obs:
        grouped[(o["bssid"], str(o["channel"]))].append(o)

    results = []

    for group in grouped.values():
        r = estimate_ap(group, args)
        if r:
            results.append(r)

    results.sort(
        key=lambda x: (x["confidence"], x["observation_count"]),
        reverse=True
    )

    os.makedirs(args.out_dir, exist_ok=True)

    out_db = os.path.join(args.out_dir, f"ap_trilateration_{args.date}.db")
    out_geojson = os.path.join(args.out_dir, f"ap_trilateration_{args.date}.geojson")

    con = create_output_db(out_db)
    write_results(con, results)
    con.close()

    write_geojson(out_geojson, results)

    print(f"[DONE] Results written: {len(results)}")
    print(f"[DONE] Output DB: {out_db}")
    print(f"[DONE] GeoJSON: {out_geojson}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
