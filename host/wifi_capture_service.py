# wifi_capture_service.py  (RAM snapshot only; NO DB)
#!/usr/bin/env python3
import os
import time
import json
import serial
import threading
import yaml
from collections import deque

BASE = "/media/sbejarano/Developer1/wifi_promiscuous"
CFG  = f"{BASE}/host/devices.yaml"
GPS  = f"{BASE}/tmp/gps.json"

# RAM output (tmpfs)
OUT  = "/dev/shm/wifi_capture.json"

BAUD_DEFAULT = 115200
MAX_OBS = 400          # hard cap per snapshot
FLUSH_MS = 200         # write snapshot every N ms

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)

def load_ports():
    """
    Supports either:
      1) ports: { "1": "/dev/ttyACM0", "LEFT": "/dev/ttyACM10", ... }
      2) directional.left/right + scanners[] style
    Returns list of dicts: {node, port, baud}
    """
    with open(CFG) as f:
        conf = yaml.safe_load(f) or {}

    ports = []

    if "ports" in conf and isinstance(conf["ports"], dict):
        for node, dev in conf["ports"].items():
            if str(node).upper() == "GPS":
                continue
            ports.append({"node": str(node), "port": str(dev), "baud": BAUD_DEFAULT})
        return ports

    directional = conf.get("directional") or {}
    for side in ("left", "right"):
        d = directional.get(side)
        if d and d.get("port"):
            ports.append({
                "node": side.upper(),
                "port": d["port"],
                "baud": int(d.get("baud", BAUD_DEFAULT)),
            })

    for s in conf.get("scanners") or []:
        node_id = str(s.get("node_id"))
        dev = s.get("port")
        if not node_id or not dev:
            continue
        ports.append({
            "node": node_id,
            "port": dev,
            "baud": int(s.get("baud", BAUD_DEFAULT)),
        })

    return ports

def read_gps():
    try:
        with open(GPS) as f:
            return json.load(f)
    except Exception:
        return None

class CaptureBus:
    def __init__(self):
        self.lock = threading.Lock()
        self.buf = deque(maxlen=MAX_OBS)

    def add(self, obs):
        with self.lock:
            self.buf.append(obs)

    def snapshot(self):
        with self.lock:
            return list(self.buf)

def capture_thread(bus: CaptureBus, node: str, dev: str, baud: int):
    while True:
        try:
            ser = serial.Serial(dev, baud, timeout=0.15)
        except Exception:
            time.sleep(2)
            continue

        while True:
            try:
                raw = ser.readline().decode(errors="ignore").strip()
                if not raw.startswith("{"):
                    continue

                pkt = json.loads(raw)

                bssid = (pkt.get("bssid") or "").strip()
                ssid  = (pkt.get("ssid") or "").strip()
                rssi  = pkt.get("rssi")
                ch    = pkt.get("ch") or pkt.get("chan") or pkt.get("channel")
                freq  = pkt.get("freq") or pkt.get("frequency")

                if not bssid or rssi is None:
                    continue

                obs = {
                    "ts": time.time(),     # PPS-disciplined system time
                    "node": str(node),
                    "bssid": bssid,
                    "ssid": ssid,
                    "rssi": int(rssi),
                    "channel": int(ch) if ch is not None and str(ch).isdigit() else ch,
                    "frequency": freq
                }

                bus.add(obs)

            except Exception:
                break

        try:
            ser.close()
        except Exception:
            pass

        time.sleep(1)

def main():
    ports = load_ports()
    bus = CaptureBus()

    for p in ports:
        threading.Thread(
            target=capture_thread,
            args=(bus, p["node"], p["port"], p["baud"]),
            daemon=True
        ).start()

    while True:
        time.sleep(FLUSH_MS / 1000.0)

        gps = read_gps()
        snap = bus.snapshot()

        if len(snap) > MAX_OBS:
            snap = snap[-MAX_OBS:]

        # --- authoritative GPS snapshot ---
        gps_block = {
            "gps_ts_utc": gps.get("ts_utc") if gps else None,
            "gps_lat": gps.get("lat") if gps else None,
            "gps_lon": gps.get("lon") if gps else None,
            "gps_alt": gps.get("alt") if gps else None,
            "gps_speed_mps": gps.get("speed_mps") if gps else None,
            "gps_track_deg": gps.get("track_deg_stable") if gps else None,
            "gps_mode": gps.get("mode") if gps else 0,
            "gps_fix": gps.get("fix") if gps else "NO FIX",
        }

        payload = {
            "ts": time.time(),
            "gps": gps_block,
            "observations": snap
        }

        atomic_write_json(OUT, payload)

if __name__ == "__main__":
    main()
