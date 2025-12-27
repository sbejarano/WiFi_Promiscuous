# broker.py  (optional live view; NO DB; no split files)
#!/usr/bin/env python3
import os
import json
import time
import yaml
from collections import defaultdict, deque

BASE = "/media/sbejarano/Developer1/wifi_promiscuous"
INP  = "/dev/shm/wifi_capture.json"

OUT  = f"{BASE}/tmp/wifi_devices.json"
DENY = f"{BASE}/host/denied_ssid.yaml"

STALE_SEC = 3.0
WINDOW_SEC = 2.0

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)

def load_denied():
    try:
        with open(DENY) as f:
            d = yaml.safe_load(f) or {}
            return set(d.get("deny", []) or [])
    except Exception:
        return set()

def read_capture():
    try:
        with open(INP) as f:
            return json.load(f)
    except Exception:
        return None

def is_hidden(ssid: str) -> bool:
    if not ssid:
        return True
    s = ssid.strip().lower()
    return s in ("hidden", "<hidden>", "<length: 0>", "null")

def main():
    denied = load_denied()

    # history per BSSID of (ts, node, rssi, channel, ssid)
    hist = defaultdict(lambda: deque())

    while True:
        cap = read_capture()
        now = time.time()

        if cap and isinstance(cap.get("observations"), list):
            for o in cap["observations"]:
                try:
                    ts = float(o.get("ts", now))
                    bssid = (o.get("bssid") or "").strip()
                    ssid  = (o.get("ssid") or "").strip()
                    node  = (o.get("node") or "").strip().upper()
                    rssi  = o.get("rssi", None)
                    ch    = o.get("channel", None)

                    if not bssid or rssi is None:
                        continue
                    if is_hidden(ssid):
                        continue
                    if ssid in denied:
                        continue

                    dq = hist[bssid]
                    dq.append((ts, node, int(rssi), ch, ssid))
                except Exception:
                    continue

        # prune old samples + build live view
        devices = []
        for bssid, dq in list(hist.items()):
            # prune by window
            while dq and (now - dq[0][0]) > WINDOW_SEC:
                dq.popleft()

            if not dq:
                hist.pop(bssid, None)
                continue

            last_ts, _, _, _, _ = dq[-1]
            if (now - last_ts) > STALE_SEC:
                hist.pop(bssid, None)
                continue

            # pick latest ssid / channel
            ssid = dq[-1][4]
            ch = dq[-1][3]

            # compute smoothed rssi (simple mean)
            rssi_vals = [x[2] for x in dq if isinstance(x[2], int)]
            rssi = int(sum(rssi_vals) / max(len(rssi_vals), 1)) if rssi_vals else None

            # side decision based on latest LEFT/RIGHT samples in window
            left = [x[2] for x in dq if x[1] == "LEFT"]
            right = [x[2] for x in dq if x[1] == "RIGHT"]

            if left and right:
                side = "LEFT" if (sum(left)/len(left)) > (sum(right)/len(right)) else "RIGHT"
            elif left:
                side = "LEFT"
            elif right:
                side = "RIGHT"
            else:
                side = "OMNI"

            devices.append({
                "bssid": bssid,
                "ssid": ssid,
                "rssi": rssi,
                "channel": ch,
                "side": side,
                "last_seen": last_ts
            })

        atomic_write_json(OUT, {"ts": now, "devices": devices})
        time.sleep(0.25)

if __name__ == "__main__":
    main()
