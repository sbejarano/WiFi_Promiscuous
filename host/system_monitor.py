# system_monitor.py  (writes tmp/system.json; NO DB)
#!/usr/bin/env python3
import os
import time
import json
import shutil

BASE = "/media/sbejarano/Developer1/wifi_promiscuous"
OUT  = f"{BASE}/tmp/system.json"

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)

def read_cpu_temp_c():
    # Pi OS common
    for p in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            with open(p) as f:
                v = int(f.read().strip())
                return v / 1000.0
        except Exception:
            pass
    return None

def read_loadavg():
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
            return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        return None

def read_mem():
    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])  # kB
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used = max(total - avail, 0)
        return {"total_kb": total, "used_kb": used, "avail_kb": avail}
    except Exception:
        return None

def main():
    while True:
        du = shutil.disk_usage(BASE)
        payload = {
            "ts": time.time(),
            "loadavg": read_loadavg(),
            "mem": read_mem(),
            "disk": {
                "path": BASE,
                "total_bytes": du.total,
                "used_bytes": du.used,
                "free_bytes": du.free
            },
            "cpu_temp_c": read_cpu_temp_c()
        }
        atomic_write_json(OUT, payload)
        time.sleep(1.0)

if __name__ == "__main__":
    main()
