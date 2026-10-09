"""Thirty-minute sensor aggregation and guarded raw-data retention."""

from collections import defaultdict
from datetime import timedelta
import logging
import math

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from .models import (
    Device,
    SensorData,
    SensorReading,
    SensorReadingSummary,
    SensorStorageSettings,
)


logger = logging.getLogger(__name__)
PERIOD_MINUTES = 30

# The combined ESP32 payload stores one raw row with several independent
# streams. Bounds mirror the model's existing validators; values outside them
# are ignored rather than converted to zero.
READING_STREAMS = {
    'temperature': ('temperature', '°C', None, None),
    'humidity': ('humidity', '%', 0, None),
    'soil_moisture': ('soil_moisture', '%', 0, None),
    'light_intensity': ('light_intensity', '', None, None),
    'light_raw': ('light_raw', 'ADC', 0, 4095),
    'light_level_percentage': ('light_level_percentage', '%', 0, 100),
    'air_quality_raw': ('air_quality_raw', 'ADC', 0, 4095),
    'air_quality_voltage': ('air_quality_voltage', 'V', 0, None),
    'air_quality_ppm': ('air_quality_ppm', 'ppm', 0, None),
    'rain_detected': ('rain_detected', 'boolean', 0, 1),
    'feeder_level': ('feeder_level', 'cm', None, None),
}


def period_for(moment):
    """Return the Manila-aligned half-hour containing an aware instant."""
    local = timezone.localtime(moment)
    minute = 30 if local.minute >= 30 else 0
    start = local.replace(minute=minute, second=0, microsecond=0)
    return start, start + timedelta(minutes=PERIOD_MINUTES)


def last_completed_period(now=None):
    """Return the most recently completed Manila-aligned period."""
    current_start, _ = period_for(now or timezone.now())
    return current_start - timedelta(minutes=PERIOD_MINUTES), current_start


def _valid_number(value, minimum=None, maximum=None):
    if value is None or isinstance(value, complex):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _add(accumulators, device_id, sensor_type, unit, value):
    key = (device_id, sensor_type)
    bucket = accumulators[key]
    bucket['unit'] = bucket['unit'] or unit or ''
    bucket['sum'] += value
    bucket['count'] += 1
    bucket['minimum'] = value if bucket['minimum'] is None else min(bucket['minimum'], value)
    bucket['maximum'] = value if bucket['maximum'] is None else max(bucket['maximum'], value)


@transaction.atomic
def aggregate_period(period_start, period_end):
    """Upsert summaries and only then mark source rows as processed."""
    if period_end <= period_start:
        raise ValueError('period_end must be after period_start')
    if period_end > timezone.now():
        raise ValueError('Only completed periods can be aggregated')

    combined = SensorReading.objects.filter(
        timestamp__gte=period_start, timestamp__lt=period_end)
    legacy = SensorData.objects.filter(
        timestamp__gte=period_start, timestamp__lt=period_end)
    accumulators = defaultdict(lambda: {
        'unit': '', 'sum': 0.0, 'count': 0, 'minimum': None, 'maximum': None,
    })

    combined_ids = []
    legacy_ids = []
    fields = ['id', 'device_id', 'air_quality_calibrated'] + [
        spec[0] for spec in READING_STREAMS.values()
    ]
    for row in combined.values(*fields).iterator(chunk_size=1000):
        combined_ids.append(row['id'])
        for sensor_type, (field, unit, minimum, maximum) in READING_STREAMS.items():
            if sensor_type == 'air_quality_ppm' and not row['air_quality_calibrated']:
                continue
            number = _valid_number(row[field], minimum, maximum)
            if number is not None:
                _add(accumulators, row['device_id'], sensor_type, unit, number)

    for row in legacy.values(
            'id', 'device_id', 'sensor_type', 'unit', 'value').iterator(chunk_size=1000):
        legacy_ids.append(row['id'])
        number = _valid_number(row['value'])
        if number is not None:
            _add(
                accumulators, row['device_id'], row['sensor_type'],
                row['unit'], number,
            )

    for (device_id, sensor_type), bucket in accumulators.items():
        SensorReadingSummary.objects.update_or_create(
            device_id=device_id,
            sensor_type=sensor_type,
            period_start=period_start,
            period_end=period_end,
            defaults={
                'unit': bucket['unit'],
                'average_value': bucket['sum'] / bucket['count'],
                'minimum_value': bucket['minimum'],
                'maximum_value': bucket['maximum'],
                'sample_count': bucket['count'],
            },
        )

    processed_at = timezone.now()
    SensorReading.objects.filter(pk__in=combined_ids).update(
        aggregation_completed_at=processed_at)
    SensorData.objects.filter(pk__in=legacy_ids).update(
        aggregation_completed_at=processed_at)
    raw_count = len(combined_ids) + len(legacy_ids)
    logger.info(
        'Aggregated sensor period %s to %s: %s summary stream(s), %s raw row(s)',
        period_start, period_end, len(accumulators), raw_count,
    )
    return {
        'period_start': period_start,
        'period_end': period_end,
        'summaries': len(accumulators),
        'raw_rows': raw_count,
    }


def aggregate_due_periods(now=None, backlog_periods=4):
    """Aggregate the last period plus a bounded amount of historical backlog."""
    now = now or timezone.now()
    latest_start, latest_end = last_completed_period(now)
    results = [aggregate_period(latest_start, latest_end)]
    processed = {(latest_start, latest_end)}

    for _ in range(max(0, backlog_periods)):
        earliest = []
        for model in (SensorReading, SensorData):
            value = model.objects.filter(
                aggregation_completed_at__isnull=True,
                timestamp__lt=latest_end,
            ).aggregate(value=Min('timestamp'))['value']
            if value is not None:
                earliest.append(value)
        if not earliest:
            break
        start, end = period_for(min(earliest))
        if end > latest_end:
            break
        if (start, end) in processed:
            break
        results.append(aggregate_period(start, end))
        processed.add((start, end))
    return results


def _latest_ids(model):
    """IDs that cleanup must preserve as each device's current raw reading."""
    result = []
    for device_id in Device.objects.values_list('pk', flat=True).iterator():
        latest_id = model.objects.filter(device_id=device_id).order_by(
            '-timestamp', '-pk').values_list('pk', flat=True).first()
        if latest_id is not None:
            result.append(latest_id)
    return result


def _delete_eligible(model, cutoff, batch_size):
    preserved = _latest_ids(model)
    deleted = 0
    while True:
        ids = list(model.objects.filter(
            timestamp__lt=cutoff,
            aggregation_completed_at__isnull=False,
        ).exclude(pk__in=preserved).order_by('pk').values_list(
            'pk', flat=True)[:batch_size])
        if not ids:
            return deleted
        count, _ = model.objects.filter(pk__in=ids).delete()
        deleted += count


def cleanup_aggregated_raw_data(now=None, batch_size=5000, force=False):
    """Delete old, processed raw rows while retaining summaries and latest rows."""
    policy = SensorStorageSettings.get_config()
    if not policy.cleanup_enabled and not force:
        logger.info('Raw sensor cleanup skipped because it is disabled')
        return {'enabled': False, 'deleted': 0, 'retention_days': policy.raw_retention_days}

    now = now or timezone.now()
    cutoff = now - timedelta(days=policy.raw_retention_days)
    deleted = (
        _delete_eligible(SensorReading, cutoff, batch_size)
        + _delete_eligible(SensorData, cutoff, batch_size)
    )
    policy.last_cleanup_at = now
    policy.last_cleanup_deleted = deleted
    policy.total_cleanup_deleted += deleted
    policy.save(update_fields=[
        'last_cleanup_at', 'last_cleanup_deleted', 'total_cleanup_deleted', 'updated_at',
    ])
    logger.info(
        'Raw sensor cleanup deleted %s row(s) older than %s days; latest rows preserved',
        deleted, policy.raw_retention_days,
    )
    return {
        'enabled': True,
        'deleted': deleted,
        'retention_days': policy.raw_retention_days,
        'cutoff': cutoff,
    }
