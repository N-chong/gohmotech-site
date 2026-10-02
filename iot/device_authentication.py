"""Authentication boundary for legacy ESP32 HTTP endpoints.

The public beta keeps physical writes disabled. This shared key is an interim
compatibility control for existing firmware; new device protocols should use a
separate provisioned and revocable credential per device, like BLE receivers.
"""

import secrets
import logging
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from rest_framework.permissions import BasePermission


logger = logging.getLogger(__name__)


def _presented_key(request):
    return request.headers.get("X-GoHMotech-Device-Key", "").strip()


def valid_device_key(request):
    expected = getattr(settings, "IOT_DEVICE_API_KEY", "").strip()
    presented = _presented_key(request)
    if not expected:
        logger.error("Device authentication is unavailable: server key is not configured")
        return False
    if not presented:
        logger.warning(
            "Device authentication rejected: key header missing on %s",
            request.path,
        )
        return False
    if not secrets.compare_digest(expected, presented):
        logger.warning(
            "Device authentication rejected: key mismatch on %s "
            "(received length %s, expected length %s)",
            request.path,
            len(presented),
            len(expected),
        )
        return False
    return True


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
