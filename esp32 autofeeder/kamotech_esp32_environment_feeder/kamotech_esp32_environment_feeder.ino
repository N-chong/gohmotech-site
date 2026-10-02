/*
 * KAMOTECH ESP32 B
 * Remaining hardware on this controller:
 *   - DHT21 temperature/humidity -> GPIO 14
 *   - Rain sensor               -> GPIO 17
 *   - Ultrasonic feeder level   -> GPIO 18 (TRIG), GPIO 19 (ECHO)
 *   - MQ-135 air quality        -> GPIO 35 (ADC1, maximum 3.3 V)
 *   - Feeder servo              -> GPIO 25
 *
 * Door, light, and LDR code is intentionally absent from this sketch.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

// Network configuration supplied for this installation.
const char* WIFI_SSID = "@MIRANDA";
const char* WIFI_PASSWORD = "miranda-090603";
const char* SERVER_BASE_URL = "http://21.1.1.1:8000";

// Keep 001 on the environmental/feeder controller because the current Django
// dashboards and scheduled-feeding task refer to this device ID.
const char* DEVICE_ID = "kamotech_esp32_001";
const char* DEVICE_NAME = "Kamotech Environment Feeder Controller";

// Copy the configured Django IOT_DEVICE_API_KEY here before uploading.
const char* DEVICE_API_KEY = "YOUR_DEVICE_API_KEY";

#define DHT_PIN 14
#define DHT_TYPE DHT21
#define RAIN_SENSOR_PIN 17
#define ULTRASONIC_TRIG_PIN 18
#define ULTRASONIC_ECHO_PIN 19
#define MQ135_PIN 35
#define SERVO_PIN 25
#define STATUS_LED 2

#define ADC_SAMPLES 16
#define ESP32_ADC_REFERENCE_VOLTS 3.3f
#define MQ135_LOAD_RESISTANCE_KOHMS 10.0f
// Leave at zero until the installed MQ-135 has been calibrated.
#define MQ135_R0_KOHMS 0.0f

#define SENSOR_READ_INTERVAL_MS 10000UL
#define SENSOR_SEND_INTERVAL_MS 30000UL
#define COMMAND_CHECK_INTERVAL_MS 5000UL
#define FEED_DURATION_MS 2000UL
#define SERVO_CLOSED_ANGLE 0
#define SERVO_OPEN_ANGLE 180

DHT dht(DHT_PIN, DHT_TYPE);
Servo feederServo;

float temperatureC = NAN;
float humidityPercent = NAN;
bool raining = false;
float feederDistanceCm = -1.0f;
int airQualityRaw = 0;
float airQualityVoltage = 0.0f;
float airQualityPpm = 0.0f;
bool airQualityCalibrated = false;

bool feeding = false;
unsigned long feedingStartedAt = 0;
String lastFeederCommand = "off";

unsigned long lastSensorRead = 0;
unsigned long lastSensorSend = 0;
unsigned long lastCommandCheck = 0;
unsigned long lastWiFiAttempt = 0;

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

float readUltrasonicDistance() {
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

  unsigned long duration = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000UL);
  if (duration == 0) return -1.0f;

  float distance = duration * 0.034f / 2.0f;
  return distance >= 2.0f && distance <= 400.0f ? distance : -1.0f;
}

void readSensors() {
  float newTemperature = dht.readTemperature();
  float newHumidity = dht.readHumidity();
  if (!isnan(newTemperature)) temperatureC = newTemperature;
  if (!isnan(newHumidity)) humidityPercent = newHumidity;

  raining = digitalRead(RAIN_SENSOR_PIN) == LOW;
  feederDistanceCm = readUltrasonicDistance();
  airQualityRaw = readAveragedAdc(MQ135_PIN);
  airQualityVoltage = airQualityRaw / 4095.0f * ESP32_ADC_REFERENCE_VOLTS;

  airQualityCalibrated =
    MQ135_R0_KOHMS > 0.0f && airQualityRaw > 0 && airQualityRaw < 4095;
  if (airQualityCalibrated) {
    float sensorResistance =
      MQ135_LOAD_RESISTANCE_KOHMS * (4095.0f / airQualityRaw - 1.0f);
    float ratio = sensorResistance / MQ135_R0_KOHMS;
    airQualityPpm = 116.6020682f * pow(ratio, -2.769034857f);
  }

  Serial.print("Temperature: ");
  Serial.print(temperatureC);
  Serial.print(" C, humidity: ");
  Serial.print(humidityPercent);
  Serial.print("%, rain: ");
  Serial.print(raining ? "yes" : "no");
  Serial.print(", feeder distance: ");
  Serial.print(feederDistanceCm);
  Serial.print(" cm, MQ-135 ADC: ");
  Serial.println(airQualityRaw);
}

void sendSensorReading() {
  if (WiFi.status() != WL_CONNECTED) return;

  StaticJsonDocument<512> doc;
  doc["device_id"] = DEVICE_ID;
  doc["device_name"] = DEVICE_NAME;
  if (!isnan(temperatureC)) doc["temperature"] = temperatureC;
  if (!isnan(humidityPercent)) doc["humidity"] = humidityPercent;
  doc["rain_detected"] = raining;
  if (feederDistanceCm >= 0.0f) doc["feeder_level"] = feederDistanceCm;
  doc["air_quality_raw"] = airQualityRaw;
  doc["air_quality_voltage"] = airQualityVoltage;
  doc["air_quality_calibrated"] = airQualityCalibrated;
  if (airQualityCalibrated) doc["air_quality_ppm"] = airQualityPpm;

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  String url = String(SERVER_BASE_URL) + "/iot/api/sensor-readings/";
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  addDeviceHeaders(http);

  int responseCode = http.POST(body);
  Serial.print("Sensor upload HTTP status: ");
  Serial.println(responseCode);
  if (responseCode > 0 && responseCode != 200 && responseCode != 201) {
    Serial.println(http.getString());
  }
  http.end();
}

void syncFeederOff() {
  if (WiFi.status() != WL_CONNECTED) return;

  StaticJsonDocument<256> doc;
  doc["device_id"] = DEVICE_ID;
  doc["actuator_type"] = "feeder";
  doc["state"] = "off";

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  String url = String(SERVER_BASE_URL) +
               "/iot/api/actuators/esp32_sync_state/";
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  addDeviceHeaders(http);

  int responseCode = http.POST(body);
  Serial.print("Feeder OFF sync HTTP status: ");
  Serial.println(responseCode);
  if (responseCode > 0 && responseCode != 200) Serial.println(http.getString());
  http.end();
}

void startFeeding() {
  if (feeding) return;
  feederServo.write(SERVO_OPEN_ANGLE);
  feeding = true;
  feedingStartedAt = millis();
  Serial.println("Feeder OPEN");
}

void updateFeeding(unsigned long now) {
  if (!feeding || now - feedingStartedAt < FEED_DURATION_MS) return;

  feederServo.write(SERVO_CLOSED_ANGLE);
  feeding = false;
  Serial.println("Feeder CLOSED");
  syncFeederOff();
}

void checkCommands() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(SERVER_BASE_URL) +
               "/iot/api/actuators/esp32_commands/?device_id=" + DEVICE_ID;
  http.begin(url);
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

        if (type == "feeder" || type == "servo") {
          if (state != lastFeederCommand) {
            lastFeederCommand = state;
            if (state == "on") startFeeding();
          }
        }
        // Door and light commands are deliberately ignored here.
      }
    }
  } else {
    Serial.print("Command poll HTTP status: ");
    Serial.println(responseCode);
    if (responseCode > 0) Serial.println(http.getString());
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(STATUS_LED, OUTPUT);
  pinMode(RAIN_SENSOR_PIN, INPUT);
  pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
  pinMode(ULTRASONIC_ECHO_PIN, INPUT);
  pinMode(MQ135_PIN, INPUT);
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);

  dht.begin();
  feederServo.attach(SERVO_PIN);
  feederServo.write(SERVO_CLOSED_ANGLE);
  delay(500);

  readSensors();
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
    readSensors();
  }

  if (now - lastSensorSend >= SENSOR_SEND_INTERVAL_MS) {
    lastSensorSend = now;
    sendSensorReading();
  }

  if (now - lastCommandCheck >= COMMAND_CHECK_INTERVAL_MS) {
    lastCommandCheck = now;
    checkCommands();
  }

  updateFeeding(now);
  digitalWrite(STATUS_LED, WiFi.status() == WL_CONNECTED && (now % 2000UL < 100UL));
  delay(50);
}
