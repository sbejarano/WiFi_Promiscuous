#include <Arduino.h>
#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

/* ================= USER CONFIG ====================== */

#define NODE_NAME   "RIGHT"        // "LEFT" or "RIGHT"
#define SERIAL_BAUD 115200
#define SCAN_DELAY  100            // ms between full sweeps
#define INCLUDE_HIDDEN false

// ESP32-S3 Dev Module
#define LED_PIN     48
#define LED_COUNT   1

/* =================================================== */

// ---------- RGB LED ----------
Adafruit_NeoPixel led(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// ---------- RING BUFFER ----------
struct ScanRec {
  uint64_t esp_us;        // monotonic µs (esp_timer)
  uint32_t sweep_id;
  uint32_t sample_id;
  uint8_t  ch;
  int8_t   rssi;
  char     bssid[18];
  char     ssid[33];
};

#define RING_SIZE 256
static ScanRec ring[RING_SIZE];
static volatile uint16_t head = 0, tail = 0;

static uint32_t sweep_counter  = 0;
static uint32_t sample_counter = 0;

bool ringFull()  { return ((head + 1U) % RING_SIZE) == tail; }
bool ringEmpty() { return head == tail; }

void ringPush(const ScanRec &r) {
  if (!ringFull()) {
    ring[head] = r;
    head = (head + 1U) % RING_SIZE;
  }
}

bool ringPop(ScanRec &r) {
  if (ringEmpty()) return false;
  r = ring[tail];
  tail = (tail + 1U) % RING_SIZE;
  return true;
}

// ---------- LED HELPERS ----------
inline void ledSet(uint8_t r, uint8_t g, uint8_t b) {
  led.setPixelColor(0, led.Color(r, g, b));
  led.show();
}

// brief non-blocking pulse
void ledPulseGreen() {
  ledSet(0, 40, 0);
  delay(30);
  ledSet(0, 0, 0);
}

/* ==================================================== */
/* TASK: Wi-Fi sweep scanning (Core 0)                  */
/* ==================================================== */
void wifiTask(void *pv) {

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(100);

  for (;;) {

    sweep_counter++;
    sample_counter = 0;

    ledPulseGreen();

    int n = WiFi.scanNetworks(false, INCLUDE_HIDDEN);
    uint64_t sweep_ts_us = esp_timer_get_time();

    if (n < 0) {
      ledSet(255, 0, 0);
      Serial.printf(
        "{\"node\":\"%s\",\"error\":\"scan_failed\",\"esp_us\":%llu}\n",
        NODE_NAME, sweep_ts_us
      );
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }

    ledSet(0, 0, 40);

    for (int i = 0; i < n; i++) {

      if (!INCLUDE_HIDDEN && WiFi.SSID(i).isEmpty())
        continue;

      ScanRec rec;
      rec.esp_us    = esp_timer_get_time();
      rec.sweep_id  = sweep_counter;
      rec.sample_id = ++sample_counter;
      rec.ch        = WiFi.channel(i);
      rec.rssi      = WiFi.RSSI(i);

      strncpy(rec.ssid, WiFi.SSID(i).c_str(), 32);
      rec.ssid[32] = '\0';

      snprintf(rec.bssid, sizeof(rec.bssid),
               "%s", WiFi.BSSIDstr(i).c_str());

      ringPush(rec);
    }

    WiFi.scanDelete();
    ledSet(0, 0, 0);

    vTaskDelay(pdMS_TO_TICKS(SCAN_DELAY));
  }
}

/* ==================================================== */
/* TASK: Serial output (Core 1)                          */
/* ==================================================== */
void serialTask(void *pv) {

  Serial.printf(
    "{\"node\":\"%s\",\"status\":\"ready\"}\n",
    NODE_NAME
  );

  for (;;) {
    ScanRec rec;
    if (ringPop(rec)) {
      Serial.printf(
        "{\"node\":\"%s\","
        "\"esp_us\":%llu,"
        "\"sweep\":%lu,"
        "\"sample\":%lu,"
        "\"ch\":%d,"
        "\"rssi\":%d,"
        "\"bssid\":\"%s\","
        "\"ssid\":\"%s\"}\n",
        NODE_NAME,
        rec.esp_us,
        rec.sweep_id,
        rec.sample_id,
        rec.ch,
        rec.rssi,
        rec.bssid,
        rec.ssid
      );
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

/* ==================================================== */
void setup() {

  Serial.begin(SERIAL_BAUD);
  while (!Serial) {}   // <<< ONLY ADDITION — REQUIRED FOR ESP32-S3 CDC

  led.begin();
  led.clear();
  led.show();
  ledSet(0, 0, 20);

  xTaskCreatePinnedToCore(
    wifiTask, "wifiTask",
    12288, NULL, 2, NULL, 0
  );

  xTaskCreatePinnedToCore(
    serialTask, "serialTask",
    8192, NULL, 1, NULL, 1
  );
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(100));
}
