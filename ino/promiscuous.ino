#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <ArduinoJson.h>

#define WIFI_CHANNEL 12        // ← fixed per node (1–12)
#define NODE_ID 1              // ← unique per ESP32
#define SERIAL_BAUD 115200
#define FILTER_BEACONS_ONLY false

QueueHandle_t packetQueue;

typedef struct {
  uint64_t timestamp;
  int8_t rssi;
  uint8_t channel;
  uint8_t bssid[6];
  char ssid[33];
  char subtype_name[20];
} wifi_packet_t;

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
  while (pos < len - 2) {
    uint8_t tag = payload[pos];
    uint8_t tag_len = payload[pos + 1];
    if (tag == 0x00) {
      if (tag_len == 0) strcpy(ssid, "hidden");
      else {
        size_t copy_len = (tag_len < 32) ? tag_len : 32;
        memcpy(ssid, &payload[pos + 2], copy_len);
        ssid[copy_len] = '\0';
      }
      return;
    }
    pos += tag_len + 2;
  }
  strcpy(ssid, "hidden");
}

void wifi_sniffer(void *buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT) return;

  const wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)buf;
  const uint8_t *payload = pkt->payload;

  uint8_t frame_ctrl = payload[0];
  uint8_t subtype = (frame_ctrl >> 4) & 0x0F;

  if (FILTER_BEACONS_ONLY && subtype != 0x08) return;

  wifi_packet_t p;
  p.timestamp = esp_timer_get_time();
  p.rssi = pkt->rx_ctrl.rssi;
  memcpy(p.bssid, payload + 10, 6);
  p.channel = pkt->rx_ctrl.channel;
  strncpy(p.subtype_name, getSubtypeName(subtype), sizeof(p.subtype_name));
  extractSSID(payload + 36, pkt->rx_ctrl.sig_len - 36, p.ssid);

  xQueueSendFromISR(packetQueue, &p, NULL);
}

void wifiInitFixedChannel(uint8_t channel) {
  // Disable any residual Wi-Fi tasks or connections
  WiFi.mode(WIFI_OFF);
  delay(100);

  // Low-level initialization
  esp_wifi_stop();
  esp_wifi_deinit();
  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&cfg);
  esp_wifi_set_mode(WIFI_MODE_NULL);  // Null mode avoids STA/AP auto management
  esp_wifi_start();

  // Important: Disable background scanning and connection manager
  esp_wifi_set_promiscuous(false);
  esp_wifi_set_ps(WIFI_PS_NONE);  // Disable power-save (no scan triggers)
  esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);

  // Set strict channel policy
  wifi_country_t country = {
    .cc = "US",
    .schan = 1,
    .nchan = 13,
    .policy = WIFI_COUNTRY_POLICY_MANUAL  // <- prevents auto-channel switching
  };
  esp_wifi_set_country(&country);

  // Enable promiscuous capture
  wifi_promiscuous_filter_t filter = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT };
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&wifi_sniffer);

  uint8_t primary;
  wifi_second_chan_t second;
  esp_wifi_get_channel(&primary, &second);
  Serial.printf("[INFO] Node %d locked on channel %d (requested %d)\n", NODE_ID, primary, channel);
}

void wifiTask(void *pvParameters) {
  wifiInitFixedChannel(WIFI_CHANNEL);
  while (true) vTaskDelay(portMAX_DELAY);
}

void serialTask(void *pvParameters) {
  StaticJsonDocument<256> doc;
  wifi_packet_t pkt;

  while (true) {
    if (xQueueReceive(packetQueue, &pkt, portMAX_DELAY) == pdTRUE) {
      doc.clear();
      doc["node_id"] = NODE_ID;
      doc["ts"] = pkt.timestamp / 1000000.0;
      doc["ssid"] = pkt.ssid;

      char bssidStr[18];
      sprintf(bssidStr, "%02X:%02X:%02X:%02X:%02X:%02X",
              pkt.bssid[0], pkt.bssid[1], pkt.bssid[2],
              pkt.bssid[3], pkt.bssid[4], pkt.bssid[5]);
      doc["bssid"] = bssidStr;
      doc["rssi"] = pkt.rssi;
      doc["chan"] = pkt.channel;
      doc["freq"] = 2407 + pkt.channel * 5;
      doc["frame_type"] = pkt.subtype_name;

      serializeJson(doc, Serial);
      Serial.println();
    }
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  packetQueue = xQueueCreate(100, sizeof(wifi_packet_t));

  xTaskCreatePinnedToCore(wifiTask, "WiFiTask", 4096, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(serialTask, "SerialTask", 4096, NULL, 1, NULL, 1);

  Serial.printf("[INFO] ESP32-S3 Node %d Initialized (Channel %d)\n", NODE_ID, WIFI_CHANNEL);
}

void loop() {}
