# Run with defaults (last 60 minutes):
./scripts/trilaterate.sh

# Or: last 30 minutes, quieter output
./scripts/trilaterate.sh --minutes 30 --quiet

# Or: target a specific BSSID
./scripts/trilaterate.sh --minutes 120 --bssid 1C:8B:76:8F:89:DB

# Custom path-loss model
./scripts/trilaterate.sh --p0 -42 --n 2.0
It will write something like:

bash
Copy code
~/wifi_promiscuous/geojson/trilateration_20250908_031415.geojson
Each feature’s properties includes confidence_pct and cov_R95_m. If you want the confidence scaling tighter/looser, tweak --conf-scale (smaller → stricter, larger → more forgiving).
