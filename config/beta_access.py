"""Exposure boundaries for the initial public web beta."""

from django.http import JsonResponse
from marketplace.auth import has_farm_access


class PublicBetaAccessMiddleware:
    FARM_PREFIXES = ('/iot/', '/feeding/', '/ml/', '/analytics/', '/security/')
    RECEIVER_PATHS = {'/iot/api/ble/heartbeat/', '/iot/api/ble/observations/'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # URL resolution also accepts slashless requests through CommonMiddleware.
        path = request.path_info.rstrip('/') + '/'
        if path in self.RECEIVER_PATHS:
            # These views enforce their own provisioned receiver credentials.
            return self.get_response(request)
        if path.startswith(self.FARM_PREFIXES):
            if not request.user.is_active or not has_farm_access(request.user):
                return JsonResponse({'detail': 'Farm access is required.'}, status=403)
            if path.startswith(('/iot/', '/feeding/')) and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                return JsonResponse({
                    'detail': 'Farm changes and equipment control are unavailable during the public web beta.'
                }, status=503)
        return self.get_response(request)
