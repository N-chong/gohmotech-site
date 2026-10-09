"""Admin registration for the SMS app."""

from django.contrib import admin

from .models import (DailySummaryRun, SmsLog, SmsRegistration, SmsReminder,
                     SmsSettings)


@admin.register(SmsSettings)
class SmsSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'recipient_number', 'daily_enabled',
                    'alerts_enabled', 'reminders_enabled', 'updated_at')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        # Singleton: only one settings row.
        return not SmsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SmsReminder)
class SmsReminderAdmin(admin.ModelAdmin):
    list_display = ('title', 'reminder_type', 'schedule_time', 'is_active',
                    'created_at')
    list_filter = ('reminder_type', 'is_active')
    search_fields = ('title', 'message')


@admin.register(SmsRegistration)
class SmsRegistrationAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'is_active', 'receives_farm_alerts',
                    'registered_at', 'updated_at')
    list_filter = ('is_active', 'receives_farm_alerts', 'registered_at')
    search_fields = ('user__username', 'user__email', 'phone_number')
    readonly_fields = ('registered_at', 'updated_at')


@admin.register(SmsLog)
class SmsLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'sms_type', 'recipient', 'status', 'provider',
                    'created_at', 'sent_at')
    list_filter = ('sms_type', 'status', 'provider', 'created_at')
    search_fields = ('recipient', 'message', 'error_message')
    readonly_fields = (
        'sms_type', 'recipient', 'message', 'status', 'provider',
        'provider_message_id', 'api_response', 'error_message',
        'notification', 'reminder', 'created_at', 'sent_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        # Logs are written by the system only.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(DailySummaryRun)
class DailySummaryRunAdmin(admin.ModelAdmin):
    list_display = ('scheduled_date', 'scheduled_for', 'executed_at', 'status',
                    'recipient', 'sms_log')
    list_filter = ('status', 'scheduled_date')
    readonly_fields = ('scheduled_date', 'scheduled_for', 'executed_at', 'status',
                       'recipient', 'error_message', 'sms_log', 'created_at',
                       'updated_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
