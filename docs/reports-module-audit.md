# Reports Module Data Audit

This audit records the user-facing metric path used by the Reports module:
template → `analytics.report_data` builder → Django model → stored system source.
No report builder generates sample sensor values.

| Report area | User-facing information | Stored source | Assessment |
|---|---|---|---|
| Report Center | Registered goats and records added | `iot.Goat` (`status`, `date_added`) | Supported; current inventory is labelled separately from period activity. |
| Report Center | Environmental readings | `iot.SensorReading.timestamp` | Supported; count uses the selected period. |
| Report Center | Feeding events | `feeding.FeedLog.timestamp` | Supported; count uses the selected period. |
| Report Center | Person detections | `security.PersonDetection.detected_at` | Supported; this is detection only, not identity recognition. |
| Report Center | High/critical alerts | `security.Notification` | Supported; severity and timestamp are stored fields. |
| Goat Inventory | Identity, breed, sex, birth date/age, current weight, health, vaccination and status | `iot.Goat` | Supported current-record snapshot. Age is calculated from stored birth date. |
| Vaccination | Current status, latest vaccine and next due date | `iot.Goat` | Supported, but not a per-dose history. The report states this limitation. |
| Health | Current health status and notes | `iot.Goat` | Supported current snapshot; no historical health trend is claimed. |
| Goat weights | Confirmed weight, source, goat and measurement time | `iot.GoatWeightMeasurement` | Supported historical measurements. Only farmer-confirmed manual/load-cell records are used. |
| Feeder | Events, amount, mode, trigger and result | `feeding.FeedLog` | Supported event log. Success rates are calculated from stored statuses. |
| Door / lighting | Actions, source and result | `iot.ActuationLog` | Supported event log. Lighting duration is clearly labelled as an estimate derived from paired ON/OFF events. |
| Environment | Temperature and humidity | `iot.SensorReading.temperature`, `.humidity` from installed environmental hardware | Supported. Average/minimum/maximum are calculated only from non-null stored values. |
| Environment | Indoor light | `iot.SensorReading.light_raw`, `.light_level_percentage` | Supported by installed indoor light sensor. |
| Environment | MQ-135 | `iot.SensorReading.air_quality_raw`, `.air_quality_voltage`, `.air_quality_ppm`, `.air_quality_calibrated` | Supported. PPM averages only include readings explicitly marked calibrated; raw readings remain labelled raw. |
| Environment | Rain status | `iot.SensorReading.rain_detected` | Supported by the installed rain sensor. |
| Environment | Soil moisture | Legacy `iot.SensorReading.soil_moisture` field | **Unsupported by installed hardware and removed from all Reports UI, print/PDF, CSV and Excel output.** The database field remains for backward compatibility outside Reports. |
| Goat AI monitoring | Goat count, confidence, camera and model | `ml_models.Detection` | Supported camera-event data; explicitly not treated as herd headcount. |
| Security | Person/face event, confidence, camera/source, review state and outcome | `security.PersonDetection` | Supported. The report explicitly states that the system does not identify people or perform facial recognition. |
| Security alerts | Alert severity/type/state | `security.Notification` | Supported stored event data. |
| Marketplace | Listings, inquiries, reservations, completed sales and revenue | `marketplace` listing/conversation/reservation/profile/report models | Supported. Revenue includes completed transactions only. |

## Corrections and UX changes

- Added one validated period model for Today, Last 7 Days, Last 30 Days, This Month and Custom Date Range. Custom end dates include the complete local calendar day; invalid or overly broad ranges are rejected.
- The selected period is shown and propagated to detailed pages, print/PDF, CSV and Excel exports.
- Empty historical datasets display a category-specific message and do not render empty charts or fabricated averages.
- Tables show human-readable labels and units, newest records first, and paginate at 50 rows on screen. Full selected-period data remains available to exports (subject to existing 500-row safety caps in high-volume event reports).
- Added a cross-module farm PDF view with executive summary, livestock, environment, feed, security, alerts, repeating table headers and print page footers.
- Saved-report API metadata is restricted to the creating farm owner, while administrators retain system-wide access.

## Deliberately unchanged limitations

- Legacy soil-moisture schema and automation choices were not migrated or deleted because they are outside the Reports module and may be needed for backward compatibility. They are not exposed by reports.
- A browser print view remains the PDF method. This avoids adding a large server-side rendering dependency on the Raspberry Pi; Chromium/browser “Save as PDF” produces the final file.
- Current goat health and vaccination models are snapshots, not dated clinical histories. Reports do not invent historical trends from them.
- Device `is_active` is configuration state, not a reliable online/uptime heartbeat, so the report does not label configured devices as online.
- `FeedLevel` stores a current snapshot rather than a dated history. Period charts and low-feed event counts are therefore not inferred from that snapshot; the report uses dated `FeedLog` events.
