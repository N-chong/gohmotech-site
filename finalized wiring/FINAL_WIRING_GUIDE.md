# GoHMoTech Final Wiring Guide

## Release status

This is the finalized **wiring configuration** for a classic ESP32 DevKit / ESP32-WROOM-32 installation. It is based on these current repository sketches:

- `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`
- `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino`

No existing sketch was moved, deleted, renamed, or overwritten. The pin map is safe to build only after the exact hardware identity/nameplate gates in `WIRING_CHECKLIST.md` are completed. The repository does not identify the servo, ultrasonic module, rain interface, actuator current, or relay contact topology precisely enough to guess those ratings.

`SOURCE_GPIO_AUDIT.md` records every ESP32 sketch variant found, its assigned pins, and why the two current split sketches—not the older combined/test files—were used as the starting point.

The final ownership is:

```text
ESP32 1: door relays + light relay + LDR + DHT21 + rain + MQ-135 + 3 buttons
ESP32 2: feeder servo + ultrasonic feed-level sensor
```

## Final maps

### ESP32 1

| Device | Pin | GPIO | Interface |
| --- | --- | ---: | --- |
| Door relay CLOSE | IN1 | 26 | Active-LOW output on verified existing board |
| Door relay OPEN | IN2 | 27 | Active-LOW output on verified existing board |
| Light relay | IN3/IN | 13 | Active-LOW output on verified existing board |
| LDR | Divider node | 34 | ADC1 input, 0–3.3 V |
| DHT21 | DATA | 14 | 3.3 V digital input |
| Rain module | DO | 17 | 3.3 V binary digital input |
| MQ-135 module | AO | 35 | ADC1 through 12 kΩ / 22 kΩ divider |
| Feeder button | Signal | 32 | `INPUT_PULLUP`, pressed LOW |
| Light button | Signal | 33 | `INPUT_PULLUP`, pressed LOW |
| Door button | Signal | 25 | `INPUT_PULLUP`, pressed LOW |

### ESP32 2

| Device | Pin | GPIO | Interface |
| --- | --- | ---: | --- |
| Feeder servo | Signal | 25 | 3.3 V PWM, external servo power |
| Ultrasonic | TRIG | 18 | 3.3 V output |
| Ultrasonic | ECHO | 19 | Input through 5.6 kΩ / 10 kΩ divider for a 5 V sensor |

See `GPIO_PIN_MAP.md` for the detailed tables, avoided pins, and every changed assignment.

## Step-by-step physical installation

### 1. Prepare the enclosure and power distribution

1. Disconnect AC and verify absence of voltage.
2. Mount the certified 12 V PSU, distribution/fuse blocks, logic buck, servo buck/BEC, relay/driver, terminal blocks, and both ESP32 boards on standoffs.
3. Segregate mains, 12 V high-current, 5 V power, and sensor/signal cable ducts.
4. Set both buck outputs with no electronics connected. Label the logic 5 V and servo-voltage rails separately.
5. Install branch fuses near the distribution source. Final values come from nameplate/stall current and wire ampacity.
6. Build the ground star described in `POWER_DISTRIBUTION.md`. Run actuator and servo returns directly to their branches, not through an ESP32 ground terminal.

### 2. Wire ESP32 1 low-voltage signals

1. Wire GPIO26 to relay CLOSE/IN1, GPIO27 to OPEN/IN2, and GPIO13 to light IN. Confirm the input side is genuinely 3.3 V compatible.
2. Wire the LDR divider: 3.3 V—10 kΩ—GPIO34 node—LDR—GND. Add 100 nF from GPIO34 to GND.
3. Wire DHT21 VCC to 3.3 V, GND to GND, DATA to GPIO14, and add a 4.7 kΩ DATA-to-3.3 V pull-up only if the installed sensor lacks one.
4. Wire rain DO to GPIO17 only after confirming its HIGH is ≤3.3 V. Use 3.3 V module supply when its datasheet permits.
5. Power MQ-135 from regulated 5 V and GND. Wire AO through 12 kΩ to GPIO35; connect 22 kΩ from GPIO35 to GND and 100 nF from GPIO35 to GND.
6. Wire normally-open buttons from GPIO32, GPIO33, and GPIO25 to GND. Label FEED, LIGHT, and DOOR.
7. Add 470 µF and 100 nF at the ESP32 1 5 V input.

### 3. Wire ESP32 2

1. Connect servo signal to GPIO25. Connect servo V+ directly to its dedicated supply and servo GND directly to that supply return.
2. Join ESP32 2 GND to the servo ground reference at the defined star/branch junction.
3. Fit 1000–2200 µF plus 100 nF at the servo power connector.
4. After identifying the ultrasonic sensor, connect VCC/GND to its rated supply and TRIG to GPIO18.
5. For a 5 V ECHO, connect ECHO—5.6 kΩ—GPIO19 and GPIO19—10 kΩ—GND. Fit 10–47 µF plus 100 nF at sensor VCC.
6. Add 470 µF and 100 nF at ESP32 2's 5 V input.

### 4. Wire switched loads

1. Use the actuator manufacturer's reversal diagram or a rated reversing driver. Verify limit switches and contact DC/stall-current ratings.
2. Fit the selected bidirectional TVS/snubber close to the actuator/driver. Do not use a single polarity diode across a reversing motor.
3. Wire the light through appropriately rated relay contacts and its fused branch.
4. With ESP32 boards disconnected, verify continuity, insulation, polarity, fuse placement, and that no relay combination shorts 12 V.

### 5. Label and inspect

Label both ends of every conductor with board, GPIO, function, voltage, and destination. Record wire colors, fuse ratings, exact models, and calibration values in `wiring_notes.md`. Use ferrules/locking connectors and strain relief; do not use solderless breadboards or loose Dupont jumpers for permanent installation.

## Voltage dividers and resistors

| Function | Upper resistor (source to GPIO) | Lower resistor (GPIO to GND) | Output at 5.00 V | Notes |
| --- | ---: | ---: | ---: | --- |
| MQ-135 AO | 12 kΩ | 22 kΩ | 3.235 V | Ratio 0.6471; add 100 nF at ADC node. |
| HC-SR04-style ECHO | 5.6 kΩ | 10 kΩ | 3.205 V | 1% values recommended. |
| 5 V rain DO, only if needed | 5.6 kΩ | 10 kΩ | 3.205 V | Prefer a 3.3 V-compatible interface or logic shifter. |

Other required resistors:

- LDR divider: 10 kΩ fixed, with LDR orientation shown in `ESP32_MAIN_WIRING.md`.
- DHT21 DATA: 4.7 kΩ to 3.3 V if not already present.
- Optional long-button protection: 1 kΩ series plus 100 nF GPIO-to-GND; confirm debounce timing after fitting.

## Existing-code findings and required firmware changes

The current main sketch safely controls only door, light, and LDR. The current environment/feeder sketch safely assigns DHT14, rain17, ultrasonic18/19, MQ35, and servo25, but combines responsibilities that the final architecture separates.

Required changes before permanent unattended use:

1. Add DHT21 GPIO14, rain GPIO17, and MQ-135 GPIO35 acquisition/reporting to ESP32 1; remove those initializations from ESP32 2.
2. Add the three `INPUT_PULLUP` buttons to ESP32 1 with the debouncer in `FIRMWARE_INTEGRATION.md`.
3. Keep the proven ESP32 1 relay/LDR and ESP32 2 servo/ultrasonic assignments.
4. Scale MQ-135 voltage for the 12 kΩ/22 kΩ divider before calculating sensor resistance.
5. Keep the door mutual-exclusion interlock, 150 ms reversal dead time, and measured maximum run time.
6. Send the feeder button to the feeder device through the server; never attach a servo to ESP32 1.
7. ESP32 2 must accept only a new feeder `off -> on` transition, ignore commands while feeding, close on timeout, and sync `off` after completion.
8. On any reset, initialize relays inactive and servo closed before Wi-Fi/network work.

The finalized wiring folder intentionally does not contain duplicated full sketches: the existing sketches include installation-specific credentials/TLS material and have not yet been hardware-verified with the newly moved sensors. `FIRMWARE_INTEGRATION.md` is the wiring-specific, reviewable change set to apply to copies when the exact modules have passed the checklist.

## Communication decision

Use the existing server/API over Wi-Fi. It already supports per-device desired actuator state, authenticated ESP32 polling, and state sync. It aligns physical-button actions with dashboard/scheduled automation and avoids another radio or cable protocol.

Tradeoffs:

| Method | Result |
| --- | --- |
| Existing API | **Selected.** Lowest architecture change; logged and centrally visible; depends on Wi-Fi/server; current polling adds latency. |
| ESP-NOW | Good offline/low-latency backup but adds pairing, channel coexistence, security keys, and a second command path. |
| UART | Good deterministic offline link at short range; requires protected wiring/shared ground and framing/CRC/ACK; unsuitable for long unprotected field cable. |

The API's stored `on` state plus edge-triggered feeder firmware prevents normal poll duplicates, but the current contract has no unique command UUID. It cannot mathematically guarantee exactly once across a reset at the wrong instant. Add persistent command IDs if duplicate feeding has a material animal-health consequence.

## Staged testing procedure

### Stage 1 — ESP32 power

Power each board with high-current loads disconnected. Verify 5 V and 3.3 V rails, boot logs, Wi-Fi, server authentication, and at least 30 minutes without resets.

### Stage 2 — sensors

Connect and test one at a time: LDR (bright/dark direction), DHT21, rain dry/wet, MQ-135 after warm-up, and ultrasonic at known distances. Confirm no GPIO exceeds 3.3 V and calibrate installed positions.

### Stage 3 — manual buttons

Test each button with a serial event counter. Tap, hold, release slowly, and create contact bounce deliberately. Every complete press/release must generate no more than one action. Confirm automatic schedules/rules remain enabled.

### Stage 4 — relays

Test logic and contacts with loads absent or a safe low-current test load. Confirm boot/reset never energizes a relay and OPEN/CLOSE are mutually exclusive.

### Stage 5 — servo

Connect the dedicated servo supply, command one cycle, and observe supply minimum voltage/reset logs. Test obstruction carefully within servo/mechanism ratings; verify close-on-timeout.

### Stage 6 — linear actuator

Test OPEN and CLOSE separately. Verify physical direction, end limits, stop timeout, reversal dead time, current, contact temperature, and TVS/snubber behavior. Immediately disconnect if both directions energize.

### Stage 7 — ESP32 communication

From feeder state `off`, press once and verify: one API state change, one feeder transition, one servo cycle, and state returns to `off`. Test held button, rapid repeated press, lost Wi-Fi, server restart, and both ESP32 resets. Resolve any stale `on` behavior before proceeding.

### Stage 8 — full integration

Test automatic/manual door, automatic/manual light, scheduled/physical feeder, environmental telemetry, and feed level. Operate actuator and servo during Wi-Fi transfers and monitor for resets, false rain/button events, ADC spikes, and disconnects. Run a supervised soak test before permanent unattended service.

## Technical references

- Espressif's ESP32 documentation identifies GPIO34–39 as input-only without internal pull resistors, the strapping pins, and the ADC2/Wi-Fi limitation: <https://documentation.espressif.com/esp32_datasheet_en.html>
- Espressif recommends ADC1 when Wi-Fi is active and a 0.1 µF ADC filter capacitor: <https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html>
- Winsen specifies MQ-135 5.0 V heater/circuit supply, up to 950 mW heater consumption, and more than 48 hours initial preheat: <https://www.winsen-sensor.com/manual/mq135.html>
