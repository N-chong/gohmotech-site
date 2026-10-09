# GoHMoTech
## Smart Goat Farm Monitoring System

# Goat Owner / Farm Owner User Manual

**[GOHMOTECH LOGO PLACEHOLDER]**

**[DEVICE PHOTO NEEDED: Complete GoHMoTech System]**

What the photo should show: the complete installed system in normal use, including the protected main unit, controller enclosures, camera, environmental sensors and feed monitoring unit.

Important parts to highlight: 1. protected main unit; 2. sensor/controller unit; 3. feed unit; 4. camera; 5. protected cables.

**Figure O-1. Complete GoHMoTech system.**

| Document field | Value |
|---|---|
| Manual version | 1.0-draft |
| System version | **[Information Needed: Deployed GoHMoTech release/version]** |
| Date | 5 October 2026 |
| Prepared by | **[Information Needed: Names of manual preparers]** |
| Capstone group | **[Information Needed: Official capstone group name]** |
| Institution | **[Information Needed: Institution name]** |

**Document status:** implementation-verified draft. The Administrator must complete all installation-specific placeholders before this manual is issued.

---

## Document control and printing

This manual is for a GoHMoTech Farm Owner account. It explains normal physical checks and the server-rendered web portal. It does not include Administrator-only model upload, global SMS configuration, user administration, device registration or Django Settings.

For the final PDF, use A4 paper, portrait orientation and automatic footer page numbers in the form “Farm Owner Manual — Page x of y.” Update the contents after photos and screenshots are inserted.

## Table of contents

1. About GoHMoTech and your role — 3  
2. Safety information — 4  
3. Know the equipment — 5  
4. One-page Quick Start — 7  
5. Starting, daily use and safe shutdown — 8  
6. Login, Dashboard and navigation map — 10  
7. Complete Farm Owner menu guide — 12  
8. Environmental and feed monitoring — 14  
9. Goats, weighing and tracking — 16  
10. Camera, security and notifications — 18  
11. Farm controls and feeding — 20  
12. Reports and PDF generation — 21  
13. SMS Alerts, account and logout — 23  
14. Basic maintenance and cleaning — 24  
15. Troubleshooting — 25  
16. Quick-reference card, do’s and don’ts, glossary — 26  
Appendix A. Photo and screenshot plan — 28

---

# 1. About GoHMoTech and your role

GoHMoTech is a smart goat-house monitoring and control system. It helps a farm owner see goat records, current temperature and humidity, indoor light, rain state, air-quality signals, feed level, camera activity, goat/person detections, nearby BLE goat trackers, notifications and reports from one web portal.

The Raspberry Pi is the main server. ESP32 controllers collect sensor data and receive door, light and feeder commands over Wi-Fi. A camera supplies farm images for monitoring and detection. The system can also provide SMS features when the Administrator has configured them.

As a Farm Owner, you can use the farm Dashboard, manage goat records, view/operate farm equipment, review Security & Alerts, use reports, register your mobile number for SMS features and use farm marketplace tools. You cannot use Administrator-only ML model management, global SMS settings, device registration or system user administration.

**IMPORTANT:** GoHMoTech supports farm decisions. Always check the real animals, feed and equipment. Missing or old data does not mean conditions are safe or normal.

---

# 2. Safety information

**WARNING**

- Keep electronic equipment dry and protected from rain, wash water and animals.
- Do not open a powered enclosure or touch exposed wiring.
- Keep goats, people and objects clear of the moving door and feeder mechanism.
- Report damaged, wet, hot or loose equipment immediately. If there is an immediate electrical or fire danger, use the approved emergency power isolation method.

**CAUTION**

- Do not unplug the Raspberry Pi, controllers, camera or network equipment.
- Do not move a sensor or camera. Movement can cause wrong readings or missed views.
- Do not repeatedly press a feeder control. A screen message that a command was **Sent** is not proof that the feeder moved.
- Do not treat an uncalibrated MQ-135 reading as an exact gas measurement.

---

# 3. Know the equipment

| Part | What it does | What you should do | What to avoid |
|---|---|---|---|
| Raspberry Pi 5 main unit | Runs the GoHMoTech server | Keep its enclosure dry, powered and ventilated | Do not unplug or cover ventilation |
| ESP32 controller units | Read sensors and receive equipment commands | Report an offline/stale device | Do not open, rewire or reset without approval |
| DHT21/AM2301 | Measures air temperature (°C) and humidity (%) | Keep its area open to normal air | Do not wet, cover or move it |
| LDR | Indicates indoor light level | Leave its view clear | Do not cover it |
| Rain sensor | Shows rain detected or dry | Report damage or movement | Do not scrape or chemically clean it |
| MQ-135 | Shows a raw/relative air-quality signal; estimated PPM only after calibration | Watch for change and calibration label | Do not call it an exact safety gas meter |
| Ultrasonic feed sensor | Measures distance to feed and reports an estimated percentage/weight | Keep the path clear and mounting fixed | Do not place feed/object directly against it |
| Feeder servo/mechanism | Dispenses feed when controlled/scheduled | Keep clear and check the real result | Do not force moving parts or repeat commands blindly |
| Door and light equipment | Opens/closes the door and switches light | Keep door path clear; check physical position | Do not work on relays or wiring |
| Camera | Provides farm view and detection images | Keep the lens and view clear | Do not block or change angle |
| Load-cell scale, when installed | Provides live goat weight for owner confirmation | Use a clear, stable platform; confirm before saving | Do not save an unstable reading |
| BLE beacon/receiver, when installed | Shows nearby/proximity state for an assigned goat | Keep beacon securely attached | Do not treat it as GPS |

**[DEVICE PHOTO NEEDED: Farm Owner Equipment Overview]**

Show only parts a Farm Owner may see or inspect safely. Highlight the closed main enclosure, controller enclosures, camera, sensor positions, feeder sensor and protected cables. **Figure O-2. Equipment a Farm Owner should recognize.**

**[Information Needed: Exact installed equipment positions and safe user-access boundaries]**

---

# 4. One-page Quick Start

1. Look for wet equipment, damaged cables or blocked moving parts. Do not continue if unsafe.
2. Confirm the system has been powered by the Administrator or authorized person.
3. Connect your phone/computer to the required network, if the farm uses local access.
4. Open **[Information Needed: Production GoHMoTech URL/IP address]**.
5. Enter your username or email and password; select **Sign in securely**.
6. On **Overview**, check Total goats, Current feed level, Temperature, Humidity, Device status, Security alerts, Recent detections and Notifications.
7. Check the Environment & goat house panel and the time of the latest data.
8. Review Recent alerts. Open **Monitoring → Security & Alerts** for details.
9. If needed, open **Farm → Manage Goats**, **Farm → Feeding**, **Monitoring → Farm Monitoring** or **Records → Reports**.
10. Select **Logout** when finished on a shared device.

**[SYSTEM SCREENSHOT NEEDED: Farm Owner Dashboard]**

Show the full Overview page. Highlight the summary cards, Environment & goat house, Quick access, feeding schedule, recent goat activity, recent alerts, navigation and user menu. **Figure O-3. Farm Owner Dashboard.**

---

# 5. Starting, daily use and safe shutdown

## 5.1 Before the system is turned on

1. Check that enclosures are closed and dry.
2. Look for cut, loose, chewed or overheated cables.
3. Make sure goats cannot touch electronics or moving equipment.
4. Make sure the camera view and sensor openings are clear.
5. Make sure the door and feeder can move safely.
6. Tell the Administrator about any problem. Farm Owners should not repair wiring.

## 5.2 Power-on and first check

The Administrator or authorized operator should use the farm’s approved power sequence. Do not guess which plugs or switches to use.

After power-on, open GoHMoTech and confirm that the Dashboard loads, device counts are reasonable and sensor times update. **[Information Needed: Verified startup time and approved power switch/sequence]**

**[DEVICE PHOTO NEEDED: GoHMoTech Powered On]** — show only actual visible indicators and closed enclosures. **Figure O-4. System powered on.**

## 5.3 Normal daily operation

The controllers normally send sensor readings to the Raspberry Pi. The feeder unit reports feed information. The camera supplies views and detections. GoHMoTech records events, creates notifications and prepares reports. The system normally stays on; do not power-cycle it every day.

### Start of day

- [ ] Open Overview and check the latest data.
- [ ] Check temperature, humidity and feed.
- [ ] Check device and camera status.
- [ ] Review unread notifications and important alerts.
- [ ] Inspect goats, feed and equipment in person.

### During the day

- Respond to high/critical or unusual alerts.
- Check that readings continue to update.
- Confirm any door/light/feed command at the actual equipment.
- Review camera/security events when needed.

### End of day

- Review alerts and goat records.
- Review the Daily Summary SMS if enabled by the Administrator.
- Generate a report if required.
- Log out on a shared device. Leave the system powered unless the Administrator has scheduled shutdown.

## 5.4 Safe shutdown and restart

The inspected web portal has no Farm Owner shutdown or restart button. Do not pull the plug. Contact the Administrator, who must finish uploads/reports and use the approved Raspberry Pi operating-system shutdown/restart procedure.

**WARNING:** Sudden power removal may cause data loss or storage corruption.

**[Information Needed: Administrator contact and emergency isolation procedure]**

---

# 6. Login, Dashboard and navigation map

## 6.1 Login

1. Open the GoHMoTech address.
2. Enter **Username or email**.
3. Enter **Password**. The eye button shows/hides it.
4. Select **Sign in securely**.

Use **Forgot password?** if password reset has been configured. **Continue with Google** appears only when the Administrator has configured Google sign-in. If you see **Access denied** or an expected Farm menu is missing, ask the Administrator to check that your account belongs to **Farm Owners**.

**[SYSTEM SCREENSHOT NEEDED: Login Page]**

Highlight Username or email, Password, visibility button, Forgot password and Sign in securely. **Figure O-5. Login page.**

## 6.2 Dashboard meaning

The Dashboard answers: **“What is happening on the farm right now?”**

It shows Total goats, Current feed level, Temperature, Humidity, Device status, Security alerts, Recent detections and Notifications. It also shows a 3D Bahay ng Kambing, environment/equipment states, quick links, feeding schedules, recent goat activity and recent alerts.

**NOTE:** Recent detections means goats seen by detection in the recent window; it is not the official herd count. A device count such as 1/2 means one of two listed controllers is currently considered online.

## 6.3 Farm Owner navigation map

```text
Farm Owner sign-in
└── Overview
    ├── Farm
    │   ├── Manage Goats
    │   ├── Feeding
    │   ├── Farm Controls
    │   ├── Marketplace
    │   └── My Listings
    ├── Monitoring
    │   ├── Farm Monitoring
    │   ├── Live Detection
    │   ├── Goat Tracking
    │   └── Security & Alerts
    ├── Records
    │   ├── Reports
    │   └── Detection History
    ├── Device Status
    ├── Help & Settings
    │   ├── Customer Service
    │   ├── SMS Alerts
    │   └── Inquiries
    └── Logout
```

On a phone, the bottom bar shows **Overview**, **Monitor**, **Herd**, **Operate** and **More**. Select **More** for the complete menu.

---

# 7. Complete Farm Owner menu guide

| Menu | What it is for | Main actions |
|---|---|---|
| Overview | Current farm and equipment summary | Review status and use quick links |
| Farm → Manage Goats | Herd list and details | Search, add/update goats, weights, health, vaccination, photos and BLE assignment |
| Farm → Feeding | Opens the combined Farm Controls page | Review feeder status, controls and schedules supported there |
| Farm → Farm Controls | Door, light, feeder, mode, schedules and rules | Send supervised commands; manage automation |
| Farm → Marketplace | Browse goat listings | View listings |
| Farm → My Listings | Owner marketplace listings | Manage the owner’s approved listings |
| Monitoring → Farm Monitoring | Sensors, alerts, camera, equipment and devices | Check current system data |
| Monitoring → Live Detection | Live goat-detection view | Review current camera detection |
| Monitoring → Goat Tracking | BLE receiver/proximity view | Find an assigned goat near receivers |
| Monitoring → Security & Alerts | Notifications and person-detection records | Read, review and resolve events |
| Records → Reports | Period reports and exports | Review history; create CSV/Excel/PDF |
| Records → Detection History | Recorded goat detections | Review camera, time and detection data |
| Device Status | Controller/device status and details | Check communication, alerts and recent data |
| Help & Settings → Customer Service | Support tickets | Ask for help and follow responses |
| Help & Settings → SMS Alerts | Your own mobile number registration | Save or pause registration |
| Help & Settings → Inquiries | Marketplace inquiries | Review messages/inquiries |
| Bell | Opens Security & Alerts | Review unread farm notifications |
| User menu | SMS Registration and Logout | Account actions available to Farm Owner |

**[SYSTEM SCREENSHOT NEEDED: Farm Owner Navigation Menu]** — show desktop groups and the mobile bottom bar in separate captures if needed. **Figure O-6. Farm Owner navigation.**

---

# 8. Environmental and feed monitoring

## 8.1 View current environmental data

**Navigation path:** Monitoring → Farm Monitoring

1. Find Temperature and Humidity and check the timestamp.
2. Review indoor light, rain and MQ-135 values when present.
3. Review active alerts and recent readings.
4. If a value is blank, shown as `—`, or old, treat it as unavailable. Open **Device Status** or tell the Administrator.

Temperature is in degrees Celsius. Humidity is relative humidity percent. Rain is a detected/dry state, not rainfall amount. Indoor light is a raw/calibrated indicator, not necessarily a certified lux value. MQ-135 PPM is meaningful only when the page/data says the sensor is calibrated.

**[DEVICE PHOTO NEEDED: Environmental Sensor Installation]**

Show DHT21, LDR, rain sensor and MQ-135 in their installed positions, without opening powered wiring. **Figure O-7. Environmental sensors.**

**[SYSTEM SCREENSHOT NEEDED: Environmental Monitoring Page]**

Show current supported values, units, source/timestamps and alerts. **Figure O-8. Environmental monitoring.**

## 8.2 View feed status

**Navigation path:** Overview or Farm → Feeding

The ultrasonic sensor measures the distance to the feed surface. GoHMoTech shows an estimated feed percentage and grams based on the stored feeder capacity. A low-feed alert may be created when estimated grams fall below the configured threshold.

If the screen looks wrong:

1. Check the real feed level.
2. Look for feed or an object blocking the sensor.
3. Check whether the sensor or container moved.
4. Check the update time and Device Status.
5. Tell the Administrator if recalibration is needed.

**[DEVICE PHOTO NEEDED: Feed Monitoring Sensor]**

Show the feed container, ultrasonic sensor, fixed mount, cable and controller enclosure. **Figure O-9. Feed monitoring unit.**

**[SYSTEM SCREENSHOT NEEDED: Feed Monitoring Page]**

Show feed level, update time, schedule/log areas and low warning if one is real. **Figure O-10. Feed monitoring.**

---

# 9. Goats, weighing and tracking

## 9.1 View or update goat information

**Navigation path:** Farm → Manage Goats

1. Search/filter for the goat.
2. Select the goat to open details.
3. Review ID/tag, name, breed, gender, birth date, current weight, status, health, vaccination, notes and photos.
4. Update only from real farm records; select **Save Changes**.

To add a goat, select **Add Goat**, complete the required real information and save. Implemented status values include Active, Sold, Dead and Missing.

**[SYSTEM SCREENSHOT NEEDED: Goat List Page]** — show search/filter, Add Goat and goat records. **Figure O-11. Goat list.**

**[SYSTEM SCREENSHOT NEEDED: Goat Details Page]** — show basic, weight, BLE, health, vaccination, notes and gallery. **Figure O-12. Goat details.**

## 9.2 Save a weight

1. Open the goat’s details.
2. Choose **Auto / Live Scale** when the installed scale is working, or **Manual Entry** for a verified manual value.
3. For the scale, clear the platform, select **Start Weighing**, place the correct goat safely and wait for a stable reading.
4. Select **Save Weight**.
5. Check the confirmation, then save. The value appears in Weight History and updates current weight.

Never save an unstable value or a weight belonging to a different goat.

## 9.3 BLE goat tracking

**Navigation path:** Monitoring → Goat Tracking

BLE shows whether an assigned beacon is heard by farm receivers and a proximity class such as Very Near, Near or Out of Range. Use **Find Goat** and then physically search the indicated receiver area. BLE is not GPS and does not provide a map coordinate.

---

# 10. Camera, security and notifications

## 10.1 Camera and Live Detection

**Navigation path:** Monitoring → Farm Monitoring or Live Detection

Use the live view to check the monitored area. Keep the lens clean and unblocked. Do not change the camera angle. Goat detection records a count/confidence from a frame; it is not the official inventory count.

**[DEVICE PHOTO NEEDED: Camera Installation]**

Show camera, stable mount, monitored area and protected cable. **Figure O-13. Camera installation.**

## 10.2 Review Security & Alerts

**Navigation path:** Monitoring → Security & Alerts

The page has Overview, Alerts and Security Detection tabs for Farm Owners.

1. Check Unread notifications, Unresolved alerts, Critical unresolved and Unreviewed detections.
2. In **Alerts**, filter by severity, type, status or date. You can use **Mark all read**, but reading does not resolve the problem.
3. In **Security Detection**, inspect snapshot, source, time, confidence and review state.
4. Open the record and record an honest review/result.
5. Resolve an alert only after the cause has been handled.

GoHMoTech may say Person Detected, Unknown Person or Face Detected, but it does not identify the person. A detected person must not automatically be called an intruder.

**[SYSTEM SCREENSHOT NEEDED: Security Monitoring Page]**

Show summary cards, Alerts filters/table and Security Detection filters/table. **Figure O-14. Security and alerts.**

## 10.3 Notification meanings

| State | Meaning | What to do |
|---|---|---|
| Unread | Not yet opened/marked read | Review it |
| Unresolved | Cause/action not closed | Investigate and act |
| Critical/High | Important severity | Inspect promptly |
| Medium/Low/Informational | Lower priority or information | Review in context |
| Unreviewed detection | Camera record not checked | Inspect snapshot/time/source |
| Dismissed / False Alarm | Reviewed and judged not a threat | Add truthful notes |

---

# 11. Farm controls and feeding

## 11.1 Send a control command

**Navigation path:** Farm → Farm Controls

The page has Door Motor, Light Relay and Servo Feeder controls, Automation mode, schedules, sensor rules and Recent actuator activity.

1. Check that people, goats and objects are clear.
2. Check whether the controller is online.
3. Select the required door, light or feeder action once.
4. Read the result:
   - **Sent to device:** the command was stored while the device was online.
   - **Queued — device offline:** the device may act after reconnecting.
   - **Failed:** the command did not complete.
5. Look at the actual equipment to confirm the result.

**WARNING:** Current hardware does not send positive execution acknowledgement. Do not repeat a feeder command simply because the screen does not say “completed.”

## 11.2 Schedules and automation

Use **Add schedule** to create door, light or feeder times and days supported by the page. Use **Pause/Resume** for a temporary change. Use **Delete schedule** only after checking the exact item. **Automatic** mode allows active rules/schedules; **Manual** means the page’s manual controls take effect according to the displayed explanation.

---

# 12. Reports and PDF generation

Reports answer: **“What happened on the farm during a selected period?”**

**Navigation path:** Records → Reports

The Report Center provides Goat Inventory, Vaccination, Health, Weight, Feeder, Door, Lighting, Environmental, AI Detection Activity, Security and Marketplace reports. Period choices are Today, Last 7 days, Last 30 days, This month and Custom.

## 12.1 Generate a combined Farm PDF

1. Select a period; enter both dates for Custom.
2. Select **Apply period**.
3. Review summary cards and important events.
4. Select **Generate Farm PDF**.
5. In the browser print page, choose Print, then **Save as PDF** or a printer.

## 12.2 Generate a detailed report

1. Open a report card.
2. Choose the available filters and select **Apply**.
3. Review summaries, charts and source table.
4. Select **CSV**, **Excel** or **Generate PDF / Print**.
5. For PDF, use the browser’s **Save as PDF** option.

The PDF is a print view; GoHMoTech does not directly download a ready-made PDF file. Environmental reports include temperature, humidity, indoor light, rain and MQ-135 information.

**[SYSTEM SCREENSHOT NEEDED: Reports Page]**

Show period controls, Generate Farm PDF, summary cards, report cards and important events. **Figure O-15. Report Center.**

**[SYSTEM SCREENSHOT NEEDED: PDF Generation Button and Example PDF]**

Show Generate PDF / Print and a redacted browser print/PDF result. **Figure O-16. PDF report generation.**

---

# 13. SMS Alerts, account and logout

## 13.1 Register your mobile number

**Navigation path:** Help & Settings → SMS Alerts

1. Open **Register your mobile number**.
2. Enter your own Philippine mobile number in the accepted format.
3. Set the active/paused choice shown by the form.
4. Select **Save SMS registration**.
5. Check **Current status** and Last updated.

This registration is your personal account number. The Administrator separately controls the system-wide SMS recipient, alerts, reminders and Daily Summary. Contact the Administrator if expected SMS is not sent.

## 13.2 Theme and account menu

The sun/moon button changes the display theme on the current browser. The Farm Owner user menu contains **SMS Registration** and **Logout**. The portal navigation does not expose a separate Farm Owner profile-edit page; use **Forgot password?** at login when reset is configured, or contact the Administrator.

## 13.3 Logout

Select **Logout** in the sidebar or user menu. Always log out on a shared phone or computer.

---

# 14. Basic maintenance and cleaning

| Interval | Farm Owner task |
|---|---|
| Daily | Check Dashboard/data times, real feed, camera view, alerts and safe door/feeder area |
| Weekly | Look for visible cable/mount damage; clean camera lens carefully; check feed sensor path; report problems |
| Monthly | Ask Administrator to review device reliability, enclosures, storage/backups and account access |

For cleaning, use a clean dry cloth only on safe external surfaces. Do not spray water or chemicals. Do not open enclosures, move sensors, scrape the rain plate, touch the MQ-135, or push an ultrasonic transducer. The Administrator must shut down/isolate equipment before any physical work that could touch wiring.

---

# 15. Troubleshooting

| Problem | What it may mean | What the Farm Owner should do |
|---|---|---|
| Page does not load | Network or server unavailable | Check your network/address, refresh once, then contact Administrator |
| Login fails | Wrong password, inactive account or wrong role | Re-enter carefully; use Forgot password; contact Administrator |
| Menu is missing | Account permission/role | Ask Administrator to check Farm Owners group |
| Data is old/not updating | Device or network stopped | Check timestamp and Device Status; inspect farm directly; report it |
| No reading / `—` | No confirmed data | Do not assume normal; check real conditions and report it |
| Feed value looks wrong | Sensor blocked/moved or needs calibration | Check real feed and sensor path; do not move it; tell Administrator |
| Device says offline/check device | Controller has no recent activity | Do not rewire; report device/location |
| Command says Queued | Controller offline | Stop; tell Administrator; supervise possible action after reconnection |
| Command says Sent but equipment did not move | No execution acknowledgement or equipment fault | Inspect safely; do not repeat feeder blindly; contact Administrator |
| Camera unavailable | Power/network/camera problem | Check whether view is blocked; contact Administrator |
| Person detection seems wrong | Detection can make mistakes | Review image/time; dismiss truthfully if false; do not identify a person from it |
| No SMS | Registration, global setting, provider or scheduler issue | Check your registration status; contact Administrator |
| Daily Summary missing | Not enabled/due or system send failed | Contact Administrator to check diagnostics |
| Report is empty | No data or wrong period/filter | Change period/filter; check whether devices recorded data |
| PDF does not download | Browser print method is used | Select Generate PDF / Print, then Save as PDF |
| System unresponsive | Pi/network/service fault | Contact Administrator; do not unplug unless immediate safety requires approved emergency isolation |

---

# 16. Quick-reference card, do’s and don’ts, glossary

## 16.1 Quick troubleshooting card

**No Dashboard?** → Check network/address; contact Administrator.  
**No sensor data?** → Check timestamp and Device Status; inspect real farm conditions.  
**No feed data?** → Check real feed and sensor path; report it.  
**No camera?** → Check for a blocked view; contact Administrator.  
**No SMS?** → Check SMS registration; contact Administrator.  
**Daily Summary missing?** → Ask Administrator to check its last run.  
**System unresponsive?** → Do not unplug; call the Administrator unless there is an immediate safety danger.

## 16.2 Farm Owner do’s and don’ts

**DO**

- Check the real animals, feed and equipment.
- Review alerts and current data times.
- Check feed level and environmental readings.
- Confirm equipment movement physically.
- Report device problems promptly.
- Keep your password private and log out on shared devices.

**DON’T**

- Move sensors or block the camera.
- Disconnect cables or power.
- Repeat feeder commands without checking.
- Assume missing data means normal conditions.
- Treat BLE as GPS or camera detection as official herd count.
- Call a detected person an intruder without review.
- Share your password.

## 16.3 Button and status reference

| Control/status | Meaning |
|---|---|
| Add Goat | Create a new goat record |
| Save Changes / Save Weight | Store reviewed information |
| Filter / Apply | Show records matching choices |
| Bell | Open notifications/security |
| Menu / More | Open full navigation |
| Sun/Moon | Change display theme |
| Generate Farm PDF | Open combined print view |
| Generate PDF / Print | Open report print view |
| Online | Recent communication meets the system rule |
| Offline / Check device | Communication needs checking |
| Sent | Command delivered/stored; not physical confirmation |
| Queued | Device was offline and may act after reconnecting |
| Unread / Unresolved | Needs review / cause not closed |
| Logout | End your session |

## 16.4 Glossary

**Alert** — Message that something may need attention.  
**BLE** — Short-range nearby/proximity tracking; not GPS.  
**Dashboard/Overview** — Main page showing current farm information.  
**Daily Summary** — Scheduled SMS digest controlled by the Administrator.  
**Environmental reading** — Measurement from a supported sensor.  
**ESP32** — Small controller that collects data or receives equipment commands.  
**Feed monitoring** — Estimate based on the ultrasonic distance to feed.  
**Notification** — Information or alert in the Security inbox.  
**PDF report** — Browser print page saved as a PDF file.  
**Raspberry Pi** — Main computer/server of GoHMoTech.  
**Security detection** — Camera event showing a person/face category; not identity recognition.  
**Sent/Queued** — Command delivery state, not proof that equipment moved.

---

# Appendix A. Photo and screenshot plan

| Figure | Required image | Important areas |
|---|---|---|
| O-1 | Complete system | Main unit, controllers, sensors, feed and camera |
| O-2 | Equipment overview | Safe owner-visible parts and boundaries |
| O-3 | Farm Owner Dashboard | Summary, environment, quick links, schedules, alerts |
| O-4 | Powered system | Real indicators only |
| O-5 | Login | Username/email, password, eye, sign-in |
| O-6 | Owner navigation | Desktop groups and mobile bar |
| O-7/O-8 | Environmental installation/page | Sensor positions; values, units and times |
| O-9/O-10 | Feed unit/page | Ultrasonic mount; feed data and warning |
| O-11/O-12 | Goat list/details | Search/add; weight, health, vaccination and photos |
| O-13/O-14 | Camera/security | View/mount; alert and detection review |
| O-15/O-16 | Reports/PDF | Period, report cards and browser print flow |

This manual deliberately excludes unsupported sensors, Administrator-only model upload, global SMS configuration, user/device administration, private credentials and unconfirmed physical ratings/LED meanings.

**End of Goat Owner / Farm Owner User Manual**
