#!/bin/bash

BASE="/media/sbejarano/Developer1/wifi_promiscuous"
HOST="$BASE/host"
LOGDIR="$BASE/tmp"

ERRLOG="/tmp/gps_init_error.log"
DEV_YAML="$BASE/host/devices.yaml"

rm -f "$ERRLOG"

# Create log directory if missing
mkdir -p "$LOGDIR"

echo "[+] Stopping old processes..."
pkill -f gps_service.py
pkill -f wifi_capture_service.py
pkill -f system_monitor.py
pkill -f dashboard.py
sleep 1

echo "[+] Cleaning JSON state..."
rm -f /tmp/*.json
rm -f "$LOGDIR"/*.log

# ====================================================================
# AUTO-GENERATE devices.yaml USING build_devices_yaml.py
# ====================================================================
echo "[+] Building devices.yaml with build_devices_yaml.py..."
python3 "$BASE/scripts/build_devices_yaml.py"
echo "[+] devices.yaml generated."

# ====================================================================
# DO NOT TOUCH GPS — NO RESET, NO USB RESET, NO GPSD MANIPULATION
# ====================================================================
echo "[GPS INIT] Skipping GPS reset / validation (disabled to avoid freezing GPS)."

# ====================================================================
# START BACKGROUND SERVICES
# ====================================================================
start_bg () {
    local NAME=$1
    local SCRIPT=$2
    local LOGFILE="$LOGDIR/${NAME}.log"

    echo "[+] Launching $NAME ..."
    nohup python3 "$SCRIPT" > "$LOGFILE" 2>&1 &
    sleep 0.3
}

echo "[+] Starting GPS..."
start_bg "gps" "$HOST/gps_service.py"

echo "[+] Starting WiFi capture..."
start_bg "wifi_capture" "$HOST/wifi_capture_service.py"

echo "[+] Starting System Monitor..."
start_bg "system_monitor" "$HOST/system_monitor.py"

sleep 1

echo "[+] Starting Dashboard (foreground)..."
echo "[+] Press CTRL+C to stop the dashboard."
python3 "$HOST/dashboard.py"
