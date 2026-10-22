"""
Views for the security app.

Provides:
  * NotificationViewSet     — the unified alert/notification inbox API
  * PersonDetectionViewSet  — person/intrusion detection records API
  * security_dashboard      — the tabbed Security page (Overview / Alerts /
                              Person Detection / ML Models)
  * person_detection_detail — single detection page (target of "open event")

Authorization reuses the existing Django auth/permission system (no new auth
mechanism is introduced):
  * All endpoints require an authenticated user.
  * Security events cannot be arbitrarily deleted by normal users — destroy is
    restricted to staff.
"""

from django.db.models import Count, Q
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from marketplace.decorators import farm_owner_required
from marketplace.permissions import IsFarmOwnerOrAdmin
from rest_framework.response import Response

from .models import Notification, PersonDetection
from .serializers import NotificationSerializer, PersonDetectionSerializer
from . import services


class NotificationViewSet(viewsets.ModelViewSet):
    """
    Unified notification inbox.

    Filtering (all optional, combinable):
      ?severity=critical            exact severity
      ?notification_type=person_detection
      ?is_read=false / ?is_resolved=false
      ?created_at__gte=... &created_at__lte=...  (date range)
      ?search=<text>                title/description/source
      ?ordering=-created_at | severity | ...
    """
    queryset = Notification.objects.prefetch_related('sms_logs').all()
    serializer_class = NotificationSerializer
    permission_classes = [IsFarmOwnerOrAdmin]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'severity': ['exact', 'in'],
        'notification_type': ['exact', 'in'],
        'is_read': ['exact'],
        'is_resolved': ['exact'],
        'created_at': ['gte', 'lte', 'date'],
    }
    search_fields = ['title', 'description', 'source']
    ordering_fields = ['created_at', 'severity', 'is_read', 'is_resolved']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    @action(detail=True, methods=['post'])
    def mark_unread(self, request, pk=None):
        notification = self.get_object()
        notification.mark_unread()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        now = timezone.now()
        updated = self.get_queryset().filter(is_read=False).update(
            is_read=True, read_at=now
        )
        return Response({'marked_read': updated})

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        notification = self.get_object()
        notes = request.data.get('resolution_notes', '') or request.data.get('notes', '')
        notification.resolve(user=request.user, notes=notes)
        return Response(self.get_serializer(notification).data)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        notification = self.get_object()
        notification.reopen()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'unread': services.unread_count()})

    @action(detail=False, methods=['get'])
    def unresolved(self, request):
        qs = self.filter_queryset(self.get_queryset().filter(is_resolved=False))
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(self.get_serializer(qs, many=True).data)


class PersonDetectionViewSet(viewsets.ModelViewSet):
    """
    Person / intrusion detection records.

    Creating a detection here (or via the detector pipeline) raises exactly one
    linked Notification through security.services — never a duplicate.
    """
    queryset = PersonDetection.objects.select_related('camera', 'notification').all()
    serializer_class = PersonDetectionSerializer
    permission_classes = [IsFarmOwnerOrAdmin]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'detection_type': ['exact', 'in'],
        'status': ['exact', 'in'],
        'review_state': ['exact'],
        'camera': ['exact'],
        'detected_at': ['gte', 'lte', 'date'],
    }
    search_fields = ['source_label', 'review_notes']
    ordering_fields = ['detected_at', 'confidence', 'status']
    ordering = ['-detected_at']

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        queryset = self.filter_queryset(self.get_queryset())
        response.data["summary"] = queryset.aggregate(
            high_confidence=Count("id", filter=Q(confidence__gte=0.8)),
            reviewed=Count("id", filter=Q(review_state="reviewed")),
            unreviewed=Count("id", filter=Q(review_state="unreviewed")),
        )
        return response

    def perform_create(self, serializer):
        detection = serializer.save()
        # Raise the single associated notification for this detection.
        services.notify_person_detection(detection)

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        detection = self.get_object()
        notes = request.data.get('review_notes', '') or request.data.get('notes', '')
        new_status = request.data.get('status')
        detection.mark_reviewed(user=request.user, notes=notes, status=new_status)
        return Response(self.get_serializer(detection).data)


# ---------------------------------------------------------------------------
# Page views (server-rendered)
# ---------------------------------------------------------------------------

@farm_owner_required
def security_dashboard(request):
    """
    The tabbed Security page: Overview / Alerts / Person Detection / ML Models.

    The Overview tab is deliberately kept simple (summary counts). Heavy data is
    loaded lazily by the tab-specific JS through the REST APIs above.
    """
    from ml_models.models import MLModel

    notifications = Notification.objects.all()
    detections = PersonDetection.objects.all()

    context = {
        'active_page': 'security',
        # Overview summary counts (cheap aggregate queries only).
        'total_notifications': notifications.count(),
        'unread_count': notifications.filter(is_read=False).count(),
        'unresolved_count': notifications.filter(is_resolved=False).count(),
        'critical_unresolved': notifications.filter(
            is_resolved=False, severity='critical'
        ).count(),
        'detections_total': detections.count(),
        'detections_unreviewed': detections.filter(review_state='unreviewed').count(),
        'ml_models_total': MLModel.objects.count(),
        'ml_models_active': MLModel.objects.filter(is_active=True).count(),
        'severity_choices': Notification.SEVERITY_CHOICES,
        'type_choices': Notification.TYPE_CHOICES,
        'detection_type_choices': PersonDetection.DETECTION_TYPE_CHOICES,
    }
    return render(request, 'security/security_dashboard.html', context)


@farm_owner_required
def person_detection_detail(request, pk):
    """Single person-detection page — target of "open related event"."""
    detection = get_object_or_404(
        PersonDetection.objects.select_related('camera', 'notification'), pk=pk
    )
    return render(request, 'security/person_detection_detail.html', {
        'active_page': 'security',
        'detection': detection,
    })
