from django.contrib import admin
from django import forms
from .models import (
    Device, SensorData, Alert, SensorReading,
    Goat, GoatWeightMeasurement, GoatImage, GoatBehaviorLog, GrassHealthLog,
    ActuatorState, AutomationRule, ActuationLog,
    BLEBeacon, BLEReceiver, BLETrackingState, BLEObservation,
    BLETrackingSettings,
)
from .goat_models import IPCamera, GoatDetectionHistory, MissingGoatAlert, NotificationLog


class IPCameraAdminForm(forms.ModelForm):
    """Do not render stored camera credentials or credential-bearing URLs."""

    username = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={'autocomplete': 'new-password'},
        ),
        help_text='Leave blank to keep the stored camera username.',
    )
    password = forms.CharField(
        required=False,
        max_length=100,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={'autocomplete': 'new-password'},
        ),
        help_text='Leave blank to keep the stored camera password.',
    )
    rtsp_url = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the stored RTSP URL.',
    )
    http_url = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the stored HTTP stream URL.',
    )
    snapshot_url = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the stored snapshot URL.',
    )

    class Meta:
        model = IPCamera
        fields = '__all__'

    def _preserved_value(self, field_name):
        value = self.cleaned_data.get(field_name)
        if value or not self.instance.pk:
            return value
        return getattr(self.instance, field_name)

    def clean_username(self):
        return self._preserved_value('username')

    def clean_password(self):
        return self._preserved_value('password')

    def clean_rtsp_url(self):
        return self._preserved_value('rtsp_url')

    def clean_http_url(self):
        return self._preserved_value('http_url')

    def clean_snapshot_url(self):
        return self._preserved_value('snapshot_url')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'name', 'device_type', 'location', 'is_active', 'created_at']
    list_filter = ['is_active', 'device_type', 'created_at']
    search_fields = ['device_id', 'name', 'device_type']


@admin.register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ['device', 'sensor_type', 'value', 'unit', 'timestamp']
    list_filter = ['sensor_type', 'timestamp']
    search_fields = ['device__name', 'sensor_type']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['device', 'severity', 'message', 'is_resolved', 'created_at']
    list_filter = ['severity', 'is_resolved', 'created_at']
    search_fields = ['device__name', 'message']
    # date_hierarchy = 'created_at'  # Commented out - requires MySQL timezone tables on Windows


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ['device', 'temperature', 'humidity', 'light_level_percentage',
                    'air_quality_raw', 'air_quality_ppm', 'air_quality_calibrated', 'timestamp']
    list_filter = ['device', 'timestamp']
    search_fields = ['device__name']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows


class GoatImageInline(admin.TabularInline):
    model = GoatImage
    extra = 1
    fields = ['image', 'angle', 'image_type', 'captured_at', 'is_primary', 'description', 'is_training_data']


@admin.register(Goat)
class GoatAdmin(admin.ModelAdmin):
    list_display = ['goat_id', 'name', 'breed', 'gender', 'owner', 'status', 'age_display', 'last_seen', 'is_active']
    list_filter = ['breed', 'gender', 'status', 'health_status', 'is_active', 'date_added']
    search_fields = ['goat_id', 'name', 'tag_number']
    # date_hierarchy = 'date_added'  # Commented out - requires MySQL timezone tables on Windows
    inlines = [GoatImageInline]
    
    fieldsets = (
        ('Identification', {
            'fields': ('goat_id', 'name', 'tag_number')
        }),
        ('Physical Characteristics', {
            'fields': ('breed', 'gender', 'date_of_birth', 'weight_kg', 'color_markings')
        }),
        ('Health & Status', {
            'fields': ('health_status', 'health_notes', 'status', 'is_active')
        }),
        ('Vaccination Information', {
            'fields': ('vaccination_status', 'vaccine_name', 'vaccination_date', 'next_due_date'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('AI/ML Re-Identification', {
            'fields': ('last_seen', 'feature_embedding', 'embedding_last_updated'),
            'classes': ('collapse',),
            'description': 'AI monitoring and re-identification tracking (not registration)'
        }),
    )
    readonly_fields = ['embedding_last_updated']

    def save_model(self, request, obj, form, change):
        if not obj.owner_id:
            obj.owner = request.user
        obj.record_source = Goat.SMART_FARM
        super().save_model(request, obj, form, change)


@admin.register(GoatWeightMeasurement)
class GoatWeightMeasurementAdmin(admin.ModelAdmin):
    list_display = ['goat', 'weight_kg', 'source', 'measured_at', 'recorded_by', 'device_id']
    list_filter = ['source', 'measured_at']
    search_fields = ['goat__goat_id', 'goat__name', 'device_id']
    readonly_fields = ['request_id', 'recorded_at']


@admin.register(GoatImage)
class GoatImageAdmin(admin.ModelAdmin):
    list_display = ['goat', 'angle', 'image_type', 'is_primary', 'captured_at', 'uploaded_at', 'is_training_data', 'is_processed', 'embedding_extracted']
    list_filter = ['angle', 'is_primary', 'image_type', 'is_training_data', 'is_processed', 'embedding_extracted', 'uploaded_at']
    search_fields = ['goat__goat_id', 'goat__name']
    # date_hierarchy = 'uploaded_at'  # Commented out - requires MySQL timezone tables on Windows


@admin.register(GoatBehaviorLog)
class GoatBehaviorLogAdmin(admin.ModelAdmin):
    list_display = ['goat', 'behavior_type', 'confidence_score', 'detected_by', 'timestamp']
    list_filter = ['behavior_type', 'timestamp', 'detected_by']
    search_fields = ['goat__goat_id', 'goat__name', 'detected_by']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows


@admin.register(GrassHealthLog)
class GrassHealthLogAdmin(admin.ModelAdmin):
    list_display = ['location', 'health_status', 'greenness_index', 'soil_moisture_percent', 'timestamp']
    list_filter = ['health_status', 'location', 'timestamp']
    search_fields = ['location', 'analyzed_by']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows


@admin.register(ActuatorState)
class ActuatorStateAdmin(admin.ModelAdmin):
    list_display = ['device', 'actuator_type', 'current_state', 'mode', 'last_changed_at', 'last_triggered_by']
    list_filter = ['actuator_type', 'current_state', 'mode', 'last_changed_at']
    search_fields = ['device__name', 'last_triggered_by']
    readonly_fields = ['last_changed_at']


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'actuator', 'rule_type', 'action', 'is_active', 'priority', 'updated_at']
    list_filter = ['rule_type', 'action', 'is_active', 'created_at']
    search_fields = ['name', 'actuator__name']
    # date_hierarchy = 'created_at'  # Commented out - requires MySQL timezone tables on Windows
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'actuator', 'is_active', 'priority')
        }),
        ('Rule Configuration', {
            'fields': ('rule_type', 'action', 'criteria')
        }),
    )


@admin.register(ActuationLog)
class ActuationLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'action', 'source', 'triggered_by', 'result', 'timestamp']
    list_filter = ['action', 'source', 'result', 'timestamp']
    search_fields = ['device__name', 'triggered_by']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows
    readonly_fields = ['timestamp']


@admin.register(IPCamera)
class IPCameraAdmin(admin.ModelAdmin):
    form = IPCameraAdminForm
    list_display = ['camera_id', 'name', 'camera_type', 'ip_address', 'mac_address', 'location', 'status', 'is_active', 'last_connected']
    list_filter = ['camera_type', 'status', 'is_active', 'enable_goat_detection', 'created_at']
    search_fields = ['camera_id', 'name', 'mac_address', 'ip_address', 'location']
    # date_hierarchy = 'created_at'  # Commented out - requires MySQL timezone tables on Windows
    readonly_fields = ['last_connected', 'created_at', 'updated_at']
    actions = ['refresh_ip_addresses']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('camera_id', 'name', 'camera_type', 'location', 'description')
        }),
        ('Network Configuration', {
            'fields': ('ip_address', 'port', 'username', 'password'),
            'description': 'IP address, port, and authentication credentials'
        }),
        ('Advanced: MAC Address (Optional)', {
            'fields': ('mac_address',),
            'classes': ('collapse',),
            'description': 'Optional: Add MAC address for auto IP discovery when camera IP changes via DHCP'
        }),
        ('Stream URLs', {
            'fields': ('rtsp_url', 'http_url', 'snapshot_url'),
            'description': 'Leave blank to use auto-generated URLs based on IP and credentials'
        }),
        ('Status', {
            'fields': ('is_active', 'status', 'last_connected', 'last_error')
        }),
        ('Detection Settings', {
            'fields': ('enable_goat_detection', 'detection_interval_seconds')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def refresh_ip_addresses(self, request, queryset):
        """Admin action to refresh IP addresses from MAC for selected cameras"""
        updated = 0
        failed = 0
        for camera in queryset:
            if camera.mac_address and camera.update_ip_from_mac():
                updated += 1
            elif not camera.mac_address:
                failed += 1
        
        if updated > 0:
            self.message_user(request, f'Successfully updated {updated} camera(s) IP address.')
        if failed > 0:
            self.message_user(request, f'{failed} camera(s) have no MAC address - add MAC to enable auto IP discovery.', level='warning')
    
    refresh_ip_addresses.short_description = "Refresh IP addresses from MAC (requires MAC address)"


@admin.register(GoatDetectionHistory)
class GoatDetectionHistoryAdmin(admin.ModelAdmin):
    list_display = ['goat', 'camera', 'detection_confidence', 'identification_confidence', 'is_new_goat', 'timestamp']
    list_filter = ['is_new_goat', 'camera', 'timestamp']
    search_fields = ['goat__goat_id', 'goat__name', 'camera__name']
    # date_hierarchy = 'timestamp'  # Commented out - requires MySQL timezone tables on Windows
    readonly_fields = ['timestamp']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('goat', 'camera', 'timestamp')
        }),
        ('Detection Details', {
            'fields': ('bounding_box', 'detection_confidence', 'crop_image')
        }),
        ('Re-Identification', {
            'fields': ('identification_confidence', 'similarity_score', 'feature_embedding', 'is_new_goat')
        }),
    )


@admin.register(MissingGoatAlert)
class MissingGoatAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'alert_type', 'severity', 'expected_count', 'detected_count', 'missing_count', 'is_resolved', 'triggered_at']
    list_filter = ['alert_type', 'severity', 'is_resolved', 'notification_sent', 'triggered_at']
    search_fields = ['title', 'message', 'resolved_by']
    # date_hierarchy = 'triggered_at'  # Commented out - requires MySQL timezone tables on Windows
    readonly_fields = ['triggered_at', 'resolved_at', 'notification_sent_at']
    filter_horizontal = ['missing_goats']
    
    fieldsets = (
        ('Alert Information', {
            'fields': ('alert_type', 'severity', 'title', 'message')
        }),
        ('Count Details', {
            'fields': ('expected_count', 'detected_count', 'missing_count', 'camera')
        }),
        ('Missing Goats', {
            'fields': ('missing_goats',)
        }),
        ('Status', {
            'fields': ('is_resolved', 'resolved_at', 'resolved_by', 'resolution_notes')
        }),
        ('Notification', {
            'fields': ('notification_sent', 'notification_sent_at')
        }),
        ('Automation', {
            'fields': ('automation_action_taken', 'metadata'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('triggered_at',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_resolved']
    
    def mark_as_resolved(self, request, queryset):
        """Mark selected alerts as resolved"""
        count = 0
        for alert in queryset:
            if not alert.is_resolved:
                alert.resolve(resolved_by=request.user.username, notes='Resolved via admin action')
                count += 1
        
        self.message_user(request, f'Marked {count} alert(s) as resolved.')
    
    mark_as_resolved.short_description = "Mark selected alerts as resolved"


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ['title', 'notification_type', 'channel', 'status', 'recipient', 'created_at', 'sent_at']
    list_filter = ['notification_type', 'channel', 'status', 'created_at']
    search_fields = ['title', 'message', 'recipient']
    # date_hierarchy = 'created_at'  # Commented out - requires MySQL timezone tables on Windows
    readonly_fields = ['created_at', 'sent_at']
    
    fieldsets = (
        ('Notification Details', {
            'fields': ('notification_type', 'channel', 'status', 'title', 'message')
        }),
        ('Recipient', {
            'fields': ('recipient',)
        }),
        ('Related Alert', {
            'fields': ('alert',)
        }),
        ('Delivery Status', {
            'fields': ('sent_at', 'error_message', 'retry_count')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(BLEBeacon)
class BLEBeaconAdmin(admin.ModelAdmin):
    list_display = [
        'device_name', 'goat', 'mac_address', 'uuid', 'major', 'minor',
        'enabled', 'battery_level', 'updated_at'
    ]
    list_filter = ['enabled', 'major', 'created_at']
    search_fields = [
        'device_name', 'mac_address', 'uuid', 'goat__goat_id', 'goat__name'
    ]
    readonly_fields = ['created_at', 'updated_at', 'battery_updated_at']


@admin.register(BLEReceiver)
class BLEReceiverAdmin(admin.ModelAdmin):
    list_display = [
        'device', 'platform', 'device_name', 'status', 'last_online',
        'scanner_version'
    ]
    list_filter = ['platform', 'status', 'created_at']
    search_fields = ['device__device_id', 'device__name', 'device_name']
    readonly_fields = ['api_key_hash', 'created_at', 'updated_at']


@admin.register(BLETrackingState)
class BLETrackingStateAdmin(admin.ModelAdmin):
    list_display = [
        'beacon', 'receiver', 'current_rssi', 'smoothed_rssi', 'proximity',
        'status', 'last_seen', 'sample_count'
    ]
    list_filter = ['status', 'proximity', 'receiver']
    search_fields = [
        'beacon__device_name', 'beacon__mac_address',
        'beacon__goat__goat_id', 'receiver__device__name'
    ]
    readonly_fields = ['created_at', 'updated_at']


@admin.register(BLEObservation)
class BLEObservationAdmin(admin.ModelAdmin):
    list_display = [
        'beacon', 'goat', 'receiver', 'rssi', 'smoothed_rssi',
        'proximity', 'detected_at'
    ]
    list_filter = ['proximity', 'receiver', 'detected_at']
    search_fields = [
        'beacon__device_name', 'beacon__mac_address',
        'goat__goat_id', 'receiver__device__name'
    ]
    readonly_fields = [
        'beacon', 'goat', 'receiver', 'rssi', 'smoothed_rssi',
        'proximity', 'detected_at'
    ]

    def has_add_permission(self, request):
        return False


@admin.register(BLETrackingSettings)
class BLETrackingSettingsAdmin(admin.ModelAdmin):
    readonly_fields = ['updated_at']

    def has_add_permission(self, request):
        return not BLETrackingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
