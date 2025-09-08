CREATE TABLE wifi_captures (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,            -- UTC ISO8601 (ms)
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
    gps_hdop REAL,                   -- NEW
    gps_vdop REAL,                   -- NEW
    pps_locked INTEGER DEFAULT 0
);

CREATE INDEX idx_bssid  ON wifi_captures(bssid);
CREATE INDEX idx_ts     ON wifi_captures(ts_utc);
CREATE INDEX idx_node_ts ON wifi_captures(node_id, ts_utc);
