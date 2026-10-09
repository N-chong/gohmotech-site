from django.conf import settings
from django.db import models


class OnboardingProgress(models.Model):
    """Account-owned dismissal and resumable first-time walkthrough progress."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="onboarding_progress")
    has_completed_tutorial = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_reason = models.CharField(max_length=10, blank=True,
                                        choices=[("finished", "Finished"), ("skipped", "Skipped")])
    role = models.CharField(max_length=20)
    step = models.PositiveSmallIntegerField(default=0)


class SystemLog(models.Model):
    """Append-only operational and security audit event."""

    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"
    LEVEL_CRITICAL = "critical"
    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_ERROR, "Error"),
        (LEVEL_CRITICAL, "Critical"),
    ]

    CATEGORY_AUTH = "auth"
    CATEGORY_REQUEST = "request"
    CATEGORY_SECURITY = "security"
    CATEGORY_SYSTEM = "system"
    CATEGORY_TASK = "task"
    CATEGORY_DEVICE = "device"
    CATEGORY_DATA = "data"
    CATEGORY_CHOICES = [
        (CATEGORY_AUTH, "Authentication"),
        (CATEGORY_REQUEST, "Request"),
        (CATEGORY_SECURITY, "Security"),
        (CATEGORY_SYSTEM, "System"),
        (CATEGORY_TASK, "Background task"),
        (CATEGORY_DEVICE, "Device"),
        (CATEGORY_DATA, "Data change"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=LEVEL_INFO,
                             db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES,
                                default=CATEGORY_SYSTEM, db_index=True)
    event = models.CharField(max_length=100, db_index=True)
    message = models.TextField()
    source = models.CharField(max_length=150, blank=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_log_entries",
    )
    # Preserve who performed an action after an account is renamed or removed.
    actor_label = models.CharField(max_length=150, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=500, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["category", "-created_at"], name="syslog_category_date_idx"),
            models.Index(fields=["level", "-created_at"], name="syslog_level_date_idx"),
            models.Index(fields=["actor", "-created_at"], name="syslog_actor_date_idx"),
        ]

    def __str__(self):
        return f"[{self.level.upper()}] {self.event}: {self.message[:80]}"
