# GoHMoTech public-beta security and reliability report

Assessment date: 2026-09-11 (Asia/Manila)

This report covers the current working tree and safe, read-only observations of
the deployed beta. The pre-change threat model and evidence table are preserved
in `ATTACK_RISK_ASSESSMENT.md`. No production record, account, file, service, or
configuration was changed during testing. Source fixes described below are not
live until a controlled deployment is performed.

## Conclusion

**YES, WITH CONDITIONS — Important issues should be addressed.**

The deployed beta is suitable for a small, controlled group of real users only
while it continues to use `config.beta`, the Cloudflare-to-loopback nginx
boundary, protected media delivery, and the beta hardware-write freeze. It is
not ready for unrestricted production use or internet-enabled actuator/feeder
control.

The marketplace has good server-side ownership enforcement: seller, buyer,
listing, conversation, reservation, agreed price, and state transitions are
derived or checked on the server. No online payment processing exists;
GoHMoTech secures inquiry, reservation, pickup, and sale-status records, while
payment itself happens outside the system.

## Overall assessment

| Area | Baseline | Candidate after fixes | Reason |
|---|---:|---:|---|
| Attack exposure | High project-wide / Moderate locked beta | Moderate locked beta | Public auth and marketplace remain exposed; hardware writes remain frozen and internal services are loopback-only |
| Authentication | 7/10 | 8/10 | allauth throttles and enumeration protection; reset timeout is now one hour and single-use flow is tested; SMTP delivery is still unverified |
| Authorization | 8/10 | 9/10 | strong marketplace ownership plus corrected actuator, BLE tracking, feeding, and SMS view-level permissions |
| Marketplace | 8/10 | 8.5/10 | strong transaction/ownership model and protected conversations; write-abuse throttling remains desirable |
| Data protection | 6/10 | 7/10 | farm images and seller documents now receive content checks; camera passwords and executable ML artifacts remain concerns |
| Server/deployment | 7/10 | 7/10 | secure loopback topology and production settings; SSH/RPC firewall posture, SMTP, and `www` DNS need external verification |
| API security | 6/10 | 8/10 | device key boundary, direct RBAC fixes, bounded history calls, generic errors, and regression tests added |
| Overall production security | 7/10 controlled beta | 8/10 candidate controlled beta | Appropriate for continued controlled beta after deployment prerequisites, not unrestricted production |

## Confirmed vulnerabilities and fixes

| Component | Confirmed issue | Severity | Resolution in candidate source |
|---|---|---:|---|
| Legacy sensor API | Anonymous readings could create sensor/device records | HIGH | Requires a non-empty device key using constant-time comparison |
| Legacy scale API | A browser could spoof live scale state | HIGH | Requires the device key; missing/invalid keys fail closed |
| Legacy feeder/actuator APIs | Command polling, confirmation, physical-feed logging, sync, and feed-level update lacked a device boundary | HIGH | All legacy hardware actions now use the shared compatibility device key; per-device credentials remain the recommended next design |
| Actuator REST API | Custom permission selection weakened declared farm RBAC | MEDIUM | Non-device actions now retain `FarmRolePermission`; Operators remain read-only |
| BLE tracking snapshot | Any authenticated user could pass the view permission if route middleware were bypassed | MEDIUM | View itself now requires a farm role |
| SMS operational APIs | Reminder/log/settings reads depended partly on route middleware | MEDIUM | Operational SMS data and provider actions are staff-only at view level |
| Actuator audit identity | Browser-supplied `triggered_by` could impersonate another actor | HIGH | Actor is always the authenticated server-side username |
| History/custom API actions | Invalid or huge `hours` values could cause 500s or oversized responses | MEDIUM | Windows are validated to 1–168 hours; serialized histories are capped; statistics use aggregates |
| API error disclosure | Several APIs returned raw exception strings | MEDIUM | Details are logged server-side and callers receive stable generic errors |
| Farm goat uploads | Claimed MIME was trusted and images lacked consistent byte/pixel limits | MEDIUM | 5 MB/25 MP bounds, Pillow verification, and JPEG re-encoding added for uploaded and captured images |
| Seller evidence | A `.pdf` name and MIME could hide unrelated content | MEDIUM | PDF/JPEG/PNG signatures must match the declared type; production delivery remains private and sandboxed |
| Marketplace admin | All listings/reservations rendered and image access could become N+1 | MEDIUM | Both tables paginate at 25; related rows/images are selected/prefetched and status counts consolidated |
| Goat inventory | Cover-image lookup was N+1 | MEDIUM | Images are prefetched and selected in memory |
| Account UI/error pages | allauth reset/change/verification pages and production errors were inconsistent | LOW | Branded responsive allauth layout and safe 400/403/404/500 pages added |
| PWA | Installability was absent | INFORMATIONAL | Manifest, three icons, root service worker, static-only cache, update versioning, and non-sensitive offline fallback added |

## Potential risks requiring verification or later work

- ML uploads include pickle/PyTorch formats and must be treated as executable.
  Keep model management staff-restricted and beta writes disabled; preferably
  move model import offline, require a reviewed hash/signature, and use a safe
  format where supported.
- Camera credentials are stored in plaintext, and owner-configurable camera
  destinations can become an SSRF surface when farm writes are enabled. Encrypt
  or externalize credentials and allow-list the actual camera subnet before
  enabling this feature.
- The nginx authentication limiter sees the tunnel origin unless a verified
  Cloudflare real-IP trust chain or edge rate-limit is configured. The current
  aggregate limit can let one attacker temporarily deny login to other testers.
- Application-level cooldowns are still advisable for marketplace messages,
  inquiries, reservations, reports, support tickets, and seller applications.
  CAPTCHA should be added only where monitoring shows automated abuse.
- CSP is not yet enabled because templates contain substantial inline script and
  third-party CDN dependencies. Introduce report-only CSP first, remove inline
  dependencies, then enforce it. A restrictive Permissions-Policy is also
  recommended after camera requirements are mapped.
- SSH (`22`) and rpcbind (`111`) listen on all host interfaces. Internet
  reachability was not probed. Restrict SSH to keys/known sources and disable or
  firewall rpcbind if it is unused. MariaDB, Redis, Daphne, and nginx origin
  listeners were confirmed on loopback.
- `www.gohmotech.site` did not resolve. Repair its DNS/tunnel route or remove it
  consistently from hosts, trusted origins, and OAuth documentation.
- SMTP fields pass preflight, but no message was sent to a real inbox. Prior
  deployment notes recorded a Gmail 535 rejection. Verify signup, verification,
  reset request, reset completion, and post-reset login with an authorized test
  inbox before depending on recovery in public beta.
- No live secret was found in reviewed source. A specialist full-history scanner
  was unavailable. Run gitleaks/trufflehog against all refs and rotate every
  Django, database, OAuth, SMS, Firebase, Wi-Fi/MQTT, receiver, and Cloudflare
  credential that was ever committed, pasted into logs, or shared insecurely.
- Mobile-responsive patterns are widespread, including table wrappers and
  breakpoints, but a physical/browser matrix was not available. Perform a
  non-destructive acceptance pass at 320, 375, 390, and 768 CSS pixels.

## Marketplace security

- Seller CRUD querysets are scoped to manageable, owned goats/listings. Changing
  a listing or goat ID does not grant ownership.
- Conversation access is limited to buyer, listing seller, and a read-only staff
  moderation role. An unrelated user cannot read or post to another chat.
- Reservation creation and transitions run through server-side services with
  atomic transactions and row locks. Buyer, seller, listing, agreed price, and
  status are not trusted from browser fields. Competing holds are rejected.
- Only the correct participant can propose/confirm pickup or perform its
  transition; sellers control acceptance/completion, and moderation cancellation
  requires a reason.
- Public seller pages omit private contact numbers and precise address details.
  Seller evidence and support files use authorized Django delivery rather than a
  public media alias.
- Financial payment is not processed by GoHMoTech. The system must continue to
  describe payment as an external/manual pickup activity.

## Sensitive endpoint matrix

| Endpoint/pattern | Authentication | Authorization/ownership | CSRF | Additional controls needed | Sensitive output/action |
|---|---|---|---|---|---|
| `/admin/` | Staff session | Django model permissions | Yes | Edge login monitoring | Full administration |
| `/accounts/login/`, signup, reset | Public entry | allauth account/token checks | Yes on POST | Existing allauth limits; verify edge client IP | Session/account recovery |
| `/accounts/email/`, password change, logout | Session | Current account only | Yes | None beyond monitoring | Account/security state |
| Public marketplace list/detail/seller profile | Public | Published active listings from trusted sellers only | Read-only | Search/request limits if abused | Intended public catalog data |
| Seller goat/listing create/edit/publish | Session | Approved seller and owner-scoped querysets | Yes | Write cooldown desirable | Inventory, price, publication |
| Conversation/message routes | Session | Buyer, listing seller, or read-only moderator | Yes | Message cooldown/spam detection | Private conversation |
| Reservation/pickup/completion routes | Session | State-specific buyer/seller checks; server-derived parties/price | Yes | Reservation cooldown desirable | Hold, pickup and sale status |
| Support ticket/message/download | Session | Ticket owner or staff | Yes on writes | Ticket/reply cooldown | Private evidence/messages |
| `/iot/api/sensor-readings/` POST | Device key | Compatibility device boundary | Not session CSRF | Per-device keys/replay protection before enablement | Creates readings/devices |
| Scale/feeding/actuator device actions | Device key | Compatibility device boundary; beta additionally blocks writes | Not session CSRF | Per-device keys/replay protection before enablement | Physical state/commands/logs |
| Farm IoT/feeding REST CRUD | Session | Farm role; Operator safe methods only | Yes | Poll/read limits | Sensors, herd and equipment |
| Actuator manual control | Session | Owner/admin only, actor server-derived | Yes | Audit/alert unusual commands | Physical desired state |
| BLE observation/heartbeat | Receiver bearer key | Active credential bound to receiver | Not session CSRF | Receiver throttling and rotation | Location observations/config |
| BLE tracking snapshot | Session | Farm role | Read-only | Poll limit | Goat proximity/location |
| Camera snapshots/config | Session | Farm role read; owner/admin write | Yes on writes | Subnet allow-list before writes | Camera image/credentials |
| ML model management/test | Staff session | Admin view permission; beta blocks writes | Yes | Offline signed model import preferred | Executable model artifacts |
| SMS operational API | Staff session | Staff-only at view level | Yes | Provider-call cooldown | Phone/log/provider data |
| WebSockets `/ws/*` | Session | Active farm role plus allowed origin | Origin validation | Connection/message limits | Live farm events |
| `/media/*` in beta | Public only for published listing photos; otherwise session | File-to-record owner/role lookup | Read-only | Keep cache bypass/no-store | Photos and private documents |

## Authentication and privacy

- Django/allauth provides cryptographic reset tokens, account-enumeration
  protection, email ownership records, Google PKCE, CSRF, and meaningful default
  rate limits for login, failed login, reset, and signup.
- The candidate uses a one-hour reset timeout and tests successful reset, new
  password acceptance, and rejection of replayed links.
- Session cookies are Secure, HttpOnly, SameSite=Lax; CSRF cookies are Secure and
  SameSite=Lax. Production uses HTTPS redirect, one-hour HSTS, no-sniff, DENY
  framing, same-origin referrer policy, explicit hosts, and debug-off behavior.
- Public-beta HSTS intentionally excludes subdomains and preload until domain
  ownership and the broken `www` route are resolved.

## PWA and mobile behavior

- The manifest starts in the public marketplace, uses standalone display, and
  contains 192/512 and maskable icons.
- The root-scoped service worker caches only same-origin `/static/` assets.
  Navigations are always fetched from the network; offline navigation receives
  one static page containing no user data.
- Admin, accounts, CSRF responses, conversations, transactions, reports, camera
  feeds, monitoring APIs, and media are never placed in the application cache.
  Cache version replacement removes older application-shell caches.
- This is intentionally not full offline mode. Logout/account switching cannot
  reveal cached private HTML because no private HTML is cached.

## Performance and reliability

- The marketplace admin's prior work scaled with every historical row and could
  issue a cover-image query per listing. It now shows 25 rows at a time,
  prefetches cover images, selects related users/goats, and consolidates counts.
  A regression test holds the page to at most 20 queries with 28 listings,
  demonstrating that query count is no longer proportional to displayed rows.
- Goat inventory image lookups are also consolidated through prefetching.
- Detection and actuation statistics now aggregate in the database rather than
  iterating rows or issuing repeated count queries.
- Custom history windows are bounded, reducing accidental memory/response spikes.
- Existing weather, notification, camera, and recent-activity paths include
  best-effort failure handling. Safe production error pages prevent traceback
  disclosure. Database, Redis, SMTP, cameras, and devices still need operational
  monitoring and backup/restore drills.

## Verification evidence

- `manage.py check`: passed.
- `manage.py check --deploy --settings=config.beta`: passed (two intentional
  HSTS checks silenced for the documented one-hour/non-preload beta policy).
- `deploy/preflight.py`: passed database connectivity, migrations, Redis, SMTP
  configuration fields, and collected baseline assets. It does not prove SMTP
  delivery or that new static assets have been deployed.
- Isolated regression suite: **196 tests passed, 0 failed** in disposable SQLite,
  local-memory cache/email, console SMS, temporary media/model storage, and no
  live providers.
- `makemigrations --check --dry-run`: no model changes detected.
- systemd unit verification: passed.
- Safe deployed GET/header checks confirmed HTTPS redirection, HSTS, no-sniff,
  frame denial, safe 404s, admin login redirection, anonymous farm API denial,
  and BLE bearer authentication. No destructive or state-changing live test ran.

## Development/change inventory

Security and reliability changes are concentrated in:

- configuration/deployment: `config/beta.py`, `config/urls.py`,
  `config/test_beta_deployment.py`, `deploy/test_isolated.py`, environment
  examples;
- device/API boundaries: `iot/device_authentication.py`, `iot/views.py`,
  `iot/ble_api.py`, `iot/goat_views.py`, `feeding/views.py`, `sms/views.py`,
  `ml_models/views.py`;
- marketplace: `marketplace/forms.py`, `marketplace/views.py`, the admin
  dashboard template, and tests;
- accounts/errors/PWA: `templates/allauth/layouts/base.html`,
  `templates/error.html`, base templates, dashboard routes/views/tests,
  manifest, registration script, service worker, offline page, and icons;
- regression coverage: `iot/tests.py`, `iot/test_weight_integration.py`,
  `marketplace/tests.py`, `dashboard/tests.py`, and beta deployment tests.

No database migration or dependency was added. No production database or
service was modified. The working tree contained extensive pre-existing changes;
review and back up the exact release diff before deployment.

## Controlled deployment conditions

1. Back up the beta database, beta data root, environment file, and exact source
   revision; test restoration.
2. Generate and install a strong `BETA_IOT_DEVICE_API_KEY` only when firmware is
   updated to send `X-GoHMotech-Device-Key`. Keep hardware routes frozen until
   bench/staging verification succeeds.
3. Run collectstatic under `config.beta`; verify manifest, icons, offline page,
   and root service-worker response before restarting Daphne.
4. Run migrations (none are currently required), preflight, isolated tests, and
   a staging smoke test. Then deploy with a reversible service restart.
5. Verify SMTP with an authorized inbox, configure edge-aware auth throttling,
   resolve `www`, and confirm firewall exposure.
6. Monitor 4xx/5xx/429 rates, authentication failures, queue/provider failures,
   response latency, database saturation, disk usage, and unusual marketplace
   activity. Maintain a rollback path.
