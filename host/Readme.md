# Caveats and Problems

This document captures the **actual failure modes**, root causes, and the configuration decisions that resolved them. It is written as a post‑mortem and reference so the same issues are not reintroduced later.

---

## What Was Actually Going Wrong (Root Causes)

There were **three independent mechanisms** fighting each other on the same UART GNSS device, plus one internal receiver state issue.

---

### 1. gpsd Socket Activation + UART GNSS = Deadlock

* `gpsd.socket` was enabled
* systemd started `gpsd` **on demand** via socket activation
* gpsd waited for "valid enough" data before signaling **READY**
* Because of **PPS + no fix (mode=1) + continuous UART streaming**, gpsd never reached READY
* systemd waited → **timeout** → retry → loop

This is a **known gpsd failure mode** on embedded UART GNSS systems.

> Cold boot appeared to work only due to **race timing**, not because the configuration was correct.

---

### 2. Forking Service Type Was Wrong

* Default gpsd runs as `Type=forking`
* systemd expects a fork + parent exit
* gpsd stayed attached to the UART and PPS
* systemd believed startup never completed

Result:

* gpsd was **running**
* systemd treated it as **still starting** (`activating` forever)

---

### 3. Mixing Data Mode and Control Mode on One UART

* GNSS was streaming NMEA continuously
* Multiple tools touched `/dev/serial0`:

  * gpsd
  * gpspipe
  * minicom
  * manual AT commands

AT commands were:

* ignored
* interleaved with NMEA
* or blocked by file descriptor ownership

> The GNSS was **not locked** — it was simply **busy and streaming**.

---

### 4. GNSS Internal State Got Wedged

* Receiver accepted a **UBX reset**
* That reset **disabled NMEA output**
* gpsd then waited forever for data that never arrived
* Manual NMEA re‑enable fixed it

This explains why:

* cold reboot "fixed" the problem
* warm restarts did not

---

## Why the Final Configuration Works

Four critical corrections were made.

---

### 1. Socket Activation Disabled

* gpsd now starts **only when explicitly requested**
* no race condition
* no socket deadlock

---

### 2. Forced `Type=simple`

* systemd tracks the **real gpsd process**
* no phantom "activating" state
* no startup timeout

---

### 3. Hard‑Coded Devices

* no USB probing
* no tty discovery
* no waiting on nonexistent hardware
* **deterministic startup every time**

---

### 4. Stabilized GNSS Output

* NMEA explicitly re‑enabled
* configuration saved to GNSS flash
* no silent state after reset

---

## Fixed ESP32 Device Naming (No Discovery)

### Current Device Map

```text
ls -l /dev/esp-*

/dev/esp-left   -> ttyACM10
/dev/esp-right  -> ttyACM0
/dev/esp-node1  -> ttyACM6
/dev/esp-node2  -> ttyACM13
/dev/esp-node3  -> ttyACM11
/dev/esp-node4  -> ttyACM7
/dev/esp-node5  -> ttyACM3
/dev/esp-node6  -> ttyACM12
/dev/esp-node7  -> ttyACM8
/dev/esp-node8  -> ttyACM4
/dev/esp-node9  -> ttyACM1
/dev/esp-node10 -> ttyACM9
/dev/esp-node11 -> ttyACM5
/dev/esp-node12 -> ttyACM2
```

---

## udev Rules – Fixed ESP32 USB JTAG / Serial Mapping

**NO DISCOVERY. NO SCANNING. NO ttyACM USAGE.**

```udev
# ============================================================
# ESP32 USB JTAG / Serial – FIXED DEVICE NAMES
# ============================================================

# -------- Directional scanners --------
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="FC:01:2C:CB:BA:14", SYMLINK+="esp-left"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="FC:01:2C:CB:BC:CC", SYMLINK+="esp-right"

# -------- Fixed scanners --------
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:50:A8", SYMLINK+="esp-node1"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:F6:D7:AC", SYMLINK+="esp-node2"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FA:12:2C", SYMLINK+="esp-node3"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:F6:D8:08", SYMLINK+="esp-node4"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:4F:04", SYMLINK+="esp-node5"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:F6:D8:10", SYMLINK+="esp-node6"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:5E:54", SYMLINK+="esp-node7"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:57:74", SYMLINK+="esp-node8"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:50:9C", SYMLINK+="esp-node9"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FA:0C:70", SYMLINK+="esp-node10"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FA:12:1C", SYMLINK+="esp-node11"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="B8:F8:62:FB:56:2C", SYMLINK+="esp-node12"
```

---

## Why Satellites Appeared Later (Mode 1 → Mode 2/3)

This behavior is expected and explained by **GNSS acquisition physics and receiver state**, not by Linux or gpsd instability.

### What Happened Internally

1. **Repeated GNSS resets wiped ephemeris/almanac**

   * UBX resets clear satellite knowledge
   * Receiver becomes effectively blind
   * NMEA, time, and PPS still function
   * gpsd reports `mode = 1`

2. **Timing can stabilize before navigation**

   * PPS does *not* require a position fix
   * Time-only solutions are valid
   * chrony can lock PPS while gpsd remains in mode 1

3. **Service churn prevented acquisition**

   * gpsd restarts
   * socket activation loops
   * UART contention
   * Each interruption delayed ephemeris download

4. **After stabilization, ephemeris download completed**

   * Continuous power
   * Continuous UART access
   * Continuous sky view
   * Satellites appeared suddenly
   * gpsd transitioned to mode 2/3

> GNSS requires **uninterrupted time** after a cold start. The final configuration allowed that to happen.

---

## Working GPS + PPS Service Flow

> **Note:** This document uses Mermaid diagrams. If your Markdown renderer does not support Mermaid, an ASCII fallback is provided below each diagram.

```mermaid
flowchart TD
    GNSS[GNSS Receiver]
    UART[/dev/serial0
NMEA]
    PPS[/dev/pps0
PPS]

    gpsd[gpsd.service
(Type=simple)]
    chrony[chronyd]

    apps[Consumers
(gpspipe, python)]

    GNSS --> UART --> gpsd --> apps
    GNSS --> PPS --> chrony
    gpsd --> chrony
```

**Key properties:**

* Single owner of UART (gpsd)
* PPS isolated from NMEA traffic
* No socket activation
* Deterministic startup

---

## devices.yaml and udev Integration

### Purpose of `devices.yaml`

`devices.yaml` provides a **logical identity layer** for ESP32 Wi-Fi scanners:

* Maps physical devices to semantic roles
* Decouples software logic from kernel-assigned names
* Enables stable node identity across reboots

Example concepts:

* Fixed scanners: `node1` … `node12`
* Directional scanners: `LEFT`, `RIGHT`

---

### Role of udev Serial Rules

udev rules convert **USB serial numbers** into **stable device paths**:

* `/dev/esp-node1`
* `/dev/esp-left`
* `/dev/esp-right`

This eliminates:

* ttyACM enumeration variance
* discovery logic
* race conditions at boot

---

### Combined Architecture Impact

```mermaid
flowchart TD
    USB[ESP32 USB Devices]
    udev[udev Rules
(serial → name)]
    devs[/dev/esp-*]
    yaml[devices.yaml
logical mapping]
    broker[broker.py]

    USB --> udev --> devs --> broker
    yaml --> broker
```

**ASCII fallback:**

```
ESP32 USB Devices
        |
      udev
 (serial → name)
        |
    /dev/esp-*
        |
   broker.py <--- devices.yaml
```

**Result:**

* No scanning
* No probing
* No ambiguity
* Appliance-grade determinism

---

## Final Rule (Do Not Break This)

> **Never mix GNSS data streaming and control commands on the same UART at the same time.**

If control commands are required:

1. Stop gpsd
2. Send commands
3. Restart gpsd

This is not a workaround — it is correct design.
