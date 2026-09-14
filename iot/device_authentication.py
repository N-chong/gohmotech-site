"""Authentication boundary for legacy ESP32 HTTP endpoints.

The public beta keeps physical writes disabled. This shared key is an interim
compatibility control for existing firmware; new device protocols should use a
separate provisioned and revocable credential per device, like BLE receivers.
"""

import secrets
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from rest_framework.permissions import BasePermission


def _presented_key(request):
    return request.headers.get("X-GoHMotech-Device-Key", "").strip()


def valid_device_key(request):
    expected = getattr(settings, "IOT_DEVICE_API_KEY", "").strip()
    presented = _presented_key(request)
    return bool(expected and presented and secrets.compare_digest(expected, presented))


class HasLegacyDeviceKey(BasePermission):
    message = "Valid device credentials are required."

    def has_permission(self, request, view):
        return valid_device_key(request)


def device_key_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not valid_device_key(request):
            return JsonResponse({"detail": "Valid device credentials are required."}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapped
