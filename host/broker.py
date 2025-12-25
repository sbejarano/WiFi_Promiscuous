#!/usr/bin/env python3
import os
import json
import time
import threading
import serial
import yaml
from datetime import datetime

# ============================================================
# PATHS / CONSTANTS
# ============================================================
BASE_DIR = "/media/sbejarano/Developer1/wifi_promiscuous"
TMP_DIR  = f"{BASE_DIR}/tmp"
CFG_FILE = f"{BASE_DIR}/host/devices.yaml"
LOG_FILE = f"{TMP_DIR}/broker.log"
BAUD_DEFAULT = 115200

os.makedirs(TMP_DIR, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

# ============================================================
# ATOMIC JSON WRITE
# ============================================================
def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

# ============================================================
# LOAD DEVICES (NO DISCOVERY)
# ============================================================
with open(CFG_FILE) as f:
    CONF = yaml.safe_load(f) or {}

PORTS = []

# Directional
directional = CONF.get("directional", {})
for side in ("left", "right"):
    d = directional.get(side)
    if d:
        PORTS.append({
            "node": d.get("node_id"),
            "port": d.get("port"),
            "baud": d.get("baud", BAUD_DEFAULT)
        })

# Fixed scanners
for s in CONF.get("scanners", []):
    PORTS.append({
        "node": str(s.get("node_id")),
        "port": s.get("port"),
        "baud": s.get("baud", BAUD_DEFAULT)
    })

# ============================================================
# CAPTURE THREAD
# ============================================================
def capture(node_id, device, baud):
    out_file = f"{TMP_DIR}/wifi_node_{node_id}.json"

    while True:
        try:
            ser = serial.Serial(device, baud, timeout=0.2)
            log(f"{node_id}: opened {device}")
        except Exception as e:
            log(f"{node_id}: open failed {device} ({e})")
            time.sleep(2)
            continue

        while True:
            try:
                raw = ser.readline().decode(errors="ignore").strip()
                if not raw.startswith("{"):
                    continue

                pkt = json.loads(raw)
                pkt["_node"] = node_id
                pkt["_ts"] = time.time()

                atomic_write(out_file, pkt)

            except Exception as e:
                log(f"{node_id}: read error ({e})")
                break

        try:
            ser.close()
        except Exception:
            pass

        time.sleep(1)

# ============================================================
# MAIN
# ============================================================
def main():
    log("Broker starting (NO SERIAL DISCOVERY)")

    for p in PORTS:
        if not p["node"] or not p["port"]:
            continue

        threading.Thread(
            target=capture,
            args=(p["node"], p["port"], p["baud"]),
            daemon=True
        ).start()

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
