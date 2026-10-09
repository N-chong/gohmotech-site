"""
SMS subsystem models.

Four tables, all additive — nothing here changes or replaces an existing model:

  * SmsSettings — operator-editable singleton of toggles/schedules. Lives in the
    DB (not settings/.env) because the Celery worker/beat process must read the
    current values at run time; a settings/.env value is per-process and only
    read at startup, so a UI change would never reach the worker. This mirrors
    feeding.AutomatedFeedingConfig and the project's cross-process DatabaseCache
    rationale. SECRETS ARE NOT STORED HERE — the Semaphore API key and sender
    name stay in settings/.env and are never exposed to the frontend.

  * SmsReminder — a scheduled recurring reminder. Its scheduling shape mirrors
    feeding.FeedSchedule (TimeField + days_of_week JSON list, 0=Sunday) so it
    reuses the exact every-minute beat-matching logic proven by
    iot.tasks.execute_scheduled_feeding.

  * SmsRegistration — one private mobile-number registration per authenticated
    account. This is separate from the administrator's global recipient so
    owners and marketplace clients can manage their own contact details without
    changing system-wide alert delivery.

  * SmsLog — history of every send attempt. Field names follow
    iot.NotificationLog (recipient / message / status / error_message /
    sent_at) for consistency, adding the sms_type dimension and the raw
    provider (Semaphore) response the requirements call for. A dedicated table
    is used instead of NotificationLog because that model is bound to
    MissingGoatAlert and lacks a Daily/Alert/Reminder type and a provider
    response field.
"""

from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from security.models import Notification


def default_alert_types():
    """Default set of notification types that trigger an SMS alert."""
    return ['missing_goat', 'person_detection', 'device_anomaly']


class SmsSettings(models.Model):
    """Singleton configuration for the SMS notification subsystem."""

    # Alert-type keys reused verbatim from the unified notification inbox so the
    # per-type toggles line up 1:1 with what actually raises a Notification.
    ALERT_TYPE_CHOICES = [
        c for c in Notification.TYPE_CHOICES
        if c[0] in ('missing_goat', 'person_detection', 'device_anomaly')
    ]

    # --- Master switch + recipient ---
    enabled = models.BooleanField(
        default=False, help_text="Master switch for all outgoing SMS")
    recipient_number = models.CharField(
        max_length=20, blank=True,
        help_text="Mobile number that receives SMS (PH format, e.g. 09171234567)")

    # --- Daily summary ---
    daily_enabled = models.BooleanField(default=False)
    daily_time = models.TimeField(
        default=time(7, 0), help_text="Local time to send the daily summary")

    # --- Alerts ---
    alerts_enabled = models.BooleanField(default=True)
    alert_min_severity = models.CharField(
        max_length=20, choices=Notification.SEVERITY_CHOICES, default='high',
        help_text="Only alerts at or above this severity are texted")
    alert_types = models.JSONField(
        default=default_alert_types, blank=True,
        help_text="Notification types that trigger an SMS alert")
    alert_cooldown_minutes = models.PositiveIntegerField(
        default=10,
        help_text="Suppress repeat SMS of the same alert type within this many minutes")

    # --- Reminders ---
    reminders_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "SMS Settings"
        verbose_name_plural = "SMS Settings"

    def __str__(self):
        return f"SMS Settings ({'ENABLED' if self.enabled else 'DISABLED'})"

    @classmethod
    def get_config(cls):
        """Get or create the single settings row (id=1)."""
        config, _ = cls.objects.get_or_create(id=1)
        return config

    def should_send_alert(self, notification_type, severity):
        """True if an alert of this type/severity should be texted."""
        if not (self.enabled and self.alerts_enabled):
            return False
        if notification_type not in (self.alert_types or []):
            return False
        # Severity threshold using the inbox's own weighting.
        weight = Notification.SEVERITY_WEIGHT
        return weight.get(severity, 0) >= weight.get(self.alert_min_severity, 0)


class SmsReminder(models.Model):
    """A scheduled recurring SMS reminder (feeding, cleaning, maintenance...)."""

    REMINDER_TYPE_CHOICES = [
        ('feeding', 'Feeding'),
        ('cleaning', 'Cleaning'),
        ('maintenance', 'Maintenance'),
        ('sensor_check', 'Sensor Checking'),
        ('custom', 'Custom'),
    ]

    # 0=Sunday to match feeding.FeedSchedule.DAYS_OF_WEEK exactly, so the same
    # beat-matching arithmetic ((weekday()+1) % 7) applies unchanged.
    DAYS_OF_WEEK = [
        (0, 'Sunday'), (1, 'Monday'), (2, 'Tuesday'), (3, 'Wednesday'),
        (4, 'Thursday'), (5, 'Friday'), (6, 'Saturday'),
    ]

    title = models.CharField(max_length=120)
    reminder_type = models.CharField(
        max_length=20, choices=REMINDER_TYPE_CHOICES, default='custom')
    message = models.TextField(help_text="SMS text to send at the scheduled time")
    schedule_time = models.TimeField(help_text="Local time to send the reminder")
    days_of_week = models.JSONField(
        default=list,
        help_text="Day numbers to send on (0=Sunday, 6=Saturday); empty = every day")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['schedule_time']
        verbose_name = 'SMS Reminder'
        verbose_name_plural = 'SMS Reminders'

    def __str__(self):
        return f"{self.get_reminder_type_display()} - {self.title} @ {self.schedule_time}"


class SmsRegistration(models.Model):
    """A user's private, self-managed Philippine mobile number."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sms_registration',
    )
    phone_number = models.CharField(
        max_length=20,
        help_text="Philippine mobile number, e.g. 09171234567 or +639171234567",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Allow this number to be used by account-related SMS features.",
    )
    receives_farm_alerts = models.BooleanField(
        default=False,
        help_text=(
            "Administrator-managed permission to receive farm alert SMS. "
            "Account owners cannot enable this themselves."
        ),
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SMS Registration'
        verbose_name_plural = 'SMS Registrations'

    def clean(self):
        super().clean()
        if not self.phone_number:
            return
        from .providers import normalize_ph_number

        try:
            self.phone_number = normalize_ph_number(self.phone_number)
        except ValueError as exc:
            raise ValidationError({'phone_number': str(exc)}) from exc

    def __str__(self):
        status = 'active' if self.is_active else 'paused'
        return f"{self.user.get_username()} — {self.phone_number} ({status})"


class SmsLog(models.Model):
    """History of every SMS the system attempts to send."""

    SMS_TYPE_CHOICES = [
        ('daily', 'Daily Summary'),
        ('alert', 'Alert'),
        ('reminder', 'Reminder'),
        ('test', 'Test'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    sms_type = models.CharField(
        max_length=20, choices=SMS_TYPE_CHOICES, db_index=True)
    recipient = models.CharField(max_length=20)
    message = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # Which backend actually handled it ('console' in dev, 'semaphore' in prod).
    provider = models.CharField(max_length=20, blank=True)
    provider_message_id = models.CharField(max_length=100, blank=True)
    # Raw JSON returned by Semaphore (or the console stub) for auditing.
    api_response = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Optional links back to what triggered the SMS (nullable; SET_NULL keeps
    # history if the source is later deleted).
    notification = models.ForeignKey(
        Notification, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sms_logs')
    reminder = models.ForeignKey(
        SmsReminder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sms_logs')

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'SMS Log'
        verbose_name_plural = 'SMS Logs'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['sms_type', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return (f"[{self.get_sms_type_display()}] to {self.recipient} — "
                f"{self.get_status_display()}")

    def mark_sent(self, provider='', message_id='', api_response=None, save=True):
        self.status = 'sent'
        self.sent_at = timezone.now()
        if provider:
            self.provider = provider
        if message_id:
            self.provider_message_id = message_id
        if api_response is not None:
            self.api_response = api_response
        if save:
            self.save(update_fields=['status', 'sent_at', 'provider',
                                     'provider_message_id', 'api_response'])

    def mark_sending(self, provider='', save=True):
        self.status = 'sending'
        if provider:
            self.provider = provider
        if save:
            self.save(update_fields=['status', 'provider'])

    def mark_failed(self, error='', api_response=None, provider='', save=True):
        self.status = 'failed'
        if error:
            self.error_message = error
        if provider:
            self.provider = provider
        if api_response is not None:
            self.api_response = api_response
        if save:
            self.save(update_fields=['status', 'error_message', 'provider',
                                     'api_response'])


class DailySummaryRun(models.Model):
    """Durable, once-per-local-day audit record for the scheduled digest.

    ``scheduled_date`` is interpreted in Asia/Manila. Its unique constraint is
    the final duplicate barrier when Beat ticks overlap or a worker restarts.
    A run is never retried automatically after reaching a terminal state: an
    ambiguous provider timeout must not result in a duplicate SMS.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]

    scheduled_date = models.DateField(unique=True)
    scheduled_for = models.DateTimeField(db_index=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    recipient = models.CharField(max_length=20, blank=True)
    error_message = models.TextField(blank=True)
    sms_log = models.OneToOneField(
        SmsLog, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='daily_summary_run')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"Daily Summary {self.scheduled_date}: {self.get_status_display()}"
