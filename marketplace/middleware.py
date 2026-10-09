from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect

from .auth import has_farm_access, is_farm_operator

# Keep the slashless form too so CommonMiddleware can issue its normal
# APPEND_SLASH redirect instead of role middleware returning a misleading 403.
SMS_REGISTRATION_PREFIX = "/sms/registration"


class FarmRoleAccessMiddleware:
    """Defence-in-depth route policy for the shared farm modules."""

    FARM_PREFIXES = (
        "/analytics/", "/feeding/", "/iot/", "/ml/", "/security/", "/sms/",
    )
    ADMIN_ONLY_PREFIXES = (
        "/admin/", "/sms/", "/marketplace/manage/",
        "/iot/camera/test/", "/ml/models/",
        "/ml/detection/test/", "/ml/recognition/test/", "/ml/detection/diagnostics/",
    )
    OPERATOR_DENIED_PREFIXES = (
        "/analytics/", "/feeding/", "/security/", "/sms/", "/iot/alerts/",
        "/iot/automation/", "/iot/owner/actuators/", "/iot/owner/schedules/",
        "/iot/devices/", "/iot/cameras/", "/iot/camera/test/",
        "/ml/models/", "/ml/detection/test/", "/ml/recognition/test/",
        "/ml/detection/diagnostics/", "/marketplace/manage/", "/marketplace/seller/",
    )
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _deny(request, detail):
        if "/api/" in request.path or request.headers.get("Accept") == "application/json":
            return JsonResponse({"detail": detail}, status=403)
        raise PermissionDenied(detail)

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)

        # The account-owned number page is intentionally separate from the
        # administrator-only SMS settings, logs, reminders, and provider APIs.
        if request.path.startswith(SMS_REGISTRATION_PREFIX):
            return self.get_response(request)

        if request.path.startswith(self.ADMIN_ONLY_PREFIXES) and not (
            user.is_staff or user.is_superuser
        ):
            return self._deny(request, "This feature is restricted to system administrators.")

        if is_farm_operator(user):
            if request.path.startswith(self.OPERATOR_DENIED_PREFIXES):
                return self._deny(request, "Farm Operators have monitoring-only access.")
            if (
                request.path.startswith(self.FARM_PREFIXES)
                and request.method not in self.SAFE_METHODS
            ):
                return self._deny(request, "Farm Operators cannot modify farm data or control equipment.")

        return self.get_response(request)


class MarketplaceBuyerAccessMiddleware:
    """Keep every marketplace-only account out of client farm operations.

    This is intentionally based on explicit farm access, not on membership in
    the legacy buyer group. Future approved sellers remain blocked unless an
    administrator separately grants them the Farm Operators role.
    """

    RESTRICTED_PREFIXES = (
        "/admin/",
        "/analytics/",
        "/feeding/",
        "/iot/",
        "/ml/",
        "/security/",
        "/sms/",
        "/overview/",
        "/map/",
        "/features/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if request.path.startswith(SMS_REGISTRATION_PREFIX):
            return self.get_response(request)
        restricted = request.path.startswith(self.RESTRICTED_PREFIXES)
        if user.is_authenticated and restricted and not has_farm_access(user):
            if "/api/" in request.path:
                return JsonResponse(
                    {"detail": "This account does not have access to farm operations."},
                    status=403,
                )
            messages.error(
                request,
                "This marketplace account does not have access to farm operations.",
            )
            return redirect("marketplace:list")
        return self.get_response(request)


class MarketplaceProfileCompletionMiddleware:
    """Collect missing names only when a Google account omitted them."""

    ALLOWED_PREFIXES = (
        "/accounts/",
        "/marketplace/profile/complete/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not has_farm_access(user)
            and not request.path.startswith(self.ALLOWED_PREFIXES)
            and user.socialaccount_set.exists()
            and (not user.first_name.strip() or not user.last_name.strip())
        ):
            messages.info(request, "Please complete your name to continue.")
            return redirect("marketplace:complete_profile")
        return self.get_response(request)
