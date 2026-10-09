"""
Daily-summary text builder for the SMS subsystem.

The daily SMS must be a *short* digest of the same real data the dashboard and
Reports module already show — so it reuses
the same domain tables used by Reports, restricted to the current Manila
calendar day. Nothing here is fabricated: every line comes from an existing
record, and missing data is shown as such instead of invented.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from feeding.models import FeedLog
from iot.goat_models import Goat
from iot.models import ActuationLog, SensorReading
from security.models import Notification


def build_daily_summary_text(now=None):
    """Return a short, multi-line daily summary string for SMS.

    Uses local-midnight bounds converted by Django to UTC for database queries,
    avoiding MySQL ``__date`` timezone-table dependencies.
    """
    now = timezone.localtime(now or timezone.now())
    day_start = timezone.make_aware(
        datetime.combine(now.date(), time.min), timezone.get_current_timezone())
    day_end = day_start + timedelta(days=1)
    lines = [f"GoHMoTech Daily Summary {now:%b %d %H:%M}"]

    # --- Herd snapshot ---
    herd = Goat.objects.filter(is_active=True)
    lines.append(
        f"Goats: {herd.count()} "
        f"(healthy {herd.filter(health_status='healthy').count()}, "
        f"sick {herd.filter(health_status='sick').count()})"
    )

    # --- Today's real automation activity ---
    feed_count = FeedLog.objects.filter(
        timestamp__gte=day_start, timestamp__lt=day_end).count()
    actions = ActuationLog.objects.filter(
        timestamp__gte=day_start, timestamp__lt=day_end)
    lines.append(
        f"Today: feed {feed_count}, "
        f"door {actions.filter(action__in=['open', 'close']).count()}, "
        f"light {actions.filter(action__in=['turn_on', 'turn_off']).count()}"
    )

    # --- Latest environmental reading received today ---
    latest = SensorReading.objects.filter(
        received_at__gte=day_start, received_at__lt=day_end,
    ).order_by('-received_at').first()
    if latest is not None:
        parts = []
        if latest.temperature is not None:
            parts.append(f"{round(latest.temperature, 1)}C")
        if latest.humidity is not None:
            parts.append(f"{round(latest.humidity)}%RH")
        lines.append("Env: " + (", ".join(parts) if parts else "no values"))
    else:
        lines.append("Env: no readings")

    # --- Alerts generated today and currently-open important alerts ---
    today_alerts = Notification.objects.filter(
        created_at__gte=day_start, created_at__lt=day_end).count()
    open_alerts = Notification.objects.filter(
        is_resolved=False, severity__in=['critical', 'high']).count()
    lines.append(f"Alerts: {today_alerts} today, {open_alerts} open high/critical")

    return "\n".join(lines)
