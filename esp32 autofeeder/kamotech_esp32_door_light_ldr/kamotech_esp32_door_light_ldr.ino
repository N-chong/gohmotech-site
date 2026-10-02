/*
 * KAMOTECH ESP32 A
 * Hardware on this controller only:
 *   - LDR / indoor light sensor -> GPIO 34 (ADC1)
 *   - 4-channel relay IN1      -> GPIO 26 (door close)
 *   - 4-channel relay IN2      -> GPIO 27 (door open)
 *   - 4-channel relay IN3      -> GPIO 13 (light)
 *
 * This board intentionally does not initialize the DHT21, rain sensor,
 * ultrasonic sensor, MQ-135, feeder servo, or physical control buttons.
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "server_ca.h"

// Network configuration supplied for this installation.
const char* WIFI_SSID = "@MIRANDA";
const char* WIFI_PASSWORD = "miranda-090603";
const char* SERVER_BASE_URL = "https://gohmotech.site";

// Keep this ID unique. Django uses it to route only door/light commands here.
const char* DEVICE_ID = "gohmotech_esp32_002";
const char* DEVICE_NAME = "gohmotech Door Light LDR Controller";

// Keep the real key in ignored device_secrets.h, never in this sketch.
#if __has_include("device_secrets.h")
#include "device_secrets.h"
#else
const char* DEVICE_API_KEY = "YOUR_DEVICE_API_KEY";
#endif

#define LDR_PIN 34
#define DOOR_CLOSE_RELAY_PIN 26
#define DOOR_OPEN_RELAY_PIN 27
#define LIGHT_RELAY_PIN 13
#define STATUS_LED 2

// The installed board was physically verified as LOW-level trigger: with LOW
// on IN1/IN2 both channel LEDs were on. HIGH must therefore be the safe,
// released state. Change this only if the relay board is replaced.
// All relay writes go through setRelay() so an inactive door always releases
// both direction channels, regardless of trigger polarity.
#define RELAY_ACTIVE_LOW true
const uint8_t RELAY_ACTIVE_LEVEL = RELAY_ACTIVE_LOW ? LOW : HIGH;
const uint8_t RELAY_INACTIVE_LEVEL = RELAY_ACTIVE_LOW ? HIGH : LOW;

// Replace these with ADC measurements from the installed LDR circuit.
#define LDR_DARK_ADC 3500
#define LDR_BRIGHT_ADC 300
#define ADC_SAMPLES 16

#define SENSOR_READ_INTERVAL_MS 10000UL
#define SENSOR_SEND_INTERVAL_MS 30000UL
#define COMMAND_CHECK_INTERVAL_MS 5000UL

// Maximum time the linear motor may run for one open/close request.
// Measure the real travel time and adjust this value before normal operation.
#define DOOR_MAX_RUN_TIME_MS 10000UL

int ldrRaw = 0;
float lightLevelPercentage = 0.0f;
bool lightOn = false;
bool doorMoving = false;
unsigned long doorStartedAt = 0;
String lastDoorCommand = "";

unsigned long lastSensorRead = 0;
unsigned long lastSensorSend = 0;
unsigned long lastCommandCheck = 0;
unsigned long lastWiFiAttempt = 0;
bool clockReady = false;

WiFiClientSecure secureClient;

bool ensureClockReady() {
  if (clockReady) return true;

  configTime(0, 0, "pool.ntp.org", "time.google.com");
  struct tm timeInfo;
  clockReady = getLocalTime(&timeInfo, 10000);
  if (!clockReady) {
    Serial.println("TLS clock sync failed; will retry before the next request");
  }
  return clockReady;
}

bool beginServerRequest(HTTPClient& http, const String& url) {
  if (strcmp(DEVICE_API_KEY, "YOUR_DEVICE_API_KEY") == 0) {
    Serial.println("Device API key is not provisioned; create device_secrets.h");
    return false;
  }
  if (!ensureClockReady()) return false;

  secureClient.setCACert(GOHMOTECH_ROOT_CA);
  secureClient.setHandshakeTimeout(8);
  if (!http.begin(secureClient, url)) {
    Serial.println("Unable to initialize secure server request");
    return false;
  }
  return true;
}

void addDeviceHeaders(HTTPClient& http) {
  http.addHeader("X-GoHMotech-Device-Key", DEVICE_API_KEY);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("Connecting to WiFi ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  for (int attempt = 0; attempt < 20 && WiFi.status() != WL_CONNECTED; attempt++) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi connection failed; retrying later");
  }
}

int readAveragedAdc(int pin) {
  unsigned long total = 0;
  for (int sample = 0; sample < ADC_SAMPLES; sample++) {
    total += analogRead(pin);
    delay(2);
  }
  return total / ADC_SAMPLES;
}

void readLdr() {
  ldrRaw = readAveragedAdc(LDR_PIN);
  lightLevelPercentage = constrain(
    100.0f * (LDR_DARK_ADC - ldrRaw) / (LDR_DARK_ADC - LDR_BRIGHT_ADC),
    0.0f,
    100.0f
  );

  Serial.print("LDR: ADC ");
  Serial.print(ldrRaw);
  Serial.print(", light ");
  Serial.print(lightLevelPercentage, 1);
  Serial.println("%");
}

void sendLdrReading() {
  if (WiFi.status() != WL_CONNECTED) return;

  StaticJsonDocument<256> doc;
  doc["device_id"] = DEVICE_ID;
  doc["device_name"] = DEVICE_NAME;
  doc["light_raw"] = ldrRaw;
  doc["light_level_percentage"] = lightLevelPercentage;

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  String url = String(SERVER_BASE_URL) + "/iot/api/sensor-readings/";
  if (!beginServerRequest(http, url)) return;
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  addDeviceHeaders(http);

  int responseCode = http.POST(body);
  Serial.print("LDR upload HTTP status: ");
  Serial.println(responseCode);
  if (responseCode < 0) {
    Serial.print("LDR connection error: ");
    Serial.println(http.errorToString(responseCode));
  }
  if (responseCode > 0 && responseCode != 200 && responseCode != 201) {
    Serial.println(http.getString());
  }
  http.end();
}

void setRelay(uint8_t pin, bool energized) {
  digitalWrite(pin, energized ? RELAY_ACTIVE_LEVEL : RELAY_INACTIVE_LEVEL);
}

void setLight(bool on) {
  lightOn = on;
  setRelay(LIGHT_RELAY_PIN, on);
  Serial.println(on ? "Light ON (relay IN3 energized)" : "Light OFF (relay IN3 released)");
}

void stopDoorMotor() {
  // Never allow the open and close relays to remain energized together.
  setRelay(DOOR_CLOSE_RELAY_PIN, false);
  setRelay(DOOR_OPEN_RELAY_PIN, false);
  doorMoving = false;
  Serial.println("Door STOPPED (relay IN1 and IN2 released)");
}

void startDoorMotor(bool opening) {
  // Release both channels before changing direction. This interlock protects
  // the actuator and relay contacts from applying both polarities at once.
  stopDoorMotor();
  delay(150);

  setRelay(opening ? DOOR_OPEN_RELAY_PIN : DOOR_CLOSE_RELAY_PIN, true);
  doorMoving = true;
  doorStartedAt = millis();
  Serial.println(opening
    ? "Door OPENING (relay IN2 energized)"
    : "Door CLOSING (relay IN1 energized)");
}

void applyDoorCommand(const String& state) {
  // A persistent desired state is returned on every poll. Run the motor only
  // when that desired state changes, rather than restarting it every 5 seconds.
  if (state == lastDoorCommand) return;
  lastDoorCommand = state;

  if (state == "open") {
    startDoorMotor(true);
  } else if (state == "closed") {
    startDoorMotor(false);
  } else if (state == "off") {
    stopDoorMotor();
  } else {
    Serial.print("Ignored unsupported door state: ");
    Serial.println(state);
  }
}

void checkCommands() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(SERVER_BASE_URL) +
               "/iot/api/actuators/esp32_commands/?device_id=" + DEVICE_ID;
  if (!beginServerRequest(http, url)) return;
  http.setTimeout(5000);
  addDeviceHeaders(http);

  int responseCode = http.GET();
  if (responseCode == 200) {
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, http.getString());
    if (error) {
      Serial.print("Command JSON error: ");
      Serial.println(error.c_str());
    } else {
      JsonArray commands = doc["commands"].as<JsonArray>();
      for (JsonObject command : commands) {
        String type = command["type"] | "";
        String state = command["state"] | "";

        if (type == "door") {
          applyDoorCommand(state);
        } else if (type == "light") {
          bool requestedOn = state == "on";
          if (requestedOn != lightOn) setLight(requestedOn);
        }
        // Feeder commands are deliberately ignored by this controller.
      }
    }
  } else {
    Serial.print("Command poll HTTP status: ");
    Serial.println(responseCode);
    if (responseCode < 0) {
      Serial.print("Command connection error: ");
      Serial.println(http.errorToString(responseCode));
    } else {
      Serial.println(http.getString());
    }
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(STATUS_LED, OUTPUT);
  pinMode(LDR_PIN, INPUT);

  // Preload the inactive level before switching each GPIO to output mode. This
  // reduces relay chatter during startup, especially on active-low boards.
  digitalWrite(DOOR_CLOSE_RELAY_PIN, RELAY_INACTIVE_LEVEL);
  digitalWrite(DOOR_OPEN_RELAY_PIN, RELAY_INACTIVE_LEVEL);
  digitalWrite(LIGHT_RELAY_PIN, RELAY_INACTIVE_LEVEL);
  pinMode(DOOR_CLOSE_RELAY_PIN, OUTPUT);
  pinMode(DOOR_OPEN_RELAY_PIN, OUTPUT);
  pinMode(LIGHT_RELAY_PIN, OUTPUT);
  analogSetPinAttenuation(LDR_PIN, ADC_11db);

  digitalWrite(STATUS_LED, LOW);
  setLight(false);
  stopDoorMotor();
  readLdr();
  connectWiFi();
}

void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED && now - lastWiFiAttempt >= 10000UL) {
    lastWiFiAttempt = now;
    connectWiFi();
  }

  if (now - lastSensorRead >= SENSOR_READ_INTERVAL_MS) {
    lastSensorRead = now;
    readLdr();
  }

  if (now - lastSensorSend >= SENSOR_SEND_INTERVAL_MS) {
    lastSensorSend = now;
    sendLdrReading();
  }

  if (now - lastCommandCheck >= COMMAND_CHECK_INTERVAL_MS) {
    lastCommandCheck = now;
    checkCommands();
  }

  if (doorMoving && now - doorStartedAt >= DOOR_MAX_RUN_TIME_MS) {
    Serial.println("Linear motor safety timeout reached");
    stopDoorMotor();
  }

  digitalWrite(STATUS_LED, WiFi.status() == WL_CONNECTED && (now % 2000UL < 100UL));
  delay(50);
}
