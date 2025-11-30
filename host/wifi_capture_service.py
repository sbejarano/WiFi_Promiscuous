#!/usr/bin/env python3
import os, time, json, serial, queue, sqlite3, threading, re
import serial.tools.list_ports
import yaml

# =====================================================================
# MARKER: CONSTANTS / PATHS
# =====================================================================
DB_PATH = "/media/sbejarano/Developer1/wifi_promiscuous/data/trilateration_data.db"
DEVICES_YAML = "/media/sbejarano/Developer1/wifi_promiscuous/host/devices.yaml"

STATE_WIFI          = "/tmp/wifi.json"
STATE_WIFI_DEVS     = "/tmp/wifi_devices.json"        # NUMERIC 1–12 ONLY
STATE_WIFI_DIR      = "/tmp/wifi_directional.json"    # LEFT / RIGHT ONLY
STATE_GPS           = "/tmp/gps.json"
STATE_SYS           = "/tmp/system.json"

BAUD = 115200
QUEUE_MAX = 50000
STALE = 4.0

stop_flag = False
db_queue = queue.Queue(maxsize=QUEUE_MAX)

rows_last_sec = 0
rows_total = 0
db_rows_last_sec = 0

# =====================================================================
# MARKER: DEVICE STORAGE
# =====================================================================
DEV_NUMERIC = {}      # <-- numeric-only 1–12
DEV_LEFT    = {}      # <-- LEFT directional isolated storage
DEV_RIGHT   = {}      # <-- RIGHT directional isolated storage

DEV_LOCK = threading.Lock()
HEARTBEAT = {}
HB_LOCK = threading.Lock()

# =====================================================================
# HELPER: Atomic JSON write
# =====================================================================
def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except:
        pass

# =====================================================================
# HELPER: Load YAML
# =====================================================================
def load_yaml():
    with open(DEVICES_YAML) as f:
        return yaml.safe_load(f)

CONF = load_yaml()

LEFT_MAC  = CONF["directional"]["left"]["mac"].upper()
RIGHT_MAC = CONF["directional"]["right"]["mac"].upper()

# =====================================================================
# HELPER: Load GPS
# =====================================================================
def load_gps():
    for _ in range(3):
        try:
            with open(STATE_GPS, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            time.sleep(0.01)
        except:
            return None
    return None

# =====================================================================
# HELPER: Detect Ports
# =====================================================================
def get_mac_from_port(port):
    for p in serial.tools.list_ports.comports():
        if p.device == port:
            return p.serial_number.upper() if p.serial_number else None
    return None

def detect_all_ports():
    mapping = []
    ports = [p.device for p in serial.tools.list_ports.comports() if "ACM" in p.device]

    for pt in ports:
        mac = get_mac_from_port(pt)
        if not mac:
            continue

        if mac == LEFT_MAC:
            mapping.append({"port": pt, "mac": mac, "node_id": "LEFT"})
            continue
        if mac == RIGHT_MAC:
            mapping.append({"port": pt, "mac": mac, "node_id": "RIGHT"})
            continue

        for s in CONF["scanners"]:
            if s["mac"] == mac:
                mapping.append({"port": pt, "mac": mac, "node_id": s["node_id"]})

    def sort_key(m):
        v = m["node_id"]
        return 1000 if isinstance(v, str) else int(v)

    mapping.sort(key=sort_key)
    return mapping

# =====================================================================
# SYSTEM JSON WRITER
# =====================================================================
def write_system_json():
    try:
        with open("/proc/stat") as f:
            parts = list(map(int, f.readline().split()[1:]))
        idle = parts[3]
        total = sum(parts)
        prev = getattr(write_system_json, "prev", None)
        write_system_json.prev = (idle, total)
        if prev is None:
            cpu_percent = 0
        else:
            idle_prev, total_prev = prev
            dt = total - total_prev
            di = idle - idle_prev
            cpu_percent = int(100 * (1 - di / dt)) if dt > 0 else 0
    except:
        cpu_percent = 0

    try:
        with open("/proc/meminfo") as f:
            mem = f.read().split()
        total_kb = int(mem[mem.index("MemTotal:")+1])
        free_kb  = int(mem[mem.index("MemAvailable:")+1])
        used_mb  = (total_kb - free_kb)//1024
        total_mb = total_kb//1024
    except:
        used_mb = total_mb = 0

    try:
        st = os.statvfs("/media/sbejarano/Developer1")
        total_disk = (st.f_blocks*st.f_frsize)//(1024*1024)
        free_disk  = (st.f_bfree *st.f_frsize)//(1024*1024)
        used_disk  = total_disk - free_disk
    except:
        used_disk = total_disk = 0

    try:
        sz = os.path.getsize(DB_PATH)/(1024*1024)
        db_mb = round(sz,1)
    except:
        db_mb = 0

    with HB_LOCK:
        hb = dict(HEARTBEAT)

    atomic_write_json(STATE_SYS, {
        "cpu": cpu_percent,
        "mem_used_mb": used_mb,
        "mem_total_mb": total_mb,
        "disk_used_mb": used_disk,
        "disk_total_mb": total_disk,
        "heartbeat": hb,
        "db_size_mb": db_mb
    })

# =====================================================================
# DB WRITER THREAD
# =====================================================================
def db_writer():
    global db_rows_last_sec
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()

    last = time.time()
    rows = 0

    while not stop_flag or not db_queue.empty():
        try:
            item = db_queue.get(timeout=0.1)
        except queue.Empty:
            item = None
        if item:
            try:
                cur.execute("""
                    INSERT INTO wifi_observations
                    (ts_utc,node_id,channel,frequency_mhz,bssid,ssid,rssi_dbm,
                     gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_track_deg)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, item)
                rows += 1
            except Exception as e:
                print("[DB ERROR]", e)

        now = time.time()
        if now - last >= 1:
            conn.commit()
            db_rows_last_sec = rows
            rows = 0
            last = now
            atomic_write_json("/tmp/db.json", {
                "queue": db_queue.qsize(),
                "rows_sec": db_rows_last_sec
            })
            write_system_json()

    conn.commit()
    conn.close()

# =====================================================================
# MARKER: SAVE STATE (FIXED FOR DIRECTIONAL)
# =====================================================================
def save_dev_state():
    now = time.time()

    # NUMERIC 1–12
    numeric = []

    # LEFT/RIGHT isolated
    lefts  = []
    rights = []

    with DEV_LOCK:
        # numeric only
        for b,d in DEV_NUMERIC.items():
            if now - d["last"] <= 4:
                numeric.append(d)

        # left
        for b,d in DEV_LEFT.items():
            if now - d["last"] <= 15:
                if d["ssid"] != "":
                    lefts.append(d)

        # right
        for b,d in DEV_RIGHT.items():
            if now - d["last"] <= 15:
                if d["ssid"] != "":
                    rights.append(d)

    numeric.sort(key=lambda x: x["rssi"], reverse=True)
    lefts.sort(key=lambda x: x["rssi"], reverse=True)
    rights.sort(key=lambda x: x["rssi"], reverse=True)

    atomic_write_json(STATE_WIFI_DEVS, {
        "devices": numeric,
        "ts": now
    })

    atomic_write_json(STATE_WIFI_DIR, {
        "left": lefts,
        "right": rights,
        "ts": now
    })

# =====================================================================
# MARKER: EXTRACTORS (UNCHANGED)
# =====================================================================
def extract(s, key):
    m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', s)
    if m: return m.group(1)
    m = re.search(rf'"{key}"\s*:\s*([0-9\.\-]+)', s)
    if m: return m.group(1)
    return None

def extract_int(s, key):
    v = extract(s, key)
    if v is None: return None
    try: return int(float(v))
    except: return None

def extract_channel(s):
    for k in ["ch","chan","channel"]:
        v = extract_int(s, k)
        if v and 1<=v<=13:
            return v
    return None

def freq_from_ch(ch):
    return 2407 + 5*ch

# =====================================================================
# MARKER: CAPTURE THREAD (LEFT/RIGHT FIXED)
# =====================================================================
def capture(port, node_id):
    global rows_last_sec, rows_total

    print(f"[WiFi] Starting {port} ({node_id})")
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except Exception as e:
        print("[WiFi] ERROR opening", port, e)
        return

    last = time.time()
    count = 0

    while not stop_flag:
        try:
            raw = ser.readline().decode(errors="ignore")
        except:
            break
        if not raw or "{" not in raw:
            continue

        s = raw.strip()

        # extract fields
        bssid = extract(s, "bssid")
        ssid  = extract(s, "ssid")
        rssi  = extract_int(s, "rssi")
        ch    = extract_channel(s)

        if not bssid or rssi is None or ch is None:
            continue

        # --------------- NUMERIC NODES ONLY filter hidden ---------------
        if node_id not in ("LEFT", "RIGHT"):
            if not ssid or ssid.strip()=="":
                continue
            low = ssid.lower()
            if low=="" or low=="hidden":
                continue

        # --------------- LEFT/RIGHT KEEP EXACT SSID ---------------------
        # Remove non-printable ASCII only
        if ssid:
            ssid = "".join(ch for ch in ssid if 32 <= ord(ch) <= 126)

        # Filter shentel/acso
        if ssid and ("shentel" in ssid.lower() or "acso" in ssid.lower()):
            continue

        # load GPS
        gps = load_gps()
        if gps:
            lat = gps.get("lat")
            lon = gps.get("lon")
            alt = gps.get("alt")
            sp  = gps.get("speed")
            tr  = gps.get("track")
        else:
            lat = lon = alt = sp = tr = None

        freq = extract_int(s,"freq") or freq_from_ch(ch)
        ts = time.time()

        # queue DB row
        row = (
            ts,node_id,ch,freq,
            bssid.upper(),
            ssid,
            rssi,
            lat,lon,alt,sp,tr
        )

        try:
            db_queue.put_nowait(row)
        except queue.Full:
            continue

        # =================================================================
        # STORE DEV (ISOLATED)
        # =================================================================
        with DEV_LOCK:
            if node_id == "LEFT":
                DEV_LEFT[bssid] = {
                    "bssid": bssid,
                    "ssid": ssid or "",
                    "rssi": rssi,
                    "node": node_id,
                    "ch": ch,
                    "freq": freq,
                    "last": ts
                }
            elif node_id == "RIGHT":
                DEV_RIGHT[bssid] = {
                    "bssid": bssid,
                    "ssid": ssid or "",
                    "rssi": rssi,
                    "node": node_id,
                    "ch": ch,
                    "freq": freq,
                    "last": ts
                }
            else:
                # numeric 1–12
                DEV_NUMERIC[bssid] = {
                    "bssid": bssid,
                    "ssid": ssid or "",
                    "rssi": rssi,
                    "node": node_id,
                    "ch": ch,
                    "freq": freq,
                    "last": ts
                }

        with HB_LOCK:
            HEARTBEAT[str(node_id)] = ts

        count += 1
        rows_total += 1

        now = time.time()
        if now-last>=1:
            last = now
            rows_last_sec = count
            count = 0
            save_dev_state()
            write_system_json()

    try:
        ser.close()
    except:
        pass

    print("[WiFi] Closed", port)

# =====================================================================
# MARKER: MAIN
# =====================================================================
def main():
    global stop_flag

    mapping = detect_all_ports()
    print("[WiFi] Detected:")
    for m in mapping:
        print(" ",m["port"],m["mac"],"node:",m["node_id"])

    tdb = threading.Thread(target=db_writer,daemon=True)
    tdb.start()

    for m in mapping:
        threading.Thread(
            target=capture,
            args=(m["port"],m["node_id"]),
            daemon=True
        ).start()

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_flag=True
        time.sleep(1)

if __name__=="__main__":
    main()
