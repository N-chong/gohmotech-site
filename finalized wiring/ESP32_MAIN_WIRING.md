# ESP32 1 — Main Controller Wiring

Controller: **GoHMoTech Door Light LDR Controller** (`gohmotech_esp32_002` in the existing firmware).

## Door actuator and relays

Connect GPIO26 to relay IN1/CLOSE and GPIO27 to relay IN2/OPEN. Keep the existing active-LOW logic only for the relay module that was physically verified. Initialize both GPIO output latches to the inactive level before changing their modes to `OUTPUT`.

The relay contact wiring must be a documented reversing circuit rated for the actuator's **12 V DC stall current**, or a purpose-built H-bridge actuator driver. Do not infer contact wiring from the IN1/IN2 labels. Confirm the actuator's internal limit switches; the firmware timeout is backup protection, not a substitute for limit switches.

Required control rules:

1. Release both direction relays.
2. Wait at least 150 ms before reversing.
3. Energize only OPEN or CLOSE.
4. Stop at the measured travel timeout or an end-limit input if fitted.
5. On boot, reset, Wi-Fi loss, or invalid command, release both relays.

For a reversing actuator, do not install a single ordinary flyback diode directly across the motor because the normal polarity reverses. Use a correctly selected bidirectional TVS/snubber at the motor/driver and relay contacts. Relay coils need flyback suppression; most modules contain it, but verify the schematic.

## Light relay

GPIO13 connects to the relay input only. The light is powered from its own rated branch through the relay contacts. Confirm contact voltage/current rating and DC rating. Never run lighting current through the ESP32 board.

## LDR divider

Wire the divider so it matches the existing firmware convention (bright = lower ADC, dark = higher ADC):

```text
3.3 V ---- 10 kΩ fixed ----+---- GPIO34
                            |
                           LDR
                            |
                           GND

Optional: 100 nF from GPIO34/divider node to GND
```

GPIO34 is ADC1 and works while Wi-Fi is active. It is input-only, which is correct for this use. Re-measure `LDR_BRIGHT_ADC` and `LDR_DARK_ADC` after permanent mounting because enclosure position and resistor tolerance change the calibration.

## DHT21 / AM2301

- VCC: 3.3 V
- GND: sensor ground
- DATA: GPIO14
- Add 4.7 kΩ from DATA to 3.3 V for a bare sensor/cabled probe unless measurement confirms the installed module already includes a pull-up.
- Add 100 nF across VCC/GND near the sensor.

Do not pull DATA to 5 V. Inspect the exact module PCB or measure resistance from DATA to VCC with power removed before deciding that an onboard pull-up exists.

## Rain sensor

The current server schema and firmware use only `rain_detected`, so the final minimal-change choice is **digital DO on GPIO17**. Power the comparator/interface at 3.3 V if its exact datasheet permits. With the device powered, measure DO in both states before connection; it must stay within 0–3.3 V.

If the installed board requires 5 V and drives DO to 5 V, use a proper level shifter or the same 5.6 kΩ upper / 10 kΩ lower divider described for ultrasonic ECHO. If rainfall intensity becomes a real requirement, use AO on a free ADC1 input such as GPIO36, protect it to 3.3 V, and update firmware/schema deliberately. Do not connect AO and DO to the same GPIO.

Mount the exposed rain plate away from high-current cables. Continuous DC excitation can corrode common resistive plates; use a corrosion-resistant/rain-specific module or switch its excitation only during measurement if supported.

## MQ-135 module

The MQ-135 sensing circuit and heater are nominal 5 V loads. Power the module from the regulated 5 V sensor branch, never from a GPIO. Budget up to roughly 1 W for the heater plus module electronics and allow the manufacturer's initial burn-in/warm-up before treating readings as meaningful.

Protect GPIO35 because a 5 V module's AO can exceed 3.3 V:

```text
MQ-135 AO ---- 12 kΩ ----+---- GPIO35
                         |
                        22 kΩ
                         |
                        GND

100 nF from GPIO35 to GND, close to ESP32
```

At a worst-case 5.00 V AO, the ESP32 node is `5 × 22 / (12 + 22) = 3.235 V`. Divider ratio is 0.6471. To reconstruct module AO in firmware, multiply the measured ADC-node voltage by `34/22 = 1.5455`. The existing code currently reports ADC-node voltage and must not label it as the undivided module output.

MQ-135 ppm is not valid from an arbitrary raw ADC value. Record clean-air baseline/R0 after burn-in, temperature/humidity compensation, and calibration against a reference if ppm is required.

## Momentary buttons

Wire each normally-open button between its assigned GPIO and GND:

```text
GPIO32 ---- feeder button ---- GND
GPIO33 ---- light button  ---- GND
GPIO25 ---- door button   ---- GND
```

Use `INPUT_PULLUP`: idle HIGH, pressed LOW. Keep button runs short; for long outdoor runs use twisted signal/GND pairs, ESD protection, and optionally a 1 kΩ series resistor plus 100 nF at the controller.

Debounce on both edges with a non-blocking 40–60 ms stable-state interval. Act only on the debounced HIGH-to-LOW transition, then require a debounced release before accepting another press. A 750 ms minimum action lockout is additional protection, not the primary debounce.

Manual actions must be momentary requests, not a permanent `manual` mode:

- Light button toggles the current desired light state, syncs it to the server, and leaves scheduled automation enabled.
- Door button issues one safe OPEN/CLOSE transition through the same motor interlock and timeout as automatic commands.
- Feeder button does not touch a servo. It writes feeder state `on` for device `kamotech_esp32_001` through the existing authenticated API. ESP32 2 performs and acknowledges the cycle.

Do not let a server poll immediately undo a local button command: update the local last-command state when the button action is accepted, then sync the new desired state.

