# GoHMoTech Ionic Mobile Client Architecture

## 1. Existing architecture analysis

GoHMoTech is a Django 6 monolith backed by MySQL. It uses server-rendered pages and Django REST Framework side by side. Production runs ASGI with Channels/Redis, while Celery handles scheduled/background work. IoT devices post to authenticated compatibility endpoints and continue to own all hardware communication; the mobile application never contacts an ESP32, HX711, BLE receiver, camera, or ML worker directly.

The established domain boundaries are:

- `iot`: devices, environmental readings, actuators, goats, weight measurements, camera configuration/streaming, BLE tracking, and missing-goat data.
- `feeding`: feeder configuration, levels, schedules, logs, and manual-feed command creation.
- `ml_models`: goat detections and model management.
- `security`: the unified notification inbox and person detections.
- `analytics`: stored report records and server-rendered report datasets/exports.
- `marketplace`: listings, inquiries, conversations, reservations, pickups, sales, and seller workflows.
- `sms`: SMS settings, reminders, and delivery logs.

Roles are already authoritative in Django: admin, Farm Owners, Farm Operators, and marketplace-only users. `FarmRolePermission` permits owner/admin writes and operator reads. The mobile UI must reflect those capabilities, but Django remains the enforcement point.

## 2. Existing reusable APIs

| Area | Existing endpoint | Notes |
| --- | --- | --- |
| Sensors | `/iot/api/sensor-readings/`, `/latest/`, `/device_history/` | Authenticated reads; device-key writes |
| Device sensor data | `/iot/api/sensor-data/` | Filterable, paginated |
| IoT alerts | `/iot/api/alerts/` | Owner/admin; resolve action exists |
| Actuators | `/iot/api/actuators/`, `/{id}/control/` | Server-authorized commands; honest sent/queued result |
| Automation | `/iot/api/automation-rules/`, `/actuation-logs/` | Existing rule and history APIs |
| Feeding | `/feeding/api/config/`, `/schedules/`, `/levels/`, `/logs/` | Includes status/toggle/manual-feed actions |
| BLE tracking | `/iot/api/ble/tracking/` | Correctly reports proximity, not GPS |
| ML detections | `/ml/api/detections/` | Paginated detection history |
| Notifications | `/security/api/notifications/` | Filtering, unread count, read/resolve actions |
| Person detections | `/security/api/detections/` | Filtering and review action |
| Reports | `/analytics/api/reports/` | Saved report records only, not chart-ready series |
| WebSockets | `/ws/sensors/`, `/ws/alerts/`, `/ws/feeding/`, `/ws/detections/` | Channels groups already exist |

The camera pipeline is RTSP/HTTP input decoded once on the Raspberry Pi, then emitted to browsers as latest-frame MJPEG, SSE, or JPEG. It avoids page refreshes and has recent low-latency/latest-frame work, but MJPEG remains more bandwidth-heavy than WebRTC and has no adaptive bitrate or audio.

## 3. Missing APIs required by Ionic

The initial mobile adapter under `/api/mobile/` adds only gaps needed for a native client:

- token login/logout/current-user with existing Django credentials and roles;
- a compact dashboard aggregate;
- paginated goat cards and goat detail/weight history;
- authenticated goat-image delivery;
- a camera catalog;
- short-lived camera and WebSocket tickets so bearer tokens are never placed in media/WebSocket URLs;
- the existing BLE snapshot exposed at a consistent mobile route.

Still missing for later phases:

- goat create/update plus validated multipart angle-photo upload;
- chart-ready environmental, feeding, weight, and security report series;
- marketplace serializers/viewsets for listings, inquiries, reservations, sales, and allowed transitions;
- a unified automation summary containing schedules, next feeding, recent feeding history, and actuator state;
- push-device registration for a future Capacitor notification provider.

## 4. Ionic folder structure

`goh-mo-tech-app/src` is organized into `components`, `composables`, `layouts`, `pages`, `router`, `services`, `stores`, `types`, `utils`, and `theme`. Routes are lazy-loaded. The five persistent tabs are Home, Live, Goats, Alerts, and More; secondary modules live outside the tab outlet and return to More.

## 5. Authentication strategy

The existing Django website keeps session authentication. Mobile APIs additionally accept DRF token authentication. Login authenticates against the same Django user table and rejects accounts without a farm role. Logout revokes the server token.

The first client keeps its bearer token in memory only. This intentionally means a fresh sign-in after process restart, but avoids insecure `localStorage` or Capacitor Preferences. Server tokens expire after 30 days (configurable with `MOBILE_TOKEN_TTL_DAYS`) and logout revokes them immediately. When a native secure-storage plugin is selected, only `stores/auth.store.ts` needs a persistence adapter. Production remains HTTPS-only, API authorization remains server-side, login is throttled, and secrets are never compiled into the app.

## 6. Real-time strategy

Channels remains the real-time authority. The mobile app exchanges its bearer token over HTTPS for a signed 60-second WebSocket ticket, then connects over WSS. Connections use exponential backoff and are closed with page/component cleanup. REST is used for initial state and reconciliation after reconnect; sockets provide invalidation/live events rather than forcing one-second polling.

## 7. Camera strategy

Phase 1 reuses the proven Pi camera manager and requests a mobile profile (640 px, 8 fps, JPEG quality 55) through an expiring camera ticket. The player preserves a 16:9 container and uses `object-fit: contain`, with selector, loading, offline, reconnect, and fullscreen states.

WebRTC is the recommended camera phase after measuring CPU, tunnel behavior, and concurrent viewers. Add an RTSP-to-WebRTC gateway (for example go2rtc or MediaMTX) beside the current pipeline, keep MJPEG as fallback, and do not replace the existing stream until WebRTC health/fallback behavior is proven on the Raspberry Pi.

## 8. Implementation phases

1. **Foundation (implemented):** auth, routing, API/error handling, network states, five-tab shell, compact dashboard, camera player, goat inventory/detail, alerts, automation controls, BLE tracking, and security event list.
2. **Owner workflows:** goat create/edit, responsive camera capture by angle, client-side compression, preview/retake/remove/confirm, and live weight UI.
3. **Operations depth:** feeding schedule/history/manual-feed confirmation, richer automation state, alert-driven live refresh, and detection details with lazy authenticated thumbnails.
4. **Reports:** bounded chart-ready endpoints and small responsive visualizations loaded per report.
5. **Marketplace:** scoped REST APIs and mobile listing/inquiry/reservation/sales workflows using the same marketplace tables and service logic.
6. **Native hardening:** secure-storage adapter, optional push registration, connectivity plugin, Android/iOS deep links, and device testing at 360/390/412 px.
7. **Camera optimization:** benchmark MJPEG, then introduce WebRTC as an additive path with MJPEG fallback.
