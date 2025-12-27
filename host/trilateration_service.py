#!/usr/bin/env python3
import json
import time
import math
import os

SRC = "/dev/shm/wifi_capture.json"
OUT = "/media/sbejarano/Developer1/wifi_promiscuous/tmp/trilaterated.json"

REF_RSSI = -40
PATH_LOSS = 2.2
MAX_DIST = 250.0

SIDE_DIFF_THRESHOLD = 4.0     # dB
MIN_SPEED_MPS = 1.0           # below this, do not classify side
LATERAL_OFFSET_M = 15.0       # meters (constant for now)

EARTH_RADIUS_M = 6378137.0

def rssi_to_distance(rssi):
    try:
        return min(10 ** ((REF_RSSI - rssi) / (10 * PATH_LOSS)), MAX_DIST)
    except Exception:
        return MAX_DIST

def confidence_from_samples(n, spread):
    base = min(60 + n * 4, 90)
    penalty = min(spread * 2, 40)
    return max(0, min(100, int(base - penalty)))

def side_confidence_from_diff(diff_db):
    mag = abs(diff_db)
    return max(0, min(100, int(mag * 12)))

def bearing_normals(bearing_deg):
    if bearing_deg is None:
        return None, None
    return (bearing_deg + 90.0) % 360.0, (bearing_deg - 90.0) % 360.0

def project_offset(lat, lon, bearing_deg, distance_m):
    """
    Project a point distance_m meters from lat/lon at bearing_deg (Earth-fixed).
    """
    if lat is None or lon is None or bearing_deg is None:
        return None, None

    theta = math.radians(bearing_deg)

    north = distance_m * math.sin(theta)
    east  = distance_m * math.cos(theta)

    dlat = (north / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (east  / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)

    return lat + dlat, lon + dlon

def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def main():
    while True:
        try:
            with open(SRC) as f:
                data = json.load(f)
        except Exception:
            time.sleep(1)
            continue

        gps = data.get("gps", {})
        obs = data.get("observations", [])

        gps_lat   = gps.get("gps_lat")
        gps_lon   = gps.get("gps_lon")
        gps_track = gps.get("gps_track_deg")
        gps_speed = gps.get("gps_speed_mps")

        left_normal_deg, right_normal_deg = bearing_normals(gps_track)

        bssids = {}
        for o in obs:
            b = o.get("bssid")
            if not b:
                continue
            bssids.setdefault(b, []).append(o)

        devices = []

        for bssid, samples in bssids.items():
            if len(samples) < 3:
                continue

            weights = []
            chans = {}

            left_rssi_vals = []
            right_rssi_vals = []

            for s in samples:
                rssi = s.get("rssi")
                if rssi is None:
                    continue

                d = rssi_to_distance(rssi)
                weights.append((1 / max(d, 1), rssi))

                ch = s.get("channel")
                if ch is not None:
                    chans[ch] = chans.get(ch, 0) + 1

                node = str(s.get("node", "")).upper()
                if node == "LEFT":
                    left_rssi_vals.append(rssi)
                elif node == "RIGHT":
                    right_rssi_vals.append(rssi)

            if not weights or not chans:
                continue

            avg_rssi = sum(r for _, r in weights) / len(weights)
            spread = max(r for _, r in weights) - min(r for _, r in weights)
            conf = confidence_from_samples(len(weights), spread)

            side = "OMNI"
            side_conf = 0
            diff = None
            offset_lat = None
            offset_lon = None

            if (
                gps_speed is not None
                and gps_speed > MIN_SPEED_MPS
                and left_rssi_vals
                and right_rssi_vals
            ):
                left_avg = sum(left_rssi_vals) / len(left_rssi_vals)
                right_avg = sum(right_rssi_vals) / len(right_rssi_vals)
                diff = left_avg - right_avg

                if diff > SIDE_DIFF_THRESHOLD:
                    side = "LEFT"
                    side_conf = side_confidence_from_diff(diff)
                    offset_lat, offset_lon = project_offset(
                        gps_lat, gps_lon, left_normal_deg, LATERAL_OFFSET_M
                    )

                elif diff < -SIDE_DIFF_THRESHOLD:
                    side = "RIGHT"
                    side_conf = side_confidence_from_diff(diff)
                    offset_lat, offset_lon = project_offset(
                        gps_lat, gps_lon, right_normal_deg, LATERAL_OFFSET_M
                    )

                else:
                    side = "OMNI"
                    side_conf = side_confidence_from_diff(diff)

            devices.append({
                "bssid": bssid,
                "ssid": max(samples, key=lambda x: x.get("rssi", -999)).get("ssid"),
                "rssi": round(avg_rssi, 1),
                "channel": max(chans, key=chans.get),

                # SIDE DECISION
                "side": side,
                "side_confidence": side_conf,
                "side_diff_db": diff,

                # GPS anchor
                "gps_lat": gps_lat,
                "gps_lon": gps_lon,
                "gps_track_deg": gps_track,
                "gps_speed_mps": gps_speed,

                # Earth-frame geometry
                "left_normal_deg": left_normal_deg,
                "right_normal_deg": right_normal_deg,

                # TASK E-3 OUTPUT
                "offset_lat": offset_lat,
                "offset_lon": offset_lon,
                "offset_m": LATERAL_OFFSET_M,

                # RF confidence
                "confidence": conf,
            })

        atomic_write(OUT, {
            "ts": time.time(),
            "devices": devices
        })

        time.sleep(1)

if __name__ == "__main__":
    main()
