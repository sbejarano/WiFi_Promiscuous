#!/usr/bin/env python3
import os
import json
import time
import shutil
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml  # NEW: for devices.yaml

STATE_GPS  = "/tmp/gps.json"
STATE_SYS  = "/tmp/system.json"
STATE_WIFI = "/tmp/wifi_devices.json"
STATE_DB   = "/tmp/db.json"

# NEW: devices.yaml path
DEVICES_YAML = "/media/sbejarano/Developer1/wifi_promiscuous/host/devices.yaml"

REFRESH = 0.4

SSID_W = 48              # original SSID width for main WiFi pane (pane 4)
DIR_SSID_W = 15          # SSID width for LEFT/RIGHT panes (pane 2 & 3)
WIFI_INNER = 77          # width for pane 4 WiFi
DIR_WIFI_INNER = 45      # width for pane 2 & 3 (LEFT/RIGHT)

RESET = "\033[0m"
BOLD  = "\033[1m"
CYAN  = "\033[36m"
GREEN = "\033[32m"
YEL   = "\033[33m"
RED   = "\033[31m"

LED_ON  = GREEN + "●" + RESET
LED_OFF = " "

ANSI = re.compile(r'\x1b\[[0-9;]*m')

# ------------------------------------------------------------
# UNIFIED LEFT-PANE BOX WIDTH / TITLES
# ------------------------------------------------------------
BOX_INNER = 35  # reduced from 55 to 35 per your request

def make_title(title: str) -> str:
    inner = BOX_INNER
    fill = inner - len(title) - 2
    if fill < 0:
        fill = 0
    left = fill // 2
    right = fill - left
    return "┌" + "─" * left + " " + title + " " + "─" * right + "┐"

GPS_TOP   = make_title("GPS")
SYS_TOP   = make_title("SYSTEM MONITOR")
DB_TOP    = make_title("DB")

BOX_BOTTOM = "└" + "─" * BOX_INNER + "┘"

GPS_BOTTOM = BOX_BOTTOM
SYS_BOTTOM = BOX_BOTTOM
DB_BOTTOM  = BOX_BOTTOM

LEFT_INNER = BOX_INNER

# ------------------------------------------------------------
def clear():
    print("\033c", end="")

def vislen(s):
    return len(ANSI.sub("", s))

def pad(s, width):
    return s + " " * max(0, width - vislen(s))

def truncate_visible(s, maxw):
    out = ""
    w = 0
    for ch in s:
        width = 2 if ord(ch) > 0xFF else 1
        if w + width > maxw:
            break
        out += ch
        w += width
    return out

def is_empty_ssid(s):
    if not s:
        return True
    cleaned = "".join(ch for ch in s if ch.isprintable() and not ch.isspace())
    return cleaned == ""

def load(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return None

# ------------------------------------------------------------
# HEARTBEAT NORMALIZATION + LED
# ------------------------------------------------------------
def norm_age(val):
    if val is None:
        return None
    try:
        v = float(val)
    except:
        return None
    if v > 1e6:
        return max(0, time.time() - v)
    return max(0, v)

def led(age):
    if age is None:
        return LED_OFF
    if age < 2.0:
        return LED_ON
    return LED_OFF

# ------------------------------------------------------------
# LOAD DEVICE PORTS FROM devices.yaml
# ------------------------------------------------------------
def load_device_ports():
    """
    Returns:
        gps_port, left_port, right_port, node_ports_dict
        node_ports_dict: { "1": "/dev/ttyACM10", ... }
    """
    gps_port = ""
    left_port = ""
    right_port = ""
    node_ports = {}

    try:
        with open(DEVICES_YAML, "r") as f:
            y = yaml.safe_load(f) or {}
    except Exception:
        return gps_port, left_port, right_port, node_ports

    try:
        gps = y.get("gps") or {}
        gps_port = gps.get("port", "") or ""

        directional = y.get("directional") or {}
        left = directional.get("left") or {}
        right = directional.get("right") or {}
        left_port = left.get("port", "") or ""
        right_port = right.get("port", "") or ""

        scanners = y.get("scanners") or []
        for s in scanners:
            nid = s.get("node_id")
            port = s.get("port", "") or ""
            if nid is None:
                continue
            node_ports[str(nid)] = port
    except Exception:
        pass

    return gps_port, left_port, right_port, node_ports

# ============================================================
# GPS BLOCK
# ============================================================
def gps_block(g):
    def s(x): return "---" if x is None else x

    if not g:
        return [
            GPS_TOP,
            "│" + pad(" Status : NO DATA", LEFT_INNER) + "│",
            GPS_BOTTOM
        ]

    utc_raw = g.get("time")
    date_str = "---"
    time_str = "---"

    if utc_raw:
        try:
            dt_utc = datetime.fromisoformat(utc_raw.replace("Z", "+00:00"))
            loc = dt_utc.astimezone(ZoneInfo("America/New_York"))
            date_str = loc.strftime("%Y-%m-%d")
            time_str = loc.strftime("%H:%M:%S %Z")
        except:
            pass

    fix  = s(g.get("fix"))
    sats = g.get("sats")
    prns = g.get("prns") or []
    lat  = s(g.get("lat"))
    lon  = s(g.get("lon"))
    alt  = s(g.get("alt"))
    spd  = s(g.get("speed"))
    trk  = s(g.get("track"))

    if fix in ("2D", "3D"):
        fix_col = GREEN + fix + RESET
    elif fix == "NO FIX":
        fix_col = RED + fix + RESET
    else:
        fix_col = fix

    prn_text = truncate_visible(", ".join(str(p) for p in prns), 20)

    out = [GPS_TOP]
    out.append("│" + pad(f" Date  : {date_str}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Time  : {time_str}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Fix   : {fix_col}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Sats  : {sats}", LEFT_INNER) + "│")
    out.append("│" + pad(f" PRNs  : {prn_text}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Lat   : {lat}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Lon   : {lon}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Alt   : {alt}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Speed : {spd}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Track : {trk}", LEFT_INNER) + "│")
    out.append(GPS_BOTTOM)
    return out

# ============================================================
# SYSTEM MONITOR BLOCK
# ============================================================
def sys_block(s):
    if not s:
        return [
            SYS_TOP,
            "│" + pad(" NO SYSTEM DATA", LEFT_INNER) + "│",
            SYS_BOTTOM
        ]

    cpu = s.get("cpu", "--")
    mu  = s.get("mem_used_mb", "--")
    mt  = s.get("mem_total_mb", "--")
    du  = s.get("disk_used_mb", "--")
    dt  = s.get("disk_total_mb", "--")
    hb  = s.get("heartbeat", {})

    # FIX #1 — LEFT/RIGHT must accept string keys ("LEFT", "RIGHT")
    gps_age   = norm_age(hb.get("gps"))
    left_age  = norm_age(hb.get("left")  if hb.get("left")  is not None else hb.get("LEFT"))
    right_age = norm_age(hb.get("right") if hb.get("right") is not None else hb.get("RIGHT"))

    # NEW: load device ports for display
    gps_port, left_port, right_port, node_ports = load_device_ports()
    gps_port   = gps_port or "-"
    left_port  = left_port or "-"
    right_port = right_port or "-"

    out = [SYS_TOP]
    out.append("│" + pad(f" CPU  : {cpu}%", LEFT_INNER) + "│")
    out.append("│" + pad(f" MEM  : {mu} / {mt} MB", LEFT_INNER) + "│")
    out.append("│" + pad(f" DISK : {du} / {dt} MB", LEFT_INNER) + "│")
    out.append("│" + pad(" Heartbeat:", LEFT_INNER) + "│")

    # One line per “special” device
    out.append("│" + pad(
        f"   GPS   : {gps_port:<12} : {led(gps_age)}",
        LEFT_INNER
    ) + "│")
    out.append("│" + pad(
        f"   LEFT  : {left_port:<12} : {led(left_age)}",
        LEFT_INNER
    ) + "│")
    out.append("│" + pad(
        f"   RIGHT : {right_port:<12} : {led(right_age)}",
        LEFT_INNER
    ) + "│")

    out.append("│" + pad(" Nodes:", LEFT_INNER) + "│")

    # Nodes 1–12 with ports
    for i in range(1, 13):
        n_key = str(i)
        n_age = norm_age(hb.get(n_key))
        port = node_ports.get(n_key, "-")
        line = f"   Node {i:<2}: {port:<12} : {led(n_age)}"
        out.append("│" + pad(line, LEFT_INNER) + "│")

    out.append(SYS_BOTTOM)
    return out

# ============================================================
# DB BLOCK
# ============================================================
def db_block(d):
    if not d:
        return [
            DB_TOP,
            "│" + pad(" NO DB STATE", LEFT_INNER) + "│",
            DB_BOTTOM
        ]

    # FIX #2 — DB size comes from system.json, not /tmp/db.json
    sz = d.get("db_size_mb", 0)

    if sz < 100:
        szc = GREEN + f"{sz} MB" + RESET
    elif sz < 300:
        szc = YEL + f"{sz} MB" + RESET
    else:
        szc = RED + f"{sz} MB" + RESET

    # Queue + rows/sec still from /tmp/db.json
    q = 0
    rs = 0
    try:
        with open(STATE_DB) as f:
            dj = json.load(f)
            q  = dj.get("queue", 0)
            rs = dj.get("rows_sec", 0)
    except:
        pass

    out = [DB_TOP]
    out.append("│" + pad(f" Size      : {szc}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Rows/sec  : {rs}", LEFT_INNER) + "│")
    out.append("│" + pad(f" Queue     : {q}", LEFT_INNER) + "│")
    out.append(DB_BOTTOM)
    return out

# ============================================================
# DIRECTIONAL WIFI BLOCKS (Pane 2 & 3: LEFT / RIGHT)
# ============================================================
def directional_block(devs):
    top    = "┌" + "─" * DIR_WIFI_INNER + "┐"
    middle = "├" + "─" * DIR_WIFI_INNER + "┤"
    bottom = "└" + "─" * DIR_WIFI_INNER + "┘"

    out = [
        top,
        "│" + pad(" BSSID              RSSI  CH  SSID", DIR_WIFI_INNER) + "│",
        middle
    ]

    for d in devs[:40]:
        ssid = d.get("ssid") or ""
        ssid = truncate_visible(ssid, DIR_SSID_W)

        b = d.get("bssid", "")[:17]
        r = d.get("rssi", 0)
        c = d.get("ch", "")

        if r >= -60:
            rc = GREEN + f"{r:>4}" + RESET
        elif r >= -75:
            rc = YEL   + f"{r:>4}" + RESET
        else:
            rc = RED   + f"{r:>4}" + RESET

        line_raw = f" {b:<17} {rc}  {str(c):>2}  {ssid}"
        out.append("│" + pad(line_raw, DIR_WIFI_INNER) + "│")

    out.append(bottom)
    return out

# ============================================================
# WIFI BLOCK (Pane 4) — NUMERIC NODES ONLY (1–12)
# ============================================================
def wifi_block(w):

    top    = "┌" + "─" * WIFI_INNER + "┐"
    middle = "├" + "─" * WIFI_INNER + "┤"
    bottom = "└" + "─" * WIFI_INNER + "┘"

    if not w:
        return [top, "│" + pad(" No WiFi devices", WIFI_INNER) + "│", bottom]

    # Filter out LEFT/RIGHT — keep only numeric nodes (1–12)
    devs_all = w.get("devices", [])
    devs = []
    for d in devs_all:
        node = d.get("node")
        if isinstance(node, int):
            devs.append(d)
        else:
            # if node is a string like "LEFT"/"RIGHT", skip it
            try:
                if str(node).isdigit():
                    devs.append(d)
            except:
                pass

    devs = sorted(devs, key=lambda x: x.get("rssi", -999), reverse=True)

    out = [top,
           "│" + pad(" BSSID              RSSI  CH  ND  SSID", WIFI_INNER) + "│",
           middle]

    for d in devs[:100]:
        ssid = d.get("ssid") or ""
        if is_empty_ssid(ssid):
            continue

        ssid = truncate_visible(ssid, SSID_W)

        b = d.get("bssid", "")[:17]
        r = d.get("rssi", 0)
        c = d.get("ch", "")
        n = d.get("node", "")

        if r >= -60:
            rc = GREEN + f"{r:>4}" + RESET
        elif r >= -75:
            rc = YEL   + f"{r:>4}" + RESET
        else:
            rc = RED   + f"{r:>4}" + RESET

        line_raw = f" {b:<17} {rc}  {str(c):>2}  {str(n):>2}  {ssid}"
        out.append("│" + pad(line_raw, WIFI_INNER) + "│")

    out.append(bottom)
    return out

# ============================================================
# ORIGINAL 2-PANE COMBINE (kept, but not used now)
# ============================================================
def combine(left, right, split):
    rows = max(len(left), len(right))
    for i in range(rows):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        print(pad(l, split) + " " + r)

# ============================================================
# NEW 4-PANE COMBINE
# ============================================================
def combine4(p1, p2, p3, p4, w1, w2, w3, w4):
    rows = max(len(p1), len(p2), len(p3), len(p4))
    for i in range(rows):
        c1 = pad(p1[i] if i < len(p1) else "", w1)
        c2 = pad(p2[i] if i < len(p2) else "", w2)
        c3 = pad(p3[i] if i < len(p3) else "", w3)
        c4 = pad(p4[i] if i < len(p4) else "", w4)
        print(c1 + " " + c2 + " " + c3 + " " + c4)

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    while True:
        gps  = load(STATE_GPS)
        sys  = load(STATE_SYS)
        wifi = load(STATE_WIFI)
        db   = load(STATE_DB)

        # keep this line for compatibility, even if not used
        cols = shutil.get_terminal_size((150, 40)).columns

        # Pane 1: GPS + SYSTEM + DB
        P1 = []
        P1.extend(gps_block(gps))
        P1.append("")
        P1.extend(sys_block(sys))
        P1.append("")
        P1.extend(db_block(sys))

        # Pane 2: LEFT scanner
        left_devs = []
        if wifi:
            for d in wifi.get("devices", []):
                if d.get("node") == "LEFT":
                    left_devs.append(d)
        left_devs = sorted(left_devs, key=lambda x: x.get("rssi", -999), reverse=True)
        P2 = directional_block(left_devs)

        # Pane 3: RIGHT scanner
        right_devs = []
        if wifi:
            for d in wifi.get("devices", []):
                if d.get("node") == "RIGHT":
                    right_devs.append(d)
        right_devs = sorted(right_devs, key=lambda x: x.get("rssi", -999), reverse=True)
        P3 = directional_block(right_devs)

        # Pane 4: numeric nodes 1–12
        P4 = wifi_block(wifi)

        clear()
        print(BOLD + CYAN + "WiFi Promiscuous Dashboard" + RESET + "\n")

        # widths: pane1 ~ BOX_INNER+2, dir panes ~ DIR_WIFI_INNER+2, wifi ~ WIFI_INNER+2
        combine4(
            P1, P2, P3, P4,
            BOX_INNER + 2,
            DIR_WIFI_INNER + 2,
            DIR_WIFI_INNER + 2,
            WIFI_INNER + 2
        )

        time.sleep(REFRESH)

if __name__ == "__main__":
    main()
