from datetime import timedelta, timezone as dt_timezone

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Device, SensorReading
from .serializers import SensorReadingSerializer


@override_settings(TIME_ZONE="Asia/Manila", USE_TZ=True)
class SensorTimestampTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            device_id="timestamp-test-esp32",
            name="Timestamp Test ESP32",
            device_type="environmental_sensor",
        )

    def payload(self, **changes):
        data = {
            "device": self.device.pk,
            "temperature": 29.5,
            "humidity": 72,
        }
        data.update(changes)
        return data

    def test_utc_device_timestamp_is_preserved_and_rendered_in_manila(self):
        measured = (timezone.now() - timedelta(minutes=2)).replace(microsecond=0)
        wire_value = measured.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
        serializer = SensorReadingSerializer(data=self.payload(timestamp=wire_value))

        self.assertTrue(serializer.is_valid(), serializer.errors)
        reading = serializer.save()

        self.assertEqual(reading.timestamp, measured)
        self.assertLess(abs((reading.received_at - timezone.now()).total_seconds()), 5)
        self.assertTrue(serializer.data["timestamp"].endswith("+08:00"))

    def test_missing_timestamp_uses_backend_receipt_time_after_restart_or_ntp_failure(self):
        before = timezone.now()
        serializer = SensorReadingSerializer(data=self.payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reading = serializer.save()
        after = timezone.now()

        self.assertLessEqual(before, reading.timestamp)
        self.assertLessEqual(reading.timestamp, after)
        self.assertLess(abs((reading.received_at - reading.timestamp).total_seconds()), 5)

    def test_legacy_seconds_since_boot_falls_back_without_breaking_upload(self):
        serializer = SensorReadingSerializer(data=self.payload(timestamp=42))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = timezone.now()
        reading = serializer.save()
        self.assertGreaterEqual(reading.timestamp, before)

    def test_explicit_null_timestamp_uses_backend_fallback(self):
        serializer = SensorReadingSerializer(data=self.payload(timestamp=None))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reading = serializer.save()
        self.assertIsNotNone(reading.timestamp)

    def test_delayed_reading_keeps_original_measurement_time(self):
        measured = (timezone.now() - timedelta(days=2)).replace(microsecond=0)
        wire_value = measured.isoformat()
        serializer = SensorReadingSerializer(data=self.payload(timestamp=wire_value))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reading = serializer.save()

        self.assertEqual(reading.timestamp, measured)
        self.assertGreater(reading.received_at, reading.timestamp)

    def test_ambiguous_or_reset_device_times_are_rejected(self):
        naive = SensorReadingSerializer(
            data=self.payload(timestamp="2026-10-02T12:30:00")
        )
        reset_epoch = SensorReadingSerializer(
            data=self.payload(timestamp="1970-01-01T00:00:03Z")
        )
        self.assertFalse(naive.is_valid())
        self.assertFalse(reset_epoch.is_valid())
        self.assertIn("timestamp", naive.errors)
        self.assertIn("timestamp", reset_epoch.errors)

    def test_device_measurement_survives_server_clock_disagreement(self):
        # The explicit device measurement remains authoritative even if the Pi
        # clock is temporarily behind; received_at preserves the comparison.
        measured = (timezone.now() + timedelta(hours=8)).replace(microsecond=0)
        serializer = SensorReadingSerializer(
            data=self.payload(timestamp=measured.isoformat())
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reading = serializer.save()
        self.assertEqual(reading.timestamp, measured)
        self.assertLess(reading.received_at, reading.timestamp)

    def test_multiple_devices_can_report_the_same_instant(self):
        other = Device.objects.create(
            device_id="timestamp-test-esp32-2",
            name="Second ESP32",
            device_type="environmental_sensor",
        )
        measured = (timezone.now() - timedelta(minutes=1)).replace(microsecond=0)
        wire_value = measured.isoformat()

        first = SensorReadingSerializer(data=self.payload(timestamp=wire_value))
        second = SensorReadingSerializer(data={
            **self.payload(timestamp=wire_value),
            "device": other.pk,
        })
        self.assertTrue(first.is_valid(), first.errors)
        self.assertTrue(second.is_valid(), second.errors)
        first.save()
        second.save()

        self.assertEqual(SensorReading.objects.filter(timestamp=measured).count(), 2)
