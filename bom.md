# Wi-Fi high speed scanning rig — bill of materials

## Compute

| Item | Qty | Spec / notes |
|---|---|---|
| Raspberry Pi 5 | 1 | |
| GeeekPi P33 M.2 NVMe PoE+ HAT w/ Official Active Cooler | 1 | Confirmed stack: 36mm (Pi + HAT + cooler); +30mm when X1203 mounts below = 66mm total |
| M.2 NVMe SSD | 1 | 2230 / 2242 / 2260 / 2280 supported; specific model TBD |
| X1203 power/UPS board | 1 | 85 x 68mm. 6-18V in, dual 5V out, dual BAT in |
| MakerFocus 10000mAh 3.7V LiPo battery | 2 | 112-115 x 65 x 8.8-9mm, 37Wh each (74Wh total) |
| GPS module (REYAX RYS352A or equivalent) | 1 | UART + PPS into Pi GPIO |
| GPS external antenna | 1 | |

## RF capture array

| Item | Qty | Spec / notes |
|---|---|---|
| Seeed XIAO ESP32S3 | 14 (+ spares recommended) | 21 x 17.8mm, U.FL antenna solder-jumper mod required |
| USB-A to USB-C direct-plug adapter (AIYEEN) | 14 (+ spares) | 30 x 15 x 15mm |
| 7-port USB 3.0 hub board | 2 | 43.9 x 84mm, 7x USB-A down, 1x upstream, DC5V in, ~12mm port pitch |
| SMA bulkhead connector, panel mount | 14 | Top face, two centered rows of 7 |
| U.FL to SMA pigtail cable | 14 | Length-matched via routing posts, ≥5-8mm bend radius |
| 2.4GHz antenna | 14 | External, one per node |

## Cooling

| Item | Qty | Spec / notes |
|---|---|---|
| 2510 (25x25x10mm) 12V dual ball-bearing fan | 8 active, order additional for spares | 2 intake + 2 exhaust per compartment, side-mounted (X faces), vertically stacked pairs |

## RF isolation wall

| Item | Qty | Spec / notes |
|---|---|---|
| Aluminum plate, 2-4mm | 1 | Wavewall, chassis-grounded around full perimeter |
| Waveguide-below-cutoff tube/sleeve | 4 | 27mm diameter x 70mm effective length; 2x data, 2x power |
| Conductive gasket (foam or copper/aluminum tape) | 1 roll | Wavewall perimeter seal, bare-metal contact line |
| Ferrite choke | 4 | One per wall-crossing cable (2x USB data, 2x power) |

## Enclosure / structural

| Item | Qty | Spec / notes |
|---|---|---|
| PETG or ASA filament | — | Main shell, RF-transparent panels |
| Kevlar-reinforced filament | — | Card guide comb only — hardened/ruby nozzle required |
| M3 standoffs / screws | — | Count TBD once panel layout is finalized |

## Power / data wiring

| Item | Qty | Spec / notes |
|---|---|---|
| 20AWG+ wire | — | 12V fan bus, power feeds crossing the wavewall |
| Inline fuse or polyfuse | 2 | One per hub 5V feed off the X1203 |
| XH2.54 2-pin connector | Matching fan count | Fan wiring harness |
| Short USB-C cable | 2 | Hub uplink to Pi (crosses wavewall) |

## Open items — not yet specced

- Panel switches (top face, left/right of the SMA array)
- LEDs (top face, left/right of the SMA array)
- Exact SMA bulkhead + pigtail part numbers
- Final fastener/screw sizes once panel hardware is chosen
