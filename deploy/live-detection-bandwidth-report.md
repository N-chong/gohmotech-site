# Live detection bandwidth investigation — 2026-10-13

## Measured cause

The deployed Pi uses a local RF-DETR Nano checkpoint. The existing Live Detection
page streamed JPEG camera frames to the browser, sent a full-size JPEG back to
`/ml/api/detect/` for each inference, and repeatedly fetched up to 500 complete
detection records from `/ml/api/detections/recent/` while rendering only 15.
The detector itself did not require a hosted inference service.

For the apparent test window, 2026-10-12 17:53 through 2026-10-13 01:53
(Asia/Manila), Nginx access logs record:

| Response path | Requests | Response bytes |
| --- | ---: | ---: |
| `/ml/api/detections/recent/` | 5,426 | 2.77 GB |
| `/iot/camera/feed/1/` | 21 long-lived streams | 1.466 GB |
| 960-pixel camera JPEG polling | 202 | 0.017 GB |
| `/ml/api/detect/` | 4,388 | 0.008 GB |

Nginx's existing log format omits request body bytes, so the repeated browser
JPEG uploads are additional unmeasured upstream traffic. The measured response
traffic alone was about 4.25 GB. These figures explain most of the reported
5 GB without attributing it to RF-DETR or remote model inference.

## Change

- A single Pi-local Celery worker processes full-resolution camera frames while
  there is scheduled, manual, or live-viewing demand. Redis leases and a lock
  prevent duplicate inference workers. The existing goat detection,
  re-identification, detection record, and person notification paths are used.
- Celery Beat checks demand every 15 seconds. The scheduled window is the first
  two minutes of each Manila clock hour. It operates without a browser.
- A live page holds a short viewer lease while visible. Its browser receives
  only a reduced preview stream and compact detection status; it does not
  upload frames for routine inference. Closing or hiding the page releases its
  lease. Manual Start persists until manual Stop.
- The Live Detection page requests 15 recent records instead of 500 and polls
  that list every 20 seconds. Its preview is capped at 480 pixels, JPEG quality
  40 and 2 FPS. Dashboard and camera-detail previews are capped at 640 pixels,
  quality 45 and 3 FPS. Full-resolution local inference is unaffected.

## Verification

- Django system check, Python compilation, template rendering, and schedule
  boundary checks passed.
- A direct production-camera probe saved two normal detections and stopped its
  local camera stream after the temporary viewer lease expired.
- The production control view returned the expected Inactive, Live Viewing,
  Manual, Live Viewing, and Inactive sequence for temporary viewer/manual
  actions. Temporary Redis state was removed.
- Two watchdog ticks with temporary demand dispatched one worker.
- The owner restarted production Django, Celery worker, and Celery Beat at
  10:33 Manila time on 2026-10-13. All three services were running afterward.
- Production HTTP smoke checks passed. The authenticated Live Detection page
  served the new reduced stream and control route; the control API returned the
  next scheduled start at 11:00 Manila time.
- The deployed 15-record history response was 9,013 bytes on loopback, versus
  roughly 511 KB per request in the earlier access-log window.
- The deployed Beat watchdog ran every 15 seconds. A temporary viewer lease
  started one deployed worker, which saved a detection from the real camera;
  after the lease ended, the worker released its camera stream and Redis lock.
- A follow-up resource check found the web process still decoding RTSP after
  all feed requests ended. An idle timeout now releases unpinned web streams
  after 90 seconds; explicit camera Start/Connect controls remain persistent.
  The camera-stream test suite passed (20 tests). Celery now recycles a worker
  child after a completed task exceeds about 1 GiB RSS, releasing retained
  RF-DETR allocator memory between sessions.
- The Live Detection page now registers viewing demand when it begins connecting,
  avoiding browser-specific delays in multipart image load events. A stream
  error releases that viewing demand.

At the first unattended production window on 2026-10-13, mode became
`Scheduled` at 11:00:03 Manila time with zero viewers. The worker lock appeared
at 11:00:13. Mode became `Inactive` at 11:02:03, and the worker lock was gone by
11:02:53. The observer found four saved detection records in the window and
confirmed `Inactive` with no worker lock at 11:04.

The owner restarted Django and the Celery worker at 11:06. The authenticated
production page, control API, and 15-record history request passed smoke checks
afterward. A 320-pixel JPEG probe returned a 14,711-byte frame at 11:07:39;
with no further consumer requests, the web process logged idle camera shutdown
at 11:09:09. A separate temporary viewer lease then started local inference,
saved another detection, and released the worker's camera and lock after the
lease ended. The RF-DETR worker child (PID 219030) was replaced by PID 219686
after completing that task, verifying memory recycling. The production services
were still active after these checks.

## Follow-up: admin and owner dashboard activation

The first version registered live-viewing demand only on the Live Detection
page. Production logs showed the dashboard requesting camera previews without
any `/ml/api/live-detection/` viewer heartbeat, so simply opening the system
did not start CV. Admin and farm-owner pages now register a visible-tab lease
from the shared base template. It stops when the tab is hidden or closed and
resumes when the user returns; Live Detection reuses that lease instead of
creating a second one. The owner and admin dashboards show the resulting mode.
The admin dashboard preview is limited to 320 pixels, JPEG quality 40, and
1 FPS. A browser fallback for viewer UUID creation supports local HTTP access.

Before restart, Django rendered the presence and status controls for both
production roles; each role successfully used the CSRF-protected lease API.
Headless Chromium exercised the browser code and observed view, leave, and
resume actions with a valid UUID. This follow-up requires a Django restart to
become active in the deployed process.
