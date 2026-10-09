"""
Celery tasks for the SMS subsystem.

Two beat-driven tasks run every minute and mirror the proven scheduling shape of
``iot.tasks.execute_scheduled_feeding`` (local time, minute-precision match,
0=Sunday day arithmetic):

  * ``send_daily_summary``  — fires the once-a-day digest at the operator's time.
  * ``send_due_reminders``  — fires any reminder whose time/day matches now.

Plus two event-driven tasks:

  * ``send_alert_sms``      — enqueued by the security notification funnel when a
                              new notification is raised (task #6).
  * ``send_test_sms``       — invoked by the Test SMS button.

All actual sending goes through ``sms.services.send_sms`` so every message is
logged uniformly. Operator toggles are read from the ``SmsSettings`` DB
singleton at run time (never from per-process settings), so a change made in the
UI is honoured by the worker on its next tick.
"""

import logging
from datetime import datetime

from celery import shared_task
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone

logger = logging.getLogger(__name__)

# Max characters we let an alert body reach before truncating, to keep an alert
# SMS to a small, predictable number of segments.
ALERT_MAX_CHARS = 300


def _format_reminder_text(reminder):
    """Build a reminder SMS with the schedule context and user message."""
    scheduled_time = reminder.schedule_time.strftime('%I:%M %p')
    return (
        f"Title: {reminder.title}\n"
        f"Type: {reminder.get_reminder_type_display()}\n"
        f"Time: {scheduled_time}\n"
        f"Message: {reminder.message}"
    )


@shared_task
def send_daily_summary():
    """Execute today's summary once at or after its Manila scheduled time.

    Missed-run policy: if the Pi is down at the exact minute, the first tick
    later on the same local calendar day performs one catch-up attempt. Runs
    from earlier dates are never replayed. A unique ``DailySummaryRun`` plus an
    atomic pending->processing claim prevents duplicate sends across workers or
    restarts. Processing runs are not auto-retried because a provider timeout
    can be ambiguous and retrying could send a duplicate message.
    """
    from .models import DailySummaryRun, SmsSettings
    from .services import send_sms
    from .summaries import build_daily_summary_text

    settings_obj = SmsSettings.get_config()
    if not settings_obj.daily_enabled:
        return "Daily summary disabled"

    now = timezone.localtime(timezone.now())
    scheduled_for = timezone.make_aware(
        datetime.combine(now.date(), settings_obj.daily_time),
        timezone.get_current_timezone(),
    )
    if now < scheduled_for:
        return "Not due"

    try:
        run, _created = DailySummaryRun.objects.get_or_create(
            scheduled_date=now.date(),
            defaults={
                'scheduled_for': scheduled_for,
                'recipient': settings_obj.recipient_number,
            },
        )
    except IntegrityError:
        run = DailySummaryRun.objects.get(scheduled_date=now.date())

    # One atomic claimant. Existing terminal/processing rows are never replayed.
    claimed = DailySummaryRun.objects.filter(
        pk=run.pk, status='pending').update(
            status='processing', executed_at=timezone.now(),
            recipient=settings_obj.recipient_number, error_message='')
    if not claimed:
        return f"Daily summary already {run.status}"

    logger.info("[DAILY SUMMARY] Job started scheduled=%s actual=%s",
                scheduled_for.isoformat(), now.isoformat())

    if not settings_obj.enabled:
        DailySummaryRun.objects.filter(pk=run.pk).update(
            status='skipped', error_message='SMS master switch is disabled')
        logger.warning("[DAILY SUMMARY] Skipped: SMS master switch is disabled")
        return "Daily summary skipped: SMS disabled"

    try:
        message = build_daily_summary_text()
        logger.info("[DAILY SUMMARY] Summary generated")
        log = send_sms(message=message, sms_type='daily')
        if log is None:
            DailySummaryRun.objects.filter(pk=run.pk).update(
                status='skipped', error_message='SMS was disabled before sending')
            return "Daily summary skipped"
        DailySummaryRun.objects.filter(pk=run.pk).update(
            status=log.status if log.status in ('sent', 'failed') else 'failed',
            sms_log=log,
            error_message=log.error_message,
        )
        if log.status == 'sent':
            logger.info("[DAILY SUMMARY] SMS sent log=%s", log.pk)
        else:
            logger.warning("[DAILY SUMMARY] SMS failed log=%s reason=%s",
                           log.pk, (log.error_message or 'unknown')[:500])
        return f"Daily summary: {log.status}"
    except Exception as exc:
        safe_error = f"{exc.__class__.__name__}: {exc}"[:500]
        DailySummaryRun.objects.filter(pk=run.pk).update(
            status='failed', error_message=safe_error)
        logger.exception("[DAILY SUMMARY] Job failed")
        return "Daily summary: failed"


@shared_task
def send_due_reminders():
    """Send any active reminders whose schedule matches the current minute.

    Runs every minute via Celery Beat. Mirrors ``execute_scheduled_feeding``:
    local-time minute match plus 0=Sunday day-of-week filtering. Per-reminder,
    per-minute dedup prevents a double-send within the same minute.
    """
    from .models import SmsLog, SmsReminder, SmsSettings
    from .services import send_sms

    settings_obj = SmsSettings.get_config()
    if not (settings_obj.enabled and settings_obj.reminders_enabled):
        return "Reminders disabled"

    now = timezone.localtime(timezone.now())
    current_time = now.time().replace(second=0, microsecond=0)
    current_day = (now.weekday() + 1) % 7  # 0=Sunday, matching the model

    reminders = SmsReminder.objects.filter(
        is_active=True, schedule_time=current_time)

    sent_count = 0
    for reminder in reminders:
        days = reminder.days_of_week
        if days and current_day not in days:
            continue

        # Dedup: skip if this reminder already sent within the current minute.
        minute_start = now.replace(second=0, microsecond=0)
        already = SmsLog.objects.filter(
            sms_type='reminder', reminder=reminder,
            created_at__gte=minute_start,
        ).exists()
        if already:
            continue

        log = send_sms(
            message=_format_reminder_text(reminder),
            sms_type='reminder',
            reminder=reminder,
        )
        if log is not None:
            sent_count += 1

    return f"Sent {sent_count} reminder(s)"


def _format_alert_text(notification):
    """Build a compact alert SMS body from a Notification (<= ALERT_MAX_CHARS)."""
    prefix = f"[{notification.get_severity_display()}] "
    body = notification.title
    if notification.description:
        body += f" - {notification.description}"
    if notification.source:
        body += f" ({notification.source})"
    text = prefix + body
    if len(text) > ALERT_MAX_CHARS:
        text = text[:ALERT_MAX_CHARS - 1].rstrip() + "…"
    return text


@shared_task
def send_alert_sms(notification_id):
    """Send an SMS for a security Notification, if the rules allow it.

    Re-checks ``SmsSettings.should_send_alert`` at send time (the toggle may have
    changed since the notification was raised) and applies a per-type cooldown
    via the shared DB cache so a burst of the same alert type does not spam SMS.
    """
    from .models import SmsRegistration, SmsSettings
    from .services import send_sms
    from security.models import Notification

    try:
        notification = Notification.objects.get(id=notification_id)
    except Notification.DoesNotExist:
        logger.warning("send_alert_sms: notification %s not found", notification_id)
        return "Notification not found"

    settings_obj = SmsSettings.get_config()
    if not settings_obj.should_send_alert(
            notification.notification_type, notification.severity):
        return "Alert not eligible for SMS"

    # Per-type cooldown, shared across processes via the DB cache.
    cooldown = settings_obj.alert_cooldown_minutes or 0
    # Scope cooldown to the alert type + source. An environmental sensor burst
    # should not suppress an unrelated security alert or another device.
    source_key = (notification.source or 'global').strip().lower()
    cache_key = f"sms_alert_cooldown:{notification.notification_type}:{source_key}"
    if cooldown and cache.get(cache_key):
        logger.info("send_alert_sms: cooldown active for %s",
                    notification.notification_type)
        return "Cooldown active"

    # Administrators may select multiple registered numbers for farm alerts.
    # Keep the original global number as a safe fallback until at least one
    # active managed recipient has been selected.
    recipients = list(
        SmsRegistration.objects.filter(
            receives_farm_alerts=True,
            is_active=True,
            user__is_active=True,
        ).values_list('phone_number', flat=True)
    )
    recipients = list(dict.fromkeys(number for number in recipients if number))

    message = _format_alert_text(notification)
    if recipients:
        logs = [
            send_sms(
                message=message,
                sms_type='alert',
                number=number,
                notification=notification,
            )
            for number in recipients
        ]
    else:
        logs = [send_sms(
            message=message,
            sms_type='alert',
            notification=notification,
        )]

    # Only start the cooldown once at least one message was actually sent.
    sent_count = sum(
        1 for log in logs if log is not None and log.status == 'sent'
    )
    failed_count = sum(
        1 for log in logs if log is not None and log.status == 'failed'
    )
    if cooldown and sent_count:
        cache.set(cache_key, True, timeout=cooldown * 60)

    if len(logs) == 1:
        log = logs[0]
        return f"Alert SMS: {log.status if log else 'skipped'}"
    return f"Alert SMS: {sent_count} sent, {failed_count} failed"


@shared_task
def send_test_sms(number=None):
    """Send a test SMS to verify configuration (Test SMS button).

    Uses ``force=True`` so an operator can confirm credentials/recipient work
    before flipping the master switch on.
    """
    from .services import send_sms

    now = timezone.localtime(timezone.now())
    message = (
        f"GoHMoTech test SMS — configuration OK. Sent {now:%Y-%m-%d %H:%M}."
    )
    log = send_sms(message=message, sms_type='test', number=number, force=True)
    return f"Test SMS: {log.status if log else 'skipped'}"
