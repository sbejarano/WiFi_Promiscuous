#!/usr/bin/env python3
import os, time, json, serial, queue, sqlite3, threading, re, yaml

BASE_DIR = "/media/sbejarano/Developer1/wifi_promiscuous"
TMP_DIR  = f"{BASE_DIR}/tmp"
DB_PATH  = f"{BASE_DIR}/data/trilateration_data.db"
DEVICES_YAML = f"{BASE_DIR}/host/devices.yaml"
STATE_GPS = f"{TMP_DIR}/gps.json"
BAUD = 115200

db_queue = queue.Queue(maxsize=50000)
stop_flag = False

def load_gps():
    try:
        with open(STATE_GPS) as f:
            return json.load(f)
    except:
        return None

def gps_time(gps):
    if gps and gps.get("ts_utc"):
        return float(gps["ts_utc"])
    return time.time()

with open(DEVICES_YAML) as f:
    CONF = yaml.safe_load(f)

PORTS = CONF.get("ports", {})

def db_writer():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    while not stop_flag:
        try:
            item = db_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            cur.execute("""
                INSERT INTO wifi_observations
                (ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,
                 gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_track_deg)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, item)
            conn.commit()
        except Exception:
            pass
    conn.close()

def capture(port, node_id):
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except Exception:
        return

    while not stop_flag:
        raw = ser.readline().decode(errors="ignore").strip()
        if not raw.startswith("{"):
            continue
        try:
            pkt = json.loads(raw)
        except:
            continue

        gps = load_gps()
        ts = gps_time(gps)

        try:
            db_queue.put_nowait((
                ts,node_id,
                pkt.get("ch"),pkt.get("freq"),
                pkt.get("bssid"),pkt.get("ssid"),
                pkt.get("rssi"),
                gps.get("lat") if gps else None,
                gps.get("lon") if gps else None,
                gps.get("alt") if gps else None,
                gps.get("speed") if gps else None,
                gps.get("track") if gps else None
            ))
        except queue.Full:
            pass

def main():
    threading.Thread(target=db_writer, daemon=True).start()
    for node, port in PORTS.items():
        threading.Thread(target=capture, args=(port, node), daemon=True).start()
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
