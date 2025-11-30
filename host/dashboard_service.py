#!/usr/bin/env python3
import os
import time
import json

STATE_GPS = "/tmp/gps.json"
STATE_WIFI = "/tmp/wifi.json"
STATE_DB = "/tmp/db.json"
STATE_SYSTEM = "/tmp/system.json"


def safe_load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None


def banner(title):
    print("=" * 70)
    print(f"{title}".center(70))
    print("=" * 70)


def main():
    while True:
        os.system("clear")

        gps = safe_load(STATE_GPS)
        wifi = safe_load(STATE_WIFI)
        dbs = safe_load(STATE_DB)
        sysm = safe_load(STATE_SYSTEM)

        banner("GPS STATUS")
        if gps:
            print(f"Time:       {time.strftime('%H:%M:%S')}")
            print(f"Fix:        {gps.get('fix')}")
            print(f"Sats:       {gps.get('sats')}")
            print(f"Lat:        {gps.get('lat')}")
            print(f"Lon:        {gps.get('lon')}")
            print(f"Alt:        {gps.get('alt')}")
            print(f"Speed:      {gps.get('speed')} mph")
            print(f"Track:      {gps.get('track')}°")
        else:
            print("NO GPS DATA")

        banner("SYSTEM MONITOR")
        if sysm:
            print(f"Storage Used:   {sysm.get('storage_used')} MB")
            print(f"Storage Total:  {sysm.get('storage_total')} MB")
            print(f"DB Size:        {sysm.get('db_size')} MB")
            print(f"DB Write:       {sysm.get('db_rows_sec')} rows/s")
            print(f"WiFi Rate:      {sysm.get('wifi_rows_sec')} rows/s")
            print(f"DB Queue:       {sysm.get('queue')}")
        else:
            print("NO SYSTEM DATA")

        banner("DB ENGINE")
        if dbs:
            print(f"Queue: {dbs.get('queue')}  Rows/sec: {dbs.get('rows_sec')}")
        else:
            print("NO DB INFO")

        banner("WIFI ENGINE")
        if wifi:
            print(f"Rows/sec: {wifi.get('rows_sec')}")
            print(f"Rows total: {wifi.get('rows_total')}")
            print(f"Aged GPS: {wifi.get('gps_age')}")
        else:
            print("NO WIFI DATA")

        print("\n(Refresh every 1 second)")
        time.sleep(1)


if __name__ == "__main__":
    main()
