#!/usr/bin/env python3
import subprocess
import json
import time
import os

OUT = "/tmp/gps.json"

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except:
        pass


def main():
    gps = subprocess.Popen(
        ["gpspipe", "-w"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    gps_state = {
        "time": None,
        "lat": None,
        "lon": None,
        "alt": None,
        "speed": None,
        "track": None,
        "mode": 0,
        "fix": "NO FIX",
        "sats": 0,
        "prns": [],
        "timestamp": time.time(),
    }

    for raw in gps.stdout:
        try:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line.startswith("{"):
                continue

            msg = json.loads(line)
        except:
            continue

        cls = msg.get("class", "")

        # ---- TPV ----
        if cls == "TPV":
            mode = msg.get("mode", 0)

            gps_state["time"] = msg.get("time")
            gps_state["lat"] = msg.get("lat")
            gps_state["lon"] = msg.get("lon")
            gps_state["alt"] = msg.get("alt")
            gps_state["speed"] = msg.get("speed")
            gps_state["track"] = msg.get("track")
            gps_state["mode"] = mode
            gps_state["timestamp"] = time.time()

            gps_state["fix"] = (
                "3D" if mode == 3 else
                "2D" if mode == 2 else
                "NO FIX"
            )

        # ---- SKY ----
        elif cls == "SKY":
            sats = msg.get("satellites", [])
            gps_state["sats"] = sum(1 for s in sats if s.get("used"))
            gps_state["prns"] = [s.get("PRN") for s in sats if s.get("used")]

        # ---- ATOMIC WRITE ----
        atomic_write_json(OUT, gps_state)


if __name__ == "__main__":
    main()
