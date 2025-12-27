#!/usr/bin/env python3
import os
import time
import json
import glob
import subprocess
from datetime import datetime

# ================= CONFIG =================
CAPTURE_FILE = "/var/www/html/wifi/data/wifi_capture.json"
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
    # numeric node → /dev/esp-<n>
    for dev in glob.glob(ESP_GLOB):
        if dev.endswith(f"-{node}") or dev.endswith(f"-{node.zfill(2)}"):
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

    # Expecting per-node timestamps inside capture
    for node, info in data.get("nodes", {}).items():
        ts = info.get("ts")
        if isinstance(ts, (int, float)):
            last_seen[str(node)] = float(ts)


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
