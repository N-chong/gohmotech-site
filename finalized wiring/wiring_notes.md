# As-Built Wiring Notes

This file is intentionally a commissioning record. Fill every `TBD` from labels, datasheets, or measurements; do not guess.

## Hardware inventory

| Item | Exact model / marking | Rated voltage | Maximum/stall current | Serial/asset note |
| --- | --- | --- | --- | --- |
| ESP32 1 | TBD | TBD | TBD | Main controller |
| ESP32 2 | TBD | TBD | TBD | Feeder controller |
| 12 V PSU | TBD | TBD | TBD | TBD |
| Logic buck | TBD | TBD | TBD | Output set to: TBD V |
| Servo buck/BEC | TBD | TBD | TBD | Output set to: TBD V |
| Linear actuator | TBD | TBD | TBD | Travel time: TBD s |
| Light | TBD | TBD | TBD | TBD |
| Relay module | TBD | TBD | TBD | Active LOW/HIGH: TBD |
| Servo | TBD | TBD | TBD | Closed/open angles: TBD |
| Ultrasonic | TBD | TBD | TBD | ECHO max: TBD V |
| DHT21 | TBD | TBD | TBD | Onboard pull-up: yes/no |
| Rain module | TBD | TBD | TBD | DO max: TBD V |
| MQ-135 module | TBD | 5 V expected; verify | TBD | Burn-in date: TBD |

## Branch protection and wire record

| Branch | Fuse | Wire gauge | Connector | Measured peak current |
| --- | --- | --- | --- | --- |
| Actuator | TBD | TBD | TBD | TBD |
| Lighting | TBD | TBD | TBD | TBD |
| Logic 5 V | TBD | TBD | TBD | TBD |
| Servo supply | TBD | TBD | TBD | TBD |

## Calibration record

- LDR bright ADC: TBD
- LDR dark ADC: TBD
- Rain threshold/comparator setting: TBD
- MQ-135 R0/reference procedure: TBD
- Ultrasonic full distance: TBD cm
- Ultrasonic empty distance: TBD cm
- Door OPEN travel time: TBD ms
- Door CLOSE travel time: TBD ms
- Servo closed angle: TBD degrees
- Servo open angle: TBD degrees

## Change control

Any deviation from `GPIO_PIN_MAP.md` must record the old GPIO, new GPIO, reason, firmware commit, test result, date, and installer. Do not update wiring without updating firmware and labels in the same maintenance window.

