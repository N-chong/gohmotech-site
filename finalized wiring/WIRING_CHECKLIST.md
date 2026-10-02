# Pre-Power and Commissioning Checklist

## Hardware identity — mandatory stop points

- [ ] Confirm both boards are classic ESP32 DevKit / ESP32-WROOM-32, not S2/S3/C3.
- [ ] Record exact servo model, rated voltage, running current, and stall current.
- [ ] Record exact ultrasonic model and its VCC/TRIG/ECHO voltage specifications.
- [ ] Record exact rain module model and verify whether DO is 3.3 V-safe.
- [ ] Confirm whether DHT21 is bare/cabled or a module with an onboard DATA pull-up.
- [ ] Record relay module VCC, input thresholds, trigger polarity, contact DC rating, and optocoupler/jumper arrangement.
- [ ] Record actuator voltage, normal/stall current, travel time, and internal limit-switch behavior.
- [ ] Record light voltage and maximum current.
- [ ] Do not continue if any unidentified signal can exceed 3.3 V at an ESP32 GPIO.

## Unpowered inspection

- [ ] Confirm the final GPIO assignments against `GPIO_PIN_MAP.md` and wire labels.
- [ ] Confirm no duplicated GPIO on either board.
- [ ] Confirm GPIO34 and GPIO35 are inputs only.
- [ ] Confirm all three buttons connect GPIO-to-GND, never GPIO-to-3.3/5 V.
- [ ] Confirm MQ-135 divider: AO—12 kΩ—ADC node—22 kΩ—GND.
- [ ] Confirm ultrasonic ECHO divider when required: ECHO—5.6 kΩ—GPIO19—10 kΩ—GND.
- [ ] Confirm DHT pull-up is to 3.3 V and only one suitable pull-up is installed.
- [ ] Confirm LDR divider orientation matches bright-low/dark-high ADC behavior.
- [ ] Confirm servo has separate external power and correct polarity.
- [ ] Confirm servo and ESP32 2 grounds share a low-noise reference.
- [ ] Confirm high-current returns do not flow through ESP32 ground wiring.
- [ ] Confirm relay channels default inactive on an unpowered/reset ESP32.
- [ ] Confirm actuator reversal wiring from an approved diagram; check terminal torque.
- [ ] Confirm OPEN and CLOSE cannot be energized together in hardware/firmware.
- [ ] Confirm DC-rated fuses protect every branch and wire gauge.
- [ ] Confirm flyback suppression on relay coils and bidirectional motor suppression.
- [ ] Confirm electrolytic capacitor polarity and voltage rating.
- [ ] Confirm mains/12 V/logic wiring segregation, strain relief, glands, and enclosure earth.
- [ ] Check resistance between each supply rail and GND for an unexpected short.

## Voltage checks with loads disconnected

- [ ] Check 12 V PSU output and polarity.
- [ ] Adjust/check logic buck output before connecting ESP32: 5.0 V within board tolerance.
- [ ] Adjust/check servo supply before connecting servo: exact nameplate voltage.
- [ ] Check ESP32 3.3 V rail after board-only power-up.
- [ ] Power MQ/rain/ultrasonic interfaces and measure their maximum signal voltage before connecting GPIO.
- [ ] Verify MQ ADC divider output stays below 3.3 V at maximum measured AO.
- [ ] Verify ultrasonic ECHO divider output stays below 3.3 V.

## Staged testing

- [ ] Stage 1: power each ESP32 without relay loads, actuator, light, or servo; confirm repeated stable boots and Wi-Fi.
- [ ] Stage 2: test LDR, DHT21, rain, MQ-135, then ultrasonic one at a time.
- [ ] Stage 3: test feeder, light, and door buttons; one press must create one event after debounce.
- [ ] Stage 4: test relay LEDs/contacts without actuator or light load where possible.
- [ ] Stage 5: connect servo supply and servo; test close/open/close while logging ESP32 resets and rail minimum voltage.
- [ ] Stage 6: test actuator OPEN and CLOSE separately; verify timeout/limits and never both directions.
- [ ] Stage 7: test main-to-server-to-feeder command; one feeder press produces exactly one complete cycle.
- [ ] Stage 8: run full integration including automatic/manual door, light, feeder, all sensors, and feed level.
- [ ] Power-cycle ESP32 1, ESP32 2, router, and server independently; confirm no unexpected motion/feeding.
- [ ] Simulate Wi-Fi/server loss; confirm door stops safely and no feeder command repeats after recovery.
- [ ] Run actuator and servo repeatedly while monitoring 5 V/3.3 V rails, sensor outliers, and Wi-Fi stability.
- [ ] Save calibrated thresholds, measured currents, fuse sizes, and as-built wire colors in `wiring_notes.md`.

