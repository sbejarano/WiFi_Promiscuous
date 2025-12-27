#!/usr/bin/env python3
import subprocess
import json
import time
import os
from datetime import datetime, timezone

OUT = "/media/sbejarano/Developer1/wifi_promiscuous/tmp/gps.json"

# --- tuning parameters ---
MIN_SPEED_MPS = 1.0      # below this, track is unreliable
WRITE_INTERVAL = 0.05    # seconds

def utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def main():
    gps = subprocess.Popen(
        ["gpspipe", "-w"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )

    state = {
        # timing
        "ts_utc": None,
        "pps_epoch": None,
        "pps_ok": False,

        # position
        "lat": None,
        "lon": None,
        "alt": None,

        # motion
        "speed_mps": None,
        "track_deg": None,          # raw GPS track (0–360)
        "track_deg_stable": None,   # held when speed drops

        # fix quality
        "mode": 0,
        "fix": "NO FIX",

        # satellites
        "sats": 0,
        "prns": []
    }

    last_good_track = None

    for line in gps.stdout:
        try:
            msg = json.loads(line)
        except Exception:
            continue

        cls = msg.get("class")

        # --------------------------------------------------
        # PPS (timing only)
        # --------------------------------------------------
        if cls == "PPS":
            sec = msg.get("real_sec")
            nsec = msg.get("real_nsec")
            if sec is not None and nsec is not None:
                state["pps_epoch"] = sec + (nsec / 1e9)
                state["pps_ok"] = True

        # --------------------------------------------------
        # SKY (satellites only)
        # --------------------------------------------------
        elif cls == "SKY":
            sats = msg.get("satellites", [])
            state["sats"] = len(sats)
            state["prns"] = [s.get("svid") for s in sats if s.get("used")]

        # --------------------------------------------------
        # TPV (position + motion authority)
        # --------------------------------------------------
        elif cls == "TPV":
            mode = msg.get("mode", 0)
            state["mode"] = mode

            if mode >= 2:
                state["lat"] = msg.get("lat")
                state["lon"] = msg.get("lon")
                state["alt"] = msg.get("alt") or msg.get("altMSL")
                state["speed_mps"] = msg.get("speed")
                state["track_deg"] = msg.get("track")
                state["fix"] = "3D FIX" if mode == 3 else "2D FIX"

                # --- stable track logic ---
                spd = state["speed_mps"]
                trk = state["track_deg"]

                if spd is not None and trk is not None and spd >= MIN_SPEED_MPS:
                    last_good_track = trk
                    state["track_deg_stable"] = trk
                else:
                    state["track_deg_stable"] = last_good_track

            else:
                state["fix"] = "NO FIX"
                state["speed_mps"] = None
                state["track_deg"] = None
                state["track_deg_stable"] = last_good_track

        # --------------------------------------------------
        # WRITE (always atomic, always last-known-good)
        # --------------------------------------------------
        state["ts_utc"] = utc_iso()
        atomic_write_json(OUT, state)

        time.sleep(WRITE_INTERVAL)

if __name__ == "__main__":
    main()
