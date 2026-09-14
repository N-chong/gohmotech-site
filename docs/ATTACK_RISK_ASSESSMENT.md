# GoHMoTech public beta attack-risk assessment

Assessment date: 2026-09-11 (Asia/Manila)

Scope: the current working tree, Django/ASGI application, marketplace, IoT and
ML integrations, local Raspberry Pi deployment configuration, and safe
anonymous HTTP observations of `gohmotech.site`. No destructive or mutating
request was sent to the public site.

> This is the required pre-modification risk baseline. Remediation status,
> post-change scores, verification results, and release conditions are recorded
> in `FINAL_SECURITY_REPORT.md`.

## Executive decision

**Current decision: YES, WITH CONDITIONS — Important issues should be addressed.**

The public beta is not presently exposed with the project's permissive
development settings. The active service uses `config.beta`; Django, MariaDB,
Redis, and nginx are active; Daphne (`127.0.0.1:8010`), nginx
(`127.0.0.1:8080`), MariaDB (`127.0.0.1:3306`), and Redis
(`127.0.0.1:6379`) listen on loopback. Cloudflare fronts the application. Safe
live requests confirmed HTTP-to-HTTPS redirection, HSTS, clickjacking and MIME
protections, anonymous denial of farm sensor data, bearer authentication on BLE
ingestion, authentication on Django admin, and non-public seller-document
paths.

Continued public beta use is conditional on keeping `config.beta`, nginx, and
the tunnel boundary exactly in place; keeping physical equipment writes
disabled; repairing and verifying SMTP; limiting enrollment to known testers;
and addressing the application-layer findings below before enabling hardware
writes or broader production use.

## Evidence and limitations

- `python manage.py check` and `python manage.py check --deploy
  --settings=config.beta` passed.
- The read-only beta preflight passed database connectivity, migration state,
  Redis, configured SMTP fields, and collected assets. It does **not** prove an
  email can be delivered.
- 157 selected isolated tests ran: 155 passed. Two WebSocket tests timed out
  because Channels accessed an in-memory SQLite database from another thread;
  the authorization middleware itself was reviewed and requires an active farm
  role. The test harness requires repair and rerun with file-backed SQLite.
- The deployment notes record a real Gmail SMTP `535` rejection. Current SMTP
  delivery remains unverified because the audit intentionally sent no email.
- `www.gohmotech.site` did not resolve during the audit even though it is listed
  in allowed hosts and OAuth guidance.
- The repository has extensive pre-existing uncommitted changes, mostly line
  ending normalization plus untracked beta deployment files. This assessment
  treats the current filesystem as the candidate release and does not assert
  that every uncommitted file has been versioned or backed up.
- No port scan, credential attempt, attack payload, upload, or state-changing
  production request was performed.

## Threat model

### Assets

- User identities, password hashes, sessions, email addresses, phone numbers,
  seller verification documents, private support evidence, and pickup details.
- Marketplace listings, private conversations, reservations, sale state, and
  audit/activity history. GoHMoTech records inquiry/reservation/manual-sale
  workflow; it does **not** process or secure online payments.
- Goat inventory, health records, reports, camera feeds and credentials, sensor
  history, BLE location/proximity data, ML models, and actuator desired state.
- Raspberry Pi host, Django signing key, database credentials, OAuth and SMS
  secrets, receiver credentials, tunnel credential, and availability.

### Likely adversaries

- Anonymous automated scanners, spammers, credential-stuffing operators, and
  opportunistic attackers.
- Authenticated buyers attempting horizontal access to another buyer/seller.
- Approved sellers attempting to alter another seller's goats, listings,
  conversations, or reservations.
- Farm Operators attempting write/administrative access.
- A compromised staff account attempting host-level escalation through ML or
  camera features.
- A network-adjacent attacker targeting MQTT, cameras, ESP32 firmware, SSH, or
  unauthenticated legacy device protocols.

### Trust boundaries

```text
Internet -> Cloudflare HTTPS/tunnel -> loopback nginx -> loopback Daphne
                                              |
                  Django sessions/CSRF/RBAC -> MariaDB / Redis / private files
                                              |
                    authenticated receiver -> BLE observations

Farm LAN -> ESP32 / camera / MQTT -> legacy endpoints (disabled in web beta)
```

## Attack-risk table

“Confirmed” means the vulnerable code/configuration is present and its behavior
is established by review or local tests. “Potential / verify” means the impact
depends on deployment state, an external account, or a privileged prerequisite.

| Component | Potential Attack | Current Protection | Vulnerable? | Severity | Recommended Fix |
|---|---|---|---|---|---|
| Public beta perimeter | Reach Daphne, MariaDB, or Redis directly | All three bind to loopback; tunnel targets loopback nginx | No, confirmed locally | INFORMATIONAL | Preserve loopback bindings; firewall LAN-facing SSH/RPC as appropriate |
| Production settings | Debug traceback, wildcard host, insecure cookies | Active service explicitly uses `config.beta`; `DEBUG=False`, explicit hosts, HTTPS and secure cookies | No in active beta; dangerous if launched with base settings | HIGH potential | Fail closed on production startup and document/verify the settings module |
| Legacy sensor ingestion | Anonymous creation of readings and even new Device rows | Base `SensorReadingViewSet.create` is `AllowAny`; beta middleware blocks it | **Confirmed project vulnerability; not reachable in current beta** | HIGH | Require a provisioned per-device credential before enabling public ingestion |
| Legacy scale ingestion | Spoof transient weights or keep scale “online” | Device ID only and CSRF exempt; beta blocks the POST | **Confirmed project vulnerability; not reachable in current beta** | HIGH | Require a provisioned credential, replay resistance, limits, and payload bounds |
| Legacy feeder/actuator APIs | Read commands, forge device state/feeding confirmations, falsify logs | Several actions deliberately have no view authentication; beta denies anonymous farm routes and disables writes | **Confirmed project vulnerability; mitigated in current beta** | HIGH | Add device authentication before any public/LAN re-enablement |
| BLE receiver ingestion | Spoof observations or enumerate assignments | Bearer key plus receiver ID, one-way Django password hash, active-device check | No bypass found | LOW | Add endpoint throttling and rotate receiver key after device loss |
| Farm WebSockets | Anonymous/buyer subscription to sensor, alert, feed, or detection events | allowed-host origin check, Django session auth, active farm-role gate | No bypass found; regression harness needs repair | MEDIUM potential | Use file-backed DB test and retain origin/role middleware |
| Actuator REST view | Buyer/operator write via direct API call if middleware is removed/misordered | Route middleware blocks buyers/operators; view's custom `get_permissions()` weakens its declared permission to `IsAuthenticated` | **Confirmed defense-in-depth defect** | MEDIUM | Enforce `FarmRolePermission` in the view itself |
| BLE tracking snapshot | Any authenticated user reads tracking if middleware is bypassed | Marketplace route middleware currently blocks buyers; view only checks `IsAuthenticated` | **Confirmed defense-in-depth defect** | MEDIUM | Enforce farm-role permission in the view |
| SMS API | Non-staff reads reminders/logs if middleware is bypassed | `/sms/` route middleware is admin-only; API permission permits authenticated safe reads | **Confirmed defense-in-depth defect** | MEDIUM | Make SMS operational data staff-only in the view |
| Farm Operator role | Hidden controls accessed directly | Backend decorators, DRF permissions, and route middleware deny writes; local RBAC tests cover representative URLs | No bypass found | HIGH impact, currently protected | Expand endpoint-matrix regression tests |
| Goat records | IDOR through changed goat/image IDs | Farm modules are shared-farm scoped; mutations require owner/admin; image deletes bind image to goat | No bypass found for the documented single-farm model | LOW | Document that farm roles intentionally see the shared smart-farm herd |
| Seller goats/listings | Seller edits another seller's record or substitutes goat ID | Querysets filter owner/seller and community record source; forms restrict selectable goats; model validation repeats ownership checks | No; tested | HIGH impact, protected | Retain scoped querysets and regression tests |
| Conversations/messages | Read or write another user's conversation | Participant/seller ownership checked server-side; moderators are read-only; model validation rejects outsiders | No; tested | HIGH impact, protected | Add abuse throttles for message creation |
| Reservations | Change buyer/seller/price/status in request | Buyer, seller, listing and agreed price are loaded server-side; atomic row locks and state transitions; competing requests rejected | No; tested | HIGH impact, protected | Keep payments explicitly out-of-system; retain transaction tests |
| Marketplace payment claims | Users assume GoHMoTech transfers money | UI states payment is manual at pickup; no gateway exists | No technical payment processing | INFORMATIONAL | Keep this disclosure prominent and never claim payment security |
| Support references | Attach another user's conversation/reservation to a ticket | Participant check for conversation/reservation; public listing may be referenced | No private IDOR found | LOW | Retain checks and keep listing references public-only |
| Support attachments | Malicious file or private-file IDOR | Extension, MIME, magic/image validation, 8 MB limit, randomized private storage, owner/staff download check, nosniff/sandbox | No practical bypass found | LOW | Force all attachments to download and optionally malware-scan when scale warrants |
| Seller verification documents | Script/content upload, public disclosure | Extension/size checks; ImageField validation for images; production media view owner/staff only with nosniff+sandbox | Potential content-validation gap for PDF | MEDIUM | Validate PDF signature/content and serve as attachment from private storage |
| Goat image uploads (farm portal) | Oversized/decompression-bomb image or MIME spoof | Farm-owner authorization; nginx 12 MB request cap; only claimed MIME checked in two legacy paths | **Confirmed validation weakness** | MEDIUM | Use Pillow verification, dimension/size limits, and normalization |
| Marketplace images | Polyglot/oversized/decompression image | Django image validation, 5 MB and 25 MP bounds, max counts, re-encoded to JPEG | No bypass found | LOW | Retain normalization and catch decompression warnings |
| ML model upload/load | Malicious pickle/PyTorch artifact executes code on activation | Staff-only private upload, extension/size/path checks; beta blocks farm writes | **Potential server compromise if staff/upload account is compromised** | HIGH | Treat models as executable; restrict to superuser/offline import, verify digest/signature, prefer safe formats |
| Camera configuration | SSRF/internal probing and credential theft | Farm-owner authorization; beta blocks writes; IP field validation | Potential when controls are enabled | MEDIUM | Restrict destinations to approved camera subnets; block loopback/link-local/cloud metadata; encrypt secrets |
| Camera credentials | Database/backup disclosure | Admin/owner-only pages; media not involved | **Confirmed plaintext at rest** | MEDIUM | Move credentials to a protected secret store or encrypt with a separately held key; rotate after migration |
| Raw SQL/injection | User input changes SQL semantics | Runtime queries use ORM and whitelisted lookups/sorts; raw cursor appears only in a data migration with fixed SQL | No SQL injection found | LOW | Keep dynamic field names allow-listed and bound through ORM |
| XSS | Stored listing/message/profile content executes for another user/admin | Django autoescaping; no template `safe` on user content; reviewed JS escapes API strings in security/SMS views | No confirmed marketplace XSS | MEDIUM potential | Add CSP after removing inline-script dependencies; test stored payloads |
| ML detection dashboard JS | Camera name inserted into `innerHTML` without escaping | Farm-only data; camera naming is staff controlled | Potential privileged stored XSS | LOW | Build DOM with `textContent` or escape camera names |
| CSRF | Cross-site state-changing form/API request | Django CSRF middleware; session-authenticated DRF; state transitions use POST/DELETE and templates send CSRF | No bypass found; device exceptions intentionally bypass session CSRF | LOW | Never remove CSRF; authenticate device exceptions independently |
| Authentication brute force | Password spraying/credential stuffing | allauth defaults include IP/key login-failure limits; nginx adds aggregate auth-route limiting | Partially protected | MEDIUM | Monitor 429s; configure trusted client IP at the edge before per-IP nginx limits |
| Nginx auth limiter | One attacker exhausts shared tunnel-origin limit for everyone | Aggregate 10 requests/minute because nginx sees tunnel as source | **Confirmed beta availability risk** | MEDIUM | Validate Cloudflare client-IP headers and real-IP trust chain, or rate-limit at Cloudflare |
| Registration/reset abuse | Email spam or enumeration | allauth signup/reset rate limits and account enumeration prevention; mandatory verification intended | SMTP failure affects reliability | MEDIUM | Verify SMTP, generic responses, and cooldown behavior end to end |
| Password reset | Token guessing/reuse/session weakness | Django/allauth cryptographic tokens, default 3-day timeout, single-use password state binding | No bypass found | LOW | Shorten reset timeout to 1 hour for public beta and add full flow tests |
| OAuth | Login CSRF/account collision/token leakage | POST initiation, PKCE, verified-email authentication, unique email migration, no OAuth token storage | External console state requires verification | MEDIUM potential | Verify exact callbacks, consent publishing/testers, and app ownership |
| API query parameters | Huge/unbounded history responses or `hours` parsing 500s | Global pagination applies to ordinary list actions, not custom recent/history actions | **Confirmed robustness weakness** | MEDIUM | Validate/clamp windows and paginate/bound custom responses |
| API exception responses | Internal database/device details disclosed to privileged callers | `DEBUG=False` blocks Django tracebacks, but several views return `str(exception)` explicitly | **Confirmed limited disclosure** | MEDIUM | Log details server-side and return stable generic errors |
| Marketplace public expiry | Repeated public requests trigger due-reservation processing | Atomic transitions; only due rows incur work | Potential load amplification | LOW | Move expiry to a scheduled job when workers are safely enabled, or cache the sweep |
| Marketplace/admin dashboard | Memory/DOM/query load from all listings/reservations | Related objects selected, but main sets are unpaginated and multiple count queries run | **Confirmed scalability defect** | MEDIUM | Paginate tables and consolidate counts with conditional aggregates |
| IoT admin dashboard | Many independent aggregates/services and repeated polling | Some aggregation/select-related and graceful service fallbacks already exist | Potential performance bottleneck | MEDIUM | Establish query/time baseline, cache slow external status, consolidate repeated reads |
| Error handling | Raw errors or inconsistent user experience | Production debug off; custom 403 only | Missing custom 400/404/429/500 pages | LOW | Add safe consistent error handlers and test without debug |
| Security response headers | XSS/data-exfiltration hardening | HSTS, nosniff, DENY framing, same-origin referrer/COOP | No CSP or Permissions-Policy | LOW | Introduce a tested CSP in report-only mode first; limit camera/microphone/geolocation APIs |
| Static/media caching | Private response reused across accounts | Private media is Django-authorized; `never_cache`; no nginx media alias | No private cache leak found | HIGH impact, protected | Keep Cloudflare bypass/no-store rules for authenticated/private paths |
| Secrets in current source | Exposed Django/OAuth/SMS/database/tunnel secret | Current config reads environment; `.env` ignored; private beta env mode 600; examples are placeholders | No current secret value found in reviewed tracked source | MEDIUM potential | Run a dedicated history scanner; rotate any credential ever committed or pasted elsewhere |
| Firmware samples | Wi-Fi/MQTT/database passwords committed | Current samples contain placeholders; two historical revisions were reviewed structurally, not with a specialist secret scanner | Requires verification | HIGH potential | Run gitleaks/trufflehog on full history and rotate any real historic Wi-Fi/DB/MQTT secret |
| Host network | SSH/RPC exposure | Application services loopback; SSH (22) and rpcbind (111) listen on all interfaces; internet reachability not tested | Potential LAN/internet host surface | MEDIUM | Confirm router/firewall rules, restrict SSH by key/source, disable rpcbind if unused |
| `www` hostname | Availability/OAuth callback failure | Listed in settings/docs | **Confirmed DNS failure during audit** | MEDIUM | Create/repair `www` DNS+tunnel route or remove it consistently |
| Email reliability | Verification/reset unusable | Configuration present; no send attempted | **Previously confirmed SMTP 535; current delivery unverified** | HIGH reliability | Replace/rotate app password and perform one authorized end-to-end delivery test |
| PWA | Unsafe private caching/account crossover | No service worker or manifest exists, so no PWA cache risk yet | Feature absent | INFORMATIONAL | Add static-only cache, network-only sensitive routes, offline shell, and cache versioning |
| Mobile support | Unusable controls/tables on small screens | Many major templates have responsive CSS/wrappers; no systematic browser matrix evidence | Requires verification | MEDIUM | Test 320/375/390/768 px and fix overflow/touch targets without desktop redesign |

## Endpoint security summary

| Endpoint family | Authentication | Authorization/ownership | CSRF | Rate-limit need | Sensitive output |
|---|---|---|---|---|---|
| `/accounts/*` | Public for login/signup/reset; session for account management | allauth account scope | Yes for state changes | Implemented by allauth; nginx edge layer | Account/email state |
| `/admin/*` | Django staff login | Model permissions plus custom admin restrictions | Yes | Login limiting present | All operational/user data |
| `/marketplace/goats`, public listing/profile detail | Public | Only trusted sellers and published/active listings | N/A for reads | Search/request limits desirable | Deliberately public listing/profile fields |
| Marketplace seller CRUD | Session | Approved seller plus owner-scoped goat/listing querysets | Yes | Moderate write throttles desirable | Seller inventory and drafts |
| Conversations/reservations | Session | Buyer/listing manager/limited moderator checks | Yes | Message/reservation throttles desirable | Private chat, pickup details, agreed price |
| Support | Session | Ticket owner or staff; attachment repeats check | Yes | Ticket/reply throttles desirable | Private messages and evidence |
| Farm HTML/API | Session | Admin/owner/operator role; operator read-only | Yes for session writes | Read/poll limits desirable | Herd, sensors, cameras, reports |
| BLE ingest | Receiver bearer credential | Credential bound to one active receiver | Session CSRF not applicable | Yes | Beacon assignments/config and observations |
| Legacy sensor/scale/feeder/actuator device routes | None in base configuration | Claimed device identifier only | Exempt/no session CSRF | Essential | Commands, readings, equipment state |
| WebSockets | Session cookie | Active farm role plus origin host | WebSocket origin validation | Connection/message limits desirable | Live farm events |
| Media | Public only for published listing images; otherwise session | Database-backed file-to-owner/role association | Read-only | Edge caching must honor policy | Photos and verification documents |

## Security scores (pre-remediation baseline)

- **Attack exposure: High project-wide / Moderate for the currently locked-down
  beta.** Public marketplace and auth are intentional; farm APIs are behind
  roles and the beta write freeze, but legacy device endpoints become high-risk
  under the base settings and SSH/RPC remain separate host surfaces.
- **Authentication security: 7/10.** Django/allauth primitives, enumeration
  prevention, OAuth PKCE, no stored OAuth tokens, and meaningful rate limits are
  good. SMTP is not proven, reset timeout is long, edge IP limiting is aggregate,
  and complete recovery testing is absent.
- **Authorization security: 8/10.** Marketplace and role boundaries are
  thoughtfully implemented and heavily tested. Three APIs weaken permissions at
  view level and currently depend on route middleware for the correct result.
- **Marketplace security: 8/10.** Ownership, private messaging, server-derived
  price/participants, state validation, transactions, and row locks are strong.
  Abuse throttling and scale/performance controls remain.
- **Data protection: 6/10.** Private support/model storage and production media
  authorization are strong. Camera credentials are plaintext, seller PDFs need
  stronger validation/private storage, and full Git-history secret scanning is
  outstanding.
- **Server/deployment security: 7/10.** The tunnel/loopback topology, dedicated
  database, secure cookies, debug-off mode, and systemd restrictions are good.
  `www` is broken, SMTP is unverified, CSP is absent, and host SSH/RPC/firewall
  posture needs owner verification.
- **API security: 6/10.** Session/role permissions cover most APIs and BLE has
  a real credential. Legacy hardware APIs, permission overrides, unbounded custom
  actions, and explicit exception text lower the score.
- **Overall production security: 7/10 for continued controlled beta; not ready
  for unrestricted production or internet-enabled equipment control.**

## Required conditions for continued beta

1. Keep `DJANGO_SETTINGS_MODULE=config.beta`, the loopback-only origin, protected
   media route, and public beta write freeze.
2. Do not expose 3306, 6379, 8010, 8080, camera streams, MQTT, or debug tooling.
3. Repair SMTP and verify signup, verification, reset request, single-use reset,
   and post-reset login with one authorized test inbox.
4. Fix view-level API permissions and the file-backed WebSocket regression test.
5. Add device authentication before enabling any legacy IoT/feeding write route.
6. Restrict beta enrollment and monitor authentication, messaging, support, and
   reservation abuse until application-level throttling is added.
7. Back up the exact working tree and beta data before deployment changes; no
   production database reset or destructive test is authorized.
