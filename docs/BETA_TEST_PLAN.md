# GoHMotech beta test and deployment plan

Prepared September 8, 2026. Public access at gohmotech.site was requested. The
user approved replacing Framer. The apex now serves the beta via Cloudflare Tunnel
with `apollo.ns.cloudflare.com` and `cora.ns.cloudflare.com` as its nameservers.
The deploy/ directory contains the public web beta package and release notes.

## Verified baseline

- Host: ARM64, Debian 13; project Python environment includes Django 6.0.8 and Daphne 4.2.3.
- Django system check passes.
- Scanner unit tests: 14 passed.
- Application tests with temporary SQLite and local-memory cache: 171 passed, 1 failed out of 172. The failure expects a redirect where seller-approval access is denied with HTTP 403.
- Deployment check reports six warnings: DEBUG enabled, weak/default-style secret key, missing secure session and CSRF cookies, SSL redirect, and HSTS configuration.
- No deployment has been performed. Database concurrency, physical devices, and live provider delivery have not been validated by these tests.

After beta preparation, the stale seller-approval assertion was corrected and all
181 application tests passed, including nine new beta access/media/WebSocket tests.
The original development settings remain separate. The new config.beta settings
pass deployment checks with two intentionally silenced advisory checks: HSTS on all
subdomains and browser preload enrollment. Neither is enabled for the initial beta.
The systemd service definition validates. Local installation subsequently completed,
and independent nginx-origin checks passed for marketplace, login, static assets,
anonymous hardware rejection, and private document rejection. Backup reference:
`/var/backups/gohmotech-beta/20260908T144740Z`. Public apex HTTPS, HTTP redirect,
marketplace/login/static assets, and anonymous hardware rejection subsequently
passed external checks using a browser user agent. Beta administrator creation,
real email delivery, machine-client edge access, www routing, and interactive
end-to-end acceptance tests remain outstanding. Farm writes and unattended
equipment automation remain excluded from this public web beta.
The isolated suite needed execution outside
the sandbox because async WebSocket tests timed out within it.

## Release preparation

1. Confirm hostname, host, private/public access, and whether beta data should be separate from existing farm data.
2. Back up database and uploaded files; verify restoration into an isolated database before migrations.
3. Create a reproducible release snapshot of the current working tree, including existing uncommitted changes. Keep secrets and private uploads out of the release artifact.
4. Configure a dedicated beta environment: database, media directories, strong secret, explicit hosts/origins, and console SMS/email until real delivery is intentionally enabled.
5. Configure HTTPS termination, secure cookies, static/media serving, ASGI process supervision, and shared Redis channels. Configure proxy trust only for the actual trusted proxy.
6. Consolidate feeding schedulers, correct FeedLog field names, and require device acknowledgement before recording success or deducting inventory. Verify automation-off behavior, command expiry, and duplicate prevention.
7. Authenticate ESP32 ingestion/command/confirmation endpoints and enforce farm permissions on WebSockets.
8. Resolve the test expectation mismatch and run regression tests against the beta database engine.
9. Run deployment checks under the exact beta settings, inspect startup logs, and rehearse restart and rollback.
10. Invite testers only after the selected exposure and workflows pass their acceptance checks.

## Tester scenarios

Record date, tester role, browser/device, steps, expected result, actual result, and evidence for each case. Use synthetic records where possible.

| Area | Scenario | Expected result |
|---|---|---|
| Accounts | Sign in/out; use an invalid password; open another role's route | Correct login behavior and access denial; no private data disclosed |
| Permissions | Buyer attempts seller approval; operator attempts equipment control | Request denied and records unchanged |
| Marketplace | List, inquire, reserve, arrange pickup, complete sale | Consistent listing and goat status with correct totals |
| Reservations | Two buyers attempt to reserve the same goat | Only one accepted reservation; verify using the actual database engine |
| BLE | Known, unknown, disabled, and temporarily absent beacon | Correct identity/status; invalid credentials rejected |
| Weight | Stable/unstable measurement and duplicate save | Only confirmed valid measurement saved once |
| Sensors | Valid readings, invalid ranges, offline device | Valid readings stored, invalid values rejected, stale status visible |
| Feeding | Manual/scheduled command and hardware acknowledgement | Exactly one operation; success and inventory reflect acknowledgement |
| Feeding recovery | Lost response, duplicate poll, offline feeder, disabled automation | No duplicate dispensing or false success; disabled schedules do not execute |
| Cameras | Normal scene, empty scene, camera disconnect/reconnect | Usable detection display and clear failure/recovery behavior |
| Reports | Compare source records and exported totals | Matching totals; exports open correctly |
| Alerts | Trigger representative event and simulated provider failure | Correct recipient, status, and failure record; no duplicate flood |
| WebSockets | Anonymous/buyer connection; authorized connection across processes | Unauthorized clients rejected; permitted events delivered across workers |
| Mobile | Core pages on a phone | Forms, navigation, images, and feedback remain usable |
| Recovery | Restart application; restore backup in isolated environment | Data preserved and selected workflows resume |

## Release record

Before invitation, record the release identifier, hostname, database backup reference, enabled services, known limitations, test results, rollback commands, and person responsible for monitoring feedback. Never put passwords, API keys, or private customer records in this document.

Rollback must account for database schema compatibility: retain the previous application/configuration and a verified matching backup. Do not restore over new beta activity without explicitly deciding how to preserve that data.
