#!/usr/bin/env python3
import os
import time
import json
import glob
import subprocess
from datetime import datetime

# ================= CONFIG =================
# Matches the path wifi_capture_service.py writes to (RAM snapshot)
CAPTURE_FILE = "/dev/shm/wifi_capture.json"
ESP_GLOB     = "/dev/esp-*"

STALL_SECONDS  = 10
CHECK_INTERVAL = 2
RESET_COOLDOWN = 30

STATE_FILE = "/var/www/html/wifi/data/usb_watchdog.json"
# =========================================

last_seen  = {}   # node -> ts
last_reset = {}   # node -> ts


def now():
    return time.time()


def iso(ts):
    return datetime.utcfromtimestamp(ts).isoformat() + "Z"


def log(*msg):
    print("[WATCHDOG]", *msg, flush=True)


def map_node_to_dev(node):
    # Case-insensitive match: handles both numeric (esp-1) and named (esp-right, esp-left)
    node_lower = str(node).lower()
    for dev in glob.glob(ESP_GLOB):
        basename = os.path.basename(dev).lower()
        if basename == f"esp-{node_lower}" or basename == f"esp-{node_lower.zfill(2)}":
            return dev
    return None


def usb_reset(dev):
    try:
        tty = os.path.realpath(dev)
        path = subprocess.check_output(
            ["udevadm", "info", "-q", "path", "-n", tty],
            text=True
        ).strip()

        usb_id = path.split("/")[-2]
        log("USB reset", dev, "bus", usb_id)

        subprocess.run(
            ["sh", "-c", f"echo '{usb_id}' > /sys/bus/usb/drivers/usb/unbind"],
            check=True
        )
        time.sleep(1)
        subprocess.run(
            ["sh", "-c", f"echo '{usb_id}' > /sys/bus/usb/drivers/usb/bind"],
            check=True
        )
        return True

    except Exception as e:
        log("RESET FAILED", dev, e)
        return False


def scan_capture():
    last_seen.clear()

    try:
        with open(CAPTURE_FILE) as f:
            data = json.load(f)
    except Exception:
        return

    # wifi_capture_service.py writes {"observations": [{node, ts, ...}, ...]}
    # Find the most recent timestamp seen per node across all observations.
    for obs in data.get("observations", []):
        node = str(obs.get("node", "")).strip()
        ts = obs.get("ts")
        if not node or not isinstance(ts, (int, float)):
            continue
        if ts > last_seen.get(node, 0):
            last_seen[node] = float(ts)


def write_state():
    data = {
        "ts": now(),
        "devices": {}
    }

    for node in sorted(set(last_seen) | set(last_reset)):
        data["devices"][node] = {
            "last_seen": iso(last_seen[node]) if node in last_seen else None,
            "last_reset": iso(last_reset[node]) if node in last_reset else None
        }

    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE_FILE)


def monitor():
    log("ESP USB Watchdog started (wifi_capture.json)")

    while True:
        scan_capture()

        for node, ts in last_seen.items():
            age = now() - ts
            if age < STALL_SECONDS:
                continue

            last_rst = last_reset.get(node, 0)
            if now() - last_rst < RESET_COOLDOWN:
                continue

            dev = map_node_to_dev(node)
            if not dev:
                log("STALL", node, f"age={age:.1f}s", "no esp device")
                continue

            log("STALL detected", f"node={node}", dev, f"age={age:.1f}s")

            if usb_reset(dev):
                last_reset[node] = now()

        write_state()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    monitor()
