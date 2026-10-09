from django.db import models
from django.utils import timezone
from django.core.validators import MaxValueValidator, MinValueValidator


class Device(models.Model):
    """IoT Device Model"""
    device_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    device_type = models.CharField(max_length=100)
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_sensor_received_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Backend receipt time of the latest environmental reading.",
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.device_id})"


class SensorData(models.Model):
    """Sensor Data Model for IoT readings"""
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='sensor_data')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    sensor_type = models.CharField(max_length=100)
    value = models.FloatField()
    unit = models.CharField(max_length=50)
    metadata = models.JSONField(null=True, blank=True)
    aggregation_completed_at = models.DateTimeField(
        null=True, blank=True, db_index=True, editable=False,
        help_text="Set only after this raw row's 30-minute period was processed.",
    )
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['sensor_type', '-timestamp']),
            models.Index(fields=['aggregation_completed_at', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.device.name} - {self.sensor_type}: {self.value} {self.unit}"


class Alert(models.Model):
    """Alert Model for IoT anomalies"""
    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='alerts')
    sensor_data = models.ForeignKey(SensorData, on_delete=models.SET_NULL, null=True, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    message = models.TextField()
    alert_kind = models.CharField(
        max_length=40, blank=True, db_index=True,
        help_text="Stable machine-readable category such as sensor_stale or temperature_high")
    deduplication_key = models.CharField(
        max_length=255, blank=True, db_index=True,
        help_text="Key used to keep one unresolved alert per ongoing condition")
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.severity.upper()} - {self.device.name}: {self.message[:50]}"


class EnvironmentalAlertSettings(models.Model):
    """Singleton policy for real sensor alerts.

    Scientific limits are deliberately nullable: an unset threshold produces
    no threshold alert. Staleness uses the firmware's documented 30-second send
    interval. To avoid false SMS alerts during brief Wi-Fi interruptions, a
    device is considered stale only after at least 30 minutes without data.
    """

    enabled = models.BooleanField(default=True)
    temperature_min_c = models.FloatField(null=True, blank=True)
    temperature_max_c = models.FloatField(null=True, blank=True)
    humidity_min_percent = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    humidity_max_percent = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    stale_detection_enabled = models.BooleanField(default=True)
    stale_after_seconds = models.PositiveIntegerField(
        default=1800,
        help_text="Minimum 1800 seconds (30 minutes) without data before a stale alert.")
    threshold_severity = models.CharField(
        max_length=20, choices=Alert.SEVERITY_CHOICES, default='high')
    stale_severity = models.CharField(
        max_length=20, choices=Alert.SEVERITY_CHOICES, default='high')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Environmental Alert Settings'
        verbose_name_plural = 'Environmental Alert Settings'

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if (self.temperature_min_c is not None and self.temperature_max_c is not None
                and self.temperature_min_c >= self.temperature_max_c):
            errors['temperature_max_c'] = 'Maximum must be greater than minimum.'
        if (self.humidity_min_percent is not None and self.humidity_max_percent is not None
                and self.humidity_min_percent >= self.humidity_max_percent):
            errors['humidity_max_percent'] = 'Maximum must be greater than minimum.'
        if self.stale_after_seconds < 1800:
            errors['stale_after_seconds'] = 'Must be at least 1800 seconds (30 minutes).'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return 'Environmental alert policy'


class SensorReading(models.Model):
    """Temporary raw environmental readings received from ESP32 devices.

    ``timestamp`` is when the device measured the values.  Older firmware does
    not provide it, in which case it safely falls back to the backend clock.
    ``received_at`` is always assigned by Django and records API arrival.  Both
    are timezone-aware instants and are stored as UTC when ``USE_TZ`` is on.
    """
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='environmental_readings'
    )
    
    # Environmental measurements
    temperature = models.FloatField(
        null=True,
        blank=True,
        help_text="Temperature in Celsius"
    )
    humidity = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Humidity percentage (0-100)"
    )
    soil_moisture = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Soil moisture percentage (0-100)"
    )
    light_intensity = models.FloatField(
        null=True,
        blank=True,
        help_text="Light intensity (lux or arbitrary units)"
    )
    light_raw = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(4095)],
        help_text="Raw ESP32 ADC reading from the indoor light sensor (0-4095)"
    )
    light_level_percentage = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Calibrated indoor light level percentage (0-100)"
    )
    air_quality_raw = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(4095)],
        help_text="Raw ESP32 ADC reading from the MQ-135 sensor (0-4095)"
    )
    air_quality_voltage = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Voltage measured by the ESP32 at the MQ-135 analog input"
    )
    air_quality_ppm = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Estimated MQ-135 gas concentration after device calibration"
    )
    air_quality_calibrated = models.BooleanField(
        default=False,
        help_text="Whether air_quality_ppm was produced using a calibrated MQ-135 R0 value"
    )
    rain_detected = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Rain sensor status (True = raining, False = dry)"
    )
    feeder_level = models.FloatField(
        null=True,
        blank=True,
        help_text="Feeder level from ultrasonic sensor (distance in cm)"
    )
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    aggregation_completed_at = models.DateTimeField(
        null=True, blank=True, db_index=True, editable=False,
        help_text="Set only after this raw row's 30-minute period was processed.",
    )
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['aggregation_completed_at', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.device.name} - {self.timestamp}"


class SensorReadingSummary(models.Model):
    """Permanent statistics for one device stream and fixed 30-minute period."""

    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name='sensor_summaries')
    sensor_type = models.CharField(max_length=100)
    unit = models.CharField(max_length=50, blank=True)
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(db_index=True)
    average_value = models.FloatField()
    minimum_value = models.FloatField()
    maximum_value = models.FloatField()
    sample_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_start', 'device_id', 'sensor_type']
        constraints = [
            models.UniqueConstraint(
                fields=['device', 'sensor_type', 'period_start', 'period_end'],
                name='unique_sensor_summary_period',
            ),
        ]
        indexes = [
            models.Index(fields=['device', 'sensor_type', 'period_start']),
            models.Index(fields=['sensor_type', 'period_start']),
        ]

    def __str__(self):
        return f"{self.device.name} {self.sensor_type} {self.period_start}"


class SensorStorageSettings(models.Model):
    """Singleton retention policy and cleanup audit state."""

    raw_retention_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(7), MaxValueValidator(365)],
        help_text="Keep raw readings for 7-365 days. Summaries are retained.",
    )
    cleanup_enabled = models.BooleanField(
        default=False,
        help_text="Enable only after historical summaries have been verified.",
    )
    last_cleanup_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_cleanup_deleted = models.PositiveIntegerField(default=0, editable=False)
    total_cleanup_deleted = models.PositiveBigIntegerField(default=0, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Sensor Storage Settings'
        verbose_name_plural = 'Sensor Storage Settings'

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        state = 'enabled' if self.cleanup_enabled else 'disabled'
        return f"Raw sensor retention: {self.raw_retention_days} days ({state})"


class ActuatorState(models.Model):
    """Current state of actuator devices (door, lights, feeder)"""
    ACTUATOR_TYPES = [
        ('door', 'Automated Door'),
        ('light', 'Automated Light'),
        ('feeder', 'Servo Feeder'),
    ]
    
    STATE_CHOICES = [
        ('on', 'ON'),
        ('off', 'OFF'),
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]
    
    MODE_CHOICES = [
        ('manual', 'Manual Control'),
        ('auto', 'Automatic'),
    ]
    
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='actuator_states'
    )
    actuator_type = models.CharField(max_length=20, choices=ACTUATOR_TYPES)
    current_state = models.CharField(
        max_length=10,
        choices=STATE_CHOICES,
        default='off'
    )
    mode = models.CharField(
        max_length=10,
        choices=MODE_CHOICES,
        default='auto',
        help_text="Manual or Automatic control mode"
    )
    last_changed_at = models.DateTimeField(auto_now=True)
    last_triggered_by = models.CharField(
        max_length=100,
        blank=True,
        help_text="User, rule, or system that triggered last state change"
    )
    
    class Meta:
        verbose_name = "Actuator State"
        verbose_name_plural = "Actuator States"
        # Ensure one actuator type per device
        unique_together = [['device', 'actuator_type']]
    
    def __str__(self):
        return f"{self.device.name} - {self.get_current_state_display()} ({self.mode})"


class AutomationRule(models.Model):
    """Automation rules for door and light control"""
    RULE_TYPES = [
        ('time_based', 'Time-Based (Schedule)'),
        ('sensor_based', 'Sensor-Based (Environmental)'),
        ('detection_based', 'Detection-Based (Goat Count)'),
        ('light_intensity', 'Light Intensity'),
    ]
    
    ACTION_CHOICES = [
        ('open_door', 'Open Door'),
        ('close_door', 'Close Door'),
        ('turn_on_light', 'Turn ON Light'),
        ('turn_off_light', 'Turn OFF Light'),
    ]
    
    name = models.CharField(max_length=200, help_text="Rule name/description")
    actuator = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='automation_rules'
    )
    rule_type = models.CharField(max_length=30, choices=RULE_TYPES)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    
    # Condition criteria stored as JSON
    criteria = models.JSONField(
        default=dict,
        help_text="Conditions for rule trigger (e.g., {'time': '06:00', 'goat_count': '>10', 'temperature': '<25'})"
    )
    
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority rules execute first"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-priority', 'created_at']
        verbose_name = "Automation Rule"
        verbose_name_plural = "Automation Rules"
    
    def __str__(self):
        return f"{self.name} - {self.get_action_display()}"


class ActuationLog(models.Model):
    """Log of all actuator state changes"""
    ACTION_TYPES = [
        ('open', 'Opened'),
        ('close', 'Closed'),
        ('turn_on', 'Turned ON'),
        ('turn_off', 'Turned OFF'),
    ]
    
    SOURCE_TYPES = [
        ('manual', 'Manual Control'),
        ('rule', 'Automation Rule'),
        ('system', 'System'),
        ('api', 'API Call'),
        # Physical button press on the device, or a state sync reported by the
        # ESP32 itself. Distinguished from app-driven 'manual' control.
        ('device', 'Device / Physical'),
    ]
    
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='actuation_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    source = models.CharField(max_length=20, choices=SOURCE_TYPES, default='manual')
    triggered_by = models.CharField(
        max_length=200,
        blank=True,
        help_text="User name, rule name, or system process"
    )
    rule = models.ForeignKey(
        AutomationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execution_logs'
    )
    result = models.CharField(
        max_length=20,
        # 'sent'   = command written for the device to pick up on its next poll
        #            and the device is currently online (recent sensor activity).
        # 'queued' = command written but the device is offline, so it will only
        #            apply once the device comes back and polls again.
        # 'success'/'failed' remain for rule/system paths that can determine an
        # outcome. NOTE: current firmware does not acknowledge execution, so a
        # manual command is honestly 'sent'/'queued', never a fake 'success'.
        choices=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('sent', 'Sent to device'),
            ('queued', 'Queued — device offline'),
        ],
        default='success'
    )
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional context (sensor values, goat count, etc.)"
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['source', '-timestamp']),
        ]
        verbose_name = "Actuation Log"
        verbose_name_plural = "Actuation Logs"
    
    def __str__(self):
        return f"{self.device.name} - {self.get_action_display()} at {self.timestamp}"


# Import goat-related models
from .goat_models import (
    Goat,
    GoatWeightMeasurement,
    GoatImage,
    GoatBehaviorLog,
    GrassHealthLog,
    BLEBeacon,
    BLEReceiver,
    BLETrackingState,
    BLEObservation,
    BLETrackingSettings,
)

__all__ = [
    'Device', 'SensorData', 'Alert', 'EnvironmentalAlertSettings', 'SensorReading',
    'SensorReadingSummary', 'SensorStorageSettings', 'ActuatorState',
    'AutomationRule', 'ActuationLog', 'Goat', 'GoatWeightMeasurement', 'GoatImage',
    'GoatBehaviorLog', 'GrassHealthLog', 'BLEBeacon', 'BLEReceiver',
    'BLETrackingState', 'BLEObservation', 'BLETrackingSettings',
]
