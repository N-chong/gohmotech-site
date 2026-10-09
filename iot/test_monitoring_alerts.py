from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from security.models import Notification

from .models import (Alert, Device, EnvironmentalAlertSettings,
                     SensorReading)
from .monitoring import check_stale_sensors, evaluate_sensor_reading


class EnvironmentalAlertPipelineTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            device_id='env-1', name='Environment Sensor',
            device_type='environmental_sensor')
        self.policy = EnvironmentalAlertSettings.get_config()
        self.policy.temperature_max_c = 30
        self.policy.temperature_min_c = None
        self.policy.humidity_min_percent = None
        self.policy.humidity_max_percent = None
        self.policy.stale_after_seconds = 1800
        self.policy.save()

    @patch('sms.tasks.send_alert_sms.delay')
    def test_real_threshold_condition_creates_notification_and_enqueues_sms(self, delay):
        reading = SensorReading.objects.create(
            device=self.device, temperature=31, humidity=70)
        with self.captureOnCommitCallbacks(execute=True):
            evaluate_sensor_reading(reading)

        alert = Alert.objects.get(alert_kind='temperature_high')
        notification = Notification.objects.get(source_object_id=alert.pk)
        self.assertEqual(notification.notification_type, 'device_anomaly')
        self.assertEqual(notification.severity, 'high')
        delay.assert_called_once_with(notification.pk)

    def test_normal_reading_does_not_create_false_alert(self):
        reading = SensorReading.objects.create(
            device=self.device, temperature=29, humidity=70)
        evaluate_sensor_reading(reading)
        self.assertFalse(Alert.objects.filter(
            alert_kind='temperature_high').exists())

    def test_ongoing_stale_condition_is_deduplicated_and_recovery_resolves(self):
        stale_time = timezone.now() - timedelta(minutes=31)
        reading = SensorReading.objects.create(device=self.device, temperature=29)
        SensorReading.objects.filter(pk=reading.pk).update(received_at=stale_time)

        check_stale_sensors()
        check_stale_sensors()
        self.assertEqual(Alert.objects.filter(
            alert_kind='sensor_stale', is_resolved=False).count(), 1)

        fresh = SensorReading.objects.create(device=self.device, temperature=29)
        evaluate_sensor_reading(fresh)
        self.assertFalse(Alert.objects.filter(
            alert_kind='sensor_stale', is_resolved=False).exists())

    def test_stale_alert_waits_for_full_thirty_minute_outage(self):
        now = timezone.now()
        self.device.last_sensor_received_at = now - timedelta(minutes=29)
        self.device.save(update_fields=['last_sensor_received_at'])

        check_stale_sensors(now=now)

        self.assertFalse(Alert.objects.filter(
            alert_kind='sensor_stale', is_resolved=False).exists())

        self.device.last_sensor_received_at = now - timedelta(minutes=31)
        self.device.save(update_fields=['last_sensor_received_at'])
        check_stale_sensors(now=now)

        self.assertTrue(Alert.objects.filter(
            alert_kind='sensor_stale', is_resolved=False).exists())

    def test_unconfigured_measurements_do_not_invent_thresholds(self):
        self.policy.temperature_max_c = None
        self.policy.save(update_fields=['temperature_max_c'])
        reading = SensorReading.objects.create(
            device=self.device, temperature=99, humidity=99,
            soil_moisture=0)
        evaluate_sensor_reading(reading)
        self.assertFalse(Alert.objects.exclude(alert_kind='sensor_stale').exists())
