# GoHMoTech redesign brief and system behavior

This document is a design handoff for another AI or designer. It describes what the existing system does, who uses it, how its main workflows behave, and what a redesign must preserve. It is not a request to change the backend or invent new capabilities.

## 1. Product summary

**Product name:** GoHMoTech Smart Goat House / Smart Goat Farm Management System

**Product type:** A responsive Django web application, progressive web app, and early Ionic mobile client for operating a goat farm and running a community goat marketplace.

**Main purpose:** Give farm personnel one place to monitor goats, cameras, sensors, feeding equipment, doors, lights, alerts, reports, and marketplace activity.

The system joins eight functional areas:

1. Farm overview and operational dashboard
2. Goat inventory, health, vaccination, photos, and weight records
3. IoT sensors, devices, doors, lights, and automation
4. Automated and manual feeding
5. Camera streaming and AI detection
6. BLE proximity tracking and missing-goat alerts
7. Security notifications, SMS, analytics, and exports
8. Community marketplace, inquiries, reservations, pickup, and support

## 2. Important product truths

The redesign must communicate these truths accurately:

- BLE tracking reports **proximity to a receiver**, not GPS coordinates or a map position.
- AI can detect goats and people. The current security feature does **not** identify a person's face or identity.
- Goat re-identification fields exist, but individual visual recognition is not a reliable primary workflow. Tags, records, reference photos, and BLE beacons remain important.
- A control request can be sent or queued before a physical device confirms execution. The UI must distinguish requested, pending, confirmed, failed, offline, and stale states.
- Marketplace payments and shipping are not supported. A sale ends through reservation, agreed farm pickup, and manual completion.
- Smart-farm goats and community-seller goats share some data structures but have separate ownership and access rules.
- Dangerous farm changes are owner/admin actions. A farm operator mainly monitors and reads data.
- Sensor timestamps distinguish when the device measured a value from when the server received it. Stale readings must not look live.

## 3. User roles and permissions

| Role | Purpose | May do | Must not do |
| --- | --- | --- | --- |
| System administrator | Operates the full platform | All farm functions, device/ML configuration, users, seller approvals, marketplace moderation, SMS settings, reports | Nothing inside normal application scope |
| Farm owner | Operates the smart farm and sells farm goats | View farm data, manage goats, control actuators, schedules and automation, respond to alerts, view reports, manage farm marketplace records | Admin-only user/platform configuration |
| Farm operator | Monitors day-to-day farm activity | View dashboard, goats, devices, cameras, tracking, detection data and other safe read-only information | Change farm records, actuator configuration, rules, schedules, or privileged settings |
| Marketplace buyer | Finds and purchases goats | Browse/search, save goats, inquire, message, request a reservation and pickup, view purchases, create support tickets | Access smart-farm operations or manage listings |
| Approved community seller | Buyer plus seller capabilities | Maintain their own goat records, listings, messages, reservations and sales | Access the client's smart-farm devices/data or another seller's records |
| Pending/rejected/suspended seller | Applicant state | View application outcome and ordinary buyer features as allowed | Publish or operate active seller listings |

Authorization must continue to be enforced by the backend. Hiding a button is not sufficient security.

## 4. Recommended navigation after redesign

The current navigation changes by role and contains many entries. Redesign it around tasks rather than Django modules.

### Farm owner

- **Overview** — operational summary and urgent actions
- **Monitor**
  - Live cameras
  - AI detections
  - Goat tracking
  - Security and alerts
- **Herd**
  - Goat records
  - Add goat
  - Missing goats
  - Detection history
- **Operate**
  - Feeding
  - Door and lighting controls
  - Automation schedules and rules
  - Devices
- **Reports** — all report types and exports
- **Marketplace** — listings, messages, reservations, sales
- **Help & settings** — SMS registration, support, account

### Farm operator

Use the same mental model, but show read-only screens and remove or disable privileged controls with a clear explanation.

### System administrator

Use the farm-owner navigation plus a separate **Administration** area for users, seller applications, marketplace moderation, SMS administration, ML models, diagnostics, and platform settings.

### Buyer / community seller

Use a storefront-oriented header or bottom navigation rather than the farm operations sidebar:

- Browse
- Saved
- Messages
- Reservations or orders
- Sell (approved sellers)
- Notifications
- Support
- Account

Do not mix farm sensor controls into the public marketplace interface.

## 5. Module-by-module behavior

### 5.1 Authentication and account state

- Users sign in with the existing Django account; Google sign-in can appear when configured.
- After sign-in, the backend determines the highest trusted role.
- Disabled/unavailable accounts are prevented from using the application.
- The web client uses session authentication. The mobile API supports expiring DRF bearer tokens for users with active farm access.
- Logout invalidates the current authenticated session or token.

**Design requirements:** friendly login, clear invalid-credential and inactive-account states, password recovery link if supported, and role-appropriate landing page.

### 5.2 Farm overview

The overview combines the most important live information rather than every available metric.

Show:

- Herd total and health breakdown
- Active/missing/monitoring goats
- Latest temperature, humidity, soil moisture, light, air-quality and rain status when available
- Feed level, next feeding, and recent feeding result
- Online/offline device count and stale-data warnings
- Door, light and feeder state
- Camera health and live preview
- Highest-priority unresolved notifications
- Recent detections and operational activity
- Quick links to full monitoring, herd, automation, and reports

Owner/admin may issue quick controls. Operator sees state without write controls.

### 5.3 Goat inventory and goat detail

Inventory supports search, filters, status summaries, card/table views, add-goat, comparison, and drill-down.

Each goat can contain:

- Unique goat ID, optional name, and physical tag number
- Breed, sex, date of birth/age, weight and color markings
- Health status: healthy, monitoring, sick, or quarantine
- Vaccination status, vaccine, last date and next due date
- Inventory status: active, sold, dead, or missing
- General and health notes
- Owner/source: smart farm or community seller
- Last seen time
- Standard reference photos: front, left, right, rear and face, plus gallery images
- Confirmed weight history from a load cell or manual entry
- BLE beacon assignment and tracking state
- Detection and missing-alert history
- Marketplace listing link when applicable

**Primary actions:** add/edit permitted fields, capture/upload photos, save a confirmed weight, assign/update tracker, mark inventory status, compare photos, open listing.

**Empty/error states:** no goats, no matching filters, missing photos, no weight history, load-cell unavailable, tracker unassigned, stale last-seen value.

### 5.4 BLE goat tracking

- A BLE receiver sends heartbeats and beacon observations.
- Observations are converted into proximity states such as near/far/out of range according to signal and freshness.
- The dashboard shows receiver health, last observation, signal strength, goat/beacon association, and tracking state.
- “Find goat” temporarily emphasizes observations for one assigned goat.
- The system can create a missing-goat alert when the configured absence rules are met.

**Never present this as GPS.** Prefer language such as “Near Barn Receiver,” “Last detected 8 minutes ago,” or “Out of receiver range.”

### 5.5 Environmental monitoring and IoT devices

Devices send readings to authenticated endpoints. The system stores generic sensor data and aggregated environmental readings.

Supported values include:

- Temperature
- Humidity
- Soil moisture
- Light intensity, raw light and calibrated light percentage
- Raw air-quality signal, voltage and estimated PPM, including calibration status
- Rain detected/dry
- Feeder distance/level

Device screens show ID, name, type, location, active state, latest values, history, heartbeat/freshness, and related alerts.

**Design requirements:** always show measurement time, freshness, units and calibration caveats. Use a trend chart for history. Avoid implying precision the sensor does not provide.

### 5.6 Door, lighting and automation

Actuators include an automated door, lights and servo feeder. Each has a current state, manual/automatic mode, last-change time and trigger source.

Automation rules may be:

- Time-based schedule
- Sensor/environment based
- Goat-detection based
- Light-intensity based

Available rule actions include opening/closing the door and turning lights on/off. The system keeps actuation logs.

**Control interaction:** show current state and device connectivity, request confirmation for risky/manual actions, display pending state immediately, then show confirmed or failed result. Log who/what initiated every change.

### 5.7 Feeding

- A global switch enables/disables automated feeding.
- Owners create schedules with feeder, time, amount, selected days, and active/inactive state.
- The feed bin reports distance, percentage and estimated grams, capacity, low threshold and last refill.
- A manual feed request creates a pending command for the feeder.
- The ESP32 polls/receives the command and confirms execution.
- Every feeding becomes a log with amount, mode, trigger, environment/ML context, timestamp and status.

Feeding modes: automated, scheduled, and manual.

Result statuses: pending, success, failed, or partial.

Triggers can include schedule, manual override, physical button, emergency, environmental conditions, poor grass health, or ML activity/behavior signals.

**Design requirements:** put safety and device truth first. Show “command pending” separately from “feed dispensed.” Confirm amount before a manual feed. Make low feed, failed command and offline feeder prominent.

### 5.8 Cameras and AI detection

- IP cameras are cataloged with connection/status information.
- The Raspberry Pi/backend reads RTSP or HTTP sources and exposes latest-frame MJPEG/JPEG streams to authorized clients.
- Users can view camera lists, camera detail, live feed, snapshot and status.
- Goat detection returns confidence and bounding boxes and stores detection history/snapshots.
- Person/face detection stores the event, confidence, camera/source, snapshot and review state. It does not perform identity recognition.
- Real-time detection updates can arrive through WebSockets.

**Person event lifecycle:** new → reviewing → confirmed threat or dismissed/false alarm. A related notification can be read, resolved, reopened and annotated.

**Design requirements:** preserve video aspect ratio; clearly distinguish live, reconnecting, offline and last-frame states; use legible boxes without obscuring the animal; show confidence as supporting evidence, not certainty.

### 5.9 Unified alerts and security

The security area combines user-facing notifications from several authoritative event sources:

- Missing goat
- Person/intrusion detection
- Device/sensor anomaly
- System or other information

Severity levels: critical, high, medium, low and informational.

Each item has read/unread and resolved/unresolved state, source, time, underlying event, optional evidence, resolution user/time and notes.

**Primary actions:** filter, open evidence, mark read/unread, begin review, resolve with notes, reopen when permitted.

**Design requirements:** sort unresolved critical/high events first. Do not rely on color alone. Separate acknowledgment (“read”) from operational closure (“resolved”).

### 5.10 SMS notifications

- Farm users can register and verify/manage a mobile number for alerts.
- Administrators configure SMS settings, test delivery, check provider balance, maintain reminders and inspect logs.
- SMS logs preserve delivery status and failure information.
- In-app notifications remain the fallback when an SMS provider fails.

Never display provider credentials or sensitive configuration values.

### 5.11 Reports and exports

The report center provides date/filter controls, detail/print views, and export where supported.

Report categories:

1. Goat inventory
2. Vaccination
3. Health
4. Automated feeder
5. Automated door
6. Automated lighting
7. Environmental monitoring
8. AI detection activity
9. Marketplace

Reports should show summary metrics first, then charts, then the underlying table. AI detection activity represents camera events, not herd size. Exported totals must match on-screen/source records.

### 5.12 Marketplace discovery

Unauthenticated visitors can see the landing/catalog as allowed. Buyers can:

- Browse available goats
- Search/filter by meaningful listing/goat/location fields
- Open a listing with goat photos, health/basic details, price, seller and public farm location
- Open the seller's public profile
- Save/unsave a goat
- Report a listing
- Start a private inquiry

Private address/pickup details must not appear on the public seller profile.

### 5.13 Seller onboarding and listings

- A marketplace account applies with farm name, public location, contact number, description, optional profile image and supporting document, plus private address details.
- Administrator reviews the application as pending, approved, rejected or suspended and may record a reason.
- Approved sellers create goats they own, then create commercial listings from those goat records.
- Listing states are draft, available, reserved and sold.
- Only active goats and authorized approved sellers may publish.

The seller dashboard summarizes goats, listings, messages, pending reservations and completed sales.

### 5.14 Inquiry, reservation and pickup workflow

1. Buyer opens an available listing.
2. Buyer starts one private conversation for that listing.
3. Buyer and seller exchange messages while the conversation is open.
4. Buyer submits a reservation request at the agreed price.
5. Reservation becomes **pending seller response**. The listing is not yet reserved.
6. Seller accepts or rejects it.
7. On acceptance, reservation becomes **accepted/reserved**, the listing becomes reserved, and competing active requests are handled by backend rules.
8. Buyer proposes a pickup date/time and notes. Seller may accept/confirm or suggest another schedule and private location.
9. Participants confirm the pickup.
10. Authorized participant completes the sale after handoff. The reservation and listing become completed/sold and the goat is retained in sales history.
11. A request may also be cancelled or expire. When appropriate, the listing returns to available.

Reservation states: pending, accepted/reserved, rejected, cancelled, completed and expired.

Pickup states: not requested, requested by buyer, alternative suggested by seller and confirmed.

**Design requirements:** present this as a visible timeline/state machine. Never label a pending request as a completed reservation. There is no online payment UI.

### 5.15 Marketplace administration and customer service

Administrators can:

- Review seller applications
- View/activate/suspend user accounts
- Inspect user listings, reservations, tickets and activity
- Create/edit/publish/feature smart-farm listings
- Inspect inquiries and reservation activity
- Moderate reported listings
- View completed sales/activity history
- Operate support tickets

Users can create support tickets, attach safe files, exchange messages and see ticket state. Staff can assign, prioritize, reply, resolve or close according to current backend rules.

## 6. Core end-to-end flows

### Sensor to alert

`ESP32 measurement → authenticated API ingestion → validated stored reading → dashboard/trend update → anomaly/event → unified notification → optional SMS → user review/resolution`

### Manual actuator command

`Owner selects action → confirm safety-sensitive action → backend permission check → command/log created → hardware receives command → pending UI → device acknowledgment or timeout → confirmed/failed state and audit log`

### Scheduled feeding

`Active schedule becomes due → background task creates feed command → feeder executes → confirmation updates feed log → feed level changes → failure/low-level event may notify user`

### Camera detection

`Camera stream → backend/ML frame processing → detection with box/confidence → snapshot/history → live update → person or missing-goat event when applicable → notification → review/resolve`

### Goat weight

`User opens a selected goat → load cell reports live reading or user enters manual value → user confirms the stable value → measurement is stored with source/time/user/device → goat current weight and chart update`

### Marketplace sale

`Seller approval → owned goat record → listing draft → published/available → buyer inquiry/messages → pending reservation → seller acceptance → pickup proposal/confirmation → physical handoff → completed sale/history`

## 7. Technical context the redesign AI should know

- Backend: Django 6 monolith and Django REST Framework
- Primary database: MySQL
- Server-rendered web pages coexist with REST APIs
- Real-time updates: Django Channels with Redis in production
- Background/scheduled work: Celery and Celery Beat
- Hardware: ESP32 sensor/actuator units, feeder servo and ultrasonic level sensor, environmental sensors, load cell/HX711, BLE receivers/beacons, IP cameras
- Computer vision: YOLO-style goat/person detection
- Web frontend today: Django templates, Bootstrap, custom CSS and JavaScript
- Mobile client: Vue 3 + Ionic + Capacitor; current persistent tabs are Home, Live, Goats, Alerts and More
- Camera delivery currently favors MJPEG/latest-frame delivery; WebRTC is a future optimization, not a current assumption
- Timezone in user-facing views: Asia/Manila

Do not redesign the backend data model unless explicitly asked. A visual redesign should reuse the existing URLs, permissions, services, APIs and state transitions wherever possible.

## 8. Recommended visual direction

The included sample uses the following direction:

- Calm agricultural operations product, not a generic finance dashboard
- Deep forest green navigation, warm off-white canvas, white surfaces and sage accents
- Amber for warnings and muted red for critical/danger only
- High-information density without cramming
- Camera, alerts and device truth receive more space than decorative KPI cards
- 8 px spacing rhythm; 10–14 px surface radius; subtle borders; restrained shadows
- Clear sans-serif typography, strong numeric hierarchy, short operational labels
- Real goat/camera imagery only where it conveys evidence or identity
- Status always uses text/icon plus color
- Destructive or physical controls need confirmation and pending feedback
- Desktop sidebar, tablet rail/drawer, and mobile bottom navigation or compact drawer

Avoid blue-purple gradients, glassmorphism, neon colors, excessive pills, giant empty hero sections, charts without units, and dozens of equal-looking cards.

## 9. Key screen specifications for a redesign

### Operational dashboard

Above the fold: system health, herd status, feed, devices, barn climate, live camera, priority alerts, and owner quick controls. Secondary area: environmental trend, recent activity, upcoming schedule and shortcuts.

### Goat inventory

Header with total and status counts; search; breed/sex/health/status filters; card/table toggle; strong photo and goat ID; compact health/tracker/last-seen indicators; add and compare actions. Bulk actions only where the backend safely supports them.

### Goat detail

Identity header and status; tabs or anchored sections for overview, health/vaccination, weights, photos, tracking, detection history and marketplace. Keep save states and permissions obvious.

### Monitoring center

Camera selector/grid; dominant live feed; connection/freshness state; AI overlay toggle; recent detections; related alert drawer; reconnect/snapshot/fullscreen actions.

### Automation and feeding

Current physical state at top; manual controls separated from schedules/rules; confirmation before actuation; next-run details; feed level; command status; history/audit log.

### Alert center

Severity/unresolved summary; filters for type, severity, source, read and resolution; list with evidence thumbnail; detail side panel or page with source event, timeline, notes and resolve controls.

### Reports

Report category index; shared date/filter bar; summary metrics; limited purposeful charts; reconciled table; print/export action with progress/error state.

### Marketplace catalog and detail

Use a distinct storefront experience. Catalog uses high-quality goat cards and meaningful filters. Detail emphasizes photos, verified factual goat information, price, seller/public location, save/report, and inquiry action. Never expose the private pickup address.

### Reservation workspace

Conversation plus a transaction timeline. Clearly show the next responsible party and only legal next actions for the current state. Pickup details appear only to participants.

## 10. Required UI states

Every data-driven component should define:

- Loading/skeleton
- Empty/no data
- No search results
- Permission denied/read-only
- Offline/network failure
- Device offline
- Stale data/last updated time
- Validation error
- Request pending/queued
- Success confirmation
- Partial success
- Recoverable failure/retry
- Destructive-action confirmation

## 11. Accessibility and responsive requirements

- Target WCAG 2.2 AA contrast and keyboard operation.
- Visible focus state for every interactive element.
- Minimum 44 × 44 px touch targets on mobile.
- Labels remain available to assistive technology; icons cannot be the only label.
- Status and charts cannot rely on color alone.
- Tables become useful cards or horizontally scroll with pinned identity/action columns on small screens.
- Live regions should announce command result and critical alert changes without overwhelming the user.
- Respect reduced motion.
- Video/camera panels must not force horizontal page overflow.

## 12. Redesign constraints and acceptance criteria

A successful design:

- Gives each role a coherent, limited navigation.
- Lets an owner understand urgent farm state within about five seconds.
- Shows timestamps and offline/stale/pending states honestly.
- Keeps monitoring separate from mutation and separates farm operations from the public marketplace.
- Makes dangerous physical actions deliberate and auditable.
- Does not invent GPS, face identity, online payment, shipping, veterinary diagnosis or guaranteed individual visual recognition.
- Represents the reservation lifecycle accurately.
- Works at desktop, tablet and 360–412 px mobile widths.
- Reuses existing domain terms and can be implemented incrementally on Django templates or the Ionic client.

## 13. Copy/paste prompt for another AI

```text
Redesign GoHMoTech, a role-based smart goat farm operations and community marketplace web app. First read the attached system brief completely. Preserve all existing capabilities, roles, permissions, state transitions, device truth, and domain limitations.

Create a coherent responsive product design for:
1) farm owner operational dashboard,
2) goat inventory and goat detail,
3) live cameras and AI detections,
4) BLE proximity tracking,
5) feeding/door/light automation,
6) unified alerts,
7) reports,
8) buyer marketplace catalog/detail,
9) seller messages/reservations/sales,
10) admin users/sellers/support/moderation.

Visual direction: trustworthy agricultural operations software; deep forest green, sage, cream, charcoal, restrained amber/red status colors; crisp accessible typography; subtle borders and shadows; practical density; no blue-purple gradients, glassmorphism, neon colors, excessive rounded cards, or decorative charts.

Prioritize live camera evidence, urgent alerts, device freshness, herd health, feed state, and the next safe action. Distinguish requested/pending/confirmed/failed hardware commands. BLE is proximity, not GPS. Person detection is not face identity. Marketplace has no online payment or shipping. A reservation is only reserved after seller acceptance.

For every screen, provide desktop and mobile layouts plus loading, empty, offline, stale, read-only, validation, pending, success, and failure states. Use a task-based role-specific navigation. Do not alter backend behavior unless you separately identify a necessary API gap.

Start with an information architecture and reusable design system, then produce high-fidelity screens and a component inventory. Use the sample dashboard only as a visual direction, not as a restriction.
```

## 14. Included sample

Open `docs/redesign/sample-dashboard.html` in a browser. It is a standalone responsive visual concept for the farm-owner operational dashboard. It does not modify the running application.

