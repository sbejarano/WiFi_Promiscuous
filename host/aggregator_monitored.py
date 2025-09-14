#!/usr/bin/env python3
import serial
import sqlite3
import json
import time
import threading
import sys
import os
import yaml
import logging
from datetime import datetime

# === CONFIG ===
DB_PATH = "data/captures.sqlite"
CONFIG_FILE = "host/config.yaml"
WARNING_LOG = "data/warnings.log"
GPS_TIMEOUT = 5        # seconds
CHANNEL_TIMEOUT = 10   # seconds
LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"

# === LOGGING SETUP ===
os.makedirs("data", exist_ok=True)
logging.basicConfig(
    filename=WARNING_LOG,
    level=logging.INFO,
    format=LOG_FORMAT,
)
RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"

# === GLOBAL STATE ===
last_gps_time = time.time()
last_channel_time = {}  # channel -> timestamp
gps_warning = False
channel_warnings = {}

# === LOAD CONFIG ===
with open(CONFIG_FILE, "r") as f:
    config = yaml.safe_load(f)
ports = config.get("ports", [])
gps_port = config.get("gps_port", None)

# === DB SETUP ===
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

def insert_capture(data):
    cur.execute("""
        INSERT INTO wifi_captures (
            ts_utc, node_id, channel, frequency_mhz, bssid, ssid, rssi_dbm,
            beacon_interval_ms, gps_lat, gps_lon, gps_alt_m,
            gps_speed_mps, gps_track_deg, gps_hdop, gps_vdop, pps_locked
        ) VALUES (
            :ts_utc, :node_id, :channel, :frequency_mhz, :bssid, :ssid, :rssi_dbm,
            :beacon_interval_ms, :gps_lat, :gps_lon, :gps_alt_m,
            :gps_speed_mps, :gps_track_deg, :gps_hdop, :gps_vdop, :pps_locked
        );
    """, data)
    conn.commit()

# === WARNING SYSTEM ===
def warn(msg):
    print(f"{RED}[!] {msg}{RESET}")
    logging.warning(msg)

def resolve(msg):
    print(f"{GREEN}[✓] {msg}{RESET}")
    logging.info(msg)

# === MONITORING ===
def monitor():
    global gps_warning, channel_warnings
    while True:
        now = time.time()

        # GPS staleness
        if now - last_gps_time > GPS_TIMEOUT:
            if not gps_warning:
                warn("No GPS update in last 5 seconds")
                gps_warning = True
        else:
            if gps_warning:
                resolve("GPS updates resumed")
                gps_warning = False

        # Channel activity
        for ch, last_seen in last_channel_time.items():
            if now - last_seen > CHANNEL_TIMEOUT:
                if ch not in channel_warnings:
                    warn(f"No signal on channel {ch} for 10s")
                    channel_warnings[ch] = True
            else:
                if channel_warnings.get(ch):
                    resolve(f"Channel {ch} receiving data again")
                    del channel_warnings[ch]

        time.sleep(1)

# === SERIAL READERS ===
def parse_line(line):
    try:
        data = json.loads(line)
        if data.get("bssid") and data.get("rssi_dbm") is not None:
            now = datetime.utcnow().isoformat() + "Z"
            ch = int(data.get("channel", 0))
            last_channel_time[ch] = time.time()
            record = {
                "ts_utc": now,
                "node_id": int(data.get("node_id", 0)),
                "channel": ch,
                "frequency_mhz": int(data.get("frequency_mhz", 0)),
                "bssid": data.get("bssid"),
                "ssid": data.get("ssid"),
                "rssi_dbm": int(data.get("rssi_dbm")),
                "beacon_interval_ms": data.get("beacon_interval_ms"),
                "gps_lat": data.get("gps_lat"),
                "gps_lon": data.get("gps_lon"),
                "gps_alt_m": data.get("gps_alt_m"),
                "gps_speed_mps": data.get("gps_speed_mps"),
                "gps_track_deg": data.get("gps_track_deg"),
                "gps_hdop": data.get("gps_hdop"),
                "gps_vdop": data.get("gps_vdop"),
                "pps_locked": int(data.get("pps_locked", 0)),
            }
            insert_capture(record)
    except Exception as e:
        print(f"[x] Parse error: {e}")

def read_serial(port_path, baud=115200):
    try:
        ser = serial.Serial(port_path, baudrate=baud, timeout=1)
        print(f"[+] Listening on {port_path}")
        while True:
            line = ser.readline().decode("utf-8").strip()
            if line:
                parse_line(line)
    except Exception as e:
        print(f"[x] Failed on {port_path}: {e}")

def read_gps(port_path, baud=9600):
    global last_gps_time
    try:
        ser = serial.Serial(port_path, baudrate=baud, timeout=1)
        print(f"[+] GPS on {port_path}")
        while True:
            line = ser.readline().decode("utf-8").strip()
            if line.startswith("$"):
                last_gps_time = time.time()
    except Exception as e:
        print(f"[x] GPS read error: {e}")

# === MAIN ===
if __name__ == "__main__":
    print("[✓] Starting monitored aggregator...")
    threads = []

    # Launch channel readers
    for p in ports:
        t = threading.Thread(target=read_serial, args=(p,))
        t.daemon = True
        t.start()
        threads.append(t)

    # Launch GPS reader
    if gps_port:
        t = threading.Thread(target=read_gps, args=(gps_port,))
        t.daemon = True
        t.start()
        threads.append(t)

    # Start monitor
    monitor()
