"""
Views for the SMS app.

  * SmsReminderViewSet  — CRUD for scheduled reminders (staff may modify).
  * SmsLogViewSet       — read-only history of every SMS attempt.
  * sms_settings_api    — GET/POST the singleton settings (staff may POST).
  * send_test_sms_api   — POST: fire a test SMS (staff only).
  * sms_balance_api     — GET: provider credit balance (staff only).
  * sms_dashboard       — the tabbed SMS page (Settings / Reminders / Logs).

Authorization reuses the existing Django auth system. Operational settings,
reminders, logs, and provider actions are staff-only. A separate view lets each
authenticated marketplace user manage only their own SMS registration.
"""

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from marketplace.auth import is_marketplace_user

from .forms import SmsRegistrationForm
from .models import SmsLog, SmsRegistration, SmsReminder, SmsSettings
from .providers import get_client
from .serializers import (SmsLogSerializer, SmsReminderSerializer,
                          SmsSettingsSerializer)


class IsStaffOrReadOnly(IsAuthenticated):
    """SMS operational data and provider actions are staff-only."""

    def has_permission(self, request, view):
        base = super().has_permission(request, view)
        if not base:
            return False
        return bool(request.user and request.user.is_staff)


class SmsReminderViewSet(viewsets.ModelViewSet):
    """CRUD for SMS reminders (feeding, cleaning, maintenance, sensor checks)."""

    queryset = SmsReminder.objects.all()
    serializer_class = SmsReminderSerializer
    permission_classes = [IsStaffOrReadOnly]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'reminder_type': ['exact', 'in'],
        'is_active': ['exact'],
    }
    search_fields = ['title', 'message']
    ordering_fields = ['schedule_time', 'created_at', 'title']
    ordering = ['schedule_time']


class SmsLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only SMS history — the SMS Logs requirement."""

    queryset = SmsLog.objects.select_related('notification', 'reminder').all()
    serializer_class = SmsLogSerializer
    permission_classes = [IsStaffOrReadOnly]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'sms_type': ['exact', 'in'],
        'status': ['exact', 'in'],
        # Only range lookups on created_at: a `__date` lookup casts in the DB's
        # session timezone, which needs MySQL timezone tables that are not loaded
        # on this install (same constraint that shaped the dedup in tasks.py).
        'created_at': ['gte', 'lte'],
    }
    search_fields = ['recipient', 'message', 'error_message']
    ordering_fields = ['created_at', 'sent_at', 'status', 'sms_type']
    ordering = ['-created_at']


def _settings_payload(config):
    """Settings + non-secret backend info for the frontend."""
    data = SmsSettingsSerializer(config).data
    data['backend'] = getattr(django_settings, 'SMS_BACKEND', 'console')
    data['sender_name'] = getattr(django_settings, 'SEMAPHORE_SENDER_NAME', '')
    # Report whether a key is present WITHOUT ever sending the key itself.
    data['api_key_configured'] = bool(
        getattr(django_settings, 'SEMAPHORE_API_KEY', ''))
    return data


@api_view(['GET', 'POST'])
@permission_classes([IsStaffOrReadOnly])
def sms_settings_api(request):
    """GET or update the singleton SMS settings.

    Only whitelisted, non-secret fields are writable; the API key/sender name
    are configured server-side and are never accepted here.
    """
    config = SmsSettings.get_config()

    if request.method == 'GET':
        return Response(_settings_payload(config))

    serializer = SmsSettingsSerializer(config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(updated_by=request.user.get_username())
    return Response(_settings_payload(config))


@api_view(['POST'])
@permission_classes([IsStaffOrReadOnly])
def send_test_sms_api(request):
    """Fire a test SMS to the given number (or the configured recipient)."""
    from .tasks import send_test_sms

    number = (request.data.get('number') or '').strip() or None
    # Run inline so the operator sees the immediate result in the UI; the task
    # is a plain function too, so calling it directly is safe and synchronous.
    result = send_test_sms(number=number)

    log = SmsLog.objects.filter(sms_type='test').order_by('-created_at').first()
    payload = {'result': result}
    if log is not None:
        payload['log'] = SmsLogSerializer(log).data
    return Response(payload)


@api_view(['GET'])
@permission_classes([IsStaffOrReadOnly])
def sms_balance_api(request):
    """Return the provider credit balance (None in console/dev mode)."""
    client = get_client()
    return Response({
        'backend': getattr(django_settings, 'SMS_BACKEND', 'console'),
        'balance': client.get_balance(),
    })


# ---------------------------------------------------------------------------
# Page view (server-rendered)
# ---------------------------------------------------------------------------

@login_required
def sms_dashboard(request):
    """The tabbed SMS page: Settings / Reminders / Logs."""
    config = SmsSettings.get_config()
    context = {
        'active_page': 'sms',
        'config': config,
        'backend': getattr(django_settings, 'SMS_BACKEND', 'console'),
        'api_key_configured': bool(
            getattr(django_settings, 'SEMAPHORE_API_KEY', '')),
        'sender_name': getattr(django_settings, 'SEMAPHORE_SENDER_NAME', ''),
        'severity_choices': SmsSettings._meta.get_field('alert_min_severity').choices,
        'alert_type_choices': SmsSettings.ALERT_TYPE_CHOICES,
        'reminder_type_choices': SmsReminder.REMINDER_TYPE_CHOICES,
        'days_of_week': SmsReminder.DAYS_OF_WEEK,
        'sms_type_choices': SmsLog.SMS_TYPE_CHOICES,
        'status_choices': SmsLog.STATUS_CHOICES,
    }
    return render(request, 'sms/sms_dashboard.html', context)


@login_required
def sms_registration(request):
    """Let an account owner register or pause their own mobile number."""
    try:
        registration = request.user.sms_registration
    except SmsRegistration.DoesNotExist:
        registration = SmsRegistration(user=request.user)

    if request.method == 'POST':
        form = SmsRegistrationForm(request.POST, instance=registration)
        if form.is_valid():
            registration = form.save(commit=False)
            registration.user = request.user
            registration.save()
            messages.success(request, 'Your SMS registration has been saved.')
            return redirect('sms:registration')
    else:
        form = SmsRegistrationForm(instance=registration)

    return render(
        request,
        'sms/sms_registration.html',
        {
            'form': form,
            'registration': registration if registration.pk else None,
            'base_template': (
                'marketplace/buyer_base.html'
                if is_marketplace_user(request.user)
                else 'base_modern.html'
            ),
            'active_page': 'sms_registration',
        },
    )
