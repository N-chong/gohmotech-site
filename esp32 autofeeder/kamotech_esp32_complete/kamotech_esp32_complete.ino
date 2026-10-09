/*
 * ═══════════════════════════════════════════════════════════════════
 * KAMOTECH ESP32 - COMPLETE IOT SYSTEM
 * ═══════════════════════════════════════════════════════════════════
 * 
 * Complete integration with all sensors and actuatorsfd
 * Device Name: kamotech esp32
 * 
 * HARDWARE CONFIGURATION: CHONG
 * ----------------------
 * SENSORS:
 * - DHT21 (Temperature/Humidity) → GPIO 14
 * - Rain Sensor                   → GPIO 17
 * - Ultrasonic (Feeder Level)     → GPIO 18 (TRIG), GPIO 19 (ECHO)
 * - Indoor Light Sensor (analog)  → GPIO 34 (ADC1)
 * - MQ-135 Air Quality (analog)   → GPIO 35 (ADC1, max 3.3V)
 * 
 * ACTUATORS:
 * - Linear Motor (Door)           → GPIO 26 (IN1), GPIO 27 (IN2)
 * - Light                         → GPIO 13
 * - Servo Motor (Feeder)          → GPIO 25
 * 
 * BUTTONS (Physical Control):
 * - Door Button                   → GPIO 32
 * - Light Button                  → GPIO 33
 * - Servo Button                  → GPIO 15
 * 
 * FEATURES:
 * - NTP Time Synchronization (fixes timezone issue)
 * - All sensor readings sent to Django
 * - Remote actuator control via API
 * - Physical button control
 * - Auto WiFi reconnection
 * - Status LED indicators
 * 
 * ═══════════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <time.h>

// ═══════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

// WiFi Credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Django Server Configuration
// ⚠️ IMPORTANT: Update this IP when your laptop restarts!
const char* serverUrl = "http://10.87.22.155:8000/iot/api/sensor-readings/";
const char* commandUrl = "http://10.87.22.155:8000/iot/api/actuators/esp32_commands/";
const char* actuatorUrl = "http://10.87.22.155:8000/iot/api/actuator-state/";

// Device Configuration
const char* deviceId = "kamotech_esp32_001";
const char* deviceName = "kamotech esp32";

// NTP provides an absolute UTC clock. Asia/Manila conversion is done once by
// Django when rendering for the farm owner.
const char* ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 0;
const int daylightOffset_sec = 0;      // No daylight saving in Philippines

// Pin Definitions
// Sensors
#define DHT_PIN 14
#define DHT_TYPE DHT21
#define RAIN_SENSOR_PIN 17
#define ULTRASONIC_TRIG 18
#define ULTRASONIC_ECHO 19
#define LIGHT_SENSOR_PIN 34
#define MQ135_SENSOR_PIN 35

// Analog sensor calibration. Measure your own dark/bright values and replace these.
#define LIGHT_DARK_ADC 3500
#define LIGHT_BRIGHT_ADC 300
#define ANALOG_SAMPLES 16

// Leave at 0 until the MQ-135 has warmed up and you have measured/calculated R0.
// A PPM estimate is only uploaded when this is greater than zero.
#define MQ135_R0_KOHMS 0.0f
#define MQ135_LOAD_RESISTANCE_KOHMS 10.0f
#define ESP32_ADC_REFERENCE_VOLTS 3.3f

// Actuators
#define DOOR_IN1 26
#define DOOR_IN2 27
#define LIGHT_PIN 13
#define SERVO_PIN 25

// Buttons
#define DOOR_BUTTON 32
#define LIGHT_BUTTON 33
#define SERVO_BUTTON 15

// Status LED
#define STATUS_LED 2

// Timing Configuration
#define SENSOR_READ_INTERVAL 10000    // Read sensors every 10 seconds
#define SEND_DATA_INTERVAL 30000      // Send data every 30 seconds
#define BUTTON_DEBOUNCE 200           // Button debounce delay
#define ACTUATOR_CHECK_INTERVAL 5000  // Check for actuator commands every 5 seconds

// ═══════════════════════════════════════════════════════════════════
// GLOBAL OBJECTS & VARIABLES
// ═══════════════════════════════════════════════════════════════════

DHT dht(DHT_PIN, DHT_TYPE);
Servo feederServo;
HTTPClient http;

// Sensor Data
float currentTemperature = 0.0;
float currentHumidity = 0.0;
bool isRaining = false;
float feederLevel = 0.0;  // Distance in cm
int lightRaw = 0;
float lightLevelPercentage = 0.0;
int airQualityRaw = 0;
float airQualityVoltage = 0.0;
float airQualityPpm = 0.0;
bool airQualityCalibrated = false;
bool sensorDataValid = false;

// Actuator States
int doorState = 0;  // 0 = stopped, 1 = opening, 2 = closing
bool lightOn = false;
int servoAngle = 0;
bool isFeeding = false;
unsigned long feedingStartTime = 0;
#define FEED_DURATION 2000  // Servo opens for 2 seconds

// Button States
bool lastDoorButtonState = HIGH;
bool lastLightButtonState = HIGH;
bool lastServoButtonState = HIGH;

// Timing Variables
unsigned long lastSensorRead = 0;
unsigned long lastDataSend = 0;
unsigned long lastActuatorCheck = 0;
unsigned long lastDoorButtonPress = 0;
unsigned long lastLightButtonPress = 0;
unsigned long lastServoButtonPress = 0;

// ═══════════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n");
  Serial.println("╔════════════════════════════════════════════════════════╗");
  Serial.println("║     KAMOTECH ESP32 - COMPLETE IOT SYSTEM              ║");
  Serial.println("╚════════════════════════════════════════════════════════╝");
  Serial.println();
  
  // Initialize Pins
  initializePins();
  
  // Initialize Sensors
  initializeSensors();
  
  // Connect to WiFi
  connectWiFi();
  
  // Configure NTP Time Synchronization
  configureTime();
  
  // Print configuration
  printConfiguration();
  
  Serial.println("\n✓ System ready! Starting monitoring...\n");
  Serial.println("─────────────────────────────────────────────────────────");
}

// ═══════════════════════════════════════════════════════════════════
// INITIALIZATION FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

void initializePins() {
  Serial.println("🔧 Initializing pins...");
  
  // Status LED
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW);
  
  // Sensor Pins
  pinMode(RAIN_SENSOR_PIN, INPUT);
  pinMode(ULTRASONIC_TRIG, OUTPUT);
  pinMode(ULTRASONIC_ECHO, INPUT);
  pinMode(LIGHT_SENSOR_PIN, INPUT);
  pinMode(MQ135_SENSOR_PIN, INPUT);
  analogSetPinAttenuation(LIGHT_SENSOR_PIN, ADC_11db);
  analogSetPinAttenuation(MQ135_SENSOR_PIN, ADC_11db);
  
  // Actuator Pins
  pinMode(DOOR_IN1, OUTPUT);
  pinMode(DOOR_IN2, OUTPUT);
  pinMode(LIGHT_PIN, OUTPUT);
  
  // Set initial actuator states to OFF
  digitalWrite(DOOR_IN1, LOW);
  digitalWrite(DOOR_IN2, LOW);
  digitalWrite(LIGHT_PIN, LOW);
  
  // Button Pins (with internal pull-up resistors)
  pinMode(DOOR_BUTTON, INPUT_PULLUP);
  pinMode(LIGHT_BUTTON, INPUT_PULLUP);
  pinMode(SERVO_BUTTON, INPUT_PULLUP);
  
  Serial.println("✓ Pins initialized");
}

void initializeSensors() {
  Serial.println("🌡️  Initializing sensors...");
  
  // DHT21 Sensor
  dht.begin();
  delay(2000);

  // Servo Motor
  feederServo.attach(SERVO_PIN);
  feederServo.write(0);  // Initial position
  
  Serial.println("✓ All sensors initialized");
}

void configureTime() {
  Serial.println("🕐 Configuring NTP time synchronization...");
  Serial.println("   This fixes the timezone issue!");
  
  // Configure time with NTP server
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
  
  // Wait for time to be set
  int retries = 0;
  while (retries < 10) {
    time_t now = time(nullptr);
    if (now > 24 * 3600) {  // If time is set (more than 1 day since epoch)
      Serial.println("✓ Time synchronized successfully!");
      struct tm timeinfo;
      localtime_r(&now, &timeinfo);
      Serial.print("   Current time: ");
      Serial.println(asctime(&timeinfo));
      return;
    }
    Serial.print(".");
    delay(1000);
    retries++;
  }
  
  Serial.println("⚠️  Time sync timeout (will retry automatically)");
}

// ═══════════════════════════════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════════════════════════════

void loop() {
  unsigned long currentMillis = millis();
  
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n⚠️  WiFi connection lost! Reconnecting...");
    connectWiFi();
  }
  
  // Read all sensors
  if (currentMillis - lastSensorRead >= SENSOR_READ_INTERVAL) {
    readAllSensors();
    lastSensorRead = currentMillis;
  }

  // Send data to Django server
  if (currentMillis - lastDataSend >= SEND_DATA_INTERVAL) {
    if (sensorDataValid) {
      sendDataToServer();
    }
    lastDataSend = currentMillis;
  }
  
  // Check for actuator control commands from server
  if (currentMillis - lastActuatorCheck >= ACTUATOR_CHECK_INTERVAL) {
    checkActuatorCommands();
    lastActuatorCheck = currentMillis;
  }
  
  // Handle physical button presses
  handleButtons();
  
  // Update feeding process (auto-close servo after 2 seconds)
  updateFeeding();
  
  // Blink LED to show system is alive
  if (currentMillis % 2000 < 100) {
    digitalWrite(STATUS_LED, HIGH);
  } else {
    digitalWrite(STATUS_LED, LOW);
  }
  
  delay(100);
}

// ═══════════════════════════════════════════════════════════════════
// WIFI CONNECTION
// ═══════════════════════════════════════════════════════════════════

void connectWiFi() {
  Serial.println("\n📡 Connecting to WiFi...");
  Serial.print("   SSID: ");
  Serial.println(ssid);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(STATUS_LED, HIGH);
    Serial.println("\n✓ WiFi Connected!");
    Serial.print("   IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("   Signal: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    digitalWrite(STATUS_LED, LOW);
    Serial.println("\n✗ WiFi Connection Failed!");
  }
}

// ═══════════════════════════════════════════════════════════════════
// SENSOR READING FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

void readAllSensors() {
  Serial.println("\n📊 Reading all sensors...");
  
  // Read DHT21 (Temperature & Humidity)
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  
  if (!isnan(temp) && !isnan(hum)) {
    currentTemperature = temp;
    currentHumidity = hum;
    sensorDataValid = true;
  } else {
    Serial.println("✗ DHT21 read failed!");
    sensorDataValid = false;
  }
  
  // Read Rain Sensor (digital output: LOW = rain detected, HIGH = no rain)
  isRaining = (digitalRead(RAIN_SENSOR_PIN) == LOW);
  
  // Read Ultrasonic Sensor (Feeder Level)
  feederLevel = readUltrasonicDistance();

  // ADC1 pins are used because ADC2 cannot be read reliably while WiFi is active.
  lightRaw = readAveragedAnalog(LIGHT_SENSOR_PIN);
  lightLevelPercentage = constrain(
    100.0f * (LIGHT_DARK_ADC - lightRaw) / (LIGHT_DARK_ADC - LIGHT_BRIGHT_ADC),
    0.0f, 100.0f
  );

  airQualityRaw = readAveragedAnalog(MQ135_SENSOR_PIN);
  airQualityVoltage = (airQualityRaw / 4095.0f) * ESP32_ADC_REFERENCE_VOLTS;
  airQualityCalibrated = MQ135_R0_KOHMS > 0.0f && airQualityRaw > 0 && airQualityRaw < 4095;
  if (airQualityCalibrated) {
    float sensorResistance = MQ135_LOAD_RESISTANCE_KOHMS * (4095.0f / airQualityRaw - 1.0f);
    float resistanceRatio = sensorResistance / MQ135_R0_KOHMS;
    // Common MQ-135 curve approximation. Treat this as an estimate, not a certified CO2 reading.
    airQualityPpm = 116.6020682f * pow(resistanceRatio, -2.769034857f);
  }
  
  // Display all readings
  displaySensorReadings();
}

int readAveragedAnalog(int pin) {
  unsigned long total = 0;
  for (int i = 0; i < ANALOG_SAMPLES; i++) {
    total += analogRead(pin);
    delay(2);
  }
  return total / ANALOG_SAMPLES;
}

float readUltrasonicDistance() {
  // Send trigger pulse
  digitalWrite(ULTRASONIC_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIG, LOW);
  
  // Read echo pulse
  long duration = pulseIn(ULTRASONIC_ECHO, HIGH, 30000);  // 30ms timeout
  
  // Calculate distance in cm
  float distance = (duration * 0.034) / 2.0;
  
  // Debug output for testing
  Serial.print("🔍 Ultrasonic Test: Duration=");
  Serial.print(duration);
  Serial.print("µs, Distance=");
  Serial.print(distance, 1);
  Serial.print("cm");
  
  // Validate reading (ultrasonic range: 2-400 cm)
  if (duration == 0) {
    Serial.println(" ⚠️ No echo (sensor disconnected?)");
    return -1;  // Invalid reading
  } else if (distance < 2 || distance > 400) {
    Serial.println(" ⚠️ Out of range (valid: 2-400cm)");
    return -1;  // Invalid reading
  } else {
    Serial.println(" ✓ Valid reading");
    return distance;
  }
}

void displaySensorReadings() {
  Serial.println("✓ Sensor readings:");
  Serial.println("  ┌─────────────────────────────────┐");
  Serial.print("  │ Temperature:  ");
  Serial.print(currentTemperature, 1);
  Serial.println(" °C          │");
  Serial.print("  │ Humidity:     ");
  Serial.print(currentHumidity, 1);
  Serial.println(" %           │");
  Serial.print("  │ Rain Status:  ");
  Serial.print(isRaining ? "RAINING" : "DRY");
  Serial.println("          │");
  Serial.print("  │ Feeder Level: ");
  Serial.print(feederLevel, 1);
  Serial.println(" cm         │");
  Serial.print("  │ Indoor Light: ");
  Serial.print(lightLevelPercentage, 1);
  Serial.print(" % (ADC ");
  Serial.print(lightRaw);
  Serial.println(")   │");
  Serial.print("  │ MQ-135:       ADC ");
  Serial.print(airQualityRaw);
  Serial.print(" / ");
  Serial.print(airQualityVoltage, 3);
  Serial.print(" V");
  if (airQualityCalibrated) {
    Serial.print(" / ~");
    Serial.print(airQualityPpm, 1);
    Serial.print(" ppm");
  } else {
    Serial.print(" (uncalibrated)");
  }
  Serial.println(" │");
  Serial.println("  └─────────────────────────────────┘");
}

// ═══════════════════════════════════════════════════════════════════
// SEND DATA TO DJANGO SERVER
// ═══════════════════════════════════════════════════════════════════

void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("✗ Cannot send data - WiFi not connected");
    return;
  }
  
  Serial.println("\n📤 Sending data to Django server...");
  
  // Create JSON payload. Send UTC only after NTP has a plausible epoch;
  // otherwise omission makes Django use its server receipt time.
  StaticJsonDocument<512> doc;
  doc["device_id"] = deviceId;
  doc["device_name"] = deviceName;
  doc["temperature"] = currentTemperature;
  doc["humidity"] = currentHumidity;
  doc["rain_detected"] = isRaining;
  doc["feeder_level"] = feederLevel;
  doc["light_raw"] = lightRaw;
  doc["light_level_percentage"] = lightLevelPercentage;
  doc["air_quality_raw"] = airQualityRaw;
  doc["air_quality_voltage"] = airQualityVoltage;
  doc["air_quality_calibrated"] = airQualityCalibrated;
  if (airQualityCalibrated) {
    doc["air_quality_ppm"] = airQualityPpm;
  }
  time_t measuredAt = time(nullptr);
  if (measuredAt >= 1704067200) {
    struct tm utcTime;
    char timestampUtc[25];
    gmtime_r(&measuredAt, &utcTime);
    if (strftime(timestampUtc, sizeof(timestampUtc), "%Y-%m-%dT%H:%M:%SZ", &utcTime) > 0) {
      doc["timestamp"] = timestampUtc;
    }
  }
  
  String jsonString;
  serializeJson(doc, jsonString);
  
  Serial.println("  JSON Payload:");
  Serial.print("  ");
  Serial.println(jsonString);
  
  // Send HTTP POST request
  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/json");
  
  int httpResponseCode = http.POST(jsonString);
  
  // Handle response
  if (httpResponseCode > 0) {
    Serial.print("  ✓ Server response: ");
    Serial.println(httpResponseCode);
    
    if (httpResponseCode == 200 || httpResponseCode == 201) {
      Serial.println("  ✓ Data sent successfully!");
      
      // Flash LED
      for (int i = 0; i < 3; i++) {
        digitalWrite(STATUS_LED, LOW);
        delay(100);
        digitalWrite(STATUS_LED, HIGH);
        delay(100);
      }
    } else {
      Serial.print("  ✗ Server error: ");
      Serial.println(http.getString());
    }
  } else {
    Serial.print("  ✗ HTTP request failed: ");
    Serial.println(http.errorToString(httpResponseCode));
  }
  
  http.end();
}

// ═══════════════════════════════════════════════════════════════════
// ACTUATOR CONTROL FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

void checkActuatorCommands() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  
  // Build command URL with device_id parameter
  String url = String(commandUrl) + "?device_id=" + deviceId;
  
  http.begin(url);
  http.setTimeout(5000);
  
  int httpResponseCode = http.GET();
  
  if (httpResponseCode == 200) {
    String payload = http.getString();
    
    // Parse JSON response
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error && doc.containsKey("commands")) {
      JsonArray commands = doc["commands"].as<JsonArray>();
      
      for (JsonObject cmd : commands) {
        String type = cmd["type"].as<String>();
        String state = cmd["state"].as<String>();
        
        // Execute door commands (don't sync back - already from Django)
        if (type == "door") {
          if (state == "open" && doorState != 1) {
            Serial.println("📱 Remote command: Opening door");
            setDoorState(1);  // Don't sync back to Django
          } else if (state == "closed" && doorState != 2) {
            Serial.println("📱 Remote command: Closing door");
            setDoorState(2);
          } else if (state == "off" && doorState != 0) {
            Serial.println("📱 Remote command: Stop door");
            setDoorState(0);
          }
        }
        
        // Execute light commands (don't sync back - already from Django)
        if (type == "light") {
          bool shouldBeOn = (state == "on");
          if (shouldBeOn != lightOn) {
            Serial.print("📱 Remote command: Light ");
            Serial.println(shouldBeOn ? "ON" : "OFF");
            controlLight(shouldBeOn);  // Don't sync back to Django
          }
        }
        
        // Execute feeder/servo commands (don't sync back - already from Django)
        if (type == "feeder" || type == "servo") {
          if (state == "on" && !isFeeding) {
            Serial.println("📱 Remote command: Start feeding");
            startFeeding();  // Trigger auto-feed cycle
          }
          // Note: Can't stop feeding mid-cycle - it auto-completes in 3 seconds
        }
      }
    }
  } else if (httpResponseCode > 0) {
    // HTTP error but connection worked
    Serial.print("⚠️  Command check HTTP error: ");
    Serial.println(httpResponseCode);
  }
  // Silently fail if no connection (don't spam logs)
  
  http.end();
}

void updateDjangoState(String actuatorType, String state) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ Not connected to WiFi, cannot sync state");
    return;
  }
  
  // Use the new sync endpoint (correct URL with 'actuators' not 'actuator-state')
  String url = "http://192.168.137.1:8000/iot/api/actuators/esp32_sync_state/";
  
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload
  StaticJsonDocument<256> doc;
  doc["device_id"] = deviceId;
  doc["actuator_type"] = actuatorType;
  doc["state"] = state;
  
  String jsonString;
  serializeJson(doc, jsonString);
  
  int httpResponseCode = http.POST(jsonString);
  
  if (httpResponseCode == 200) {
    Serial.print("✅ Synced to Django: ");
    Serial.print(actuatorType);
    Serial.print(" = ");
    Serial.println(state);
  } else {
    Serial.print("⚠️ Sync failed (HTTP ");
    Serial.print(httpResponseCode);
    Serial.print("): ");
    Serial.print(actuatorType);
    Serial.print(" = ");
    Serial.println(state);
  }
  
  http.end();
}

// Sync state with physical button trigger flag
void updateDjangoStateWithButton(String actuatorType, String state) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ Not connected to WiFi, cannot sync state");
    return;
  }
  
  String url = "http://192.168.137.1:8000/iot/api/actuators/esp32_sync_state/";
  
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload with physical_button trigger
  StaticJsonDocument<256> doc;
  doc["device_id"] = deviceId;
  doc["actuator_type"] = actuatorType;
  doc["state"] = state;
  doc["triggered_by"] = "physical_button";  // Mark as physical button press
  
  String jsonString;
  serializeJson(doc, jsonString);
  
  Serial.print("🔘 Physical button ");
  Serial.print(actuatorType);
  Serial.print(" → ");
  Serial.println(state);
  
  int httpResponseCode = http.POST(jsonString);
  
  if (httpResponseCode == 200) {
    Serial.println("✅ Physical button action logged to Django");
  } else {
    Serial.print("⚠️ Failed to log (HTTP ");
    Serial.print(httpResponseCode);
    Serial.println(")");
  }
  
  http.end();
}

// Log physical button feeding to Django
void logPhysicalButtonFeed(int amount) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ Not connected to WiFi, cannot log feeding");
    return;
  }
  
  String url = "http://192.168.137.1:8000/feeding/api/logs/physical-button-feed/";
  
  http.begin(url);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload
  StaticJsonDocument<256> doc;
  doc["device_id"] = deviceId;
  doc["feeder_id"] = 1;  // Default feeder ID
  doc["amount"] = amount;
  
  String jsonString;
  serializeJson(doc, jsonString);
  
  Serial.print("📤 Logging physical button feed: ");
  Serial.print(amount);
  Serial.println("g");
  
  int httpResponseCode = http.POST(jsonString);
  
  if (httpResponseCode == 200 || httpResponseCode == 201) {
    Serial.println("✅ Physical button feeding logged to Django");
  } else {
    Serial.print("⚠️ Failed to log feeding (HTTP ");
    Serial.print(httpResponseCode);
    Serial.println(")");
  }
  
  http.end();
}

void setDoorState(int state) {
  doorState = state;
  
  switch (doorState) {
    case 0:  // STOP
      digitalWrite(DOOR_IN1, LOW);
      digitalWrite(DOOR_IN2, LOW);
      Serial.println("🚪 Door STOPPED");
      break;
      
    case 1:  // OPENING (reversed wiring)
      digitalWrite(DOOR_IN1, LOW);
      digitalWrite(DOOR_IN2, HIGH);
      Serial.println("🚪 Door OPENING...");
      break;
      
    case 2:  // CLOSING (reversed wiring)
      digitalWrite(DOOR_IN1, HIGH);
      digitalWrite(DOOR_IN2, LOW);
      Serial.println("🚪 Door CLOSING...");
      break;
  }
}

void setDoorStateAndSync(int state, bool syncToDjango) {
  setDoorState(state);
  
  if (syncToDjango) {
    // Convert door state to Django format
    String djangoState = "off";
    if (state == 1) djangoState = "open";
    else if (state == 2) djangoState = "closed";
    
    updateDjangoState("door", djangoState);
  }
}

void setDoorStateAndSyncWithButton(int state) {
  setDoorState(state);
  
  // Convert door state to Django format and log as physical button
  String djangoState = "off";
  if (state == 1) djangoState = "open";
  else if (state == 2) djangoState = "closed";
  
  updateDjangoStateWithButton("door", djangoState);
}

void controlLight(bool on) {
  lightOn = on;
  digitalWrite(LIGHT_PIN, on ? HIGH : LOW);
  Serial.print("💡 Light turned ");
  Serial.println(on ? "ON" : "OFF");
}

void controlLightAndSync(bool on, bool syncToDjango) {
  controlLight(on);
  
  if (syncToDjango) {
    String djangoState = on ? "on" : "off";
    updateDjangoState("light", djangoState);
  }
}

void startFeeding() {
  if (isFeeding) {
    return;  // Already feeding, don't start again
  }
  
  Serial.println("🍽️ AUTO-FEEDING: Opening feeder...");
  feederServo.write(180);  // Open to 180°
  servoAngle = 180;
  isFeeding = true;
  feedingStartTime = millis();
}

void updateFeeding() {
  if (!isFeeding) {
    return;
  }
  
  unsigned long elapsed = millis() - feedingStartTime;
  
  if (elapsed >= FEED_DURATION) {
    // 3 seconds elapsed - close feeder
    Serial.println("✓ AUTO-FEEDING: Closing feeder");
    feederServo.write(0);  // Close to 0°
    servoAngle = 0;
    isFeeding = false;
    
    // Sync back to Django - set feeder to "off" so it doesn't retrigger
    updateDjangoState("feeder", "off");
  }
}

// ═══════════════════════════════════════════════════════════════════
// BUTTON HANDLING
// ═══════════════════════════════════════════════════════════════════

void handleButtons() {
  unsigned long currentMillis = millis();
  
  // Door Button - Cycles: STOP → OPEN → STOP → CLOSE → STOP
  bool doorButtonState = digitalRead(DOOR_BUTTON);
  if (doorButtonState == LOW && lastDoorButtonState == HIGH) {
    if (currentMillis - lastDoorButtonPress > BUTTON_DEBOUNCE) {
      // Cycle through states: 0 → 1 → 0 → 2 → 0
      if (doorState == 0) {
        setDoorStateAndSyncWithButton(1);  // Start opening - log as physical button
      } else if (doorState == 1) {
        setDoorStateAndSyncWithButton(0);  // Stop opening - log as physical button
      } else if (doorState == 2) {
        setDoorStateAndSyncWithButton(0);  // Stop closing - log as physical button
      }
      lastDoorButtonPress = currentMillis;
    }
  }
  // Long press detection for closing (hold button for 1 second when stopped)
  if (doorButtonState == LOW && lastDoorButtonState == LOW) {
    if (doorState == 0 && (currentMillis - lastDoorButtonPress > 1000)) {
      setDoorStateAndSyncWithButton(2);  // Start closing - log as physical button
      lastDoorButtonPress = currentMillis;
    }
  }
  lastDoorButtonState = doorButtonState;
  
  // Light Button
  bool lightButtonState = digitalRead(LIGHT_BUTTON);
  if (lightButtonState == LOW && lastLightButtonState == HIGH) {
    if (currentMillis - lastLightButtonPress > BUTTON_DEBOUNCE) {
      lightOn = !lightOn;
      controlLight(lightOn);  // Control the light
      // Log as physical button press
      String lightState = lightOn ? "on" : "off";
      updateDjangoStateWithButton("light", lightState);
      lastLightButtonPress = currentMillis;
    }
  }
  lastLightButtonState = lightButtonState;
  
  // Servo Button - Auto Feed (Open 180° for 3 seconds, then auto-close)
  bool servoButtonState = digitalRead(SERVO_BUTTON);
  if (servoButtonState == LOW && lastServoButtonState == HIGH) {
    if (currentMillis - lastServoButtonPress > BUTTON_DEBOUNCE) {
      if (!isFeeding) {
        startFeeding();  // Start auto-feed cycle
        // Log physical button feeding to Django (3 seconds @ 180° = ~500g)
        logPhysicalButtonFeed(500);
        // Sync actuator state to Django with physical button flag
        updateDjangoStateWithButton("feeder", "on");
      }
      lastServoButtonPress = currentMillis;
    }
  }
  lastServoButtonState = servoButtonState;
}

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

void printConfiguration() {
  Serial.println("\n📋 System Configuration:");
  Serial.println("  ╔════════════════════════════════════════════════╗");
  Serial.println("  ║              SENSORS                           ║");
  Serial.println("  ╠════════════════════════════════════════════════╣");
  Serial.println("  ║  DHT21 (Temp/Humidity)  → GPIO 14              ║");
  Serial.println("  ║  Rain Sensor             → GPIO 17              ║");
  Serial.println("  ║  Ultrasonic (Feeder)     → GPIO 18/19          ║");
  Serial.println("  ║  Indoor Light Sensor     → GPIO 34             ║");
  Serial.println("  ║  MQ-135 Air Quality      → GPIO 35             ║");
  Serial.println("  ╠════════════════════════════════════════════════╣");
  Serial.println("  ║              ACTUATORS                         ║");
  Serial.println("  ╠════════════════════════════════════════════════╣");
  Serial.println("  ║  Linear Motor (Door)     → GPIO 26/27          ║");
  Serial.println("  ║  Light                   → GPIO 13              ║");
  Serial.println("  ║  Servo Motor             → GPIO 25              ║");
  Serial.println("  ╠════════════════════════════════════════════════╣");
  Serial.println("  ║              BUTTONS                           ║");
  Serial.println("  ╠════════════════════════════════════════════════╣");
  Serial.println("  ║  Door Control            → GPIO 32              ║");
  Serial.println("  ║    (Quick press: Open/Stop, Hold 1s: Close)    ║");
  Serial.println("  ║  Light Control           → GPIO 33              ║");
  Serial.println("  ║    (Toggle ON/OFF)                             ║");
  Serial.println("  ║  Servo/Feed Control      → GPIO 15              ║");
  Serial.println("  ║    (Open 180° for 3sec, auto-close)            ║");
  Serial.println("  ╚════════════════════════════════════════════════╝");
  Serial.println();
  Serial.print("  Server URL: ");
  Serial.println(serverUrl);
  Serial.print("  Timezone: GMT");
  Serial.print(gmtOffset_sec / 3600 > 0 ? "+" : "");
  Serial.println(gmtOffset_sec / 3600);
}

// ═══════════════════════════════════════════════════════════════════
// END OF CODE
// ═══════════════════════════════════════════════════════════════════
