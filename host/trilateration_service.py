#!/usr/bin/env python3
import json
import time
import math
import os
from collections import deque

# INPUT from capture (RAM snapshot)
SRC = "/dev/shm/wifi_capture.json"

# OUTPUT for DB writer (RAM is best, but keep your path if you want)
OUT = "/dev/shm/trilaterated.json"
# If you insist on disk:
# OUT = "/media/sbejarano/Developer1/wifi_promiscuous/tmp/trilaterated.json"

# --- RF model (used for weighting/confidence only; not geometric trilateration) ---
REF_RSSI = -40
PATH_LOSS = 2.2
MAX_DIST = 250.0

# --- SIDE inference ---
SIDE_DIFF_THRESHOLD = 4.0     # dB
MIN_SPEED_MPS = 1.0           # below this, do not classify side
LATERAL_OFFSET_M = 15.0       # meters (constant for now)

# --- Trilateration/solver window ---
HISTORY_SECONDS = 120         # keep last N seconds of points per BSSID
MIN_POINTS_SOLVE = 6          # require at least this many points to "solve"
MAX_POINTS_PER_BSSID = 300    # hard cap per BSSID history
WRITE_INTERVAL_S = 1.0

EARTH_RADIUS_M = 6378137.0

def rssi_to_distance(rssi):
    """Crude RSSI->distance mapping, used only to build weights (NOT for circle intersection)."""
    try:
        return min(10 ** ((REF_RSSI - rssi) / (10 * PATH_LOSS)), MAX_DIST)
    except Exception:
        return MAX_DIST

def confidence_from_samples(n, spread):
    """0..100-ish quality from sample count + RSSI stability."""
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
    Uses a local tangent-plane approximation (good at these distances).
    """
    if lat is None or lon is None or bearing_deg is None:
        return None, None

    theta = math.radians(bearing_deg)

    north = distance_m * math.sin(theta)
    east  = distance_m * math.cos(theta)

    dlat = (north / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (east  / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)

    return lat + dlat, lon + dlon

def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c

def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def now_ts():
    return time.time()

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def main():
    # History store: bssid -> deque of points
    # Each point: {ts, lat, lon, weight, rssi, channel, side, conf}
    hist = {}

    last_src_ts = None
    last_write = 0.0

    while True:
        # Read capture snapshot
        try:
            with open(SRC) as f:
                data = json.load(f)
        except Exception:
            time.sleep(0.2)
            continue

        # Avoid reprocessing same capture snapshot if it has stable ts
        src_ts = data.get("ts")
        if src_ts is not None and src_ts == last_src_ts:
            # still write periodically from existing history
            pass
        else:
            last_src_ts = src_ts

            gps = data.get("gps", {}) or {}
            obs = data.get("observations", []) or []

            gps_lat   = gps.get("gps_lat")
            gps_lon   = gps.get("gps_lon")
            gps_track = gps.get("gps_track_deg")
            gps_speed = gps.get("gps_speed_mps")

            # Validate GPS anchor
            if gps_lat is None or gps_lon is None:
                # no GPS -> cannot project offsets
                gps_lat = None
                gps_lon = None

            left_normal_deg, right_normal_deg = bearing_normals(gps_track)

            # Group observations by BSSID
            bssids = {}
            for o in obs:
                b = o.get("bssid")
                if not b:
                    continue
                bssids.setdefault(b, []).append(o)

            # For each BSSID, compute side + a single inferred point for this snapshot
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

                    # Weighting: closer (higher RSSI) -> higher weight
                    d = rssi_to_distance(float(rssi))
                    w = 1.0 / max(d, 1.0)
                    weights.append((w, float(rssi)))

                    ch = s.get("channel")
                    if ch is not None:
                        chans[ch] = chans.get(ch, 0) + 1

                    node = str(s.get("node", "")).upper()
                    if node == "LEFT":
                        left_rssi_vals.append(float(rssi))
                    elif node == "RIGHT":
                        right_rssi_vals.append(float(rssi))

                if not weights or not chans:
                    continue

                # Weighted average RSSI (simple)
                avg_rssi = sum(r for _, r in weights) / len(weights)
                spread = max(r for _, r in weights) - min(r for _, r in weights)
                conf = confidence_from_samples(len(weights), spread)  # 0..100

                dominant_channel = max(chans, key=chans.get)

                # Side decision
                side = "OMNI"
                side_conf = 0
                diff = None
                inferred_lat = None
                inferred_lon = None

                if (
                    gps_lat is not None
                    and gps_lon is not None
                    and gps_speed is not None
                    and float(gps_speed) > MIN_SPEED_MPS
                    and left_rssi_vals
                    and right_rssi_vals
                    and left_normal_deg is not None
                    and right_normal_deg is not None
                ):
                    left_avg = sum(left_rssi_vals) / len(left_rssi_vals)
                    right_avg = sum(right_rssi_vals) / len(right_rssi_vals)
                    diff = left_avg - right_avg

                    if diff > SIDE_DIFF_THRESHOLD:
                        side = "LEFT"
                        side_conf = side_confidence_from_diff(diff)
                        inferred_lat, inferred_lon = project_offset(
                            float(gps_lat), float(gps_lon), left_normal_deg, LATERAL_OFFSET_M
                        )
                    elif diff < -SIDE_DIFF_THRESHOLD:
                        side = "RIGHT"
                        side_conf = side_confidence_from_diff(diff)
                        inferred_lat, inferred_lon = project_offset(
                            float(gps_lat), float(gps_lon), right_normal_deg, LATERAL_OFFSET_M
                        )
                    else:
                        side = "OMNI"
                        side_conf = side_confidence_from_diff(diff)

                # Only add a point to trilateration history if we actually inferred a point
                # (i.e., classified LEFT or RIGHT and we have an offset point).
                if inferred_lat is None or inferred_lon is None:
                    continue

                # Build a weight for the solver:
                # combine RF confidence with side confidence and RSSI-based closeness.
                # Keep it stable and bounded.
                d_est = rssi_to_distance(avg_rssi)
                w_rssi = 1.0 / max(d_est, 1.0)
                w_conf = (conf / 100.0)
                w_side = max(0.2, side_conf / 100.0)  # don’t zero it out completely
                weight = clamp(w_rssi * w_conf * w_side, 0.0001, 10.0)

                entry = {
                    "ts": now_ts(),
                    "lat": float(inferred_lat),
                    "lon": float(inferred_lon),
                    "weight": float(weight),
                    "rssi": float(avg_rssi),
                    "channel": dominant_channel,
                    "side": side,
                    "confidence": int(conf),
                    "side_confidence": int(side_conf),
                }

                dq = hist.get(bssid)
                if dq is None:
                    dq = deque(maxlen=MAX_POINTS_PER_BSSID)
                    hist[bssid] = dq
                dq.append(entry)

        # Prune old history
        cutoff = now_ts() - HISTORY_SECONDS
        for bssid in list(hist.keys()):
            dq = hist[bssid]
            while dq and dq[0]["ts"] < cutoff:
                dq.popleft()
            if not dq:
                del hist[bssid]

        # Write solved trilateration results periodically
        tnow = now_ts()
        if (tnow - last_write) < WRITE_INTERVAL_S:
            time.sleep(0.05)
            continue
        last_write = tnow

        aps = []

        for bssid, dq in hist.items():
            pts = list(dq)
            if len(pts) < MIN_POINTS_SOLVE:
                continue

            sw = sum(p["weight"] for p in pts)
            if sw <= 0:
                continue

            # Weighted centroid (robust for your use-case)
            lat = sum(p["lat"] * p["weight"] for p in pts) / sw
            lon = sum(p["lon"] * p["weight"] for p in pts) / sw

            # Error radius: weighted RMS distance to centroid
            d2_sum = 0.0
            w_sum = 0.0
            for p in pts:
                d = haversine_m(lat, lon, p["lat"], p["lon"])
                if d is None:
                    continue
                d2_sum += (d * d) * p["weight"]
                w_sum += p["weight"]

            if w_sum <= 0:
                continue

            err_m = math.sqrt(d2_sum / w_sum)
            err_m = max(1.0, float(err_m))

            # Aggregate confidence as weighted average of per-point confidence
            conf_w = sum((p["confidence"] / 100.0) * p["weight"] for p in pts) / sw
            conf_w = clamp(conf_w, 0.0, 1.0)  # 0..1

            # Latest metadata (for display/DB fields that you want)
            last = pts[-1]
            dominant_channel = last.get("channel")
            avg_rssi = last.get("rssi")
            side = last.get("side", "UNKNOWN")

            aps.append({
                "bssid": bssid,
                "lat": float(lat),
                "lon": float(lon),
                "err_m": float(err_m),

                # DB writer expects confidence numeric; keep it 0..1 or 0..100.
                # Your writer uses confidence/err_m; 0..1 works fine.
                "confidence": float(round(conf_w, 4)),

                # metadata
                "avg_rssi": float(round(avg_rssi, 1)) if avg_rssi is not None else None,
                "dominant_channel": dominant_channel,
                "side": side,

                # helpful debug fields (optional)
                "samples": int(len(pts)),
                "method": "weighted_centroid"
            })

        atomic_write(OUT, {
            "ts": now_ts(),
            "aps": aps
        })

        time.sleep(0.05)

if __name__ == "__main__":
    main()

