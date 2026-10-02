# Existing ESP32 Source GPIO Audit

Audit date: 2026-09-21. This inventory was completed before selecting the final map. “Historical/test” means the file remains untouched but is not the wiring authority for permanent installation.

## Wiring-authority starting points

| Sketch | Role | Assigned GPIOs found |
| --- | --- | --- |
| `kamotech_esp32_door_light_ldr.ino` | Current main-controller starting point | LDR 34; door CLOSE 26; door OPEN 27; light relay 13; status LED 2 |
| `kamotech_esp32_environment_feeder.ino` | Current environment/feeder starting point | DHT21 14; rain 17; ultrasonic TRIG 18/ECHO 19; MQ-135 35; servo 25; status LED 2 |

These current split sketches contain no duplicate GPIO within either board. Their electrical issues are external-interface voltage/power questions: MQ-135 AO protection, ultrasonic ECHO level shifting, servo power, and exact rain/relay module compatibility.

## Other repository sketches

| Sketch / variant | Assigned GPIOs found | Audit finding |
| --- | --- | --- |
| `8398yeiuhdakj.ino` | servo 15; rain AO 32; TRIG 5; ECHO 18; feed button 25 | Historical; servo GPIO15 and TRIG GPIO5 are strapping-pin risks. |
| Root and nested `esp32_django_integrated.ino` copies | servo 25; door OPEN 26/CLOSE 27; light 13; rain AO 32; TRIG 5; ECHO 18; door button 15; light button 33; feed button 34 | Historical combined design; GPIO5/15 are strapping pins; GPIO34 has no internal pull-up; ECHO protection is not evident from assignment alone. |
| `esp32_mqtt_integrated.ino` | same combined pins above plus DHT21 14 and status LED 2 | Same conflicts/risks as the Django combined design. |
| `esp32_web_code.ino` | relay OPEN 26/CLOSE 27; door button 15; light button 32; servo button 33; light 13; servo 25 | Historical; door button GPIO15 is a strapping-pin risk. |
| `kamotech_esp32_complete.ino` | DHT21 14; rain 17; ultrasonic 18/19; LDR 34; MQ-135 35; door 26/27; light 13; servo 25; buttons 32/33/15; LED 2 | Historical all-in-one design; servo button GPIO15 is a strapping-pin risk; too many high-noise loads on one controller for the requested split. |
| `esp32_servo_feeder.ino` | servo 25 | Confirms the final servo signal assignment. |
| `kamotech_esp32_servo_only.ino` | HX711 DOUT 19; CLK 18 | File name is misleading: it contains load-cell code, not servo code. It is outside the requested two-board wiring and conflicts with ultrasonic only if incorrectly flashed on ESP32 2. |
| `kamotech_esp32_dht21.ino` copies and `dht21_sensor_test.ino` | DHT21 14; LED 2 | Confirms the DHT21 assignment. |
| `esp32 load cell/kamotech_load_cell_esp32.ino` | HX711 DOUT 19; SCK 18; LED 2 | Separate load-cell controller; outside this task. Do not combine it with ESP32 2 ultrasonic GPIO18/19. |

## Final-change justification

| Existing assignment | Device | Problem | Replacement | Reason |
| --- | --- | --- | --- | --- |
| GPIO34 | Feed button in old combined sketch | Conflicts with final LDR and cannot use `INPUT_PULLUP`. | GPIO32 | Safe internal pull-up input. |
| GPIO15 | Door/servo button in old sketches | Strapping pin can disturb boot when held during reset. | GPIO25 for final door button | Safe internal pull-up input on ESP32 1; servo GPIO25 is on a different board. |
| GPIO5 | Ultrasonic TRIG in old sketches | Strapping pin. | GPIO18 | Already used by the current feeder sketch; safe output. |
| ESP32 2 GPIO14/17/35 | DHT/rain/MQ | No pin defect; wrong final controller responsibility. | Same GPIO numbers on ESP32 1 | Minimal firmware/wiring change and retains ADC1 for MQ. |

All other final GPIOs preserve current proven assignments. Files listed here were not modified.

