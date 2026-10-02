"""
URL configuration for KaMoTech.

Web Pages (MTV Pattern):
    - / : Main dashboard home
    - /detection/ : Live goat detection feed
    - /feeding/ : Feeding system dashboard
    - /analytics/ : Analytics and reports
    - /admin/ : Django admin panel

API Endpoints (Optional for AJAX/Mobile):
    - /api/iot/ : IoT devices and sensors
    - /api/ml/ : ML models and detection
    - /api/feeding/ : Feeding system
    - /api/analytics/ : Analytics and reports
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from allauth.account import views as account_views

handler403 = 'dashboard.views.permission_denied_view'
handler400 = 'dashboard.views.bad_request_view'
handler404 = 'dashboard.views.not_found_view'
handler500 = 'dashboard.views.server_error_view'

urlpatterns = [
    # Admin panel
    path('admin/', admin.site.urls),
    
    # Main web pages (Django templates - MTV pattern)
    path('', include('dashboard.urls')),  # Home dashboard
    path('iot/', include(('iot.urls', 'iot'), namespace='iot')),  # IoT devices
    path('ml/', include('ml_models.urls')),  # ML detection
    path('feeding/', include('feeding.urls')),  # Feeding system
    path('analytics/', include('analytics.urls')),  # Analytics
    path('security/', include('security.urls')),  # Security & notifications
    path('sms/', include(('sms.urls', 'sms'), namespace='sms')),  # SMS notifications
    path('marketplace/', include(('marketplace.urls', 'marketplace'), namespace='marketplace')),
    path('api/mobile/', include(('mobile_api.urls', 'mobile_api'), namespace='mobile_api')),

    # Authentication. Legacy URL names remain available for existing templates,
    # while allauth provides email/password and Google OAuth/OIDC flows.
    path(
        'accounts/login/',
        account_views.LoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path('accounts/logout/', account_views.LogoutView.as_view(), name='logout'),
    path('accounts/', include('allauth.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
