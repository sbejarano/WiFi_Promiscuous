#!/bin/bash

BASE="/media/sbejarano/Developer1/wifi_promiscuous"
LOGDIR="$BASE/tmp"

echo "[+] Stopping WiFi Promiscuous Stack..."
echo

# ----------------------------------------------------------------------
# 1) Kill all known python services cleanly
# ----------------------------------------------------------------------
echo "[-] Killing primary Python services..."

pkill -f gps_service.py            2>/dev/null
pkill -f wifi_capture_service.py   2>/dev/null
pkill -f system_monitor.py         2>/dev/null
pkill -f dashboard.py              2>/dev/null
pkill -f dashboard_service.py      2>/dev/null
pkill -f data_aggregator.py        2>/dev/null

# ----------------------------------------------------------------------
# 2) Kill orphaned python processes referencing ACM ports or project path
# ----------------------------------------------------------------------
echo "[-] Killing orphaned python3 processes..."

pkill -f "python3 .*wifi_promiscuous"   2>/dev/null
pkill -f "python3 .*ttyACM"             2>/dev/null

# ----------------------------------------------------------------------
# 3) Kill GPS utilities (gpspipe produces stray processes)
# ----------------------------------------------------------------------
echo "[-] Killing GPS utilities (gpspipe / gpsmon / cgps)..."

pkill -f gpspipe   2>/dev/null
pkill -f gpsmon    2>/dev/null
pkill -f cgps      2>/dev/null

# DO NOT kill gpsd itself — required for GPS
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 4) Clean JSON state files
# ----------------------------------------------------------------------
echo "[-] Cleaning /tmp JSON state..."

rm -f /tmp/gps.json
rm -f /tmp/wifi.json
rm -f /tmp/wifi_devices.json
rm -f /tmp/system.json
rm -f /tmp/db.json
rm -f /tmp/system_state.json
rm -f /tmp/wifi_state.json

# ----------------------------------------------------------------------
# 5) Clean internal logs
# ----------------------------------------------------------------------
echo "[-] Cleaning internal logs..."
rm -f "$LOGDIR"/*.log 2>/dev/null

# ----------------------------------------------------------------------
# 6) Remove PID files
# ----------------------------------------------------------------------
echo "[-] Removing PID files..."

rm -f /tmp/wifi_promiscuous.pids
rm -f /tmp/wifi_pids
rm -f /tmp/gps_pids

sleep 0.5

# ----------------------------------------------------------------------
# 7) Verification pass
# ----------------------------------------------------------------------
echo
echo "[+] Verifying shutdown..."
leftover=$(ps aux | grep -E "gps_service|wifi_capture_service|system_monitor|dashboard|ttyACM|gpspipe" | grep -v grep)

if [[ -z "$leftover" ]]; then
    echo "[✓] All services stopped cleanly."
else
    echo "[!] WARNING: Some processes survived:"
    echo "$leftover"
    echo "[!] Forcing kill..."
    echo "$leftover" | awk '{print $2}' | xargs kill -9 2>/dev/null
    echo "[✓] Forced cleanup completed."
fi

echo "[✓] System is fully stopped."
