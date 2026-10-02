# Power Distribution and Noise Control

## Final architecture

Exact PSU and fuse ratings cannot be frozen until the actuator, lighting, relay, and servo nameplate currents are recorded. The topology is final; component current ratings remain a commissioning gate.

```text
AC MAINS
   |
   +-- RCD/GFCI + disconnect + correctly rated AC fuse/breaker
   |
   v
Isolated certified 12 V DC PSU
   |
   +-- Fuse A --> 12 V linear actuator / rated reversing relay contacts
   |              (bidirectional TVS/snubber at motor/driver)
   |
   +-- Fuse B --> 12 V lighting, only if the installed light is rated 12 V
   |
   +-- Fuse C --> 12 V-to-5 V logic buck (low-noise, regulated)
   |                 +-- ESP32 1 at board 5V/VIN input
   |                 +-- ESP32 2 at board 5V/VIN input
   |                 +-- compatible 5 V relay coils/module
   |                 +-- MQ-135 module/heater
   |                 +-- 5 V ultrasonic sensor
   |                 +-- 3.3 V sensors from ESP32 3V3 only within regulator budget
   |
   +-- Fuse D --> separate 12 V-to-servo-voltage buck/BEC
                     +-- feeder servo only
```

Do not feed a regulated 5 V source into the ESP32 3V3 pin. Feed the correct board `5V`/`VIN` input only after confirming the specific development board schematic. Never power an ESP32 simultaneously from USB and an external 5 V rail unless the board provides safe source isolation.

Do not power an actuator, motor, servo, light, relay coil, MQ heater, or ultrasonic module from a GPIO. The ESP32 3.3 V output may power only compatible low-current sensors within the specific board regulator's remaining budget.

## Grounding

For the recommended non-isolated low-voltage design:

```text
12 V PSU negative / low-voltage star point
   |
   +-- actuator power return (separate heavy pair)
   +-- lighting return (separate pair)
   +-- logic buck IN-
   |     +-- ESP32 1 GND
   |     +-- ESP32 2 GND
   |     +-- relay logic GND
   |     +-- LDR, DHT21, rain, MQ-135, ultrasonic grounds
   |
   +-- servo buck/BEC IN-
         +-- servo GND
         +-- ESP32 2 GND reference at star/logic junction
```

Use a star or branched distribution block. Do not daisy-chain actuator or servo return current through either ESP32 ground conductor. ESP32 2 and the servo supply must share a signal reference. ESP32 and sensor grounds must share a reference. Buck input/output grounds are normally common unless the converter is explicitly isolated.

Relay **contacts** provide galvanic isolation from their coils; do not connect load power to ESP32 GPIO ground through the contacts. If the relay module is deliberately wired for true optocoupler isolation with separate JD-VCC/VCC domains, preserve the manufacturer's isolation scheme and do not bridge grounds across the isolation barrier. Most jumper-fitted hobby relay boards are not truly isolated.

Protective earth belongs on the PSU/enclosure terminal specified by the manufacturer, not on an ESP32 GND pin. Mains wiring must stay in a segregated, touch-safe compartment and be installed by a qualified person under local rules.

## Supply sizing and fusing

Record these measured/data-sheet maxima:

```text
12 V PSU current >= actuator stall + lighting + both buck input currents + 25% margin
Logic 5 V buck   >= ESP32 peaks + relay coils + MQ-135 + ultrasonic + 30% margin
Servo supply     >= servo stall current with at least 50% transient margin
```

Place a fuse close to each source/distribution output. Size fuses to protect wire and connectors, not merely the load. Use a DC-rated fuse and relay/contact rating. Do not guess actuator stall current; measure with an appropriate method or use manufacturer data.

## Decoupling and suppression

| Location | Recommended starting value | Purpose |
| --- | --- | --- |
| Each ESP32 5 V input | 470 µF electrolytic + 100 nF ceramic | Wi-Fi/current transient support |
| Servo connector | 1000–2200 µF low-ESR + 100 nF ceramic | Servo startup/stall spikes |
| Ultrasonic VCC | 10–47 µF + 100 nF | Local pulse-current filtering |
| DHT21 VCC | 100 nF | Local digital sensor bypass |
| MQ-135 5 V module branch | 100 µF + 100 nF | Heater/module rail filtering |
| LDR ADC node | 100 nF to GND | ADC noise filtering |
| MQ-135 ADC node | 100 nF to GND | ADC/noise filtering after divider |
| 12 V distribution | 470–1000 µF, voltage rating ≥25 V | Branch transient support; confirm converter/PSU stability |

Capacitors do not compensate for an undersized supply or thin wire. Observe electrolytic polarity and temperature/ripple ratings.

For the actuator, use a bidirectional TVS selected from the actual 12 V rail maximum and motor energy, plus an RC contact snubber if required by the relay/driver manufacturer. Place suppression close to the noise source. Keep actuator/lighting/servo power pairs separate from sensor cables; cross at right angles. Twist each high-current supply with its return and use shielded/twisted pairs for long low-level signals. Terminate cable shields at one end unless the enclosure grounding design calls for otherwise.

