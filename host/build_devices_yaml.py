#!/usr/bin/env python3
import subprocess
import yaml
import re
import os

OUT = "/media/sbejarano/Developer1/wifi_promiscuous/host/devices.yaml"

LEFT_MAC  = "B8:F8:62:FB:56:2C"
RIGHT_MAC = "B8:F8:62:FB:50:9C"


def list_ports():
    cmd = [
        "bash", "-c",
        r'''
        for dev in /dev/ttyACM*; do
            [[ -e "$dev" ]] || continue
            sys=$(udevadm info -q path -n "$dev")
            sys="/sys$sys"

            mfr=$(cat "$sys/device/../manufacturer" 2>/dev/null)
            ser=$(cat "$sys/device/../serial" 2>/dev/null)

            printf "%s %s %s\n" "$dev" "$ser" "$mfr"
        done
        '''
    ]
    out = subprocess.check_output(cmd).decode().strip().splitlines()

    devices = []
    for line in out:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        dev, mac, mfr = parts[0], parts[1], " ".join(parts[2:])
        devices.append({
            "port": dev,
            "mac": mac,
            "manufacturer": mfr
        })
    return devices


def build_yaml(devs):
    # Identify GPS (UBLOX)
    gps = None
    for d in devs:
        if "u-blox" in d["manufacturer"]:
            gps = {
                "serial": d["mac"],
                "port": d["port"],
            }

    # Clean list of ESP32 nodes
    esp = [d for d in devs if d["mac"] and ":" in d["mac"]]

    # LEFT directional
    left_dev = next((d for d in esp if d["mac"] == LEFT_MAC), None)

    # RIGHT directional
    right_dev = next((d for d in esp if d["mac"] == RIGHT_MAC), None)

    # Build scanner list excluding directional
    scanners = []
    channel = 1
    for d in esp:
        if d["mac"] in (LEFT_MAC, RIGHT_MAC):
            continue

        scanners.append({
            "mac": d["mac"],
            "port": d["port"],
            "node_id": channel,
            "channel": channel
        })
        channel += 1

    yaml_out = {
        "gps": gps,
        "directional": {
            "left":  {
                "mac": LEFT_MAC,
                "port": left_dev["port"] if left_dev else ""
            },
            "right": {
                "mac": RIGHT_MAC,
                "port": right_dev["port"] if right_dev else ""
            }
        },
        "scanners": scanners
    }

    return yaml_out


def main():
    devs = list_ports()
    config = build_yaml(devs)

    with open(OUT, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    print("[build_devices_yaml] devices.yaml written.")


if __name__ == "__main__":
    main()
