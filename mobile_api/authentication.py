from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF token authentication with a bounded mobile-session lifetime."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        ttl_days = max(1, int(getattr(settings, "MOBILE_TOKEN_TTL_DAYS", 30)))
        if token.created < timezone.now() - timedelta(days=ttl_days):
            token.delete()
            raise AuthenticationFailed("Session expired. Please sign in again.")
        return user, token
