# Raspberry Pi BLE receiver

The production receiver is `pi5-gohmotech`. The scanner runs as the
`gohmotech-ble-scanner.service` systemd **user** service. User lingering is
enabled on this Pi, so it starts at boot without an interactive login.

The private receiver credential is in
`/home/gohmotech/.config/gohmotech/ble-scanner.env` (mode `0600`).
`BLE_SCANNER_ENV_FILE` selects this file and skips the development `.env` and
`ble_scanner.local.env`; the old laptop receiver settings must not override
production credentials.

The Pi sends readings through its local production nginx proxy:

```dotenv
BLE_BACKEND_URL=http://127.0.0.1:8080/iot/api/ble
BLE_BACKEND_HOST=gohmotech.site
BLE_RECEIVER_ID=pi5-gohmotech
BLE_RECEIVER_KEY=<private provisioned credential>
BLE_SCAN_MODE=active
BLE_REPORT_INTERVAL_SECONDS=1
BLE_RESTART_INTERVAL_SECONDS=300
```

The Host override is restricted to loopback URLs. Nginx supplies the existing
production forwarding headers. Local ingestion does not depend on public DNS,
Internet access, or the Cloudflare tunnel. The API still authenticates each
request using this receiver's credential.

Manage the installed service as `gohmotech`:

```bash
systemctl --user status gohmotech-ble-scanner.service
systemctl --user restart gohmotech-ble-scanner.service
journalctl _SYSTEMD_USER_UNIT=gohmotech-ble-scanner.service -n 50 --no-pager
```

To reinstall the unit after editing it:

```bash
install -m 644 deploy/user-services/gohmotech-ble-scanner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gohmotech-ble-scanner.service
```

The backend heartbeat loads enabled trackers automatically. No device-name
filter is set because some beacon frames omit the name. BlueZ duplicate-data
filtering is disabled so repeated advertisements can refresh the last-seen
time even when the payload does not change.

For diagnosis, look for `Backend heartbeat accepted`, `DETECTED`, and
`Backend updated goat=...` in the journal. A heartbeat alone confirms receiver
connectivity, not a beacon sighting. Keep the beacon powered and advertising,
and disconnect its phone configuration app during tracking.

On 2026-09-28 the Pi received CP101-3E95 (`48:87:2D:9E:3E:95`) with UUID
`E2C56DB5-DFFB-48D2-B060-D0F5A71096E0`, major `5`, minor `6`, matching the
existing enabled assignment to goat `G001`.

Validation: 19 standalone scanner tests and 20 isolated Django BLE tests passed.
Real advertisements were accepted for G001 at approximately -32 to -35 dBm,
and the tracking snapshot reported `detected` / `very_near`. Local ingestion
completed in approximately half a second without the public HTTPS timeouts.

Reception recovered after a temporary passive controller scan and restoring
the production scanner on 2026-09-28. The production scanner remains in
**active** mode; no experimental BlueZ interfaces were enabled. Between
13:56:42 and 13:59:53 Asia/Manila, it received and saved **112 fresh readings**,
with no errors and a maximum gap of **5.99 seconds**. The user also confirmed
the detector was working. Live signal changes from approximately -66 to
-30 dBm were reflected in the tracking snapshot.

The tracker settings confirmed by the user are **400 ms** advertising interval
and **Trigger OFF**, with the phone configuration app disconnected. Keep the
normal 300-second scanner recovery interval and the existing 8-second
possibly-lost / 20-second out-of-range thresholds.

Diagnostic results before recovery:

| Check | Duration | Other/total radio observations | CP101 sightings |
| --- | --- | --- | --- |
| Active controller capture | 30 seconds | 187 reports from 5 devices | 0 |
| Wi-Fi power saving disabled | 35 seconds | 409 reports from 3 devices | 0 |
| Temporary native passive scan | 30-second scan | 461 reports from 8 devices | 72 |

Shorter watcher restarts, an explicit RSSI filter, and a Bluetooth power cycle
did not restore reception on their own. These experiments were reverted.
Wi-Fi power saving was restored to its original **on** setting after the
comparison. Wi-Fi stayed connected throughout. The precise cause of the
earlier radio reception failure remains unconfirmed; passive scanning was a
successful diagnostic, followed by successful active scanning.

If reception fails again, this diagnostic captures controller packets and the
scanner's output together. It requires administrator authentication:

```bash
bash /home/gohmotech/capstone/deploy/capture_ble_controller.sh
```

Run this as the normal `gohmotech` user. It requests sudo for a 30-second `btmon`
capture, restarts the existing user scanner once to capture its scan parameters,
and saves private controller and scanner logs under
`/tmp/gohmotech-ble-controller.XXXXXX`. It does not change Wi-Fi settings.
Compare actual HCI advertisements with the scanner log before changing radio
configuration or recommending additional hardware.
