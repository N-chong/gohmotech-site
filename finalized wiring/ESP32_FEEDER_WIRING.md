# ESP32 2 — Feeder Controller Wiring

The finalized feeder controller contains only the servo, ultrasonic feed-level sensor, Wi-Fi/API command handling, and the existing onboard status LED.

## Servo

- Signal: ESP32 GPIO25 (existing proven assignment)
- Servo V+: dedicated regulated supply at the servo nameplate voltage, commonly 5–6 V but **verify the exact servo**
- Servo GND: dedicated supply return joined to ESP32 GND at the low-voltage star point
- ESP32 GPIO supplies signal only

Select the servo supply and wiring from the servo's **stall current**, not its no-load current. Until the model is identified, do not finalize the supply current rating. A practical design margin is at least 1.5× the measured/data-sheet stall current while remaining within connector and wire ratings.

At the servo connector, fit:

- 1000–2200 µF low-ESR electrolytic across servo V+/GND (voltage rating at least 10 V for a 5–6 V rail)
- 100 nF ceramic across servo V+/GND

Use short, adequately sized power wires. Route the signal with a ground reference and away from motor/actuator wiring. Do not feed servo current through the ESP32 5 V pin, USB connector, breadboard rail, or onboard regulator.

## Ultrasonic sensor

The repository calls the device only “ultrasonic”; it does **not identify the exact model**. Read the part marking before power-up.

For a standard 5 V HC-SR04-style module:

```text
5 V ------------------------ VCC
ESP32 GPIO18 --------------- TRIG
Sensor ECHO -- 5.6 kΩ --+--- ESP32 GPIO19
                         |
                        10 kΩ
                         |
GND ---------------------+--- Sensor GND and ESP32 GND
```

The divider produces `5 × 10 / (5.6 + 10) = 3.205 V` at GPIO19. Use 1% resistors. The 3.3 V TRIG level usually works with HC-SR04-style inputs, but confirm against the exact installed sensor. If it does not, use a 3.3-to-5 V logic buffer; do not connect its 5 V output back to ESP32.

For a genuinely 3.3 V-compatible model, follow that model's datasheet and omit the divider only if ECHO is guaranteed ≤3.3 V. A waterproof single-wire sensor (for example, some JSN variants) is not pin-compatible; do not apply this table blindly.

Add 100 nF plus 10–47 µF near ultrasonic VCC. Mount it perpendicular to the feed surface, outside the fill stream, and calibrate full/empty distances after permanent installation.

## Communication with ESP32 1

Use the existing GoHMoTech HTTPS/API architecture as the primary command path:

```text
Button press on ESP32 1
  -> debounced falling edge (one event)
  -> authenticated POST: feeder state = on for kamotech_esp32_001
  -> server stores desired state
  -> ESP32 2 polls its existing command endpoint
  -> ignores command if already feeding or already consumed
  -> performs exactly one timed servo cycle
  -> authenticated state sync: feeder = off
```

This reuses `/iot/api/actuators/esp32_sync_state/` and `/iot/api/actuators/esp32_commands/` already present in the project. It has about the existing poll interval of latency and requires the server/Wi-Fi path. It is simpler and consistent with dashboard/scheduled commands.

Duplicate controls:

1. Main board generates only one event per debounced press/release.
2. Main board does not retry an accepted HTTP 2xx request as a new action.
3. Server stores a level (`on`), not a stream of repeated pulses.
4. Feeder board starts only on a new `off -> on` transition and refuses while `feeding == true`.
5. Feeder returns server state to `off` only after closing the servo.
6. A booted feeder must initialize its last observed state without dispensing if it finds a stale `on`; clear/test stale commands during commissioning.

The existing endpoint does not provide a unique command ID/atomic acknowledgement, so it is not exactly-once across every reset or lost response. For animals where an extra portion is safety-critical, add a server command UUID and persistent consumed-ID storage before unattended operation.

ESP-NOW offers offline low latency but adds channel/key/provisioning complexity and Wi-Fi coexistence considerations. UART offers deterministic offline behavior but needs a protected cable and shared ground between enclosures. Use UART only if offline feeder-button operation is mandatory; then use framed messages with sequence number, CRC, ACK, and retry. Do not run unprotected 3.3 V UART over long outdoor wiring.

