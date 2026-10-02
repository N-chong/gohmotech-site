# Door, light, and LDR controller setup

This firmware connects to the production API through validated HTTPS. It is
registered as `gohmotech_esp32_002` and polls only its door/light commands.

## Relay wiring

The dedicated controller expects a 4-channel relay module wired as follows:

| Relay input | ESP32 | Function |
| --- | ---: | --- |
| IN1 | GPIO 26 | Door close |
| IN2 | GPIO 27 | Door open |
| IN3 | GPIO 13 | Light |

Connect relay-module GND to ESP32 GND. Power the relay module using the voltage
specified on the module; do not power relay coils from an ESP32 GPIO.

The installed relay board was physically verified as active-low: IN1 and IN2
were both illuminated when held LOW. The sketch therefore uses
`RELAY_ACTIVE_LOW true`, making HIGH the safe/released state. Only change that
setting if the relay board is replaced. When idle, the IN1 and IN2 indicator
LEDs must both be off. If the door direction is reversed, swap
`DOOR_OPEN_RELAY_PIN` and
`DOOR_CLOSE_RELAY_PIN`; do not swap polarity logic.

Before compiling:

1. Copy `device_secrets.h.example` to `device_secrets.h`.
2. Replace `YOUR_DEVICE_API_KEY` with the production
   `PRODUCTION_IOT_DEVICE_API_KEY` value. Do not add quotes around the value
   beyond the quotes already in the C++ declaration.
3. Keep `device_secrets.h` local; it is ignored by Git.
4. Select the correct ESP32 board and serial port, then upload the sketch.
5. Open Serial Monitor at 115200 baud.

After upload, test with the actuator disconnected from mains/motor power first:

1. At startup, IN1 and IN2 must both be released.
2. Send Open: only IN2 should click and illuminate, then release after 10 seconds.
3. Send Close: only IN1 should click and illuminate, then release after 10 seconds.
4. Send Light ON/OFF: only IN3 should change.

Never continue testing if IN1 and IN2 are energized at the same time.

A working controller reports `WiFi connected`, then HTTP 201 for LDR uploads.
Command polls should return HTTP 200. HTTP 403 means the device key does not
match production; HTTP 404 means the device ID is not registered. A negative
HTTP status indicates Wi-Fi, DNS, TLS, or connection failure and should be
reported with the exact numeric status, never with the key.
