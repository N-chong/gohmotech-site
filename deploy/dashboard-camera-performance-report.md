# Dashboard and live-camera performance report

Date: 2026-09-17 (Asia/Manila). **Deployed:** served asset checksums match the source; the production Django service restarted at 00:56:37 (PID 15989), the existing user Celery worker restarted, and production smoke checks passed. Existing uncommitted changes were preserved. No dependencies, database migrations, camera credentials, hardware settings, or production proxy settings were changed.

## Root cause

- `iot/camera_utils.py` retained and returned the last captured frame indefinitely, including after failed reads/reconnection. The MJPEG generators reset their timeout whenever those old bytes were returned. A disconnected capture could therefore masquerade as an indefinitely healthy feed. This failure mechanism is reproduced by regression tests; the historical upstream trigger cannot be conclusively identified without timestamped capture telemetry.
- The Dashboard camera used a native MJPEG `<img>` with only a terminal error handler, no per-frame freshness check, and no automatic retry. The detail page inferred “live” from backend status rather than decoded browser frames.
- Capture slept 40 ms after each decode, potentially queueing frames from a faster RTSP source. Setting `CAP_PROP_FPS`/`CAP_PROP_BUFFERSIZE` does not guarantee control of an FFmpeg RTSP source. Actual probe input was approximately 12 FPS; high resolution was **not identified as the freeze cause**.
- `dashboard_modern.html` reloaded the complete page every 45 seconds, rebuilding the scene and reconnecting the camera. Startup requested feeder configuration twice and immediately re-fetched data already rendered by Django. Three five-second API polls generated approximately 36 requests/minute, excluding full reloads and popup actions.
- `goat_house_viewer.js` rendered a static, shadowed 3D scene continuously, including offscreen, at up to 1.75 device pixel ratio. Three.js and the scene code loaded immediately even far below the phone viewport.
- Dashboard alert rendering accessed `alert.device` without `select_related`. Separate aggregate/count/existence queries added avoidable database work.
- A Celery real-time detection task created its own camera manager and did not stop its capture thread in `finally`, allowing a stopped task to leave an RTSP connection running.

## Changes made

- Preserve the existing shared camera manager, OpenCV/FFmpeg capture, MJPEG endpoint, WSGI/ASGI handling, permissions, and UI features.
- Publish monotonic frame age and sequence; reject stale frames for video, snapshots, and AI consumers. Failed `grab()` cannot retrieve an old frame. Detect stalled FFmpeg presentation timestamps only after observed progression, avoiding false alarms on unsupported/constant-zero backends.
- Drain capture continuously, retain bounded open/read timeouts, and use interruptible bounded reconnect backoff. Restart an exited managed worker on the next stream request. Camera-status database failures no longer kill capture.
- Cache JPEG encodes by source sequence, quality, and width with bounded memory. Send only new sequences, with multipart `Content-Length` and `X-Frame-Sequence`. Add receiving/delivery progress logs every 30 seconds and per-client closure counts. Keep no-cache/no-buffer headers and add `no-transform`.
- Consume the same MJPEG response through a bounded browser stream parser. Announce Live only after JPEG decode; reconnect on EOF/errors or 15 seconds without a new decoded frame, with 2–30-second backoff. Discard buffered intermediate packets, revoke object URLs, and abort feeds on hidden tabs, offscreen components, and page exit. Expose displayed count/sequence and log browser progress/staleness. Show Live, Reconnecting, Offline, or Paused.
- Use a delivery cap of 12 FPS and quality 75 on Dashboard/detail monitoring. Phone delivery is 640 pixels wide with the source aspect ratio; desktop delivery remains up to 1280. Source capture and full-resolution snapshots/AI frames are unchanged. Mobile delivery was reduced **after** identifying the freeze mechanism and measuring frame size.
- Refresh Dashboard cards/status/activity in place every 45 seconds without replacing the camera, 3D scene, or control handlers. Initial values remain server-rendered. BLE polls every 10 seconds; feeding polls every 20 seconds. Prevent overlapping requests and skip hidden tabs. Count active schedules correctly across paginated results.
- Lazy-load the existing 3D assets near the viewport. Render only for scene changes/camera interaction, pause offscreen/hidden, use pixel ratio 1 and no MSAA on phones, and preserve shadowed visuals and controls. Handle browser history return without duplicate scenes.
- Join alert/device queries and combine environmental/vaccination/feed aggregates. Stop the Celery task's own capture in `finally`; its AI behavior is unchanged. Separate Celery processes still have independent capture connections; this is not a cross-process singleton architecture.

## Files modified for this task

- `iot/camera_utils.py`
- `iot/views.py`
- `iot/ai_tasks.py` (capture cleanup only)
- `iot/templates/iot/dashboard_modern.html`
- `iot/templates/iot/camera_detail.html`
- `static/js/goat_house_viewer.js`
- `static/js/live-camera.js` (new)
- `static/js/dashboard-runtime.js` (new)
- `iot/test_camera_streaming.py` (existing tests preserved; additional regressions)
- This report.

## Performance improvement

- Warm Dashboard query count on actual production data: **37 → 35**. Alert lists additionally avoid up to one device lookup per alert. Timing samples were noisy (original warm 59–89 ms; optimized 44–86 ms), so no precise latency percentage is claimed.
- Scheduled API polling: **36 → 12 requests/minute**, approximately 67% fewer, excluding user-triggered actions and the one HTML metrics refresh per 45 seconds. The six initial redundant/status API requests were removed. The metrics refresh still computes the full Dashboard context and transfers its HTML; it is not a new minimal JSON endpoint.
- Real-camera frame payload: approximately **96 KB full-width → 31 KB mobile**, roughly **68% less data per frame**. In the two-viewer probe, delivery was approximately 9 FPS while capture produced approximately 12 FPS; the configured 12 FPS is a ceiling, not a guaranteed rate. Mobile delivery was around 2.2 Mbit/s during healthy intervals.
- Continuous offscreen/static WebGL rendering and below-fold camera delivery are eliminated by lifecycle controls. No measured device-wide RAM reduction or physical-phone scrolling improvement is claimed.

## Camera test result

- Two isolated real-camera runs lasted **152 seconds each**, including a **20-second simulated capture interruption**. No live camera/network settings or production camera records were changed. This was not a physical network cable/RTSP-server outage.
- Final run: phone-width and desktop-width ASGI consumers shared **one initial RTSP connection**. Only **one additional real RTSP open** occurred for recovery; viewer count did not multiply capture connections.
- Interrupt at t=40 s; stale/non-live by t=50 s; no old frames sent during outage; automatic RTSP reopen and both consumers receiving new sequences by t=70 s after interruption ended at t=60 s. Continued new frames through t=150 s; final source sequence **1483**, mobile **1070** delivered frames, desktop **1083**.
- Real-time Chromium frontend fixture at **390×844, DPR 3, 4× CPU throttling** verified fragmented MJPEG headers/payloads, an open connection that stops producing frames, automatic recovery, and hide/return/history events. Maximum active connection was one, JPEG object URLs remained bounded, and the feed returned to Live. The fixture used generated JPEGs and simulated transport, not the real HTTP/Cloudflare route.
- A separate Chromium Dashboard fixture passed: concurrent refresh calls made one request; metrics, alerts, and light state updated while retaining the original camera element, scene, and working control handler.
- **228 isolated project tests passed**, covering IoT/device authentication, automation, BLE, photo workflows, Dashboard, marketplace, analytics, SMS, and deployment checks. `git diff --check` passed. Production remained active and was not restarted.

## Deployment and remaining validation

The three changed/new static assets were collected and published to the root-owned served static directory with owner-assisted sudo; Django and the existing user Celery worker were restarted. Celery Beat remained running; service units, Nginx, and DNS were not replaced. The monitoring scripts use versioned asset URLs to avoid the current service worker's old cache entries. No migration was required. Open Dashboard tabs need one reload/navigation to pick up the new client code.

Post-deployment authenticated HTTP verification used one temporary administrator session, deleted afterward, and did not interrupt the production camera. All three assets returned 200 and the Dashboard contained the new monitoring/runtime markup on both origin and public HTTPS. Two 45-second streaming phases with a client disconnect/reconnect delivered **780 frames / 778 distinct JPEGs in 92 seconds through Nginx**, with increasing sequence 1–1093 and approximately 30.7 KB/frame. **Public HTTPS delivered only 65 frames / 64 distinct JPEGs in 96 seconds**, with substantial delayed delivery, and failed the sustained-throughput check. Backend receive/delivery progress continued. Therefore deployment succeeded but **public real-time reliability is not yet resolved**; the bottleneck observed in this check is downstream of the healthy origin, somewhere in tunnel/edge/network delivery, not conclusively Cloudflare itself. New source receipt logged 2304×1296, with the existing worker scaling monitoring frames to 1280×720 and phone delivery to 640 pixels wide.

Do not consider the complete production issue closed yet: Chromium in this environment failed even a minimal localhost HTTP navigation, while curl reached that server. Consequently a full Dashboard browser timing/scrolling comparison and a real-camera browser test through Django, Nginx, and Cloudflare remain unverified. The supplied Nginx config already disables proxy buffering and the production service runs one Daphne process; actual Cloudflare behavior was not changed or conclusively ruled out. After deployment, repeat a longer sustained mobile/public-HTTPS test, hide/return test, and controlled genuine camera/network interruption without disrupting livestock monitoring.

For a future freeze, compare the 30-second capture `receiving frames` logs, MJPEG `delivering` sequence/count logs, status API `frame_age_seconds`/`worker_alive`, and browser `Camera frames displayed`/`Camera delivery stale` messages plus image `data-frame-sequence`/`data-frames-displayed`. Successful reads with advancing timestamps cannot conclusively distinguish a genuinely static scene from a camera encoder repeating identical pictures; unsupported timestamp backends are not forced to reconnect just because pixels are unchanged.

References: [OpenCV capture timeout properties](https://docs.opencv.org/4.10.0/d4/d15/group__videoio__flags__base.html), [browser readable-stream lifecycle](https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream/getReader).
