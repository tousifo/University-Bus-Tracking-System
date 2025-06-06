#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "esp_camera.h"
#include <TinyGPS++.h>
#include <SoftwareSerial.h>
#include <ArduinoJson.h>

// WiFi and Server Configuration
const char* ssid = "cou_bus";
const char* password = "11235813";
const char* serverName = "https://bus.roboict.com";
const int serverPort = 443;
const char* gpsEndpoint = "/api/gps";
const char* streamEndpoint = "/api/stream";

// Timing Configuration
const unsigned long GPS_UPDATE_INTERVAL = 500;
const int WIFI_RETRY_DELAY = 5000;
const int HTTP_RETRY_COUNT = 3;
unsigned long lastGPSUpdate = 0;

// Camera Configuration - AI Thinker
#define CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Global Objects
TinyGPSPlus gps;
WiFiClientSecure client;
const String serverUrl = serverName;

// Root CA Certificate
const char* rootCACertificate = R"(
-----BEGIN CERTIFICATE-----
MIIEVzCCAj+gAwIBAgIRALBXPpFzlydw27SHyzpFKzgwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMjQwMzEzMDAwMDAw
WhcNMjcwMzEyMjM1OTU5WjAyMQswCQYDVQQGEwJVUzEWMBQGA1UEChMNTGV0J3Mg
RW5jcnlwdDELMAkGA1UEAxMCRTYwdjAQBgcqhkjOPQIBBgUrgQQAIgNiAATZ8Z5G
h/ghcWCoJuuj+rnq2h25EqfUJtlRFLFhfHWWvyILOR/VvtEKRqotPEoJhC6+QJVV
6RlAN2Z17TJOdwRJ+HB7wxjnzvdxEP6sdNgA1O1tHHMWMxCcOrLqbGL0vbijgfgw
gfUwDgYDVR0PAQH/BAQDAgGGMB0GA1UdJQQWMBQGCCsGAQUFBwMCBggrBgEFBQcD
ATASBgNVHRMBAf8ECDAGAQH/AgEAMB0GA1UdDgQWBBSTJ0aYA6lRaI6Y1sRCSNsj
v1iU0jAfBgNVHSMEGDAWgBR5tFnme7bl5AFzgAiIyBpY9umbbjAyBggrBgEFBQcB
AQQmMCQwIgYIKwYBBQUHMAKGFmh0dHA6Ly94MS5pLmxlbmNyLm9yZy8wEwYDVR0g
BAwwCjAIBgZngQwBAgEwJwYDVR0fBCAwHjAcoBqgGIYWaHR0cDovL3gxLmMubGVu
Y3Iub3JnLzANBgkqhkiG9w0BAQsFAAOCAgEAfYt7SiA1sgWGCIpunk46r4AExIRc
MxkKgUhNlrrv1B21hOaXN/5miE+LOTbrcmU/M9yvC6MVY730GNFoL8IhJ8j8vrOL
pMY22OP6baS1k9YMrtDTlwJHoGby04ThTUeBDksS9RiuHvicZqBedQdIF65pZuhp
eDcGBcLiYasQr/EO5gxxtLyTmgsHSOVSBcFOn9lgv7LECPq9i7mfH3mpxgrRKSxH
pOoZ0KXMcB+hHuvlklHntvcI0mMMQ0mhYj6qtMFStkF1RpCG3IPdIwpVCQqu8GV7
s8ubknRzs+3C/Bm19RFOoiPpDkwvyNfvmQ14XkyqqKK5oZ8zhD32kFRQkxa8uZSu
h4aTImFxknu39waBxIRXE4jKxlAmQc4QjFZoq1KmQqQg0J/1JF8RlFvJas1VcjLv
YlvUB2t6npO6oQjB3l+PNf0DpQH7iUx3Wz5AjQCi6L25FjyE06q6BZ/QlmtYdl/8
ZYao4SRqPEs/6cAiF+Qf5zg2UkaWtDphl1LKMuTNLotvsX99HP69V2faNyegodQ0
LyTApr/vT01YPE46vNsDLgK+4cL6TrzC/a4WcmF5SRJ938zrv/duJHLXQIku5v0+
EwOy59Hdm0PT/Er/84dDV0CSjdR/2XuZM3kpysSKLgD1cKiDA+IRguODCxfO9cyY
Ig46v9mFmBvyH04=
-----END CERTIFICATE-----
)";


bool ensureWiFiConnection() {
  if (WiFi.isConnected()) return true;
  
  Serial.println("WiFi disconnected. Reconnecting...");
  WiFi.disconnect();
  WiFi.begin(ssid, password);
  
  unsigned long startAttemptTime = millis();
  while (WiFi.status() != WL_CONNECTED && 
         millis() - startAttemptTime < WIFI_RETRY_DELAY) {
    delay(100);
  }
  
  return WiFi.isConnected();
}

void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count = 2;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }
  Serial.println("Camera initialized successfully");
}

bool sendGPSData() {
  if (!ensureWiFiConnection()) return false;
  if (!gps.location.isValid()) return false;
  
  for (int i = 0; i < HTTP_RETRY_COUNT; i++) {
    HTTPClient https;
    if (!https.begin(client, serverUrl + gpsEndpoint)) {
      Serial.println("HTTPS setup failed");
      delay(1000);
      continue;
    }
    
    https.addHeader("Content-Type", "application/json");
    String jsonData = "{\"lat\":" + String(gps.location.lat(), 6) + 
                     ",\"lng\":" + String(gps.location.lng(), 6) + 
                     ",\"alt\":" + String(gps.altitude.meters()) + 
                     ",\"speed\":" + String(gps.speed.kmph()) + 
                     ",\"satellites\":" + String(gps.satellites.value()) + "}";
    
    int httpCode = https.POST(jsonData);
    https.end();
    
    if (httpCode == HTTP_CODE_OK) return true;
    
    Serial.printf("HTTP Error: %d (Attempt %d/%d)\n", 
                 httpCode, i + 1, HTTP_RETRY_COUNT);
    delay(1000);
  }
  return false;
}

bool sendVideoFrame() {
  if (!ensureWiFiConnection()) return false;
  
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    return false;
  }
  
  bool success = false;
  for (int i = 0; i < HTTP_RETRY_COUNT && !success; i++) {
    HTTPClient https;
    if (!https.begin(client, serverUrl + streamEndpoint)) {
      Serial.println("HTTPS setup failed");
      delay(1000);
      continue;
    }
    
    https.addHeader("Content-Type", "image/jpeg");
    int httpCode = https.POST(fb->buf, fb->len);
    https.end();
    
    if (httpCode == HTTP_CODE_OK) {
      success = true;
    } else {
      Serial.printf("HTTP Error: %d (Attempt %d/%d)\n", 
                   httpCode, i + 1, HTTP_RETRY_COUNT);
      delay(1000);
    }
  }
  
  esp_camera_fb_return(fb);
  return success;
}

void setup() {
  Serial.begin(9600);
  
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (!ensureWiFiConnection()) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nWiFi connected: " + WiFi.localIP().toString());

  client.setCACert(rootCACertificate);
  setupCamera();
}

void loop() {
  // Update GPS data
  while (Serial.available() > 0) {
    gps.encode(Serial.read());
  }

  // Send GPS data at specified interval
  if (millis() - lastGPSUpdate >= GPS_UPDATE_INTERVAL) {
    if (sendGPSData()) {
      Serial.println("GPS data sent successfully");
    }
    lastGPSUpdate = millis();
  }

  // Send video frame
  if (sendVideoFrame()) {
    Serial.println("Frame sent successfully");
  }
  
  delay(100);  // Prevent overwhelming the server
}