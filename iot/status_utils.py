"""
Derived device / system status helpers.

The hardware (ESP32) exposes **no heartbeat field** — it simply POSTs a
``SensorReading`` roughly every 30 seconds. We therefore treat a controller as
"online" when it has produced sensor data within a short recency window
(default 90s = three missed intervals). Cameras expose a real status on
``IPCamera``. The active detection model is whichever ``MLModel`` has
``is_active=True``.

Everything here is READ-ONLY and intentionally defensive: any failure degrades
to "offline/unknown" instead of raising, so a dashboard never returns a 500
because a table is empty or a related app is unavailable. This mirrors the
try/except-guarded imports already used across ``iot/views.py``.
"""
from django.utils import timezone

# ESP32 posts sensor data about every 30s; allow 3 missed intervals before we
# call it offline. Callers may override per-context.
DEFAULT_ONLINE_WINDOW_SECONDS = 90

# Primary door/light controller. The environment/feeder board is a separate
# device and must not determine whether these controls are online.
MAIN_CONTROLLER_DEVICE_ID = 'gohmotech_esp32_002'


def device_last_seen(device):
    """Most recent moment we heard from ``device`` (SensorReading or legacy
    SensorData), or ``None`` if we never have."""
    if device is None:
        return None
    try:
        from .models import SensorReading, SensorData
        reading_ts = (
            SensorReading.objects.filter(device=device)
            .order_by('-timestamp').values_list('timestamp', flat=True).first()
        )
        data_ts = (
            SensorData.objects.filter(device=device)
            .order_by('-timestamp').values_list('timestamp', flat=True).first()
        )
        candidates = [t for t in (reading_ts, data_ts) if t is not None]
        return max(candidates) if candidates else None
    except Exception:
        return None


def seconds_since_seen(device):
    """Whole seconds since we last heard from ``device``, or ``None``."""
    last = device_last_seen(device)
    if last is None:
        return None
    return max(0, int((timezone.now() - last).total_seconds()))


def is_device_online(device, window_seconds=DEFAULT_ONLINE_WINDOW_SECONDS):
    """True when ``device`` produced sensor data within the recency window."""
    last = device_last_seen(device)
    if last is None:
        return False
    return (timezone.now() - last).total_seconds() <= window_seconds


def get_main_controller():
    """The main ESP32 ``Device`` row, or ``None`` if not registered yet."""
    try:
        from .models import Device
        return Device.objects.filter(device_id=MAIN_CONTROLLER_DEVICE_ID).first()
    except Exception:
        return None


def controller_status(window_seconds=DEFAULT_ONLINE_WINDOW_SECONDS):
    """Online summary for the main controller, safe on an empty database."""
    device = get_main_controller()
    return {
        'device_id': MAIN_CONTROLLER_DEVICE_ID,
        'device': device,
        'configured': device is not None,
        'online': is_device_online(device, window_seconds) if device else False,
        'last_seen': device_last_seen(device) if device else None,
        'seconds_since_seen': seconds_since_seen(device) if device else None,
    }


def active_ml_model():
    """The currently active goat-detection model, or ``None``.

    Scoped to ``category='goat'`` because a person model may now be active at
    the same time; this status helper describes the farm's goat detector.
    """
    try:
        from ml_models.models import MLModel
        return (
            MLModel.objects.filter(category='goat', is_active=True)
            .order_by('-updated_at').first()
        )
    except Exception:
        return None


def camera_status_summary():
    """Real status of the primary monitoring camera (from ``IPCamera``)."""
    empty = {'configured': False, 'online': False, 'status': None,
             'camera': None, 'last_connected': None}
    try:
        from .goat_models import IPCamera
        camera = (
            IPCamera.objects.filter(is_active=True)
            .order_by('-last_connected').first()
            or IPCamera.objects.first()
        )
        if not camera:
            return empty
        return {
            'configured': True,
            'camera': camera,
            'status': camera.status,
            'online': camera.status == 'active',
            'last_connected': camera.last_connected,
        }
    except Exception:
        return empty


def system_status(window_seconds=DEFAULT_ONLINE_WINDOW_SECONDS):
    """Aggregate status for the dashboard 'System' panel: controller online,
    camera status, and the active ML model."""
    return {
        'controller': controller_status(window_seconds),
        'camera': camera_status_summary(),
        'active_model': active_ml_model(),
    }
