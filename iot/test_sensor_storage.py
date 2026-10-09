from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from analytics.report_data import build_environmental
from iot.models import (
    Alert,
    Device,
    EnvironmentalAlertSettings,
    SensorReading,
    SensorReadingSummary,
    SensorStorageSettings,
)
from iot.monitoring import evaluate_sensor_reading
from iot.sensor_storage import (
    aggregate_period,
    cleanup_aggregated_raw_data,
    period_for,
)


MANILA = ZoneInfo('Asia/Manila')


class SensorAggregationTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            device_id='storage-test-device',
            name='Storage Test Device',
            device_type='environmental_sensor',
        )
        self.start = datetime(2026, 10, 5, 8, 0, tzinfo=MANILA)
        self.end = self.start + timedelta(minutes=30)

    def reading(self, minute, **values):
        return SensorReading.objects.create(
            device=self.device,
            timestamp=self.start + timedelta(minutes=minute),
            **values,
        )

    def test_grouping_average_minimum_maximum_and_sample_count(self):
        self.reading(0, temperature=27.8)
        self.reading(10, temperature=28.4)
        self.reading(29, temperature=30.1)

        aggregate_period(self.start, self.end)

        summary = SensorReadingSummary.objects.get(sensor_type='temperature')
        self.assertAlmostEqual(summary.average_value, 28.766666, places=5)
        self.assertEqual(summary.minimum_value, 27.8)
        self.assertEqual(summary.maximum_value, 30.1)
        self.assertEqual(summary.sample_count, 3)
        self.assertEqual(summary.period_start, self.start)
        self.assertEqual(summary.period_end, self.end)

    def test_missing_null_and_invalid_values_are_not_faked(self):
        self.reading(0, temperature=28, humidity=None, light_level_percentage=25)
        self.reading(1, temperature=None, humidity=72, light_level_percentage=150)

        aggregate_period(self.start, self.end)

        self.assertEqual(
            SensorReadingSummary.objects.get(sensor_type='temperature').sample_count, 1)
        self.assertEqual(
            SensorReadingSummary.objects.get(sensor_type='humidity').sample_count, 1)
        self.assertEqual(
            SensorReadingSummary.objects.get(
                sensor_type='light_level_percentage').sample_count, 1)

    def test_no_data_period_creates_no_fake_summary(self):
        result = aggregate_period(self.start, self.end)
        self.assertEqual(result['summaries'], 0)
        self.assertFalse(SensorReadingSummary.objects.exists())

    def test_rerun_updates_instead_of_duplicating(self):
        self.reading(0, temperature=20)
        aggregate_period(self.start, self.end)
        self.reading(20, temperature=30)

        aggregate_period(self.start, self.end)

        self.assertEqual(
            SensorReadingSummary.objects.filter(sensor_type='temperature').count(), 1)
        summary = SensorReadingSummary.objects.get(sensor_type='temperature')
        self.assertEqual(summary.average_value, 25)
        self.assertEqual(summary.sample_count, 2)

    def test_periods_are_manila_aligned_across_date_boundary(self):
        with timezone.override(MANILA):
            instant = datetime(2026, 10, 5, 23, 45, tzinfo=MANILA)
            start, end = period_for(instant)
        self.assertEqual(start, datetime(2026, 10, 5, 23, 30, tzinfo=MANILA))
        self.assertEqual(end, datetime(2026, 10, 6, 0, 0, tzinfo=MANILA))

    def test_latest_raw_reading_remains_distinct_from_summary(self):
        self.reading(0, temperature=20)
        latest = self.reading(29, temperature=31)
        aggregate_period(self.start, self.end)

        self.assertEqual(
            SensorReading.objects.filter(device=self.device).order_by(
                '-timestamp').first().pk,
            latest.pk,
        )
        self.assertEqual(
            SensorReadingSummary.objects.get(
                sensor_type='temperature').average_value, 25.5)


class RawSensorCleanupTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 6, 12, 0, tzinfo=MANILA)
        self.device = Device.objects.create(
            device_id='cleanup-device', name='Cleanup Device',
            device_type='environmental_sensor',
        )
        self.policy = SensorStorageSettings.get_config()
        self.policy.raw_retention_days = 7
        self.policy.cleanup_enabled = True
        self.policy.save()

    def test_cleanup_only_deletes_old_processed_rows_and_preserves_latest(self):
        completed = self.now - timedelta(days=10)
        deletable = SensorReading.objects.create(
            device=self.device, timestamp=completed, temperature=20,
            aggregation_completed_at=self.now - timedelta(days=9),
        )
        unaggregated = SensorReading.objects.create(
            device=self.device, timestamp=completed + timedelta(minutes=1), temperature=21,
        )
        recent = SensorReading.objects.create(
            device=self.device, timestamp=self.now - timedelta(days=1), temperature=22,
            aggregation_completed_at=self.now - timedelta(hours=12),
        )

        result = cleanup_aggregated_raw_data(now=self.now, batch_size=1)

        self.assertEqual(result['deleted'], 1)
        self.assertFalse(SensorReading.objects.filter(pk=deletable.pk).exists())
        self.assertTrue(SensorReading.objects.filter(pk=unaggregated.pk).exists())
        self.assertTrue(SensorReading.objects.filter(pk=recent.pk).exists())

    def test_cleanup_preserves_an_old_latest_reading(self):
        latest = SensorReading.objects.create(
            device=self.device, timestamp=self.now - timedelta(days=20),
            temperature=23, aggregation_completed_at=self.now - timedelta(days=19),
        )

        cleanup_aggregated_raw_data(now=self.now)

        self.assertTrue(SensorReading.objects.filter(pk=latest.pk).exists())


class SensorStorageIntegrationTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            device_id='integration-device', name='Integration Device',
            device_type='environmental_sensor',
        )

    def test_alert_evaluation_uses_incoming_raw_value(self):
        policy = EnvironmentalAlertSettings.objects.create(
            temperature_max_c=30, stale_detection_enabled=False)
        reading = SensorReading.objects.create(
            device=self.device, temperature=35, timestamp=timezone.now())

        evaluate_sensor_reading(reading, policy=policy)

        alert = Alert.objects.get(alert_kind='temperature_high')
        self.assertIn('35', alert.message)
        self.assertFalse(SensorReadingSummary.objects.exists())

    def test_long_environment_report_prefers_summaries_with_peak_lines(self):
        period_start = timezone.now() - timedelta(days=8)
        SensorReadingSummary.objects.create(
            device=self.device, sensor_type='temperature', unit='°C',
            period_start=period_start, period_end=period_start + timedelta(minutes=30),
            average_value=28, minimum_value=24, maximum_value=35, sample_count=52,
        )

        report = build_environmental(days=30)

        self.assertIn('Sensor', report['columns'])
        self.assertIn('30-minute summaries', report['note'])
        daily = next(chart for chart in report['charts'] if chart['id'] == 'daily')
        labels = {dataset['label'] for dataset in daily['datasets']}
        self.assertIn('Avg Temp (°C)', labels)
        self.assertIn('Min Temp (°C)', labels)
        self.assertIn('Max Temp (°C)', labels)
