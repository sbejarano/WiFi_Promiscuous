#include <Arduino.h>
#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

// ================= USER CONFIG ======================
#define NODE_NAME   "RIGHT"        // change to "LEFT" or "RIGHT"
#define SERIAL_BAUD 115200
#define SCAN_DELAY  100           // ms between sweeps
#define INCLUDE_HIDDEN false        // ignore hidden SSIDs
#define LED_PIN     48             // onboard RGB LED
#define LED_COUNT   1
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

#define RING_SIZE 256
static ScanRec ring[RING_SIZE];
static volatile uint16_t head = 0, tail = 0;

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
void ledSet(uint8_t r, uint8_t g, uint8_t b) {
  led.setPixelColor(0, led.Color(r, g, b));
  led.show();
}

void ledFlash(uint8_t r, uint8_t g, uint8_t b, int dur = 80) {
  ledSet(r,g,b);
  delay(dur);
  ledSet(0,0,0);
}

// ====================================================
// TASK: Wi-Fi scanning  (Core 0)
void wifiTask(void *pv) {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(100);

  for (;;) {

    // 🔵 BLINK ONCE PER FULL 14-CHANNEL SWEEP
    ledFlash(0, 40, 0, 80);   // dim green blink per sweep

    int n = WiFi.scanNetworks(false, INCLUDE_HIDDEN);
    uint32_t now = millis();

    if (n < 0) {
      ledSet(255,0,0);        // red = error
      Serial.printf("{\"node\":\"%s\",\"error\":\"scan_failed\"}\n", NODE_NAME);
      vTaskDelay(pdMS_TO_TICKS(2000));
      continue;
    }

    ledSet(0,80,0);           // on while parsing

    for (int i=0; i<n; i++) {
      if (!INCLUDE_HIDDEN && WiFi.SSID(i).isEmpty())
        continue;

      ScanRec rec;
      rec.ts   = now;
      rec.ch   = WiFi.channel(i);
      rec.rssi = WiFi.RSSI(i);
      strncpy(rec.ssid, WiFi.SSID(i).c_str(), 32);
      rec.ssid[32] = '\0';
      snprintf(rec.bssid,sizeof(rec.bssid), "%s", WiFi.BSSIDstr(i).c_str());

      ringPush(rec);
    }

    WiFi.scanDelete();
    ledSet(0,0,0);            // LED off during idle

    vTaskDelay(pdMS_TO_TICKS(SCAN_DELAY));
  }
}

// ====================================================
// TASK: Serial output  (Core 1)
void serialTask(void *pv) {
  Serial.printf("{\"node\":\"%s\",\"status\":\"ready\"}\n", NODE_NAME);

  for (;;) {
    ScanRec rec;
    if (ringPop(rec)) {
      Serial.printf(
        "{\"node\":\"%s\",\"ts\":%lu,\"ch\":%d,"
        "\"rssi\":%d,\"bssid\":\"%s\",\"ssid\":\"%s\"}\n",
        NODE_NAME, rec.ts, rec.ch,
        rec.rssi, rec.bssid, rec.ssid
      );
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

// ====================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(400);
  Serial.println("\n--- ESP32-S3 WiFi Sweep Scanner (LEFT/RIGHT) ---");

  led.begin();
  led.clear();
  led.show();
  ledSet(0,0,20);               // dim blue = booting

  // Core 0 = WiFi Scan
  xTaskCreatePinnedToCore(wifiTask, "wifiTask", 12288, NULL, 2, NULL, 0);

  // Core 1 = Serial output
  xTaskCreatePinnedToCore(serialTask, "serialTask", 8192, NULL, 1, NULL, 1);
}

void loop() { vTaskDelay(pdMS_TO_TICKS(100)); }
