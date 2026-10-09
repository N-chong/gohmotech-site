# GoHMoTech
## Smart Goat Farm Monitoring System

# Administrator User Manual

**[GOHMOTECH LOGO PLACEHOLDER]**

**[DEVICE PHOTO NEEDED: Complete GoHMoTech System]**

What the photo should show: the complete installed prototype, including the protected main computer, both ESP32 controller units, camera, feeder, environmental sensors, door/light equipment, power distribution and safe cable routing.

Important parts to highlight: 1. main computer enclosure; 2. main ESP32 controller; 3. feeder ESP32 controller; 4. camera; 5. sensor locations; 6. feeder; 7. protected power equipment.

**Figure A-1. Complete GoHMoTech system.**

| Document field | Value |
|---|---|
| Manual version | 1.0-draft |
| System version | **[Information Needed: Deployed GoHMoTech release/version]** |
| Date | 5 October 2026 |
| Prepared by | **[Information Needed: Names of manual preparers]** |
| Capstone group | **[Information Needed: Official capstone group name]** |
| Institution | **[Information Needed: Institution name]** |

**Document status:** implementation-verified draft. Complete all **[Information Needed]**, photo and screenshot items after checking the installed unit.

---

## Document control and printing

This manual is for GoHMoTech system administrators. It covers the physical equipment and the server-rendered GoHMoTech web portal. It does not document the separate Ionic mobile client.

For the final PDF, use A4 paper, portrait orientation, normal margins and automatic page numbers in the footer in the form “Administrator Manual — Page x of y.” Update the table of contents after final photos and screenshots are inserted. Keep warning blocks with the procedure they protect.

**IMPORTANT:** Repository inspection confirms software capabilities and a finalized wiring design, but the development database contains no registered production devices. The exact installed component models, enclosure layout, power ratings, network address and hardware commissioning state must be checked on the physical prototype.

## Table of contents

1. Introduction and user role — 3  
2. Safety information — 4  
3. Know your GoHMoTech system — 5  
4. Physical parts and installation — 7  
5. Quick start — 9  
6. Startup, normal operation, shutdown and restart — 10  
7. Status indicators — 12  
8. Initial administrator setup — 13  
9. Administrator dashboard and navigation map — 14  
10. Complete menu guide — 16  
11. Common software tasks — 18  
12. Environmental and feed monitoring — 21  
13. Camera, detection, security and notifications — 23  
14. SMS and Daily Summary — 24  
15. Machine-learning model management — 26  
16. Reports and PDF generation — 27  
17. Accounts, profile and logout — 29  
18. Maintenance and cleaning — 30  
19. Troubleshooting — 31  
20. Technical specifications — 33  
21. Button, status and icon reference — 34  
22. Quick-reference cards, do’s and don’ts, glossary — 35  
Appendix A. Photo and screenshot plan — 37  
Appendix B. Implementation verification record — 38

---

# 1. Introduction and user role

## 1.1 What GoHMoTech does

GoHMoTech is a smart goat-house monitoring and control system. It brings herd records, temperature and humidity readings, indoor light, rain state, MQ-135 air-quality signals, feeder level, cameras, goat and person detection records, BLE goat proximity, equipment controls, notifications, SMS and farm reports into one web portal.

The Raspberry Pi hosts the GoHMoTech services. ESP32 controllers read sensors and receive equipment commands over Wi-Fi. The installed camera supplies monitoring images. Detection models can record goats and people seen by a camera. The system can send configured SMS alerts, reminders and a Daily Summary through the selected SMS backend.

GoHMoTech supports farm work; it does not replace direct inspection, veterinary judgment, security judgment or safe electrical practices. Missing data never means that farm conditions are normal.

## 1.2 Administrator role

An Administrator is a Django staff or superuser account. The confirmed interface allows an Administrator to:

- see the Administrator Overview and System Monitoring pages;
- manage goat inventory, goat details, weights, photos and BLE assignments;
- view BLE tracking and live goat detection;
- operate the door, light and feeder and manage schedules/rules;
- review cameras, person detections, alerts and notifications;
- generate farm and detailed reports and export CSV/Excel;
- configure SMS, reminders, Daily Summary and review SMS logs;
- upload, validate, activate and deactivate ML models;
- review device status;
- use Django Settings for registered data and user administration;
- manage marketplace users, seller applications, support and listings.

Farm Owner accounts can change farm data and use farm controls, reports and security. Farm Operator accounts are read-only. Marketplace-only accounts do not receive farm access.

**NOTE:** “Registered Users” in the navigation is the marketplace-user list. General Django users and group assignment are managed through **Settings** (`/admin/`).

---

# 2. Safety information

## 2.1 Signal words

**WARNING** means a risk of injury, electric shock, fire, animal injury or serious equipment damage.

**CAUTION** means a risk of data loss, incorrect operation or minor equipment damage.

**IMPORTANT** identifies an action required for reliable operation.

**NOTE** provides useful operating information.

## 2.2 Safety rules

**WARNING**

- Keep mains-voltage and 12 V power equipment inside the approved protected enclosure. Only an authorized person may open or work on powered electrical equipment.
- Disconnect the relevant power source before hardware maintenance. Verify that voltage is absent before touching wiring.
- Keep electronics dry and protected from rain, wash water, condensation and excessive moisture.
- Use only the verified power supplies, buck converters, fuses, relays/drivers, wire sizes and connectors for the installed equipment.
- Keep cables protected from goats and secured against pulling, chewing and trip hazards.
- Do not touch exposed contacts. Do not operate damaged or wet equipment.

**CAUTION**

- Keep Raspberry Pi and enclosure ventilation clear.
- Do not move sensors, the feed-level sensor or camera without approval; movement changes measurements and coverage.
- Do not disconnect Raspberry Pi power during a model upload, database work, update or report generation.
- Do not assume a displayed command means that an actuator physically moved. Current ESP32 control records a command as **Sent** or **Queued**; the firmware does not provide positive execution acknowledgement.

---

# 3. Know your GoHMoTech system

## 3.1 Confirmed system components

| Component | Purpose | Confirmed design/location | User guidance |
|---|---|---|---|
| Raspberry Pi 5 | Main GoHMoTech server | Main protected computer area; exact enclosure location is installation-specific | Keep powered, dry, ventilated and network-connected. Do not remove power suddenly. |
| ESP32 1, main controller | Door relay, light relay, LDR, DHT21, rain sensor, MQ-135 and three physical-button inputs in the finalized wiring design | Main controller enclosure | Observe status through the web portal. Do not handle powered wiring. |
| ESP32 2, feeder controller | Feeder servo and ultrasonic feed-level sensor | At/near feeder in a protected enclosure | Keep its sensor position and cabling fixed. |
| DHT21/AM2301 | Air temperature in °C and relative humidity in % | GPIO14 in the finalized design; installed location **[Information Needed]** | Keep exposed to representative air but protected from direct water. |
| LDR and divider | Indoor light level, shown as raw and calibrated percentage when available | GPIO34; goat-house interior **[Information Needed]** | Do not cover it or shine a test light continuously. |
| Rain sensor, digital output | Reports rain detected/dry | GPIO17; outdoor mounting **[Information Needed]** | Keep mounting secure; do not scrape or chemically clean the plate. |
| MQ-135 module | Reports raw ADC/voltage and estimated PPM only if calibrated | GPIO35 through the finalized voltage divider | Treat uncalibrated output as a relative signal, not an exact gas measurement. |
| Ultrasonic feed-level sensor | Measures distance to feed; firmware sends distance and percentage | GPIO18/19 on ESP32 2; above feed surface | Keep perpendicular to feed, outside the fill stream and at the calibrated position. |
| Feeder servo | Operates the dispensing mechanism | ESP32 2, GPIO25 signal, separate verified supply | Keep hands and animals clear during movement. Do not force the mechanism. |
| Door actuator and relay/driver | Opens/closes the goat-house door | ESP32 1, GPIO26/27 control; physical location **[Information Needed]** | Keep travel path clear. Confirm the actual position after a command. |
| Light and relay | Switches goat-house light | ESP32 1, GPIO13 control | Do not exceed the installed relay/load rating. |
| Three momentary buttons | Feed, light and door requests in finalized design | ESP32 1 GPIO32/33/25; enclosure position **[Information Needed]** | Press once and observe the physical result. Do not hold or repeatedly press. |
| IP/RTSP/HTTP/MJPEG/USB camera support | Live view, snapshots and detection source | Installed camera position **[Information Needed]** | Keep lens clean, view unobstructed and angle fixed. |
| Load cell with HX711 | Supplies live goat weighing data when installed | Separate scale unit; exact model/location **[Information Needed]** | Use only on a stable, empty platform; confirm the value before saving. |
| BLE beacon and receiver support | Shows whether an assigned goat is detected nearby and proximity class | Beacon on goat; receiver location **[Information Needed]** | BLE is proximity, not GPS. Secure the beacon safely. |
| Network/router | Connects Pi, ESP32 units, camera and user device | Farm network **[Information Needed]** | Keep credentials private and network equipment powered. |

**[DEVICE PHOTO NEEDED: Raspberry Pi 5 Installed in GoHMoTech]**

What the photo should show: the Raspberry Pi in its normal protected, ventilated installation. Important parts: enclosure, approved power connection, network connection and ventilation. **Figure A-2. Raspberry Pi main unit.**

## 3.2 Items that must be confirmed on the installed prototype

- Raspberry Pi RAM, storage device/capacity, operating-system release and official power-supply rating.
- Exact ESP32 board models and quantity actually commissioned.
- Exact ultrasonic, rain, MQ-135 module, servo, actuator, relay/driver, camera, load-cell/HX711, BLE beacon/receiver and power-supply models.
- Installed fuse ratings, enclosure ingress protection, connector labels and cable colors.
- Whether the finalized two-ESP32 sensor split and three physical buttons have been flashed and commissioned. The wiring guide lists firmware integration changes that were still required when written.

---

# 4. Physical parts and installation

## 4.1 Parts identification photo plan

**[DEVICE PHOTO NEEDED: Front View of Main GoHMoTech Unit]**

Show the closed enclosure in its operating location. Label only verified installed items: enclosure, ventilation, power entry, network entry and warning label. **Figure A-3. Main unit front view.**

**[DEVICE PHOTO NEEDED: Rear or Connection View]**

Show protected, labeled connections. Highlight Raspberry Pi power/network, controller power, camera/network and cable strain relief. Do not expose passwords or unsafe energized terminals. **Figure A-4. Main unit connection view.**

**[DEVICE PHOTO NEEDED: ESP32 Main Monitoring Unit]**

Show ESP32 1, terminal labels and its connected sensor/relay cables. Highlight controller, DHT21, LDR, rain and MQ-135 connections, door/light outputs and installed buttons. **Figure A-5. Main ESP32 controller.**

**[DEVICE PHOTO NEEDED: Feed Monitoring Unit]**

Show feed container, ultrasonic sensor, stable mount, sensor cable, servo/mechanism and ESP32 2 enclosure. **Figure A-6. Feed monitoring and dispensing unit.**

**[DEVICE PHOTO NEEDED: Camera Installation]**

Show the camera’s field of view and protected cable route. Highlight lens, mount, monitored zone and network/power cable. **Figure A-7. Camera installation.**

## 4.2 Location guidelines

- **Raspberry Pi:** dry, ventilated, protected, accessible to an authorized technician and connected to a stable network.
- **ESP32/controllers:** fixed to standoffs inside protected enclosures. Separate mains, 12 V, 5 V and signal cable routes.
- **Environmental sensors:** fixed in representative locations, away from splashing, direct heater airflow and animal contact.
- **Camera:** stable, protected and aimed at the intended area without blocking paths or private areas outside the farm.
- **Feed sensor:** perpendicular to the feed surface, away from the fill stream and protected from accidental movement.
- **Scale:** firm and level, with the load platform unobstructed.

**[Information Needed: Approved installation drawing with exact positions and mounting heights]**

## 4.3 Before turning on

1. Check that all enclosures are closed and dry.
2. Inspect visible cables for cuts, loose connectors, heat damage or animal damage.
3. Confirm that animals cannot reach exposed electronics or moving mechanisms.
4. Check that Raspberry Pi, router/network, camera and both ESP32 units have their approved power and data connections.
5. Confirm the camera lens and sensor openings are unobstructed.
6. Confirm the door and feeder mechanisms can move safely.
7. Do not energize the system if a cable, enclosure or power device is damaged or wet.

---

# 5. Administrator quick start

1. Complete the pre-power inspection in Section 4.3.
2. Apply power using the site’s approved power sequence. **[Information Needed: Exact switch names and order]**
3. Wait for the Raspberry Pi, network equipment, camera and ESP32 units to start. **[Information Needed: Verified normal startup time]**
4. On an authorized computer or phone, open **[Information Needed: Production GoHMoTech URL/IP address]**.
5. Enter the Administrator username or email and password; select **Sign in securely**.
6. In **Overview**, check main controller, camera, detection model, Environment & Feed and Active Alerts.
7. Open **Monitor** and check device cards/recent activity. A configured device is not automatically online; use its live status/last data.
8. Open **Monitoring → Farm Monitoring** and confirm current readings.
9. Open **Security & Alerts** and review unread/unresolved items.
10. Open **SMS Notifications** and check System diagnostics, Last attempt and Next run.

**[SYSTEM SCREENSHOT NEEDED: Administrator Dashboard]**

Show the entire Overview page. Highlight navigation menu, Environment & Feed, System Status, Automation, Active Alerts, Recent Activity, camera panel, bell and user menu. **Figure A-8. Administrator Overview.**

---

# 6. Startup, normal operation, shutdown and restart

## 6.1 Powering on

1. Perform the checks in Section 4.3.
2. Power the network equipment if it is not already running.
3. Power the protected GoHMoTech equipment using the approved site switch/sequence.
4. Do not press actuator buttons while controllers are starting.
5. Open the portal and sign in.
6. Confirm current sensor timestamps, controller status, camera status and active model.
7. Perform one supervised equipment test only if maintenance or commissioning requires it.

Expected successful result: the portal loads; current data has a recent timestamp; configured controllers and camera show their real state; no unexplained high/critical alert remains open.

**[DEVICE PHOTO NEEDED: GoHMoTech Powered On]** — show the closed powered installation and only actual visible power/status indicators. **Figure A-9. Powered system.**

## 6.2 Normal operation

During normal operation, ESP32 devices send readings to the server. The feeder controller reports feed distance/percentage, the camera provides images, and configured detection processes create records. The server stores data, runs schedules and notifications, builds reports and can send SMS. Users normally leave the system running; daily power cycling is not required.

**NOTE:** The controller’s documented environmental reporting interval is 30 seconds, and the current stale-data policy defaults to 90 seconds. Treat the page timestamp—not a memorized interval—as the primary check.

## 6.3 Safe shutdown

The inspected web portal has no confirmed **Shutdown Raspberry Pi** control.

1. Stop model uploads and wait for any PDF/export operation to finish.
2. Avoid shutting down during scheduled actuator activity or SMS processing.
3. Save any form being edited.
4. Use the site-approved Raspberry Pi operating-system shutdown procedure from an authorized local/remote session.
5. Wait until shutdown is complete, then isolate power using the approved switch.

**WARNING:** Sudden power removal may cause data loss or storage corruption.

**[Information Needed: Exact approved shutdown command/interface, account authorized to use it, and physical indication that shutdown is complete]**

## 6.4 Restart

Restart only for authorized maintenance, after a service/system fault that did not recover, or after an update that requires it. Finish current work, use the approved operating-system restart procedure, then repeat the checks in Section 6.1. Do not repeatedly unplug and reconnect the unit.

**[Information Needed: Exact approved restart command/interface and escalation contact]**

---

# 7. Status indicators

| Interface status | Meaning | Administrator action |
|---|---|---|
| Online | Recent device activity meets the system’s freshness rule | No action if data timestamps are current. |
| Check device / Offline | No recent activity or camera not active | Check last update, device power and network. |
| Active / Inactive | Configuration or camera state; not always a live heartbeat | Check recent communication before concluding it is online. |
| No data / `—` | No confirmed value is available | Inspect the sensor/device; do not assume normal conditions. |
| Sent to device | Command stored while device was considered online | Watch the equipment and next state/report. It is not execution confirmation. |
| Queued — device offline | Command stored; device was offline | Restore device connection and supervise the eventual action. |
| Failed | Operation did not complete | Open the error/status details and correct the cause. |
| Unread / Unresolved | Notification has not been read/resolved | Review the source event and act before resolving. |
| Unreviewed / Reviewed | Security detection review state | Inspect snapshot/time/source; record a truthful outcome. |
| New / Under Review / Confirmed Threat / Dismissed | Person-detection outcome | Do not label a person an intruder solely from detection. |
| Uploaded (pending validation) | Model is stored but cannot yet be activated | Select **Validate**. |
| Validated / Active / Inactive / Archived / Rejected | Model lifecycle state | Activate only the approved validated model. |
| Pending / Processing / Sent / Failed / Skipped | Daily Summary run state | Review error and SMS settings for failed/skipped runs. |

**[Information Needed: Physical LED meanings on the exact installed Raspberry Pi, ESP32 boards, camera, router and power equipment]**

---

# 8. Initial administrator setup

## 8.1 Hardware and network commissioning

Only trained personnel should perform wiring and first power tests.

1. Record exact component model/nameplate information and complete the finalized wiring checklist.
2. Verify supply voltages before connecting electronics.
3. Commission ESP32 1 and ESP32 2 separately, then sensors one at a time.
4. Confirm Wi-Fi/API authentication and current timestamps.
5. Calibrate installed LDR full-scale points, ultrasonic empty/full distance and load cell. Calibrate MQ-135 before enabling a PPM claim.
6. Verify safe door interlock, travel limits/timeout and feeder close-on-timeout.
7. Register real devices/cameras in **Settings** or the appropriate device/camera page.
8. Test the complete system under supervision before unattended use.

**[Information Needed: Commissioning record proving the finalized sensor split and buttons are installed and tested]**

## 8.2 First portal setup

1. Obtain the bootstrap superuser through the project’s secure handover process. Do not place a password in this manual.
2. Sign in and open **Settings**.
3. Create users and assign the correct group: **Farm Owners** for owners, **Farm Operators** for read-only farm staff. Do not give staff/superuser status unless the person is an Administrator.
4. Register devices and camera records with their verified identifiers and locations.
5. Open **Monitor** and verify current communication; use the authorized Device Status page at `/iot/devices/` when a full device list is needed.
6. Open **Farm → Manage Goats** and add/verify herd records.
7. Open **Operate** and verify actuator entries, automation mode and schedules.
8. Open **Security & Alerts → ML Models** and verify the approved model is validated and active.
9. Open **SMS Notifications**; select the real backend, master switch, recipient, Daily Summary time, alert rules and reminders. Send a test SMS.
10. Open **Reports** and generate a short-period Farm PDF to verify print output.

**[SYSTEM SCREENSHOT NEEDED: Settings User and Group Setup]** — show the Users page and group assignment without personal data. Highlight Add user, Active, Staff status and Groups. **Figure A-10. Administrator account setup.**

---

# 9. Administrator dashboard and navigation map

## 9.1 Login page

1. Open the production GoHMoTech address.
2. Enter **Username or email**.
3. Enter **Password**. Use the eye button only when no one else can see the screen.
4. Select **Sign in securely**.

The page also shows **Forgot password?**, an optional **Continue with Google** control when OAuth is configured, and a marketplace link. After successful Administrator sign-in, the system opens **Overview**.

Common errors: check spelling and keyboard state; confirm the account is active; use **Forgot password?** when email reset is configured; contact the system custodian for a role/permission error.

**[SYSTEM SCREENSHOT NEEDED: Login Page]**

Highlight Username or email, Password, password visibility, Forgot password and Sign in securely. **Figure A-11. Farm Portal Sign In.**

## 9.2 Overview

The Administrator Overview answers “What is happening across the farm and system now?” It shows herd summary, BLE tracking, Environment & Feed, System Status, Automation, outdoor weather when available, the 3D goat house, Active Alerts, Recent Activity and a camera panel.

**IMPORTANT:** **Last Camera Count** is the latest camera detection count, not the registered herd total. Outdoor Weather comes from Open-Meteo; local sensors remain separate.

## 9.3 Navigation map

```text
Administrator sign-in
└── Overview
    ├── Monitor
    ├── Operate
    ├── Security
    │   ├── Overview
    │   ├── Alerts
    │   ├── Security Detection
    │   └── ML Models
    ├── Reports
    ├── Goat Inventory
    ├── Goat Tracking
    ├── Marketplace
    ├── Manage Marketplace
    ├── Registered Users
    ├── Seller Applications
    ├── Support Tickets
    ├── Live Detection
    ├── SMS Notifications
    │   ├── Settings
    │   ├── Reminders
    │   └── Logs
    ├── Settings (Django administration)
    └── Logout
```

On small screens the bottom bar shows **Overview**, **Monitor**, **Herd**, **Operate** and **More**. **More** opens the full navigation drawer.

---

# 10. Complete Administrator menu guide

| Menu | Purpose and main information/actions | When to use |
|---|---|---|
| Overview | Current herd, BLE, sensor/feed, controller/camera/model, automation, weather, alerts, activity and camera summary | First check of the day and after startup |
| Monitor | System Monitoring: environment, alert, camera, automation, device and recent-reading panels | Diagnose current farm/system condition |
| Operate | Door Motor, Light Relay, Servo Feeder, Automation mode, time schedules, sensor rules and recent actuator activity | Supervised control and automation setup |
| Security | Notification and person-detection review; Administrator-only ML Models tab | Respond to security/system events |
| Reports | Report Center, period selector, Farm PDF, detailed reports, CSV, Excel and print/PDF | Historical review and documentation |
| Goat Inventory | Search/filter/list goats, add goat, compare and open details | Maintain herd records |
| Goat Tracking | BLE proximity status, receivers and Find Goat | Locate an assigned beacon near receivers |
| Marketplace | Browse farm/community listings | View available goats/listings |
| Manage Marketplace | Administrator marketplace dashboard | Administer listings and transactions |
| Registered Users | Marketplace registered-user records | Review marketplace users; not farm-role assignment |
| Seller Applications | Seller approval workflow | Review applicants |
| Support Tickets | Customer-service tickets | Respond to user issues |
| Live Detection | Live camera goat-detection feed and recent results | Supervise camera detection |
| SMS Notifications | SMS Settings, Reminders, Logs and diagnostics | Configure and audit SMS |
| Settings | Django administration for authorized records and users | Privileged configuration only |
| Bell | Opens Security/notifications; badge is unread count | Review new items |
| User name | Settings (Administrator) and Logout | Account menu |

**[SYSTEM SCREENSHOT NEEDED: Administrator Navigation Menu]** — show the full desktop sidebar and top bar. Highlight menu order, bell, theme toggle and user menu. **Figure A-12. Administrator navigation.**

---

# 11. Common software tasks

## 11.1 View environmental data

**Navigation path:** Monitor

1. Open **Monitor**.
2. Find the latest temperature, humidity, light, rain and MQ-135 information that is present.
3. Check the measurement timestamp and source device.
4. Review active alerts and recent readings.
5. If a value is absent or stale, open **Device Status** and inspect the device before interpreting conditions.

## 11.2 Operate door, light or feeder

**Navigation path:** Operate → equipment card

1. Confirm people, goats and objects are clear of the mechanism.
2. Confirm the controller banner indicates current communication.
3. Select the intended action: door **Open/Close/Stop**, light **Turn ON/Turn OFF**, or feeder activation shown by the page.
4. Read the returned result: **Sent**, **Queued** or **Failed**.
5. Observe the real equipment. A **Sent** result is not physical confirmation.

**WARNING:** Do not repeat a feeder command merely because the screen lacks execution acknowledgement. Inspect the mechanism/feed first to avoid unintended repeated feeding.

## 11.3 Manage schedules/rules

**Navigation path:** Operate → Time-based schedules or Sensor rules

Use **Add schedule** or **Add rule**, select only available page fields, review days/time/action, then save. Use **Pause/Resume** to temporarily change a schedule. **Delete schedule/rule** is permanent and requires confirmation. The page groups door, light and feeder schedules separately.

## 11.4 Manage goats

**Navigation path:** Goat Inventory

1. Use search/filter controls to find a goat.
2. Select the goat to open details, or select **Add Goat** to create a record.
3. Confirm ID/tag, name, breed, gender and date of birth. Complete health, vaccination, status and notes only from real farm records.
4. On details, use **Auto / Live Scale** or **Manual Entry** for weight. Start weighing, wait for a stable value, select **Save Weight**, and confirm before saving.
5. Upload/capture real photos when needed; delete only the intended image.
6. Update status using the page control. The implemented statuses are Active, Sold, Dead and Missing; removal is by status/archive behavior, not an exposed “delete goat” button on this page.

**[SYSTEM SCREENSHOT NEEDED: Goat List Page]** — show search, filters, Add Goat, Compare and goat cards/table. **Figure A-13. Goat Inventory.**

**[SYSTEM SCREENSHOT NEEDED: Goat Details Page]** — show weight modes/history, basic information, BLE, health, vaccination, notes and photos. **Figure A-14. Goat details.**

## 11.5 Review a security detection

**Navigation path:** Security → Security Detection

1. Filter by Type, Review state or dates if needed.
2. Check snapshot, type, source, confidence, date/time and status.
3. Open the record.
4. Compare the image with farm context; person/face detection does not identify anyone.
5. Mark it reviewed and record an accurate outcome: Under Review, Confirmed Threat or Dismissed/False Alarm as supported.

## 11.6 Check device status

**Navigation path:** `/iot/devices/` (authorized Device Status page; it is not a separate item in the Administrator desktop sidebar)

The Device Status page shows total, configured active/inactive counts, device types and **Online/Check device** badges. Open **View Details** for device identity, location, active state, 24-hour sensor statistics, recent alerts and recent sensor data. Administrators can use **Add Device** or **Edit Device** links into Settings.

## 11.7 Logout

Select the user menu or sidebar **Logout** button. Logout is submitted securely as a form. Always log out on a shared device.

---

# 12. Environmental and feed monitoring

## 12.1 Temperature and humidity

The DHT21/AM2301 produces temperature in degrees Celsius and relative humidity in percent. The system can create configured high/low threshold alerts and a stale-sensor alert. Thresholds are intentionally unset until an Administrator supplies approved values.

If readings stop: check timestamp, device status, 3.3 V/data connection, mounting and sensor condition. Do not invent or copy generic animal thresholds; use farm/veterinary guidance.

## 12.2 Indoor light

The LDR reports a raw ESP32 ADC value and a calibrated light percentage when calibration values are available. It is an indoor light-level indicator, not a certified lux meter unless the installation has been separately calibrated and documented.

## 12.3 Rain

The installed design records a binary **rain detected/dry** value from a digital rain module. It does not measure rainfall amount.

## 12.4 MQ-135 air-quality signal

The portal can store raw ADC, measured input voltage, estimated PPM and a calibration flag. Unless **calibrated** is true and a documented calibration exists, interpret the raw/voltage reading only as a relative change. Do not use it as an exact gas concentration or safety instrument.

## 12.5 Feed level

The ultrasonic sensor measures distance to the feed surface. ESP32 firmware reports distance in centimeters and a percentage. The server stores capacity and calculates estimated grams from the received percentage. A low-feed alert is raised when stored grams fall below the configured low threshold.

If feed appears wrong:

1. Inspect actual feed safely.
2. Remove any obstruction in the sensor path.
3. Check that the sensor is perpendicular and has not moved.
4. Check distance/percentage and last update.
5. Recalibrate the installed empty/full distance if mounting changed.

**[SYSTEM SCREENSHOT NEEDED: Environmental and Feed Monitoring Page]**

Show Monitor with current supported values, timestamps, alerts and recent readings. **Figure A-15. Environmental and feed monitoring.**

---

# 13. Camera, detection, security and notifications

## 13.1 Camera operation

The camera system supports configured Wi-Fi IP, RTSP, HTTP/MJPEG or USB sources. Camera records include location, active/status, last connection/error and goat-detection setting. Keep the lens clean and view clear. Do not change IP, credentials, port, URL or angle without recording the change.

## 13.2 Goat detection

**Live Detection** uses an active model to record camera events with goat count, confidence and bounding boxes. It is evidence from one camera frame, not the official herd inventory.

## 13.3 Person detection

The Security page records Person Detected, Unknown Person or Face Detected events with snapshot, confidence, source and review state. These are detection categories only. GoHMoTech does not perform identity matching or facial recognition.

## 13.4 Notifications and alerts

A notification is the unified inbox entry. Types are Missing Goat, Person/Intrusion Detection, Device/Sensor Anomaly, System and Other. Severities are Critical, High, Medium, Low and Informational.

**Navigation path:** Security → Alerts

1. Filter by Severity, Type, Status or date, or search title/source.
2. Unread rows require review. **Mark all read** changes read state only; it does not fix a cause.
3. Open a related event where available.
4. Resolve only after action has been completed; enter truthful resolution notes.
5. Reopen if the condition returns or was resolved in error.

**[SYSTEM SCREENSHOT NEEDED: Security and Notifications Page]** — show tabs, summary cards, filters, unread state and detection table. **Figure A-16. Security and notifications.**

---

# 14. SMS and Daily Summary

## 14.1 SMS configuration

**Navigation path:** SMS Notifications → Settings

1. Check the backend/status banner and System diagnostics.
2. Enter the system Recipient number in Philippine format.
3. Set the master **Enable SMS** switch.
4. Configure **Daily Summary**, **Reminders** and **Alerts** separately.
5. For alerts, select minimum severity, allowed types (Missing Goat, Person Detection, Device Anomaly) and cooldown minutes.
6. Select **Save settings**.
7. In **Test SMS**, optionally enter a number; select **Send test** and read the result.
8. Use **Check balance** when the live Semaphore backend is configured.

API keys and sender credentials are server-side and must never appear in the page, screenshots or manual.

## 14.2 Daily Summary

The Daily Summary contains current goat health counts, that day’s feed/door/light event counts, latest temperature/humidity received that day, and alert counts. It uses Asia/Manila local time.

To configure: enable SMS, enable **Send a daily summary**, choose **Send time**, save, then inspect **Daily Summary**, **Last attempt**, result/error and **Next run** under diagnostics. The default in code is 7:00 AM; 10:00 PM occurs only when the page is configured to 22:00.

If the Pi misses the exact minute, the first scheduler tick later on the same local day makes one catch-up attempt. Previous days are not replayed, and terminal/processing runs are not automatically retried to avoid duplicate SMS.

## 14.3 Reminders and logs

The **Reminders** tab can add/edit/delete feeding, cleaning, maintenance, sensor-checking or custom reminders with time, message and selected days. No selected days means every day. The **Logs** tab filters send history by type, status, dates and search text.

**[SYSTEM SCREENSHOT NEEDED: SMS Configuration Page]** — show Settings, General, Daily Summary, Alerts, Test SMS and diagnostics without phone numbers or secrets. **Figure A-17. SMS configuration.**

**[SYSTEM SCREENSHOT NEEDED: Daily Summary Configuration]** — highlight enable switch, Send time, Last attempt, result/error and Next run. **Figure A-18. Daily Summary status.**

---

# 15. Machine-learning model management

**Navigation path:** Security → ML Models. A separate Administrator page also exists at `/ml/models/`.

1. Enter model name and version.
2. Select category and model type. Select RF-DETR size only when RF-DETR is chosen.
3. Select an allowed model file. The current upload control accepts `.pt`, `.pth`, `.ckpt`, `.onnx`, `.tflite`, `.h5` and `.keras`; server validation may support additional documented weight formats. Maximum configured size is 500 MB.
4. Check the displayed filename, type and size.
5. Select **Upload model**.
6. Watch **Preparing**, then **Uploading**. The page displays percentage, MB uploaded, MB remaining and chunk count.
7. Wait for **Upload complete** while the server assembles, validates basic file rules and stores it privately.
8. Confirm success or read the failure message. Upload success leaves the model **Uploaded (pending validation)**.
9. Select **Validate** and wait for **Validated**.
10. Select **Activate** only after approval. Activation loads the candidate before changing the active model. Use **Deactivate** when required.

**IMPORTANT:** Do not disconnect power or network while a model upload, validation or activation is in progress. Do not upload unknown model files. Upload is chunked but a failed attempt should be restarted as directed by the error.

**[SYSTEM SCREENSHOT NEEDED: Model Upload Page]** — show fields, accepted-file control and model list. **Figure A-19. Model management.**

**[SYSTEM SCREENSHOT NEEDED: Upload Progress]** — show state, percent, uploaded, remaining and chunk progress. **Figure A-20. Model upload progress.**

**[SYSTEM SCREENSHOT NEEDED: Successful Model Upload]** — show success plus Uploaded (pending validation), Validate and Activate sequence. **Figure A-21. Model upload result.**

---

# 16. Reports and PDF generation

Reports answer “What happened on the farm during a selected period?”

## 16.1 Available reports

- Goat Inventory, Vaccination, Health and Goat Weight;
- Automated Feeder, Automated Door and Automated Lighting;
- Environmental Monitoring (temperature, humidity, indoor light, rain and MQ-135);
- AI Detection Activity;
- Security Monitoring;
- Marketplace.

Report periods are Today, Last 7 days, Last 30 days, This month and Custom date range. Detailed reports can include report-specific filters, summary cards, charts and a data table. Screen pages show 50 rows per page; exports use the selected data subject to the application’s safety caps.

## 16.2 Generate the combined Farm PDF

**Navigation path:** Reports → period → Generate Farm PDF

1. Choose the reporting period. For Custom, enter start and end dates.
2. Select **Apply period** and review the summary/events.
3. Select **Generate Farm PDF**.
4. In the print-friendly page, use the browser Print command.
5. Choose **Save as PDF** or a printer, then save/print.

## 16.3 Generate a detailed PDF or export

**Navigation path:** Reports → report card → filters → Generate PDF / Print

1. Open the required report card.
2. Choose filters and select **Apply**.
3. Check the period, notes, summaries and source rows.
4. Select **CSV**, **Excel**, or **Generate PDF / Print**.
5. For PDF, use the browser’s **Save as PDF**. The server does not directly create a PDF file.

**[SYSTEM SCREENSHOT NEEDED: Reports Page]** — show period controls, Farm PDF, summary cards, report categories and important events. **Figure A-22. Report Center.**

**[SYSTEM SCREENSHOT NEEDED: Example PDF Report]** — show the print preview/result with private data removed. **Figure A-23. Farm report PDF.**

---

# 17. Accounts, profile and logout

## 17.1 User management

**Navigation path:** Settings → Authentication and Authorization → Users

Use Django administration to add/edit a user, set Active state, and assign the correct group. Staff status creates Administrator-level portal routing and must be restricted. Passwords must be set through the secure password controls and never recorded in this manual.

Disabling **Active** blocks sign-in without deleting history. Deleting users may affect audit ownership and must be approved and backed up. The inspected custom portal does not expose a separate profile-edit/password-change page in its navigation; password reset is available from login when configured.

## 17.2 Marketplace user tools

Use **Registered Users**, **Seller Applications**, **Support Tickets** and **Manage Marketplace** for marketplace administration. These are separate from farm-role access.

## 17.3 Logout

Select **Logout** in the sidebar or user menu. Log out whenever an Administrator leaves a shared device.

---

# 18. Maintenance and cleaning

## 18.1 Schedule

| Interval | Administrator check |
|---|---|
| Daily | Overview; device freshness; temperature/humidity/feed; camera; high/critical alerts; failed SMS; Daily Summary result |
| Weekly | Visible cables and strain relief; sensor mounts; feed sensor path; camera lens/view; door/feeder mechanism; test one approved notification path |
| Monthly | Enclosures/ventilation; power and network connections; device reliability; storage through approved OS monitoring **[Information Needed: command/threshold]**; backup result **[Information Needed: backup procedure]**; user access review |
| After movement/repair | Recalibrate affected sensor/scale, retest actuator safety and update installation record |

## 18.2 Cleaning

1. Schedule downtime if cleaning could touch equipment.
2. Shut down/isolate the relevant equipment using the approved procedure.
3. Use a clean, dry, lint-free cloth on enclosures.
4. Clean the camera lens gently with suitable lens material.
5. Remove dry loose debris around ventilation and the ultrasonic path without moving calibration points.
6. Do not spray water or chemicals on electronics or sensors.
7. Do not open or abrade the DHT21, LDR, MQ-135, rain plate or ultrasonic transducer.

---

# 19. Troubleshooting

| Problem | Possible cause | Recommended action |
|---|---|---|
| System does not start | Site power, supply, fuse or Pi fault | Isolate if unsafe; check approved power path and contact technician. Do not bypass a fuse. |
| Web portal unavailable | Pi/service/network down or wrong address | Check router/Pi power, correct URL and network; retry from authorized device. |
| Login fails | Wrong credentials, inactive account or role | Re-enter username/email; reset password; verify Active/group/staff settings. |
| Menu missing / Access denied | Role lacks permission | Verify group and account role. Do not grant Administrator only to reveal a menu. |
| Data not updating | ESP32/network/sensor stopped | Check timestamp, Device Status, power/Wi-Fi/API; inspect sensor safely. |
| No readings | No data received | Treat state as unknown, not normal. Check device/source and recent alerts. |
| Temperature/humidity absent | DHT21 or data connection issue | Check main controller, DHT power/data/mounting and logs. |
| MQ-135 value misleading | Warm-up/calibration absent | Use raw trend only; confirm calibrated flag/documentation before PPM. |
| Feed value incorrect | Obstruction, moved sensor or wrong calibration | Inspect real feed and mount; check distance/percentage; recalibrate empty/full. |
| Door/light/feed command queued | Controller offline | Restore connection; supervise equipment when it reconnects. |
| Command says Sent but nothing moved | No hardware acknowledgement, power/mechanical issue | Inspect physical equipment, controller, power and logs; do not repeat feeder blindly. |
| Camera unavailable | Camera power/network/URL/credentials or obstruction | Check Camera status/error, connections and view; do not expose credentials. |
| Detection absent | Camera/model inactive | Verify camera stream and active validated model. |
| False person event | Detection error or harmless activity | Review snapshot/time/source; dismiss with notes if appropriate. |
| SMS not received | Master/type switch, recipient, provider credit/key, worker or cooldown | Check diagnostics, Logs, Test SMS, balance and scheduler; never expose API key. |
| Daily Summary missing | Disabled, not due, skipped/failed run or scheduler down | Check Send time, Last attempt/error and Next run; inspect Celery worker/beat. |
| Model upload stuck/fails | Connection, invalid file, storage, order or timeout | Read message; keep power on; verify file/type/size/storage; restart upload if directed. |
| Model cannot activate | Pending/failed validation or load error | Validate first; review notes; keep current active model. |
| PDF “download” not found | PDF uses browser print | Open Generate PDF / Print and choose Save as PDF. |
| Report empty | No records in selected period/filter | Check period and underlying devices; do not create sample values. |

**System unresponsive:** contact the authorized Administrator/technician before removing power unless there is an immediate electrical, fire or animal-safety danger. In an immediate danger, isolate power by the approved emergency method.

---

# 20. Technical specifications

| Item | Confirmed specification |
|---|---|
| Main computer | Raspberry Pi 5 |
| RAM/storage/OS release | **[Specification to be confirmed from installed unit]** |
| Server framework | Django 6.0-compatible project; Daphne/ASGI in production services |
| Database | MySQL production configuration; local development database may differ |
| Background services | Celery worker and Celery Beat; Redis broker/cache/channels in production |
| Local time zone | Asia/Manila |
| Controllers | Two classic ESP32 DevKit / ESP32-WROOM-32 controllers in finalized wiring design; installed boards **[Specification to be confirmed]** |
| Environmental hardware | DHT21/AM2301, LDR divider, digital rain sensor, MQ-135 module |
| Feed hardware | Ultrasonic distance sensor and servo; exact models **[Specification to be confirmed]** |
| Other hardware support | Door actuator/relay or driver, light relay, load cell/HX711, BLE beacons/receivers, network camera |
| Network | Wi-Fi/API for ESP32; web access through configured HTTP/HTTPS deployment; exact network **[Specification to be confirmed]** |
| Camera protocols | Wi-Fi IP camera record; RTSP, HTTP/MJPEG and USB types supported |
| ML formats/types | YOLOv8, RF-DETR, PyTorch, TensorFlow/Keras, YOLO TF/Keras, Roboflow self-hosted/hosted and scikit-learn; upload UI accepts listed weight extensions |
| Model upload limit | 500 MB configured maximum; chunked upload and private storage |
| Report output | HTML, CSV, Excel; PDF through browser Print/Save as PDF |
| SMS | Console test backend or Semaphore live backend; PH number normalization |
| Sensor reporting/freshness | Firmware documentation: 30-second environmental reporting; default stale policy: 90 seconds |
| Power ratings | **[Specification to be confirmed from installed nameplates and power-distribution record]** |
| Accuracy/ranges | **[Specification to be confirmed through component datasheets and calibration records]** |

---

# 21. Button, icon and status reference

| Control | Meaning |
|---|---|
| Add / Add Goat / Add schedule / Add rule | Create the named record |
| View Details / Open report | Open full information |
| Save / Save settings / Save Weight | Store reviewed changes |
| Edit | Change an existing record |
| Delete | Permanently remove the selected supported record; confirm target first |
| Pause / Resume | Disable/enable a schedule without deleting it |
| Bell | Open Security notifications; badge shows unread count |
| Menu / More | Open full navigation on small screens |
| Sun/Moon | Change local display theme |
| Filter / Apply | Apply selected filters/period |
| Mark all read | Change unread state only |
| Validate | Test a stored ML model before activation |
| Activate / Deactivate | Make model current / stop using it |
| Generate Farm PDF | Open combined print view |
| Generate PDF / Print | Open detailed print view |
| CSV / Excel | Download report data |
| Logout | End the authenticated session |

---

# 22. Quick-reference cards, do’s and don’ts, glossary

## 22.1 Daily checklist

- [ ] Overview has current controller/camera/model information.
- [ ] Temperature, humidity and feed show current timestamps.
- [ ] Camera view and detection are available when expected.
- [ ] Device Status has no unexplained offline controller.
- [ ] High/critical and unread/unresolved alerts were reviewed.
- [ ] SMS Logs have no unexplained failure.
- [ ] Daily Summary Last attempt/Next run are correct.
- [ ] Door, light and feeder area are physically safe.

## 22.2 Quick troubleshooting card

**No dashboard?** → Check production address, network, Raspberry Pi and service status.  
**No sensor data?** → Check timestamp, ESP32 and Device Status.  
**No feed data?** → Inspect actual feed, ultrasonic sensor and feeder controller.  
**No camera?** → Check camera power/network/status/error.  
**No SMS?** → Check master switch, recipient, diagnostics, Logs and provider.  
**Daily Summary missing?** → Check Last attempt/error and Next run.  
**Model upload failed?** → Read error; verify file/type/size/storage/network and retry safely.  
**System unresponsive?** → Use authorized recovery; do not pull power except for immediate safety.

## 22.3 Administrator do’s and don’ts

**DO:** check device freshness; review failed SMS; use approved model files; verify scheduled summaries; protect accounts; inspect physical results; use safe shutdown.

**DON’T:** share Administrator credentials; upload unknown weights; disconnect during uploads; expose keys/camera passwords; delete records without approval; assume **Sent** means moved; report uncalibrated MQ-135 values as exact PPM.

## 22.4 Glossary

**Actuator** — Equipment that performs an action, such as door, light or feeder.  
**Alert** — A notification that may require action.  
**BLE** — Short-range radio used here for nearby/proximity tracking, not GPS.  
**Dashboard/Overview** — Main page showing current farm and system information.  
**Daily Summary** — Scheduled SMS digest of real farm records.  
**Device freshness** — Whether recent data has been received within the system rule.  
**ESP32** — Controller that reads sensors or controls equipment.  
**Feed monitoring** — Ultrasonic distance/percentage used to estimate available feed.  
**ML model** — Detection model file used to analyze images.  
**Notification** — Inbox item linked to an event or system message.  
**PDF report** — Print view saved as PDF using the browser.  
**Raspberry Pi** — Main GoHMoTech server computer.  
**Security detection** — Camera record that a person/face category was detected; not identity recognition.  
**Sent/Queued** — Command delivery state, not proof of physical execution.

---

# Appendix A. Photo and screenshot plan

| Figure | Required image | Important areas |
|---|---|---|
| A-1 | Complete system | All installed subsystems |
| A-2 | Raspberry Pi | Enclosure, power, network, ventilation |
| A-3/A-4 | Main unit front/connections | Labels and safe cable entries |
| A-5 | Main ESP32 | Confirmed controller/sensor connections |
| A-6 | Feed unit | Ultrasonic, mount, feed bin, servo, ESP32 2 |
| A-7 | Camera | Lens, mount, monitored zone, cable |
| A-8 | Administrator Overview | Navigation, summaries, status, alerts, camera |
| A-9 | Powered system | Actual indicators only |
| A-10 | User/group setup | Non-sensitive user role controls |
| A-11 | Login | Username/email, password, eye, sign-in |
| A-12 | Admin navigation | Exact menu order and top controls |
| A-13/A-14 | Goat list/details | Search/actions; weight/health/photos |
| A-15 | Environmental/feed | Readings, units, timestamps, alerts |
| A-16 | Security | Tabs, filters, notification/detection states |
| A-17/A-18 | SMS/Daily Summary | Toggles, time, diagnostics; redact numbers |
| A-19–A-21 | Model upload | Form, progress, lifecycle result |
| A-22/A-23 | Reports/PDF | Period, report cards, Print/Save as PDF |

# Appendix B. Implementation verification record

This draft was checked against the Django URL configuration, role helpers/decorators, shared navigation template, Administrator and owner dashboards, IoT/goat/feed/security/SMS/ML models and views, report registry/templates, deployment configuration, finalized wiring guides and current ESP32 sketches. The development database was queried and contained no registered production devices, actuators or cameras; installation-specific claims are therefore marked for confirmation.

Deliberate exclusions: no unsupported environmental sensor; no claim that BLE is GPS; no person identity recognition; no fake actuator acknowledgement; no direct server-generated PDF; no invented hardware LEDs, electrical ratings, installed part numbers, URL, startup time or shutdown button.

**End of Administrator User Manual**
