"""URL configuration for the SMS app."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'reminders', views.SmsReminderViewSet, basename='smsreminder')
router.register(r'logs', views.SmsLogViewSet, basename='smslog')

app_name = 'sms'

urlpatterns = [
    # Self-service mobile registration for authenticated owners and clients.
    path('registration/', views.sms_registration, name='registration'),
    path('alert-recipients/', views.manage_alert_recipients,
         name='alert_recipients'),
    # Tabbed SMS page.
    path('', views.sms_dashboard, name='dashboard'),
    # Singleton settings + operator actions.
    path('api/settings/', views.sms_settings_api, name='settings_api'),
    path('api/test/', views.send_test_sms_api, name='test_api'),
    path('api/balance/', views.sms_balance_api, name='balance_api'),
    path('api/diagnostics/', views.sms_diagnostics_api, name='diagnostics_api'),
    # REST API (reminders + logs).
    path('api/', include(router.urls)),
]
