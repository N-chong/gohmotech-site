"""
Serializers for the security app (notifications + person detections).
"""

from rest_framework import serializers

from .models import Notification, PersonDetection


class NotificationSerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    severity_rank = serializers.IntegerField(read_only=True)
    resolution_time_seconds = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()
    event_url = serializers.SerializerMethodField()
    sms_status = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'description',
            'severity', 'severity_display', 'severity_rank',
            'notification_type', 'type_display', 'source',
            'is_read', 'read_at',
            'is_resolved', 'resolved_at', 'resolved_by', 'resolved_by_name',
            'resolution_notes', 'resolution_time_seconds',
            'metadata', 'created_at', 'updated_at',
            'source_content_type', 'source_object_id', 'event_url', 'sms_status',
        ]
        read_only_fields = [
            'read_at', 'resolved_at', 'resolved_by', 'created_at', 'updated_at',
            'source_content_type', 'source_object_id',
        ]

    def get_resolution_time_seconds(self, obj):
        rt = obj.resolution_time
        return rt.total_seconds() if rt else None

    def get_resolved_by_name(self, obj):
        if obj.resolved_by:
            return obj.resolved_by.get_username()
        return None

    def get_event_url(self, obj):
        """
        Best-effort deep link to the underlying event, so "open related event"
        works from the inbox. Returns None when there is no backing event.
        """
        obj_ = obj.source_object
        if obj_ is None:
            return None
        # Person detections are viewable inside the security section.
        if isinstance(obj_, PersonDetection):
            return f'/security/detections/{obj_.pk}/'
        # Other event types expose their own admin/detail pages elsewhere;
        # we avoid guessing a URL we cannot guarantee exists.
        return None

    def get_sms_status(self, obj):
        logs = list(obj.sms_logs.all())
        if not logs:
            return None
        latest = max(logs, key=lambda log: log.created_at)
        return {
            'status': latest.status,
            'display': latest.get_status_display(),
            'attempted_at': latest.created_at,
            'error': latest.error_message,
        }


class PersonDetectionSerializer(serializers.ModelSerializer):
    detection_type_display = serializers.CharField(
        source='get_detection_type_display', read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(read_only=True)
    snapshot_url = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    notification_id = serializers.IntegerField(source='notification.id', read_only=True)

    class Meta:
        model = PersonDetection
        fields = [
            'id', 'detected_at', 'snapshot', 'snapshot_url',
            'camera', 'source_label', 'source_display',
            'detection_type', 'detection_type_display',
            'confidence', 'bounding_boxes',
            'status', 'status_display', 'review_state',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'review_notes',
            'notification_id', 'metadata', 'created_at',
        ]
        read_only_fields = [
            'reviewed_by', 'reviewed_at', 'created_at', 'notification_id',
        ]

    def get_snapshot_url(self, obj):
        if obj.snapshot:
            request = self.context.get('request')
            url = obj.snapshot.url
            return request.build_absolute_uri(url) if request else url
        return None

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_username()
        return None
