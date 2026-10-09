"""
Serializers for the SMS app (settings, reminders, logs).

The settings serializer deliberately exposes ONLY operator-editable toggles and
the recipient number. Provider credentials (API key, sender name) live in
settings/.env and are never part of any serializer, so they can never be read or
written through the API / frontend.
"""

from rest_framework import serializers

from .models import SmsLog, SmsReminder, SmsSettings


class SmsSettingsSerializer(serializers.ModelSerializer):
    alert_type_choices = serializers.SerializerMethodField()
    severity_choices = serializers.SerializerMethodField()

    class Meta:
        model = SmsSettings
        fields = [
            'enabled', 'recipient_number',
            'daily_enabled', 'daily_time',
            'alerts_enabled', 'alert_min_severity', 'alert_types',
            'alert_cooldown_minutes',
            'reminders_enabled',
            'updated_at', 'updated_by',
            'alert_type_choices', 'severity_choices',
        ]
        read_only_fields = ['updated_at', 'updated_by']

    def get_alert_type_choices(self, obj):
        return [{'value': v, 'label': l} for v, l in obj.ALERT_TYPE_CHOICES]

    def get_severity_choices(self, obj):
        from security.models import Notification
        return [{'value': v, 'label': l} for v, l in Notification.SEVERITY_CHOICES]

    def validate_recipient_number(self, value):
        from .providers import normalize_ph_number
        if not value:
            return ''
        try:
            return normalize_ph_number(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        enabled = attrs.get('enabled', getattr(self.instance, 'enabled', False))
        recipient = attrs.get(
            'recipient_number', getattr(self.instance, 'recipient_number', ''))
        if enabled and not recipient:
            raise serializers.ValidationError({
                'recipient_number': 'A recipient is required when SMS is enabled.'
            })
        return attrs


class SmsReminderSerializer(serializers.ModelSerializer):
    reminder_type_display = serializers.CharField(
        source='get_reminder_type_display', read_only=True)

    class Meta:
        model = SmsReminder
        fields = [
            'id', 'title', 'reminder_type', 'reminder_type_display',
            'message', 'schedule_time', 'days_of_week', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class SmsLogSerializer(serializers.ModelSerializer):
    sms_type_display = serializers.CharField(
        source='get_sms_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = SmsLog
        fields = [
            'id', 'sms_type', 'sms_type_display', 'recipient', 'message',
            'status', 'status_display', 'provider', 'provider_message_id',
            'api_response', 'error_message',
            'notification', 'reminder', 'created_at', 'sent_at',
        ]
        read_only_fields = fields  # logs are history — never edited via the API
