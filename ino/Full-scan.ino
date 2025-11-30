#include <Arduino.h>
#include "WiFi.h"

// =====================================================
// USER CONFIG
// =====================================================
#define NODE_NAME   "LEFT"         // Change to "RIGHT" on the other ESP32
#define DWELL_MS    500            // Dwell time per channel
#define BAUDRATE    115200
#define MIN_RSSI    -95            // Ignore ultra-weak
#define MAX_CH      14             // Channels 1–14 on ESP32-S3

// =====================================================
// INTERNAL CONFIG
// =====================================================
wifi_country_t wifi_country_cfg = {
  .cc = "US",
  .schan = 1,
  .nchan = MAX_CH,
  .policy = WIFI_COUNTRY_POLICY_MANUAL
};

// This struct mirrors Pi expected fields
typedef struct {
  String ssid;
  uint8_t bssid[6];
  int32_t rssi;
  uint8_t primary;
} ap_record_t;


// =====================================================
// Convert MAC → string
// =====================================================
String macToString(const uint8_t *mac) {
  char buff[18];
  sprintf(buff, "%02X:%02X:%02X:%02X:%02X:%02X",
          mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(buff);
}


// =====================================================
// Scan SINGLE CHANNEL
// =====================================================
int scanChannel(uint8_t ch, std::vector<ap_record_t> &out) {
  wifi_scan_config_t cfg = {
    .ssid = NULL,
    .bssid = NULL,
    .channel = ch,
    .show_hidden = true,
    .scan_type = WIFI_SCAN_TYPE_ACTIVE,
    .scan_time = { .active = { DWELL_MS*1000, DWELL_MS*1000 } }
  };

  WiFi.scanStart(&cfg, false);  // async
  delay(DWELL_MS);

  int n = WiFi.scanGetResults();

  out.clear();
  out.reserve(n);

  for (int i = 0; i < n; i++) {
    wifi_ap_record_t r;
    if (!WiFi.getApRecord(&r)) continue;

    String ssid = String((char*)r.ssid);

    // Filtering
    if (ssid.length() == 0) continue;
    if (r.rssi < MIN_RSSI) continue;

    ap_record_t rec;
    rec.ssid = ssid;
    memcpy(rec.bssid, r.bssid, 6);
    rec.rssi = r.rssi;
    rec.primary = r.primary;

    out.push_back(rec);
  }

  WiFi.scanDelete();
  return out.size();
}


// =====================================================
// Emit results in JSON (Pi-compatible)
// =====================================================
void emitResults(uint8_t ch, const std::vector<ap_record_t> &aps) {
  uint32_t ts = millis();

  for (const auto &ap : aps) {
    String out = "{";

    out += "\"node\":\"";
    out += NODE_NAME;
    out += "\",";

    out += "\"ts\":";
    out += ts;
    out += ",";

    out += "\"ch\":";
    out += ch;
    out += ",";

    out += "\"rssi\":";
    out += ap.rssi;
    out += ",";

    out += "\"bssid\":\"";
    out += macToString(ap.bssid);
    out += "\",";

    out += "\"ssid\":\"";
    out += ap.ssid;
    out += "\"";

    out += "}";

    Serial.println(out);
  }
}


// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(BAUDRATE);
  delay(300);

  WiFi.mode(WIFI_MODE_STA);
  esp_wifi_set_promiscuous(false);

  esp_wifi_set_country(&wifi_country_cfg);

  WiFi.disconnect(true, true);
  delay(200);
}


// =====================================================
// MAIN LOOP — FULL SCAN 1→14
// =====================================================
void loop() {
  std::vector<ap_record_t> aps;

  for (uint8_t ch = 1; ch <= MAX_CH; ch++) {
    scanChannel(ch, aps);
    emitResults(ch, aps);
  }

  // Repeat forever
}
