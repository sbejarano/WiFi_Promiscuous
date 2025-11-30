#include <Arduino.h>
#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

// ================= USER CONFIG ======================
#define NODE_NAME     "LEFT"         // "LEFT" or "RIGHT"
#define SERIAL_BAUD   115200

#define DWELL_MS      500            // time per channel
#define SCAN_DELAY    0              // no global delay, channel sweep handles pacing
#define IGNORE_HIDDEN true
#define LED_PIN       48
#define LED_COUNT     1
// ====================================================

// ---------- RGB LED ----------
Adafruit_NeoPixel led(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// ---------- RING BUFFER ----------
struct ScanRec {
  uint32_t ts;
  uint8_t  ch;
  int8_t   rssi;
  char     bssid[18];
  char     ssid[33];
};

#define RING_SIZE 512
static ScanRec ring[RING_SIZE];
static volatile uint16_t head = 0, tail = 0;

bool ringFull()  { return ((head + 1U) % RING_SIZE) == tail; }
bool ringEmpty() { return head == tail; }

void ringPush(const ScanRec &rec) {
  if (!ringFull()) {
    ring[head] = rec;
    head = (head + 1U) % RING_SIZE;
  }
}

bool ringPop(ScanRec &rec) {
  if (ringEmpty()) return false;
  rec = ring[tail];
  tail = (tail + 1U) % RING_SIZE;
  return true;
}

// ---------- LED ----------
void ledSet(uint8_t r, uint8_t g, uint8_t b) {
  led.setPixelColor(0, led.Color(r, g, b));
  led.show();
}

void ledFlash(uint8_t r, uint8_t g, uint8_t b, int dur = 60) {
  ledSet(r,g,b);
  delay(dur);
  ledSet(0,0,0);
}

// ======================================================
// Task 1: Wi-Fi scanning (Core 0) — CHANNEL BY CHANNEL
// ======================================================
void wifiTask(void *pv) {

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(150);

  wifi_country_t country = {
    .cc = "US",
    .schan = 1,
    .nchan = 14,
    .policy = WIFI_COUNTRY_POLICY_MANUAL
  };
  esp_wifi_set_country(&country);

  for (;;) {
    uint32_t now = millis();

    for (int ch = 1; ch <= 14; ch++) {

      ledFlash(0, 40, 0, 40);   // low green flash per channel

      // Scan a single channel
      wifi_scan_config_t cfg = {
        .ssid = NULL,
        .bssid = NULL,
        .channel = (uint8_t)ch,
        .show_hidden = true,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time = { .active = { DWELL_MS*1000UL, DWELL_MS*1000UL } }
      };

      WiFi.scanStart(&cfg, false);
      delay(DWELL_MS);

      int n = WiFi.scanGetResults();

      if (n < 0) {
        WiFi.scanDelete();
        continue;
      }

      for (int i = 0; i < n; i++) {
        String ssid = WiFi.SSID(i);

        if (IGNORE_HIDDEN && ssid.length() == 0)
          continue;

        ScanRec rec;
        rec.ts = now;
        rec.ch = ch;
        rec.rssi = WiFi.RSSI(i);

        snprintf(rec.bssid, sizeof(rec.bssid), "%s", WiFi.BSSIDstr(i).c_str());
        strncpy(rec.ssid, ssid.c_str(), 32);
        rec.ssid[32] = '\0';

        ringPush(rec);
      }

      WiFi.scanDelete();
    }
  }
}



// ======================================================
// Task 2: Serial output (Core 1)
// ======================================================
void serialTask(void *pv) {
  Serial.printf("{\"node\":\"%s\",\"status\":\"ready\"}\n", NODE_NAME);

  for (;;) {
    ScanRec r;

    if (ringPop(r)) {
      Serial.printf(
        "{\"node\":\"%s\",\"ts\":%lu,\"ch\":%d,"
        "\"rssi\":%d,\"bssid\":\"%s\",\"ssid\":\"%s\"}\n",
        NODE_NAME, r.ts, r.ch, r.rssi, r.bssid, r.ssid
      );
    } else {
      vTaskDelay(pdMS_TO_TICKS(3));
    }
  }
}



// ======================================================
// SETUP + LOOP
// ======================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) delay(10);

  led.begin();
  led.clear();
  led.show();
  ledSet(0,0,20);   // dim blue on boot

  xTaskCreatePinnedToCore(wifiTask,   "wifiTask",   12288, NULL, 2, NULL, 0);
  xTaskCreatePinnedToCore(serialTask, "serialTask",  8192, NULL, 1, NULL, 1);
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}
