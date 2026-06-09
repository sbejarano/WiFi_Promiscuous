#!/usr/bin/env python3

import json
import subprocess
import time

GPS_JSON = "/home/sbejarano/wifi_promiscuous/tmp/gps.json"

CHECK_SEC = 1.0
LOCK_HOLD_SEC = 3

locked_since = None
started = False


def gps_locked():
    try:
        with open(GPS_JSON, "r") as f:
            d = json.load(f)

        mode = int(d.get("mode", 0) or 0)
        gps_valid = bool(d.get("gps_valid", False))

        lat = d.get("lat", d.get("latitude"))
        lon = d.get("lon", d.get("longitude"))

        # HARD RULE:
        # mode must be 3D
        # gps_valid must be true
        # lat/lon cannot be zero

        if mode < 3:
            return False

        if not gps_valid:
            return False

        if lat in (None, 0, 0.0):
            return False

        if lon in (None, 0, 0.0):
            return False

        return True

    except Exception:
        return False


while True:
    now_locked = gps_locked()
    now = time.time()

    if now_locked:
        if locked_since is None:
            locked_since = now

        if not started and (now - locked_since) >= LOCK_HOLD_SEC:
            print("[gate] GPS LOCKED -> starting db_writer", flush=True)

            subprocess.run(
                ["systemctl", "start", "db_writer.service"],
                check=False
            )

            started = True

    else:
        locked_since = None

        if started:
            print("[gate] GPS LOST -> stopping db_writer", flush=True)

            subprocess.run(
                ["systemctl", "stop", "db_writer.service"],
                check=False
            )

            started = False

    time.sleep(CHECK_SEC)
