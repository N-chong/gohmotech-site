"""
Security notification service.

Single funnel for creating user-facing Notification rows and pushing them over
the *existing* Django Channels 'alerts' group. This generalizes the older
iot.notification_service (which was hard-bound to MissingGoatAlert) so that any
event — iot.Alert, iot.MissingGoatAlert, security.PersonDetection, or a plain
system message — raises exactly one notification, with no duplicates.

Realtime is preserved, not replaced: we reuse the 'alerts' group and the
AlertConsumer.alert_notification handler that already exist. Existing WebSocket
clients keep receiving {'type': 'alert', 'data': ...}; the data payload is
simply richer now.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

logger = logging.getLogger(__name__)


def create_or_update_notification(*, title, description='', severity='medium',
                                  notification_type='other', source='',
                                  source_object=None, metadata=None,
                                  broadcast=True):
    """
    Create the notification for an event, or update the existing one if a
    notification for that exact source already exists (deduplication).

    Args:
        title: short headline
        description: detailed message
        severity: one of Notification.SEVERITY_CHOICES keys
        notification_type: one of Notification.TYPE_CHOICES keys
        source: human-readable origin (camera/device name)
        source_object: the backing event instance (Alert, MissingGoatAlert,
                       PersonDetection, ...) or None for a standalone message
        metadata: optional JSON-serializable dict
        broadcast: push over WebSocket when True

    Returns:
        (notification, created) tuple.
    """
    from .models import Notification

    defaults = {
        'title': title,
        'description': description,
        'severity': severity,
        'notification_type': notification_type,
        'source': source,
        'metadata': metadata,
    }

    created = False

    if source_object is not None and getattr(source_object, 'pk', None):
        ct = ContentType.objects.get_for_model(source_object.__class__)
        notification, created = Notification.objects.get_or_create(
            source_content_type=ct,
            source_object_id=source_object.pk,
            defaults=defaults,
        )
        if not created:
            # Update the existing row in place — never create a second one for
            # the same event. We deliberately leave is_read / is_resolved alone
            # so an ongoing event does not silently reopen a resolved alert.
            for field, value in defaults.items():
                setattr(notification, field, value)
            notification.save(update_fields=[
                'title', 'description', 'severity', 'notification_type',
                'source', 'metadata', 'updated_at',
            ])
    else:
        notification = Notification.objects.create(**defaults)
        created = True

    if broadcast:
        broadcast_notification(notification)

    if created:
        logger.info("[NOTIFICATION] Created id=%s type=%s severity=%s source=%s",
                    notification.pk, notification.notification_type,
                    notification.severity, notification.source or '-')

    # Fan a newly-raised alert out to SMS (best-effort). Only on `created` so
    # dedup updates and person-detection cooldown folds (which call this with
    # created=False) never re-text. The SMS app authoritatively decides whether
    # this type/severity is eligible and enforces cooldown, so this side keeps
    # no alert rules of its own — it just enqueues.
    if created:
        _maybe_enqueue_alert_sms(notification)

    return notification, created


def _maybe_enqueue_alert_sms(notification):
    """Enqueue an alert SMS for a new notification without ever breaking the
    notification flow if the SMS app or broker is unavailable."""
    try:
        from sms.tasks import send_alert_sms
        # Signals commonly run inside a request transaction. Queue only after
        # commit so a fast worker cannot look up an uncommitted notification.
        def enqueue():
            try:
                send_alert_sms.delay(notification.id)
            except Exception:
                logger.exception("Failed to enqueue alert SMS for #%s",
                                 notification.id)

        transaction.on_commit(enqueue)
    except Exception as exc:  # pragma: no cover - SMS is best-effort
        logger.error(f"Failed to enqueue alert SMS for #{notification.id}: {exc}")


def broadcast_notification(notification):
    """
    Push a notification to the existing 'alerts' WebSocket group.

    Keeps the established contract (AlertConsumer.alert_notification emits
    {'type': 'alert', 'data': ...}) while enriching the data payload so both
    legacy and new front-end listeners work.
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("Channel layer not configured; skipping broadcast")
            return False

        payload = {
            'type': 'security_notification',
            'id': notification.id,
            'title': notification.title,
            # 'message' kept for backward compatibility with older listeners
            'message': notification.description,
            'description': notification.description,
            'severity': notification.severity,
            'notification_type': notification.notification_type,
            'source': notification.source,
            'is_read': notification.is_read,
            'is_resolved': notification.is_resolved,
            'timestamp': notification.created_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(
            'alerts',
            {'type': 'alert_notification', 'data': payload},
        )
        return True
    except Exception as exc:  # pragma: no cover - broadcast is best-effort
        logger.error(f"Failed to broadcast notification #{notification.id}: {exc}")
        return False


def unread_count():
    """Current number of unread notifications (drives the header bell badge)."""
    from .models import Notification
    return Notification.objects.filter(is_read=False).count()


def notify_person_detection(detection, *, broadcast=True):
    """
    Raise (or update) the single Notification associated with a PersonDetection
    and link it back. Idempotent: calling twice for the same detection reuses
    the same notification row.
    """
    severity_map = {
        'unknown_person': 'high',
        'person': 'high',
        'face': 'medium',
    }
    severity = severity_map.get(detection.detection_type, 'high')

    title = f"{detection.get_detection_type_display()}"
    source = detection.source_display
    description = (
        f"{detection.get_detection_type_display()} at {source} "
        f"(confidence {detection.confidence:.0%})."
    )

    notification, _created = create_or_update_notification(
        title=title,
        description=description,
        severity=severity,
        notification_type='person_detection',
        source=source,
        source_object=detection,
        metadata={'confidence': detection.confidence,
                  'detection_type': detection.detection_type},
        broadcast=broadcast,
    )

    if detection.notification_id != notification.id:
        detection.notification = notification
        detection.save(update_fields=['notification'])

    return notification


def record_person_detection(*, camera=None, source_label='', confidence,
                            bounding_boxes, snapshot_bytes=None,
                            detection_type='person', cooldown_seconds=None):
    """
    Throttled create/update of a PersonDetection (and its single Notification).

    Live detection runs at streaming FPS and each PersonDetection is a distinct
    source object, so notification-level dedup alone does NOT bound alert spam.
    This coalesces a burst: within ``cooldown_seconds`` (settings-driven,
    default 30) and for the same source (the camera, or ``source_label`` when
    there is no camera), it UPDATES the most-recent still-open detection instead
    of creating a new row, and re-notifies WITHOUT re-broadcasting. A new row and
    a fresh WebSocket ping are raised only when no open detection falls inside
    the window.

    "Open" means ``status='new'`` and ``review_state='unreviewed'`` — once a
    reviewer touches a detection it is never folded into again.

    Returns ``(detection, created)``.
    """
    from datetime import timedelta

    from django.conf import settings
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from .models import PersonDetection

    if cooldown_seconds is None:
        cooldown_seconds = getattr(settings, 'PERSON_DETECTION_COOLDOWN_SECONDS', 30)

    now = timezone.now()
    window_start = now - timedelta(seconds=cooldown_seconds)

    recent_qs = PersonDetection.objects.filter(
        detection_type=detection_type,
        status='new',
        review_state='unreviewed',
        detected_at__gte=window_start,
    )
    if camera is not None:
        recent_qs = recent_qs.filter(camera=camera)
    else:
        recent_qs = recent_qs.filter(camera__isnull=True, source_label=source_label)
    recent = recent_qs.order_by('-detected_at').first()

    def _save_snapshot(detection):
        """Attach a JPEG snapshot to ``detection`` (best-effort; never raises)."""
        if not snapshot_bytes:
            return False
        try:
            detection.snapshot.save(
                f"person_{now:%Y%m%d_%H%M%S_%f}.jpg",
                ContentFile(snapshot_bytes), save=False,
            )
            return True
        except Exception:
            logger.exception("Failed to save person-detection snapshot")
            return False

    if recent is not None:
        # Fold this frame into the open detection: refresh the live values but
        # keep the original snapshot (ImageField.save mints a new file each call,
        # so re-snapshotting every frame would orphan files at FPS).
        recent.confidence = confidence
        recent.bounding_boxes = bounding_boxes
        recent.detected_at = now
        update_fields = ['confidence', 'bounding_boxes', 'detected_at']
        if not recent.snapshot and _save_snapshot(recent):
            update_fields.append('snapshot')
        recent.save(update_fields=update_fields)
        notify_person_detection(recent, broadcast=False)
        return recent, False

    detection = PersonDetection(
        camera=camera,
        source_label=source_label,
        detection_type=detection_type,
        confidence=confidence,
        bounding_boxes=bounding_boxes,
        detected_at=now,
    )
    _save_snapshot(detection)
    detection.save()
    notify_person_detection(detection, broadcast=True)   # first sighting = ping
    return detection, True
