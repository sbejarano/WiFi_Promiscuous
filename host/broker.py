#!/usr/bin/env python3
import os, json, time, threading, serial, yaml
from datetime import datetime

BASE_DIR = "/media/sbejarano/Developer1/wifi_promiscuous"
TMP_DIR  = f"{BASE_DIR}/tmp"
DEVICES_YAML = f"{BASE_DIR}/host/devices.yaml"
LOG_FILE = f"{TMP_DIR}/broker.log"
BAUD = 115200

os.makedirs(TMP_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

with open(DEVICES_YAML) as f:
    CONF = yaml.safe_load(f)

PORTS = CONF.get("ports", {})

def capture(node_id, port):
    log(f"Starting capture {node_id} on {port}")
    out_file = f"{TMP_DIR}/wifi_node_{node_id}.json"

    try:
        ser = serial.Serial(port, BAUD, timeout=0.2)
    except Exception as e:
        log(f"ERROR opening {port}: {e}")
        return

    while True:
        try:
            raw = ser.readline().decode(errors="ignore").strip()
            if not raw.startswith("{"):
                continue
            data = json.loads(raw)
            data["_ts"] = time.time()
            data["_node"] = node_id
            atomic_write(out_file, data)
        except Exception as e:
            log(f"{node_id} error: {e}")
            time.sleep(0.2)

def main():
    log("Broker starting")
    for node, port in PORTS.items():
        threading.Thread(target=capture, args=(node, port), daemon=True).start()
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
