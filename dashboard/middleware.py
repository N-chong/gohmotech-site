"""Request-level audit capture for meaningful mutations and failures."""

from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model

from .models import SystemLog
from .system_logging import record_system_log


class SystemAuditMiddleware(MiddlewareMixin):
    excluded_prefixes = ("/static/", "/media/", "/service-worker.js", "/system-logs/")
    auth_prefixes = ("/accounts/",)

    def _excluded(self, request):
        return request.path.startswith(self.excluded_prefixes)

    def process_exception(self, request, exception):
        if self._excluded(request):
            return None
        request._system_log_exception_recorded = True
        record_system_log(
            event="request.unhandled_exception",
            message=f"{exception.__class__.__name__} while handling {request.method} {request.path}.",
            level=SystemLog.LEVEL_ERROR,
            category=SystemLog.CATEGORY_REQUEST,
            source=getattr(getattr(request, "resolver_match", None), "view_name", "") or "django",
            actor=getattr(request, "user", None),
            request=request,
            status_code=500,
            metadata={"exception_type": exception.__class__.__name__},
        )
        return None

    def process_response(self, request, response):
        if self._excluded(request) or getattr(request, "_system_log_exception_recorded", False):
            return response

        status_code = response.status_code
        is_error = status_code >= 400
        user = getattr(request, "user", None)
        is_user_mutation = (
            request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
            # Hardware API principals are authenticated too, but their frequent
            # heartbeats already have dedicated history and must not flood this
            # human audit trail.
            and isinstance(user, get_user_model())
            and getattr(user, "is_authenticated", False)
            and not request.path.startswith(self.auth_prefixes)
        )
        if not (is_error or is_user_mutation):
            return response

        if status_code >= 500:
            level = SystemLog.LEVEL_ERROR
        elif status_code >= 400:
            level = SystemLog.LEVEL_WARNING
        else:
            level = SystemLog.LEVEL_INFO

        record_system_log(
            event="request.failed" if is_error else "request.mutation",
            message=f"{request.method} {request.path} returned HTTP {status_code}.",
            level=level,
            category=SystemLog.CATEGORY_REQUEST,
            source=getattr(getattr(request, "resolver_match", None), "view_name", "") or "django",
            actor=user,
            request=request,
            status_code=status_code,
        )
        return response
