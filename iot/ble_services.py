"""Transactional BLE matching and state-update services."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from .models import (
    BLEBeacon,
    BLEObservation,
    BLEReceiver,
    BLETrackingSettings,
    BLETrackingState,
    GoatImage,
)


class BeaconNotFoundError(Exception):
    pass


class BeaconIdentityConflictError(Exception):
    pass


def classify_proximity(smoothed_rssi, config):
    """Classify signal strength without claiming physical distance."""
    if smoothed_rssi >= config.very_near_min_rssi:
        return 'very_near'
    if smoothed_rssi >= config.near_min_rssi:
        return 'near'
    if smoothed_rssi >= config.medium_min_rssi:
        return 'medium'
    return 'far'


def find_enabled_beacon(observation):
    """Prefer complete iBeacon identity and safely fall back to registered MAC."""
    identity_supplied = all(
        observation.get(field) is not None for field in ('uuid', 'major', 'minor')
    )
    identity_beacon = None
    mac_beacon = None

    if identity_supplied:
        identity_beacon = BLEBeacon.objects.filter(
            enabled=True,
            uuid=observation['uuid'],
            major=observation['major'],
            minor=observation['minor'],
        ).first()

    if observation.get('address'):
        mac_beacon = BLEBeacon.objects.filter(
            enabled=True,
            mac_address=observation['address'],
        ).first()

    if identity_beacon and mac_beacon and identity_beacon.pk != mac_beacon.pk:
        raise BeaconIdentityConflictError(
            'The advertised iBeacon identity and MAC address belong to different trackers.'
        )
    if identity_supplied and not identity_beacon and mac_beacon:
        raise BeaconIdentityConflictError(
            'The advertised iBeacon identity does not match the tracker registered to this MAC.'
        )

    beacon = identity_beacon or mac_beacon
    if beacon is None:
        raise BeaconNotFoundError('No enabled tracker matches this advertisement.')
    return beacon


def touch_receiver(receiver, *, scanner_version=None, device_name=None,
                   platform=None, metadata=None):
    """Mark a receiver online and selectively update self-reported metadata."""
    receiver.status = 'online'
    receiver.last_online = timezone.now()
    receiver.last_error = ''
    update_fields = ['status', 'last_online', 'last_error', 'updated_at']

    for field, value in (
        ('scanner_version', scanner_version),
        ('device_name', device_name),
        ('platform', platform),
    ):
        if value not in (None, ''):
            setattr(receiver, field, value)
            update_fields.append(field)

    if metadata is not None:
        receiver.metadata = metadata
        update_fields.append('metadata')

    receiver.save(update_fields=update_fields)
    return receiver


def record_observation(receiver, observation):
    """Update current state and create only a throttled history snapshot."""
    config = BLETrackingSettings.get_config()
    beacon = find_enabled_beacon(observation)
    received_at = timezone.now()
    smoothed_rssi = observation.get('smoothed_rssi')
    if smoothed_rssi is None:
        smoothed_rssi = float(observation['rssi'])
    proximity = classify_proximity(smoothed_rssi, config)

    with transaction.atomic():
        state, _ = BLETrackingState.objects.select_for_update().get_or_create(
            beacon=beacon,
            receiver=receiver,
        )
        previous_proximity = state.proximity
        state.current_rssi = observation['rssi']
        state.smoothed_rssi = smoothed_rssi
        state.proximity = proximity
        state.status = 'detected'
        # Server receipt time is authoritative for online/offline freshness.
        state.last_seen = received_at
        state.sample_count += 1
        state.save(update_fields=[
            'current_rssi',
            'smoothed_rssi',
            'proximity',
            'status',
            'last_seen',
            'sample_count',
            'updated_at',
        ])

        latest_history = BLEObservation.objects.filter(
            beacon=beacon,
            receiver=receiver,
        ).order_by('-detected_at').first()
        snapshot_due = (
            latest_history is None
            or previous_proximity != proximity
            or latest_history.detected_at
            <= received_at - timedelta(
                seconds=config.history_snapshot_interval_seconds
            )
        )
        history = None
        if snapshot_due:
            history = BLEObservation.objects.create(
                beacon=beacon,
                goat=beacon.goat,
                receiver=receiver,
                rssi=observation['rssi'],
                smoothed_rssi=smoothed_rssi,
                proximity=proximity,
                # Use server time so clock drift cannot defeat history throttling.
                detected_at=received_at,
            )

        battery_level = observation.get('battery_level')
        if battery_level is not None:
            beacon.battery_level = battery_level
            beacon.battery_updated_at = received_at
            beacon.save(update_fields=[
                'battery_level',
                'battery_updated_at',
                'updated_at',
            ])

    touch_receiver(receiver)
    return state, history


def refresh_tracking_statuses(now=None):
    """Age current states and receivers using the database-backed timeouts."""
    now = now or timezone.now()
    config = BLETrackingSettings.get_config()
    detected_cutoff = now - timedelta(
        seconds=config.possibly_lost_timeout_seconds
    )
    out_of_range_cutoff = now - timedelta(
        seconds=config.out_of_range_timeout_seconds
    )

    BLETrackingState.objects.filter(
        Q(last_seen__isnull=True) | Q(last_seen__lt=out_of_range_cutoff)
    ).exclude(
        status='out_of_range',
        proximity='out_of_range',
    ).update(
        status='out_of_range',
        proximity='out_of_range',
        updated_at=now,
    )
    BLETrackingState.objects.filter(
        last_seen__gte=out_of_range_cutoff,
        last_seen__lt=detected_cutoff,
    ).exclude(status='possibly_lost').update(
        status='possibly_lost',
        updated_at=now,
    )
    BLETrackingState.objects.filter(
        last_seen__gte=detected_cutoff,
    ).exclude(status='detected').update(
        status='detected',
        updated_at=now,
    )

    receiver_cutoff = now - timedelta(
        seconds=max(config.heartbeat_interval_seconds * 3, 10)
    )
    BLEReceiver.objects.filter(
        Q(last_online__isnull=True) | Q(last_online__lt=receiver_cutoff),
        status='online',
    ).update(status='offline', updated_at=now)
    return config


def build_tracking_snapshot(now=None, record_source=None):
    """Return the current list payload without implying exact position."""
    now = now or timezone.now()
    config = refresh_tracking_statuses(now)
    image_queryset = GoatImage.objects.order_by('-uploaded_at')
    state_queryset = BLETrackingState.objects.select_related(
        'receiver__device'
    ).order_by('-last_seen')
    beacons = BLEBeacon.objects.filter(
        enabled=True,
        goat__isnull=False,
    )
    if record_source is not None:
        beacons = beacons.filter(goat__record_source=record_source)
    beacons = beacons.select_related('goat').prefetch_related(
        Prefetch(
            'goat__images',
            queryset=image_queryset,
            to_attr='tracking_images',
        ),
        Prefetch(
            'tracking_states',
            queryset=state_queryset,
            to_attr='tracking_state_cache',
        ),
    ).order_by('goat__goat_id')

    rows = []
    for beacon in beacons:
        goat = beacon.goat
        states = beacon.tracking_state_cache
        state = states[0] if states else None
        status_value = state.status if state else 'out_of_range'
        proximity = (
            state.proximity
            if state and status_value != 'out_of_range'
            else 'out_of_range'
        )
        images = getattr(goat, 'tracking_images', [])
        image_url = None
        if images:
            try:
                image_url = images[0].image.url
            except ValueError:
                image_url = None

        receiver = state.receiver if state else None
        rows.append({
            'goat': {
                'id': goat.pk,
                'goat_id': goat.goat_id,
                'name': goat.name,
                'image_url': image_url,
                'detail_url': reverse(
                    'iot:goat_detail_enhanced',
                    args=[goat.goat_id],
                ),
            },
            'beacon': {
                'id': beacon.pk,
                'device_name': beacon.device_name,
                'mac_address': beacon.mac_address,
                'uuid': beacon.uuid,
                'major': beacon.major,
                'minor': beacon.minor,
                'battery_level': beacon.battery_level,
            },
            'receiver': (
                {
                    'receiver_id': receiver.device.device_id,
                    'name': receiver.device.name,
                    'location': receiver.device.location,
                    'status': receiver.status,
                    'last_online': receiver.last_online,
                }
                if receiver
                else None
            ),
            'current_rssi': state.current_rssi if state else None,
            'smoothed_rssi': state.smoothed_rssi if state else None,
            'proximity': proximity,
            'proximity_display': dict(
                BLETrackingState.PROXIMITY_CHOICES
            )[proximity],
            'status': status_value,
            'status_display': dict(
                BLETrackingState.STATUS_CHOICES
            )[status_value],
            'last_seen': state.last_seen if state else None,
            'sample_count': state.sample_count if state else 0,
        })

    summary = {
        'tracked_goats': len(rows),
        'detected': sum(row['status'] == 'detected' for row in rows),
        'possibly_lost': sum(
            row['status'] == 'possibly_lost' for row in rows
        ),
        'out_of_range': sum(
            row['status'] == 'out_of_range' for row in rows
        ),
        'very_near': sum(
            row['status'] == 'detected' and row['proximity'] == 'very_near'
            for row in rows
        ),
        'near': sum(
            row['status'] == 'detected' and row['proximity'] == 'near'
            for row in rows
        ),
        'medium': sum(
            row['status'] == 'detected' and row['proximity'] == 'medium'
            for row in rows
        ),
        'far': sum(
            row['status'] == 'detected' and row['proximity'] == 'far'
            for row in rows
        ),
    }
    receivers = [{
        'receiver_id': receiver.device.device_id,
        'name': receiver.device.name,
        'location': receiver.device.location,
        'platform': receiver.platform,
        'status': receiver.status,
        'last_online': receiver.last_online,
    } for receiver in BLEReceiver.objects.select_related('device').order_by(
        'device__name'
    )]
    return {
        'generated_at': now,
        'poll_interval_seconds': 2,
        'timing': {
            'possibly_lost_timeout_seconds': (
                config.possibly_lost_timeout_seconds
            ),
            'out_of_range_timeout_seconds': (
                config.out_of_range_timeout_seconds
            ),
        },
        'summary': summary,
        'receivers': receivers,
        'goats': rows,
    }
