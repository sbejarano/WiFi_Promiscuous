#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <ArduinoJson.h>

/* ===================== CONFIG ===================== */

#define WIFI_CHANNEL        1        // Fixed per node
#define NODE_ID             1        // Unique per ESP32 (1–12)
#define SERIAL_BAUD         115200
#define SCAN_EPOCH_MS       1000     // 1-second logical scan window
#define FILTER_BEACONS_ONLY false

// XIAO ESP32S3 Yellow User LED is GPIO21, active-low (LOW=ON, HIGH=OFF)
#define USER_LED_PIN        21
#define LED_ON_LEVEL        LOW
#define LED_OFF_LEVEL       HIGH

// Blink behavior when packets are seen
#define LED_PULSE_US        30000    // 30ms blink

/* ===================== DATA STRUCT ===================== */

typedef struct {
  uint64_t esp_us;          // esp_timer_get_time()
  int8_t   rssi;
  uint8_t  channel;
  uint8_t  bssid[6];
  char     ssid[33];
  char     frame_type[20];
} wifi_packet_t;

/* ===================== GLOBALS ===================== */

QueueHandle_t packetQueue;

static uint32_t scan_cycle = 0;
static uint32_t sample_seq = 0;

// Non-blocking LED pulse control
static volatile uint64_t led_on_until_us = 0;

/* ===================== HELPERS ===================== */

const char* getSubtypeName(uint8_t subtype) {
  switch (subtype) {
    case 0x08: return "Beacon";
    case 0x04: return "Probe Request";
    case 0x05: return "Probe Response";
    case 0x00: return "Assoc Req";
    case 0x01: return "Assoc Resp";
    default:   return "Other";
  }
}

void extractSSID(const uint8_t *payload, size_t len, char *ssid) {
  ssid[0] = '\0';
  size_t pos = 0;

  while (pos + 2 < len) {
    uint8_t tag     = payload[pos];
    uint8_t tag_len = payload[pos + 1];

    if (tag == 0x00) {
      if (tag_len == 0) {
        strcpy(ssid, "hidden");
      } else {
        size_t n = (tag_len < 32) ? tag_len : 32;
        memcpy(ssid, payload + pos + 2, n);
        ssid[n] = '\0';
      }
      return;
    }
    pos += tag_len + 2;
  }

  strcpy(ssid, "hidden");
}

static inline void pulseUserLedNow(uint64_t now_us) {
  // Turn LED on immediately, keep on for LED_PULSE_US after last packet
  digitalWrite(USER_LED_PIN, LED_ON_LEVEL);
  led_on_until_us = now_us + LED_PULSE_US;
}

static inline void serviceUserLed(uint64_t now_us) {
  if (led_on_until_us != 0 && now_us >= led_on_until_us) {
    digitalWrite(USER_LED_PIN, LED_OFF_LEVEL);
    led_on_until_us = 0;
  }
}

/* ===================== PROMISCUOUS CALLBACK ===================== */

void wifi_sniffer(void *buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT) return;

  const wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)buf;
  const uint8_t *payload = pkt->payload;

  uint8_t frame_ctrl = payload[0];
  uint8_t subtype = (frame_ctrl >> 4) & 0x0F;

  if (FILTER_BEACONS_ONLY && subtype != 0x08) return;

  wifi_packet_t p;
  p.esp_us  = esp_timer_get_time();
  p.rssi    = pkt->rx_ctrl.rssi;
  p.channel = pkt->rx_ctrl.channel;

  memcpy(p.bssid, payload + 10, 6);
  strncpy(p.frame_type, getSubtypeName(subtype), sizeof(p.frame_type));

  extractSSID(payload + 36, pkt->rx_ctrl.sig_len - 36, p.ssid);

  xQueueSendFromISR(packetQueue, &p, NULL);
}

/* ===================== WIFI INIT ===================== */

void wifiInitFixedChannel(uint8_t channel) {
  WiFi.mode(WIFI_OFF);
  delay(100);

  esp_wifi_stop();
  esp_wifi_deinit();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&cfg);

  esp_wifi_set_mode(WIFI_MODE_NULL);
  esp_wifi_start();

  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);

  wifi_country_t country = {
    .cc     = "US",
    .schan  = 1,
    .nchan  = 13,
    .policy = WIFI_COUNTRY_POLICY_MANUAL
  };
  esp_wifi_set_country(&country);

  wifi_promiscuous_filter_t filter = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT };
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(&wifi_sniffer);
  esp_wifi_set_promiscuous(true);

  uint8_t primary;
  wifi_second_chan_t second;
  esp_wifi_get_channel(&primary, &second);

  Serial.printf("[INFO] Node %d locked on channel %d\n", NODE_ID, primary);
}

/* ===================== TASKS ===================== */

void wifiTask(void *pvParameters) {
  wifiInitFixedChannel(WIFI_CHANNEL);

  while (true) {
    scan_cycle++;
    sample_seq = 0;
    vTaskDelay(pdMS_TO_TICKS(SCAN_EPOCH_MS));
  }
}

void serialTask(void *pvParameters) {
  StaticJsonDocument<384> doc;
  wifi_packet_t pkt;

  while (true) {
    // Service LED even when idle (keeps it non-blocking)
    serviceUserLed(esp_timer_get_time());

    if (xQueueReceive(packetQueue, &pkt, pdMS_TO_TICKS(50)) == pdTRUE) {
      const uint64_t now_us = pkt.esp_us;

      // Blink LED on any captured packet presence
      pulseUserLedNow(now_us);

      sample_seq++;

      doc.clear();
      doc["node_id"]     = NODE_ID;
      doc["scan_cycle"]  = scan_cycle;
      doc["sample_seq"]  = sample_seq;
      doc["esp_us"]      = pkt.esp_us;
      doc["ssid"]        = pkt.ssid;

      char bssidStr[18];
      sprintf(bssidStr, "%02X:%02X:%02X:%02X:%02X:%02X",
              pkt.bssid[0], pkt.bssid[1], pkt.bssid[2],
              pkt.bssid[3], pkt.bssid[4], pkt.bssid[5]);

      doc["bssid"]      = bssidStr;
      doc["rssi"]       = pkt.rssi;
      doc["chan"]       = pkt.channel;
      doc["freq"]       = 2407 + pkt.channel * 5;
      doc["frame_type"] = pkt.frame_type;

      serializeJson(doc, Serial);
      Serial.println();

      // Keep LED timing accurate even with bursts
      serviceUserLed(esp_timer_get_time());
    }
  }
}

/* ===================== SETUP / LOOP ===================== */

void setup() {
  Serial.begin(SERIAL_BAUD);

  pinMode(USER_LED_PIN, OUTPUT);
  digitalWrite(USER_LED_PIN, LED_OFF_LEVEL);

  packetQueue = xQueueCreate(256, sizeof(wifi_packet_t));

  xTaskCreatePinnedToCore(wifiTask, "WiFiTask", 4096, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(serialTask, "SerialTask", 4096, NULL, 1, NULL, 1);

  Serial.printf("[INFO] ESP32-S3 Node %d Initialized (Channel %d)\n", NODE_ID, WIFI_CHANNEL);
}

void loop() {
  // Not used
}
