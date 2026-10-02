# GoHMoTech Final GPIO Pin Map

## Scope and board assumption

This map is for the **classic ESP32 DevKit / ESP32-WROOM-32 pinout used by the existing sketches**. It is not automatically valid for ESP32-S2, S3, C3, or another board family. Confirm the module marking before installation.

## ESP32 1 — Main Controller

```text
GPIO 26 -> Door relay IN1 / CLOSE
GPIO 27 -> Door relay IN2 / OPEN
GPIO 13 -> Light relay IN
GPIO 34 -> LDR divider node (ADC1_CH6; input-only)
GPIO 14 -> DHT21 DATA
GPIO 17 -> Rain module DO (binary rain detection)
GPIO 35 -> MQ-135 AO through 12 kΩ / 22 kΩ divider (ADC1_CH7; input-only)
GPIO 32 -> Feeder momentary button (INPUT_PULLUP)
GPIO 33 -> Light momentary button (INPUT_PULLUP)
GPIO 25 -> Door momentary button (INPUT_PULLUP)
GPIO  2 -> Existing onboard status LED only; do not add external wiring
```

## ESP32 2 — Feeder Controller

```text
GPIO 25 -> Feeder servo signal
GPIO 18 -> Ultrasonic TRIG
GPIO 19 -> Ultrasonic ECHO through 5.6 kΩ / 10 kΩ divider when sensor ECHO is 5 V
GPIO  2 -> Existing onboard status LED only; do not add external wiring
```

Pins reused on different ESP32 boards are not conflicts.

## Complete wiring tables

### ESP32 1 — Main Controller

| Device | Device Pin | ESP32 GPIO | Voltage | Direction | Additional component / notes |
| --- | --- | ---: | --- | --- | --- |
| Door Relay | IN1 / CLOSE | 26 | 3.3 V logic | OUTPUT | Existing assignment; active-LOW board was previously verified. Use a 3.3 V-compatible input/driver. |
| Door Relay | IN2 / OPEN | 27 | 3.3 V logic | OUTPUT | Existing assignment; firmware interlock must never energize IN1 and IN2 together. |
| Light Relay | IN | 13 | 3.3 V logic | OUTPUT | Existing assignment; relay contacts switch the separately powered light load. |
| LDR | Divider node / AO | 34 | 0–3.3 V | INPUT / ADC1 | Existing assignment; 10 kΩ fixed resistor; 100 nF node-to-GND optional filter. |
| DHT21 | DATA | 14 | 3.3 V logic | INPUT | Existing DHT assignment moved from ESP32 2; 4.7 kΩ DATA-to-3.3 V pull-up if not already on module. |
| Rain Sensor | DO | 17 | 3.3 V logic | INPUT | Existing assignment retained; use binary RAIN/NO RAIN. Power interface at 3.3 V or level-shift DO if its measured HIGH exceeds 3.3 V. |
| MQ-135 module | AO | 35 | ≤3.24 V at ESP32 | INPUT / ADC1 | Existing assignment moved from ESP32 2; 12 kΩ upper + 22 kΩ lower divider and 100 nF at ADC node. Module/heater uses regulated 5 V. |
| Feeder Button | Signal | 32 | 3.3 V logic | INPUT | `INPUT_PULLUP`; normally HIGH, pressed LOW; other terminal to GND. |
| Light Button | Signal | 33 | 3.3 V logic | INPUT | `INPUT_PULLUP`; normally HIGH, pressed LOW; other terminal to GND. |
| Door Button | Signal | 25 | 3.3 V logic | INPUT | `INPUT_PULLUP`; normally HIGH, pressed LOW; other terminal to GND. |

### ESP32 2 — Feeder Controller

| Device | Device Pin | ESP32 GPIO | Voltage | Direction | Additional component / notes |
| --- | --- | ---: | --- | --- | --- |
| Feeder Servo | Signal | 25 | 3.3 V PWM | OUTPUT / PWM | Existing assignment; power servo from its own correctly rated 5–6 V supply, not ESP32. |
| Ultrasonic | TRIG | 18 | 3.3 V logic | OUTPUT | Existing current assignment; confirm the installed sensor accepts 3.3 V HIGH. |
| Ultrasonic | ECHO | 19 | ≤3.21 V | INPUT | Existing current assignment; for 5 V HC-SR04-style ECHO use 5.6 kΩ upper + 10 kΩ lower divider. |

## Pin-selection findings

The current split sketches have no duplicate GPIO on a single board. The following historical assignments are not suitable for the finalized arrangement:

| Current / historical GPIO | Device | Problem | Final GPIO | Reason |
| ---: | --- | --- | ---: | --- |
| 34 | Feeder button in older combined sketches | Conflicts with the retained LDR on GPIO34; GPIO34 also has no internal pull-up. | 32 | Safe bidirectional pin with internal pull-up; ADC1 capability remains available but is not needed. |
| 15 | Door button in older combined sketches | ESP32 strapping pin; an asserted button during reset can affect boot. | 25 | Safe general-purpose input with internal pull-up. |
| 5 | Ultrasonic TRIG in older combined sketches | ESP32 strapping pin and unnecessary boot risk. | 18 | The newer feeder sketch already proves GPIO18 for TRIG. |
| ESP32 2 GPIO14 | DHT21 | No electrical fault, but the finalized responsibility puts environmental sensors on ESP32 1. | ESP32 1 GPIO14 | Preserves the proven GPIO number while moving only the wire/controller ownership. |
| ESP32 2 GPIO17 | Rain DO | No electrical fault; controller ownership changes. | ESP32 1 GPIO17 | Preserves the proven GPIO number. |
| ESP32 2 GPIO35 | MQ-135 AO | No GPIO fault; controller ownership changes. | ESP32 1 GPIO35 | Preserves ADC1 and the proven GPIO number. |

## GPIOs to avoid or reserve

- Avoid GPIO0, 2, 5, 12, and 15 for new field wiring because they are boot/strapping pins. GPIO2 remains only the board's existing status LED.
- Do not use GPIO6–11; they are normally connected to SPI flash.
- Reserve GPIO1 and GPIO3 for USB serial/programming unless the exact board design says otherwise.
- GPIO34–39 are input-only and have no internal pull-up/down. They are suitable here only for the LDR and MQ-135 ADC inputs.
- Avoid ADC2 pins for analog sensors while Wi-Fi is active. The finalized analog inputs use ADC1 GPIO34 and GPIO35.
- Do not apply more than 3.3 V to any ESP32 GPIO. Do not treat ADC attenuation as over-voltage protection.

## Firmware constants

```cpp
// ESP32 1
#define DOOR_CLOSE_RELAY_PIN 26
#define DOOR_OPEN_RELAY_PIN  27
#define LIGHT_RELAY_PIN      13
#define LDR_PIN              34
#define DHT_PIN              14
#define RAIN_SENSOR_PIN      17
#define MQ135_PIN            35
#define FEED_BUTTON_PIN      32
#define LIGHT_BUTTON_PIN     33
#define DOOR_BUTTON_PIN      25

// ESP32 2
#define SERVO_PIN            25
#define ULTRASONIC_TRIG_PIN  18
#define ULTRASONIC_ECHO_PIN  19
```

