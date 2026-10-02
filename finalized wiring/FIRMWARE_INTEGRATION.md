# Final Wiring Firmware Integration

This is the code-level contract for copies of the two existing sketches. It prevents wiring documentation and firmware from drifting while keeping the working originals intact.

## Non-blocking one-event button implementation

Use one instance per button. This accepts a new state only after it remains stable for 50 ms and emits only the debounced press edge.

```cpp
struct DebouncedButton {
  uint8_t pin;
  bool raw = HIGH;
  bool stable = HIGH;
  uint32_t changedAt = 0;

  void begin() {
    pinMode(pin, INPUT_PULLUP);
    raw = stable = digitalRead(pin);
    changedAt = millis();
  }

  bool pressed(uint32_t now) {
    const bool sample = digitalRead(pin);
    if (sample != raw) {
      raw = sample;
      changedAt = now;
    }
    if (raw != stable && now - changedAt >= 50) {
      stable = raw;
      return stable == LOW;  // exactly one event per debounced press
    }
    return false;
  }
};

DebouncedButton feedButton{32};
DebouncedButton lightButton{33};
DebouncedButton doorButton{25};
```

Call all three `begin()` methods in `setup()`. Call `pressed(millis())` on every loop, not inside the 5-second network poll block. Never use `delay(200)` as button debounce; it blocks motor safety timing and can still repeat on a held button in a naïve loop.

## Main-controller event rules

```cpp
void handleButtons(uint32_t now) {
  if (feedButton.pressed(now)) requestRemoteFeedOnce();
  if (lightButton.pressed(now)) requestLightToggle();
  if (doorButton.pressed(now)) requestDoorToggleSafely();
}
```

- `requestRemoteFeedOnce()` POSTs feeder `on` for `kamotech_esp32_001` to `/iot/api/actuators/esp32_sync_state/` with `triggered_by: physical_button`. It never drives a servo.
- `requestLightToggle()` calls the same relay function used by automation, updates the local last-command value, then syncs desired state. It does not permanently set an automation-disabled flag.
- `requestDoorToggleSafely()` calls the existing `startDoorMotor()`/`stopDoorMotor()` path so automatic and manual operation share the same interlock and timeout.

Example feeder request body:

```json
{
  "device_id": "kamotech_esp32_001",
  "actuator_type": "feeder",
  "state": "on",
  "triggered_by": "physical_button"
}
```

Only an HTTP 2xx means accepted. Do not turn an ambiguous timeout into repeated dispense requests. Show/log the failure and allow a new physical press. A future server-side `command_id` is the correct basis for safe retries.

## Feeder-controller transition rule

```cpp
void applyFeederCommand(const String& state) {
  if (state == lastFeederCommand) return;
  const String previous = lastFeederCommand;
  lastFeederCommand = state;
  if (previous == "off" && state == "on" && !feeding) {
    startFeeding();
  }
}
```

After the timed cycle closes the servo, POST feeder `off` through the existing sync endpoint. Set `lastFeederCommand = "off"` only consistently with the acknowledged/stored state. Refuse a second start while `feeding` is true.

At boot, close the servo before networking. For commissioning, clear server feeder state to `off`. With the current API contract, do not automatically execute a pre-existing `on` discovered at boot; treat it as stale and require an operator/server reset unless a future command UUID proves it is new.

## Sensor scaling changes

For the 12 kΩ/22 kΩ MQ divider:

```cpp
constexpr float MQ_DIVIDER_GAIN = 34.0f / 22.0f;
float adcNodeVolts = /* calibrated ADC conversion */;
float mqModuleAoVolts = adcNodeVolts * MQ_DIVIDER_GAIN;
```

Do not assume `raw / 4095 * 3.3` is a calibrated ESP32 voltage. Use the Arduino core's calibrated millivolt API where supported or calibrate the installed ADC against a meter. Apply any R0/ppm formula to the reconstructed module voltage and verified circuit/load resistance.

## Required pin constants

Use the constants in `GPIO_PIN_MAP.md`. Before uploading, search the finalized copy for all `#define`, `pinMode`, `analogRead`, `digitalRead`, `digitalWrite`, and servo `attach` calls and confirm there are no old GPIO15, button GPIO34, or ultrasonic GPIO5 assignments.

