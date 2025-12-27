SQLite version 3.40.1 2022-12-28 14:03:47
Enter ".help" for usage hints.
sqlite> .schema
CREATE TABLE vendor_lookup (oui TEXT PRIMARY KEY, vendor TEXT);
CREATE TABLE side_observations (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    bssid TEXT NOT NULL,
    left_rssi INTEGER,
    right_rssi INTEGER,
    gps_lat REAL,
    gps_lon REAL,
    gps_alt REAL
);
CREATE TABLE resolved_locations (
    id INTEGER PRIMARY KEY,
    bssid TEXT NOT NULL,
    ssid TEXT,
    est_lat REAL,
    est_lon REAL,
    est_alt REAL,
    accuracy_m REAL,
    sample_count INTEGER,
    last_seen_ts TEXT
);
CREATE TABLE wifi_captures (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    bssid TEXT NOT NULL,
    ssid TEXT,
    sample_count INTEGER,
    median_rssi INTEGER,
    avg_rssi REAL,
    dominant_channel INTEGER,
    frequency_mhz INTEGER,
    est_lat REAL,
    est_lon REAL,
    est_alt REAL,
    accuracy_m REAL,
    left_rssi INTEGER,
    right_rssi INTEGER,
    differential INTEGER,
    side TEXT,
    side_confidence REAL,
    gps_lat_min REAL,
    gps_lat_max REAL,
    gps_lon_min REAL,
    gps_lon_max REAL,
    last_seen_ts TEXT
, gps_ts_utc    TEXT, gps_track_deg REAL, gps_speed_mps REAL);
CREATE TABLE wifi_ap_position(bssid TEXT PRIMARY KEY, lat REAL, lon REAL, err_m REAL, last_seen_utc REAL, ssid TEXT);
CREATE TABLE ap_locations (
    bssid           TEXT PRIMARY KEY,
    ssid            TEXT,
    lat             REAL,
    lon             REAL,
    confidence      INTEGER CHECK(confidence BETWEEN 0 AND 100),
    side            TEXT CHECK(side IN ('LEFT','RIGHT','OMNI')),
    rssi            INTEGER,
    channel         INTEGER,
    samples_used    INTEGER,
    last_seen_ts    REAL,
    updated_ts      REAL
, samples INTEGER DEFAULT 0);
CREATE INDEX idx_sideobs_bssid ON side_observations(bssid);
CREATE INDEX idx_sideobs_ts ON side_observations(ts_utc);
CREATE INDEX idx_wificap_bssid ON wifi_captures(bssid);
CREATE INDEX idx_wificap_ts ON wifi_captures(ts_utc);
