-- SQLite schema for Wi-Fi Multi-Probe Mapper

CREATE TABLE IF NOT EXISTS wifi_captures (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,            -- UTC timestamp (ISO8601 with ms, PPS disciplined)
    node_id INTEGER NOT NULL,        -- 1..12
    channel INTEGER NOT NULL,        -- 1..12
    frequency_mhz INTEGER NOT NULL,
    bssid TEXT NOT NULL,
    ssid TEXT,
    rssi_dbm INTEGER NOT NULL,
    beacon_interval_ms INTEGER,
    gps_lat REAL,
    gps_lon REAL,
    gps_alt_m REAL,
    gps_speed_mps REAL,
    gps_track_deg REAL,
    pps_locked INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bssid ON wifi_captures(bssid);
CREATE INDEX IF NOT EXISTS idx_ts ON wifi_captures(ts_utc);
CREATE INDEX IF NOT EXISTS idx_node_ts ON wifi_captures(node_id, ts_utc);
