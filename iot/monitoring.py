"""Evaluate real sensor readings against operator-owned alert policy."""

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Alert, Device, EnvironmentalAlertSettings, SensorReading

logger = logging.getLogger(__name__)


def _set_condition(*, device, key, kind, active, severity, message):
    """Open one alert for an active condition, or resolve it on recovery."""
    with transaction.atomic():
        # Locking the device serializes incoming readings and the periodic health
        # check without requiring a MySQL partial unique index.
        Device.objects.select_for_update().get(pk=device.pk)
        open_alerts = Alert.objects.filter(
            device=device, deduplication_key=key, is_resolved=False)
        if active:
            existing = open_alerts.order_by('-created_at').first()
            if existing:
                return existing, False
            alert = Alert.objects.create(
                device=device,
                severity=severity,
                alert_kind=kind,
                deduplication_key=key,
                message=message,
            )
            logger.warning("[ALERT] %s device=%s alert=%s", kind,
                           device.device_id, alert.pk)
            return alert, True

        now = timezone.now()
        resolved = list(open_alerts)
        for alert in resolved:
            alert.is_resolved = True
            alert.resolved_at = now
            alert.save(update_fields=['is_resolved', 'resolved_at'])
            logger.info("[ALERT] Resolved %s device=%s alert=%s", kind,
                        device.device_id, alert.pk)
        return (resolved[0] if resolved else None), False


def evaluate_sensor_reading(reading, policy=None):
    """Evaluate only supported measurements with explicitly set thresholds."""
    policy = policy or EnvironmentalAlertSettings.get_config()
    if not policy.enabled:
        return []

    device = reading.device
    # A received reading proves that the reporting path recovered.
    _set_condition(
        device=device, key=f"sensor-stale:{device.pk}", kind='sensor_stale',
        active=False, severity=policy.stale_severity,
        message='',
    )

    specs = [
        ('temperature', reading.temperature, policy.temperature_min_c,
         policy.temperature_max_c, 'C', 'Temperature'),
        ('humidity', reading.humidity, policy.humidity_min_percent,
         policy.humidity_max_percent, '%', 'Humidity'),
    ]
    results = []
    for field, value, minimum, maximum, unit, label in specs:
        if value is None:
            continue
        conditions = (
            ('low', minimum, minimum is not None and float(value) < float(minimum), '<'),
            ('high', maximum, maximum is not None and float(value) > float(maximum), '>'),
        )
        for direction, threshold, active, operator in conditions:
            key = f"sensor-threshold:{device.pk}:{field}:{direction}"
            message = (f"{label} {value:g}{unit} is {operator} configured "
                       f"{threshold:g}{unit} limit") if threshold is not None else ''
            result = _set_condition(
                device=device, key=key, kind=f'{field}_{direction}',
                active=active, severity=policy.threshold_severity,
                message=message,
            )
            if result[0] is not None:
                results.append(result)
    return results


def check_stale_sensors(now=None, policy=None):
    """Raise one warning per sensor device after the configured long outage."""
    policy = policy or EnvironmentalAlertSettings.get_config()
    if not (policy.enabled and policy.stale_detection_enabled):
        return 0
    now = now or timezone.now()
    checked = 0
    # Only devices that have actually reported environmental readings are in
    # scope; BLE receivers/cameras have different heartbeat mechanisms.
    devices = Device.objects.filter(
        Q(last_sensor_received_at__isnull=False)
        | Q(environmental_readings__isnull=False)
    ).distinct()
    for device in devices:
        latest = SensorReading.objects.filter(device=device).order_by('-received_at').first()
        last_received = device.last_sensor_received_at or (
            latest.received_at if latest else None)
        if last_received is None:
            continue
        age_seconds = max(0, int(
            (now - last_received).total_seconds()))
        stale = age_seconds > policy.stale_after_seconds
        _set_condition(
            device=device,
            key=f"sensor-stale:{device.pk}",
            kind='sensor_stale',
            active=stale,
            severity=policy.stale_severity,
            message=(f"{device.name} has not reported sensor data for "
                     f"{age_seconds // 60} minute(s); expected every 30 seconds."),
        )
        checked += 1
    return checked
