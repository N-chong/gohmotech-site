"""
ASGI config for KaMoTech

Exposes the ASGI callable as a module-level variable named ``application``.

This configuration supports both HTTP and WebSocket protocols:
- HTTP: Standard Django views and API endpoints
- WebSocket: Real-time updates for detections, sensors, and alerts
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import OriginValidator
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django ASGI application early
django_asgi_app = get_asgi_application()

# Import routing after Django is initialized
from config import routing
from config.websocket_access import FarmWebSocketAccess
from mobile_api.websocket import MobileTicketAuthMiddleware

application = ProtocolTypeRouter({
    # HTTP requests handled by Django
    "http": django_asgi_app,
    
    # WebSocket requests handled by Channels
    "websocket": OriginValidator(
        AuthMiddlewareStack(
            MobileTicketAuthMiddleware(
                FarmWebSocketAccess(URLRouter(routing.websocket_urlpatterns))
            )
        ),
        ["*"] if settings.DEBUG else settings.CSRF_TRUSTED_ORIGINS + settings.MOBILE_ALLOWED_ORIGINS,
    ),
})
