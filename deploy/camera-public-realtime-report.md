# Public camera real-time investigation

## Current production outcome — supersedes historical sections below

At 09:16:25 on 2026-09-18, deployed a finite latest-JPEG preview on the existing authenticated endpoint (`transport=jpeg`). Only one request is outstanding; the next starts after rendering, preventing ordered stream backlog. Defaults remain 320 pixels/q50/6-FPS ceiling. Three-second request/age guards reject stale frames and retry automatically; hidden/offscreen/navigation cleanup remains. Shared RTSP capture, full-quality snapshots, and optional MJPEG/SSE remain unchanged. Static asset version is now 5.

Backup: `/var/backups/gohmotech-camera-realtime/20260918T011625Z`. Application check and `nginx -t` passed; only `gohmotech-production` restarted, active/running PID 14225. Nginx/cloudflared configuration and services unchanged. Published/source script SHA-256 match: `57b6ac0645b3f18033285a8cffe5dc77208124286c3ec7a85a2ce06a07138509`. All **234 isolated tests passed**, including 17 camera tests; production smoke checks passed. No migrations/data deletion/security downgrade/new ports.

The owner previously deployed SSE successfully at 08:57:02, backup `/var/backups/gohmotech-camera-realtime/20260918T005702Z`, but sustained tests failed freshness. A public HTTP/2 SSE run produced Nginx 521 changing frames/90.03 s = 5.79 FPS, public 432/90.10 s = 4.79 FPS, with public capture age p95 14.802 s/max 15.632 s. Genuine SSE and reduced bitrate did not eliminate tunnel/network bursts. Further QUIC inactivity/re-registration logs appeared around 08:59–09:00. Exact WAN/router/edge cause remains unproven.

### Final deployed finite-JPEG stage comparison

| Stage | Changing frames / duration | Changing FPS | Capture age median / p95 / max | Maximum gap |
| --- | --- | --- | --- | --- |
| Daphne backend | 526 / 90.11 s | 5.84 | 0.055 / 0.114 / 0.227 s | 0.327 s |
| Nginx origin | 526 / 90.15 s | 5.84 | 0.052 / 0.108 / 0.135 s | 0.342 s |
| Actual public HTTPS | 235 / 90.07 s | 2.61 | 0.245 / 0.389 / 1.274 s | 1.494 s |

No gaps above two seconds or probe errors. Public first frame 0.714 s; reconnect 0.517 s. Mean JPEG ~7064 bytes, public ~0.147 Mbit/s. This establishes fresh public frames without growing backlog, not sustained 6-FPS delivery. Capture age starts at Pi frame publication, not the physical sensor.

### Browser result and unresolved limitation

Two simultaneous deployed-public Chromium viewers (desktop and 390×844 mobile emulation with 4× CPU slowdown) ran 120 seconds with induced offline interval and navigation return. Pixel hashes confirmed actual changing images; no JavaScript exceptions. Automatic recovery/navigation return worked, but desktop reached only 111 frames and mobile 114 by ~115 seconds. Several intervals stalled/retried and adaptive rate fell to 2 FPS. **This does not satisfy uninterrupted multi-viewer operation. The whole issue is not marked solved.** A single-browser follow-up is in progress.

Single-viewer desktop HTTP/3 follow-up: 120 changing displayed frames by 115.49 seconds, with an induced offline interval at 25–35 seconds. Before interruption it displayed approximately 3 FPS with age ~0.3 s; later fell below 1 FPS and stalled at 110–115 s. Navigation return did not recover within the ten-second observation. No JavaScript exceptions. Thus remaining failures are not restricted to simultaneous viewers. Three tunnel connections timed out around 09:26:03–09:26:15, then re-registered. A process check found no leftover diagnostic browsers. Pi Ethernet has no carrier; active connectivity is Wi-Fi.

Single-viewer diagnostic HTTP/2 browser: 68 changing displayed frames by 85.37 seconds, including the same ten-second induced offline interval. Frames stopped after ~45 s; navigation away/back recovered to Live with 32 fresh frames in ten seconds. Actual protocol recorded h2. No JavaScript exceptions. This rules out browser HTTP/3 as the sole explanation, not tunnel QUIC. A contemporaneous separate public login request succeeded (200, first byte 0.588 s, total 1.352 s): public delivery is intermittent/per-connection, not a proven total website outage. Production smoke tests passed again. Further safe isolation requires a wired-network comparison or additional network/edge evidence; do not claim uninterrupted recovery solved.

Wi-Fi power-save-off trial still produced stale long-stream bursts; original power-save-on restored. No persistent network change. Tunnel HTTP/2 was not applied because it would remove current QUIC post-quantum agreement. Public browser HTTP/3 and edge HTTP/2 are distinct from tunnel QUIC.

Additional changed/new files: finite transport in `iot/views.py`; finite polling/age guard in `static/js/live-camera.js`; version-5 dashboard/detail templates; finite/authentication tests in `iot/test_camera_streaming.py`; `deploy/install_camera_latest_preview.sh` and expanded delivery/browser probes. Existing capture timestamp changes in `iot/camera_utils.py` retained. All unrelated changes preserved.

Remaining limitations: public RTT-limited FPS below preferred 5–10, tunnel/network instability and multi-viewer stalls, no physical-phone test or calibrated sensor timestamp, legacy stream clients may still buffer. Existing tabs need one navigation to obtain version 5; subsequent recovery is automatic. **Historical owner commands below are superseded; do not redeploy the older SSE version.**

## Historical investigation (v3/v4; not current deployment instructions)

Date: 2026-09-18, Asia/Manila. Status: **v3 bitrate/freshness fix deployed; final verification found remaining public stalls. Scoped v4 SSE fix prepared, awaiting owner sudo deployment. Not complete.**

## Post-deployment findings and next scoped fix

The owner deployed v3 successfully at 08:42:14. Protected backup: `/var/backups/gohmotech-camera-realtime/20260918T004214Z`. Django restarted and is active/running (PID 7485); Nginx and cloudflared were not restarted. Published `live-camera.js` matches source SHA-256 `0e5a9e6ca52e53e593e3f7d7a8750cf3face499f790704792b0215eab4a719ab`. Production smoke checks passed again, including login, marketplace, static/manifest, and device-authentication rejection checks.

**The deployed public stream did not pass final sustained freshness verification.**

| Deployed v3 run | Nginx changing FPS | Public changing FPS | Public sequence lag median / p95 / max | Public maximum frame gap |
| --- | --- | --- | --- | --- |
| 90 seconds, reconnect, concurrent desktop browser | 507 / 90.07 s = 5.63 | 351 / 94.68 s = 3.71 | 1.880 / 8.246 / 20.629 s | 13.289 s |
| 90 seconds, continuous stream, no additional test browser | 511 / 90.04 s = 5.68 | 507 / 90.14 s = 5.62 | 0.132 / 6.531 / 9.727 s | 3.377 s |

The second run demonstrates why matching average FPS is insufficient: delayed bursts eventually catch up, but the images were temporarily almost ten seconds old. Thus the original bitrate mismatch is a contributor, **not the whole remaining cause**. Public buffering/bursty tunnel/network behavior remains after the reduced rate; no specific edge rule can be identified without account access.

At 08:44:32, cloudflared logged `failed to accept QUIC stream: timeout: no recent network activity`, failed datagram handling, and connection termination for connection index 2. It re-registered at 08:45:38. This is genuine tunnel instability, unlike ordinary client-canceled-stream logs. It does not prove that every stall came from that connection; camera requests also used other connection indices.

The actual desktop HTTPS browser initially displayed approximately six FPS with capture-age bounds around 0.7–1.9 seconds. It detected age above three seconds, rejected buffered frames, and reduced bitrate, but still experienced freezes during a later delivery stall. Navigation back recovered automatically to Live. No JavaScript exception was recorded. The first offline-emulation attempt did not close the existing stream, so it is **not counted** as a valid disconnect test.

Actual mobile-emulated HTTPS test: 390×844, DPR 3, fourfold CPU throttling. Displayed-pixel hashes were instrumented in the test browser, not production code. The preview initially updated near six FPS, but buffering forced fallback to two FPS. Client stream was explicitly canceled at t≈25 seconds while Chromium was offline; count remained 70 through t≈35, then Live/new pixels returned by t≈40 after restoration. Continued viewing through t≈85 reached 150 displayed frames and 150 changing pixel hashes; capture-age samples after recovery were approximately 0.3–0.9 seconds. Navigation away/back returned to Live with 23 fresh frames within the ten-second return observation. No JavaScript exception. Recovery works; continuous six-FPS reliability remains unproven.

### Prepared v4 change, not yet deployed

- Opt-in `transport=sse` on the **same authenticated camera endpoint**, same capture thread, same shared JPEG encoder, same quality/rate limits and age guard.
- Genuine SSE framing carries base64 JPEG, source sequence, and atomic capture time; response is correctly `text/event-stream`, with an initial flush comment. No false MIME override on binary MJPEG. This follows Cloudflare's documented unbuffered streaming transport behavior: https://developers.cloudflare.com/tunnel/troubleshooting/.
- Dashboard/detail monitoring script selects SSE and parses fragmented events; legacy native MJPEG clients remain supported. Asset version v4 avoids reuse of v3 static-cache entries.
- Base64 adds approximately 33% payload overhead (around 0.45 Mbit/s for the measured small preview); public sustained-throughput and freshness testing are still required after deployment.
- No tunnel protocol/config/security changes. An HTTP/2 trial was considered but **not applied**, because HTTP/2 tunnel connections do not support the post-quantum key agreement currently used by QUIC: https://developers.cloudflare.com/tunnel/reference/run-parameters/#post-quantum. Its draft helper/config were removed. HTTPS, authentication, and the existing tunnel remain intact.
- All **232 isolated regression tests passed**, including 15 camera tests. A real Chromium synthetic fragmented-SSE test exercised the actual v4 script: a deliberately six-second-old frame caused immediate rejection/reconnect to four FPS; 38 fresh frames displayed by t≈10 seconds, maximum active connection one, zero JavaScript exceptions. This fixture is not a substitute for actual public deployment testing.
- v3 pre-v4 source/served backups: `/tmp/gohmotech-camera-sse-backup-MAk1jR9P`; `deploy/install_camera_sse.sh` reuses the narrow validated installer and rolls back to v3 on deployment failure. It publishes only the changed script and restarts only Django, with durable protected backups.

Required owner step:

```sh
sudo bash /home/gohmotech/capstone/deploy/install_camera_sse.sh
```

Afterward compare MJPEG versus SSE across actual backend/Nginx/public stages for 60–120 seconds, including capture-publication age, and repeat desktop/mobile prolonged rendering and interruption/navigation checks. Do not call v4 successful until those checks pass.

## Actual production architecture

IP camera RTSP → one in-process OpenCV capture thread using the FFmpeg backend → shared latest frame and cached JPEG encodes → Django asynchronous MJPEG iterator → one Daphne ASGI process on 127.0.0.1:8010 → Nginx on 127.0.0.1:8080 → remotely managed Cloudflare Tunnel (`cloudflared` 2026.8.3, QUIC) → Cloudflare public HTTPS edge → browser fetch/parser/JPEG decoding.

The remotely supplied tunnel ingress maps `gohmotech.site` to `http://127.0.0.1:8080`, with a terminal 404 rule. Four tunnel connections were active across Manila/Hong Kong locations; measured public responses came through the Singapore edge. No local tunnel YAML is used. The token file was not read or changed. The application, Nginx, and tunnel were active/running.

## Bottleneck and evidence

The rate collapse and progressively old frame sequences occur **after Nginx**, across the public tunnel/edge/network delivery path. At 640 pixels, quality 75, 12-FPS ceiling, the origin produces approximately 2.52 Mbit/s of MJPEG while public delivery in the same run carries only 0.628 Mbit/s. Capture remains current and origin consumers receive new sequences continuously. A long-lived ordered stream then delivers increasingly old JPEGs rather than discarding the upstream transport backlog. The existing browser parser drops intermediate complete frames from a single read, but cannot discard bytes still queued in the tunnel/network.

Reducing the offered rate, without changing Nginx, the tunnel, capture, or transport, brought public throughput close to the origin in the initial controlled runs. This establishes an unsustainable public delivery-rate mismatch as a contributor. Later deployed tests above found burst delays even at this reduced rate, so that first intervention was insufficient. The exact contribution of WAN capacity, tunnel/edge buffering, and per-connection behavior cannot be separated with available local logs and no Cloudflare account-rule access. It is **not justified** to claim packet loss, a CDN cache hit, or a specific Cloudflare defect as the proven underlying physical cause.

Cloudflare documents that Tunnel may buffer streaming responses unless `Content-Type: text/event-stream` is used: https://developers.cloudflare.com/tunnel/troubleshooting/. That is a relevant risk, not proof that changing the MJPEG MIME type would cure the measured transfer-rate mismatch. No dishonest MIME-type override or transport redesign was applied.

## Timed comparisons on the actual Pi and domain

Each run below used simultaneous Daphne/Nginx/public consumers, 75 seconds total and one client disconnect/reconnect around the midpoint. Counts are changing JPEG hashes, not HTTP request counts or repeated frames. Sessions belonged to an existing authorized administrator and were deleted after each probe.

| Run/profile | Backend | Nginx | Public HTTPS | Public lag versus backend, median / p95 / max |
| --- | --- | --- | --- | --- |
| Supplied earlier baseline | not measured | 780 / 92 s ≈ 8.5 FPS | 65 / 96 s ≈ 0.68 FPS | not measured |
| New baseline: 640 px, q75, ceiling 12 FPS | 688 / 75.14 s = 9.16 FPS | 686 / 75.01 s = 9.15 FPS | 170 / 75.00 s = 2.27 FPS | 16.874 / 26.019 / 27.693 s |
| Candidate: 320 px, q50, ceiling 6 FPS, with concurrent desktop high-bitrate viewing during part of run | 439 / 75.09 s = 5.85 FPS | 439 / 75.09 s = 5.85 FPS | 410 / 75.04 s = 5.46 FPS | 0.436 / 3.810 / 4.218 s |
| Candidate repeated independently: 320 px, q50, ceiling 6 FPS | 440 / 75.06 s = 5.86 FPS | 441 / 75.06 s = 5.88 FPS | 431 / 75.17 s = 5.73 FPS | 0.216 / 2.084 / 3.243 s |

Independent candidate transfer: mean JPEG 7,381 bytes, Nginx 0.355 Mbit/s, public 0.348 Mbit/s. New baseline mean JPEG approximately 34,274 bytes, Nginx 2.522 Mbit/s. Measured bitrate reduction is approximately 86%, not a blind camera-resolution change. RTSP capture resolution/settings and high-quality snapshots are preserved.

New baseline first frame: backend 0.063 s, Nginx 0.074 s, public 1.648 s. Public reconnect first frame 1.255 s, followed by renewed backlog growth. No interframe gap exceeded two seconds; that does not mean real-time video—the image was updating while becoming stale.

Independent candidate first frame: backend/Nginx 0.079 s, public 0.822 s. Reconnect first frame: backend 0.065 s, Nginx 0.074 s, public 1.264 s. Maximum public frame gap 1.511 s; no gaps exceeded two seconds. Transient delay remains, motivating the new age guard. These lag measurements compare source sequences with backend arrival, not a physical camera-to-screen timestamp calibration.

## Production configuration and resource checks

- Active Nginx configuration is `/etc/nginx/conf.d/gohmotech-production.conf`, not a sites-enabled file. Its application location uses HTTP/1.1, `proxy_buffering off`, 300-second read timeout, and the existing connection-upgrade map. No proxy cache is configured. Request buffering concerns uploads, not this GET response. Nginx global gzip only targets its default text/html type, not MJPEG.
- Django sends `no-cache, no-store, must-revalidate, no-transform` and `X-Accel-Buffering: no`. Public replies report `cf-cache-status: DYNAMIC`, no Content-Encoding, and chunked transfer. There is no demonstrated Nginx caching/compression/buffering cause, so its configuration is unchanged.
- Tunnel logs showed client-canceled requests, not repeated tunnel registration failures during the test window. Four connections remained active. Cancellation logs alone are not evidence of tunnel instability.
- Pi temperature approximately 50°C, `get_throttled=0x0`, approximately 6.7 GB memory available, zero swap use. Daphne CPU was approximately 36–42% of one core in sampled checks, not device-wide saturation. Wi-Fi signal −48 dBm, advertised TX 65/RX 72.2 Mbit/s; those link rates do not establish WAN upload capacity. Interface TX errors/drops were zero.
- Capture drains RTSP continuously and replaces one latest frame; there is no growing application frame queue or per-browser RTSP decode. Encoding is cached and protected by bounded locks. Database writes occur on status transitions rather than per-delivered-frame database reads. Separate Celery processes can still have independent RTSP captures; they were not redesigned.
- Service worker caches only `/static/`, not dynamic camera requests. Monitoring components already stop on hidden/offscreen/page-exit and recover on return. Dashboard polling does not replace the camera element or reload the whole page periodically.

## Real browser baseline

An isolated real Chromium desktop browser loaded the authenticated public camera-detail page. Samples at 15/20/25 seconds showed only 2/4/6 displayed frames, at 1280×720. It reported Live despite slow updates: the old watchdog detected missing frames, not old frames. No JavaScript exception was recorded. The noninteractive `--password-store=basic` option resolved the Pi desktop-keyring hang that had previously prevented browser diagnostics; this flag is for the temporary test browser only.

## v3 changes (deployed by owner; v4 extends these as described above)

- `iot/views.py`: preview defaults become 320-pixel width, JPEG q50, 6-FPS ceiling. Explicit higher-quality requests remain available. Add per-frame capture timestamp and per-connection start timestamp. Existing authentication, MJPEG, ASGI/WSGI iteration, and cache/security headers remain.
- `iot/camera_utils.py`: optional atomic capture timestamp alongside the existing JPEG packet; existing two-item callers remain compatible. Cached JPEGs retain their actual source capture timestamp.
- `static/js/live-camera.js`: remove the mobile 640-pixel override. Calculate conservative capture age using the Pi's relative timeline and browser monotonic time, without requiring synchronized client clocks. Reject frames older than three seconds, abort the queued stream, and reconnect promptly with reduced q40/4-FPS then q40/2-FPS profiles. Network failures retain existing bounded retry behavior. Resolution/source aspect ratio, bounded parser, and URL/lifecycle cleanup are retained.
- `iot/templates/iot/dashboard_modern.html` and `iot/templates/iot/camera_detail.html`: request the measured profile; static asset version changes from v2 to v3 so old service-worker/static-cache entries are not reused.
- `iot/test_camera_streaming.py`: capture timestamp/cache/staleness and bounded preview/explicit high-quality regression coverage.
- `deploy/camera_delivery_probe.py`: repeatable authenticated simultaneous stage measurements with hash changes, sequence lag, first frame, gaps, reconnect, and transfer diagnostics; never prints credentials or retains images.
- `deploy/camera_browser_probe.py`: actual public-page Chromium desktop/mobile-emulation and network/navigation checks using a temporary browser profile/session. Diagnostic-only websocket-client was downloaded into `/tmp/gohmotech-browser-tools`; production dependencies were not changed.
- `deploy/install_camera_realtime.sh`: narrow owner-sudo deployment with protected backups, application check, Nginx syntax validation, only the changed static asset published, only Django restarted, smoke checks, and rollback on deployment failure.

## Safety, verification, and remaining work

Existing unrelated/uncommitted user changes were preserved. Pre-edit source/served-file backups are in `/tmp/gohmotech-camera-backup-dJ3Lm6YN`. The deployment script copies these to a root-protected timestamped `/var/backups/gohmotech-camera-realtime/` directory before publishing or restarting.

All **230 isolated regression tests passed**, including 13 camera tests. Shell syntax validation and `git diff --check` passed. Tests used disposable SQLite storage and no live providers. Two sandbox-hung diagnostic test processes were stopped; no production process was killed. No migrations, production-data resets/deletions, camera hardware changes, authentication bypasses, HTTPS changes, or additional public ports occurred.

**Services restarted/reloaded: Django production only, by the owner at v3 deployment.** Nginx/tunnel configuration remains unchanged. This is not marked solved.

Owner action:

```sh
sudo bash /home/gohmotech/capstone/deploy/install_camera_sse.sh
```

After v4 succeeds, repeat 60–120-second origin/public SSE comparisons and capture-publication age. Repeat real public-page desktop and mobile-emulated prolonged updates and lifecycle checks. Existing open tabs need one navigation/reload to receive the new script; the goal is then continuous automatic updates, not repeated manual reloads.

Remaining limitations: small monitoring preview, transient WAN/tunnel jitter, adaptive FPS potentially below 5 under constrained links, no physical-phone confirmation yet, no physical RTSP outage introduced, and no camera-embedded timestamp validation of total sensor-to-screen latency. Arbitrary forced high-bitrate/native MJPEG clients can still exceed the public link; the adaptive age guard protects the dashboard/detail monitoring components once deployed.
