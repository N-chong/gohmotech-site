# GoHMoTech BLE Scanner: Windows Phase 1 Guide

For the deployed Raspberry Pi receiver, see
[the production BLE scanner guide](../deploy/BLE_SCANNER.md). The Windows
Phase 1 notes below describe the earlier development setup.

This guide covers development and acceptance testing for the DX-CP101 beacon
using the Windows laptop as the BLE receiver. Raspberry Pi 5 deployment is not
part of Phase 1.

## Phase 1 architecture

```text
DX-CP101 beacon on goat
        |
        | connectionless BLE advertisements (no pairing)
        v
Windows laptop Bluetooth
        |
        v
ble_scanner.py
        |
        | authenticated heartbeat and observation POST requests
        v
GoHMoTech Django API and database
        |
        +--> Goat Inventory
        +--> Goat Tracking Radar
        +--> Find Goat
        +--> Dashboard BLE summary
```

The scanner never pairs, bonds, opens a GATT connection, or requests an exact
location. It listens for advertisements and reports approximate RSSI
proximity. A single receiver cannot determine direction, coordinates, or an
exact distance in meters.

## Test beacon record

| Field | Registered Phase 1 value |
| --- | --- |
| Goat | `298439` (jericson) |
| Device | `CP101-3E95` |
| MAC | `48:87:2D:9E:3E:95` |
| UUID | `E2C56DB5-DFFB-48D2-B060-D0F5A71096E0` |
| Major / Minor | `1 / 1` |
| Calibrated RSSI | `-57 dBm` |
| Advertising interval | approximately 400-500 ms |
| Configured TX power | +2.5 dBm |

Important acceptance-test finding: an earlier successful raw laptop scan
observed the same MAC and UUID advertising iBeacon Major/Minor `5 / 6`, not
the registered `1 / 1`. The beacon also alternated between iBeacon and
Eddystone frames. The database was deliberately left at `1 / 1` because that
is the requested assignment. Before field acceptance, use the raw scan below
and either reconfigure the physical beacon to `1 / 1` or update the Goat
Inventory assignment to match the confirmed over-air values. Do not create a
second beacon record to work around the mismatch.

A 12-second recheck on 2026-08-18 received no packet. That does not change the
earlier observation; it means the beacon was powered off, asleep, shielded, or
outside the receiver's range during that short window.

## Runtime and dependencies

- Combined Django plus scanner workflow: Python 3.12 or newer.
- Standalone scanner package: Python 3.10 or newer.
- Environment verified for this project: Python 3.14.2.
- BLE library verified: Bleak 3.0.1.
- HTTP reporter: Requests 2.32.5.
- Local configuration loader: python-dotenv 1.2.1.
- Windows Bluetooth must support Bluetooth Low Energy.

The focused scanner dependencies are in
`ble_scanner_service/requirements.txt`. The root `requirements.txt` also
contains them for the complete application.

## 1. Prepare the Windows environment

Open PowerShell in the capstone project directory:

```powershell
cd C:\Users\johnc\OneDrive\Desktop\capstone
```

Use the existing project environment:

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -m pip install -r ble_scanner_service\requirements.txt
```

For a new checkout without a virtual environment:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Confirm the scanner command:

```powershell
.\venv\Scripts\python.exe ble_scanner.py --version
.\venv\Scripts\python.exe ble_scanner.py --help
```

## 2. Verify Windows Bluetooth

1. Open **Settings > Bluetooth & devices**.
2. Turn Bluetooth on.
3. Confirm the laptop Bluetooth adapter is enabled in Device Manager.
4. Optionally inspect healthy Bluetooth devices in PowerShell:

```powershell
Get-PnpDevice -Class Bluetooth | Where-Object Status -eq 'OK'
```

Do not pair CP101-3E95. The scanner uses connectionless advertisements.

## 3. Start the GoHMoTech backend

Apply migrations and check the application:

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
```

Start the Django server in terminal 1:

```powershell
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Keep this terminal running while testing the connected scanner.

## 4. Provision the laptop receiver

The development database already has receiver ID `phase-1-laptop`. Do not
rotate its key if `ble_scanner.local.env` is already working.

For a fresh database only, run:

```powershell
.\venv\Scripts\python.exe manage.py provision_ble_receiver --receiver-id phase-1-laptop --name "My Laptop" --device-name $env:COMPUTERNAME --location "Phase 1 Development Laptop" --platform windows
```

The command prints the receiver key once. Only a one-way hash is stored by the
backend. Copy the safe template:

```powershell
Copy-Item ble_scanner.env.example ble_scanner.local.env
```

Paste the one-time key into `BLE_RECEIVER_KEY`. Never paste the key into this
README, source code, screenshots, issue reports, or Git. The local environment
file is ignored by Git.

If the key is lost, explicitly invalidate it and generate a replacement:

```powershell
.\venv\Scripts\python.exe manage.py provision_ble_receiver --receiver-id phase-1-laptop --platform windows --rotate-key
```

## 5. Verify the Goat Inventory assignment

1. Sign in to GoHMoTech.
2. Open **Goat Inventory**.
3. Open goat `298439`.
4. Confirm the BLE Tracker section is enabled and shows CP101-3E95.
5. Confirm the MAC, UUID, Major, Minor, and calibrated RSSI.

The database prevents duplicate MAC assignments and duplicate
UUID/Major/Minor identities. A goat may exist without a tracker.

## 6. Detect CP101-3E95 locally without the backend

Place the beacon near the laptop and run:

```powershell
.\venv\Scripts\python.exe ble_scanner.py --target-mac 48:87:2D:9E:3E:95 --target-name CP101-3E95 --raw --duration 30 --no-backend
```

Expected startup messages include:

- the active Windows scan started;
- no pairing or connection will be attempted;
- the Bluetooth scanner is listening.

When the beacon advertises, `RAW` and `DETECTED` lines show the available
address, name, protocol, RSSI, UUID, Major, Minor, measured power, and raw
manufacturer/service data.

If the beacon name is not present in every frame, retry without the name filter:

```powershell
.\venv\Scripts\python.exe ble_scanner.py --target-mac 48:87:2D:9E:3E:95 --raw --duration 30 --no-backend
```

To inspect all nearby BLE advertisements for a short diagnostic session:

```powershell
.\venv\Scripts\python.exe ble_scanner.py --show-all --duration 15 --no-backend
```

`--show-all` can reveal identifiers belonging to other nearby BLE devices.
Use it locally and do not publish its output.

## 7. Verify UUID, Major, and Minor

Use the target-MAC raw command and find an output line with
`protocol=ibeacon`. Verify:

- UUID equals `E2C56DB5-DFFB-48D2-B060-D0F5A71096E0`;
- Major equals the intended farm/herd ID;
- Minor equals the intended individual goat ID;
- measured power is plausible for the configured one-meter calibration.

Eddystone frames do not contain iBeacon UUID/Major/Minor fields. Seeing
`protocol=eddystone` for some frames is valid for this CP101 configuration;
wait for an iBeacon frame before comparing those fields.

If the over-air identity is still `5 / 6`, correct the hardware configuration
or the single database assignment before acceptance testing. MAC matching lets
the registered device be recognized during development, but it does not make
conflicting iBeacon identity data correct.

## 8. Run the connected scanner

With terminal 1 still running the backend, open terminal 2:

```powershell
cd C:\Users\johnc\OneDrive\Desktop\capstone
.\venv\Scripts\python.exe ble_scanner.py
```

The scanner automatically loads `ble_scanner.local.env`. Expected messages:

- backend heartbeat accepted for `phase-1-laptop`;
- enabled beacon assignments loaded;
- CP101-3E95 detected;
- backend updated goat `298439`;
- proximity and tracking status reported.

Leave the command running for continuous tracking. Stop it with **Ctrl+C**.
Scanning recovers from failures using exponential retry and periodically
restarts the OS watcher.

## 9. Verify the web interfaces

While the backend and scanner are running:

- Dashboard: `http://127.0.0.1:8000/iot/`
- Goat Tracking Radar: `http://127.0.0.1:8000/iot/tracking/`
- Find Goat 298439:
  `http://127.0.0.1:8000/iot/tracking/find/298439/`
- Goat profile:
  `http://127.0.0.1:8000/iot/inventory/298439/`

Confirm:

1. My Laptop changes to online.
2. Goat 298439 changes to Detected.
3. Current and smoothed RSSI update without a full page refresh.
4. The marker moves between proximity rings, not compass directions.
5. Find Goat becomes stronger when the receiver moves closer.
6. After stopping the scanner, status moves through Possibly Lost and then Out
   of Range instead of changing immediately.

## 10. Test and calibrate RSSI

Use repeatable locations in the goat house:

1. Hold the laptop in a consistent orientation.
2. Keep the beacon in its intended collar position.
3. Record at least 20-30 seconds at each location.
4. Test unobstructed line of sight and realistic obstructions such as a goat,
   wood, metal rails, and people.
5. Compare the smoothed value, not a single raw packet.

Initial database defaults:

| Smoothed RSSI | Initial class |
| --- | --- |
| `>= -50 dBm` | Very Near |
| `-60 to -51 dBm` | Near |
| `-70 to -61 dBm` | Medium |
| `< -70 dBm` | Far |
| no packet for more than 8 seconds | Possibly Lost |
| no packet for more than 20 seconds | Out of Range |

These values are calibration starting points, not permanent physical-distance
claims. Edit the singleton **BLE Tracking Settings** record in Django Admin
after collecting goat-house measurements. The defaults use a rolling median
window of five samples.

Current state is updated frequently. History is saved on proximity changes or
at the configured snapshot interval (30 seconds by default), not for every
advertisement.

## 11. Common Windows troubleshooting

### No advertisement output

- Confirm the beacon is on, Trigger is OFF, and it is close to the laptop.
- Confirm Bluetooth is on and the adapter is healthy.
- Retry with only `--target-mac`; the local name may be omitted from a frame.
- Use a short `--show-all` scan to confirm Windows is receiving any BLE
  advertisements.
- Close beacon configuration apps that may be occupying or changing the
  device.
- Disable and re-enable the Bluetooth adapter, then retry.
- Restart Windows if the Bluetooth watcher remains unavailable.
- Check beacon battery and advertising configuration.

### Scanner says Bluetooth is unavailable

- Ensure Windows Bluetooth is enabled before starting Python.
- Check Device Manager for adapter driver errors.
- Install the laptop manufacturer's current Bluetooth driver.
- Do not run the Windows scanner with `--scan-mode passive`; Windows requires
  the default `active` discovery mode. It remains connectionless.

### Heartbeat or observation cannot reach the backend

- Confirm `manage.py runserver` is still running.
- Confirm `BLE_BACKEND_URL=http://127.0.0.1:8000/iot/api/ble`.
- Confirm receiver ID and key are all present in the local environment file.
- HTTP 401/403 means the receiver ID/key pair is invalid; rotate only if the
  original key is unavailable.
- If the backend runs on another computer, replace `127.0.0.1` with that
  computer's LAN address and allow the Django port through its firewall.

### Beacon is detected but the goat does not update

- Compare the raw MAC and iBeacon identity with the Goat Inventory assignment.
- Check for the known `1/1` versus `5/6` mismatch.
- Confirm Tracking Enabled is selected.
- Confirm the scanner heartbeat reports at least one enabled assignment.
- Check backend logs for an unknown beacon or identity-conflict response.

### RSSI jumps

- This is normal for 2.4 GHz radio around bodies, water, walls, and metal.
- Use smoothed RSSI and repeatable test positions.
- Increase the smoothing window only after measuring its response delay.
- Do not convert one reading into an exact distance.

## 12. Automated verification

```powershell
.\venv\Scripts\python.exe -m unittest discover -s ble_scanner_service\tests -v
.\venv\Scripts\python.exe manage.py test iot.test_ble_api iot.test_ble_tracking --noinput
.\venv\Scripts\python.exe manage.py check
```

## Raspberry Pi 5 preparation — not deployed

The scanner core has no Django dependency and uses Bleak's OS-selected backend.
The same `ble_scanner.py` and `ble_scanner_service` package will be reused
on Linux.

Current preparation assumptions:

- Raspberry Pi OS 64-bit;
- Python 3.10 or newer for the standalone scanner;
- BlueZ 5.55 or newer;
- system D-Bus available;
- Pi can reach the GoHMoTech backend over the LAN;
- each Pi receives its own receiver ID and credential.

Bleak 3.0.1 officially supports Linux with BlueZ 5.55 or newer and uses BlueZ
over D-Bus. See the
[Bleak backend documentation](https://bleak.readthedocs.io/en/latest/backends/)
and
[Bleak Linux backend documentation](https://bleak.readthedocs.io/en/latest/backends/linux.html).

When Phase 1 is accepted, the later Pi workflow will be:

1. Verify `bluetoothctl show` reports a powered adapter.
2. Copy only the application/scanner files needed for deployment.
3. Create a Python environment and install
   `ble_scanner_service/requirements.txt`.
4. Provision a new receiver such as `pi5-goat-house-entrance` with platform
   `raspberry_pi`; never reuse the laptop key.
5. Set `BLE_BACKEND_URL` to the backend computer's LAN URL, not
   `127.0.0.1`, unless Django also runs on the Pi.
6. Test the same command interactively in active mode first.
7. Optionally evaluate `BLE_SCAN_MODE=passive` on BlueZ after active-mode
   verification.
8. Only then create a systemd service with restart and least-privilege rules.

No systemd unit, Linux package installation, Bluetooth permission change, or
Pi deployment has been performed in Phase 1.

If the Pi misses advertisements while Wi-Fi is busy, Bleak's official
[troubleshooting guide](https://bleak.readthedocs.io/en/stable/troubleshooting.html)
notes possible Wi-Fi/Bluetooth coexistence interference on the built-in radio.
Test with reduced Wi-Fi activity or a supported USB Bluetooth adapter before
changing application logic.

Future receivers map to zones such as Entrance, Feeding Area, Resting Area, or
Outdoor Pen. The backend will compare reliable receiver observations for
zone-level estimates only. It will not claim triangulation, compass direction,
or exact coordinates.

## Phase 1 acceptance gate before Pi work

- [ ] CP101-3E95 is consistently visible in Windows raw scans.
- [ ] Physical iBeacon UUID/Major/Minor match the single database assignment.
- [ ] Backend accepts the laptop heartbeat and observations.
- [ ] Goat 298439 updates with raw and smoothed RSSI.
- [ ] Radar and live list update automatically.
- [ ] Find Goat becomes stronger and weaker during a controlled walk test.
- [ ] Possibly Lost and Out of Range timeouts behave as configured.
- [ ] Dashboard counts match the full tracking page.
- [ ] Thresholds are calibrated in the real goat-house environment.
- [ ] Only after every item passes should Raspberry Pi deployment begin.
