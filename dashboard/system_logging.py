"""Small, failure-safe API for writing persistent system audit events."""

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import SystemLog


logger = logging.getLogger(__name__)


def request_ip(request):
    """Return the directly connected client address without trusting spoofable headers."""
    if request is None:
        return None
    value = request.META.get("REMOTE_ADDR") or None
    try:
        if value:
            # Let the model field validate both IPv4 and IPv6.
            SystemLog._meta.get_field("ip_address").clean(value, None)
        return value
    except ValidationError:
        return None


def record_system_log(*, event, message, level=SystemLog.LEVEL_INFO,
                      category=SystemLog.CATEGORY_SYSTEM, source="", actor=None,
                      request=None, status_code=None, metadata=None):
    """Record an event without allowing audit-storage failure to break the caller."""
    try:
        authenticated_actor = (
            actor
            if isinstance(actor, get_user_model()) and getattr(actor, "is_authenticated", False)
            else None
        )
        actor_label = ""
        if authenticated_actor is not None:
            actor_label = authenticated_actor.get_username()
        elif getattr(actor, "is_authenticated", False):
            # Device principals are deliberately not assigned to the User foreign
            # key, but retaining their non-secret identifier helps investigate a
            # failed device request.
            actor_label = str(getattr(actor, "username", "device"))

        return SystemLog.objects.create(
            level=level,
            category=category,
            event=str(event)[:100],
            message=str(message),
            source=str(source)[:150],
            actor=authenticated_actor,
            actor_label=actor_label[:150],
            ip_address=request_ip(request),
            request_method=((getattr(request, "method", "") or "")[:10]),
            path=((getattr(request, "path", "") or "")[:500]),
            status_code=status_code,
            metadata=metadata or {},
        )
    except Exception:
        # Logging must never turn a successful request, login, or logout into a 500.
        logger.exception("Unable to persist system log event %s", event)
        return None
