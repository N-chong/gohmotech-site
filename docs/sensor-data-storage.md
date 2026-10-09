# Sensor data storage

ESP32 uploads remain raw `SensorReading` records and continue through the live
dashboard and alert pipeline immediately. Celery Beat runs
`iot.tasks.aggregate_sensor_data` every five minutes. The task finalizes fixed
30-minute periods aligned to `Asia/Manila` and stores one
`SensorReadingSummary` per device and sensor stream with average, minimum,
maximum, and sample count.

Raw readings default to 30 days of retention. Cleanup runs daily at 02:30
Manila time, but is disabled after migration so deployment cannot remove old
records automatically. An administrator should use this sequence:

1. Preview the existing backlog:
   `.venv/bin/python manage.py backfill_sensor_summaries`
2. Build summaries in bounded runs:
   `.venv/bin/python manage.py backfill_sensor_summaries --apply --max-periods 500`
3. Check summary counts and values in **Administrator > Sensor Reading
   Summaries**. Re-run step 2 until the reported backlog is zero.
4. Choose 7-365 days and enable cleanup in **Administrator > Sensor Storage
   Settings**.
5. Optionally test one cleanup run with
   `.venv/bin/python manage.py cleanup_sensor_readings --force`.

Cleanup only selects raw rows whose period was successfully processed. It
deletes in batches, preserves the newest raw row for every device, and never
targets alerts, notifications, SMS logs, detections, reports, livestock data,
or summaries. The administrator page shows disk usage, database size for a
file-based database, and cleanup totals.

Long environmental reports use summaries once the requested historical range
has no unprocessed backlog. Recent and incomplete periods continue using raw
data. Device offline checks use `Device.last_sensor_received_at`, so raw
retention cannot make a silent device appear healthy or erase its last contact
time.
