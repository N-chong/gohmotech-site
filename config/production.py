"""HTTPS production settings for the public GoHMoTech deployment."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


_env_file = Path(
    os.environ.get(
        "PRODUCTION_ENV_FILE",
        "/home/gohmotech/.config/gohmotech/production.env",
    )
)
if _env_file.is_file():
    load_dotenv(_env_file, override=True)
os.environ["DJANGO_SKIP_PROJECT_DOTENV"] = "1"

from .settings import *  # noqa: E402,F403


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be configured for production.")
    return value


DEBUG = False
SECRET_KEY = required("PRODUCTION_SECRET_KEY")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("PRODUCTION_SECRET_KEY is not sufficiently strong.")

ALLOWED_HOSTS = [
    host.strip() for host in required("PRODUCTION_ALLOWED_HOSTS").split(",")
]
if any(not host or "*" in host or "/" in host or ":" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Production hosts must be explicit hostnames.")
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
MOBILE_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        "PRODUCTION_MOBILE_ALLOWED_ORIGINS",
        "https://localhost,capacitor://localhost",
    ).split(",") if origin.strip()
]
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS + MOBILE_ALLOWED_ORIGINS

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_NAME = "gohmotech_session"
CSRF_COOKIE_NAME = "gohmotech_csrf"
PASSWORD_RESET_TIMEOUT = 3600
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = ["security.W021"]

DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql",
    "NAME": required("PRODUCTION_DB_NAME"),
    "USER": required("PRODUCTION_DB_USER"),
    "PASSWORD": required("PRODUCTION_DB_PASSWORD"),
    "HOST": os.environ.get("PRODUCTION_DB_HOST", "127.0.0.1"),
    "PORT": os.environ.get("PRODUCTION_DB_PORT", "3306"),
    "CONN_MAX_AGE": 60,
    "CONN_HEALTH_CHECKS": True,
    "OPTIONS": {
        "charset": "utf8mb4",
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    },
}}

_data_root = Path(required("PRODUCTION_DATA_ROOT")).resolve()
MEDIA_ROOT = _data_root / "media"
STATIC_ROOT = _data_root / "static"
PRIVATE_SUPPORT_ROOT = _data_root / "private_support"
PRIVATE_INQUIRY_ROOT = _data_root / "private_inquiries"
PROTECTED_MODELS_ROOT = _data_root / "protected_models"
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
ROOT_URLCONF = "config.production_urls"

_redis = os.environ.get("PRODUCTION_REDIS_URL", "redis://127.0.0.1:6379/2")
CHANNEL_LAYERS = {"default": {
    "BACKEND": "channels_redis.core.RedisChannelLayer",
    "CONFIG": {"hosts": [_redis], "prefix": "gohmotech-production"},
}}
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": _redis,
    "KEY_PREFIX": "gohmotech-production",
}}
CELERY_BROKER_URL = os.environ.get(
    "PRODUCTION_CELERY_BROKER_URL", "redis://127.0.0.1:6379/3"
)

# Device writes remain fail-closed until the hardware receives the matching key.
IOT_DEVICE_API_KEY = os.environ.get("PRODUCTION_IOT_DEVICE_API_KEY", "").strip()

ACCOUNT_EMAIL_VERIFICATION = os.environ.get(
    "PRODUCTION_EMAIL_VERIFICATION", "mandatory"
).strip().lower()
if ACCOUNT_EMAIL_VERIFICATION not in {"mandatory", "optional", "none"}:
    raise ImproperlyConfigured("Invalid production email-verification mode.")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("PRODUCTION_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("PRODUCTION_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("PRODUCTION_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("PRODUCTION_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get("PRODUCTION_FROM_EMAIL", EMAIL_HOST_USER)

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("PRODUCTION_GOOGLE_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("PRODUCTION_GOOGLE_CLIENT_SECRET", "")
SOCIALACCOUNT_PROVIDERS = {"google": {
    "SCOPE": ["profile", "email"],
    "AUTH_PARAMS": {"access_type": "online"},
    "OAUTH_PKCE_ENABLED": True,
    "EMAIL_AUTHENTICATION": True,
}}
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS["google"]["APPS"] = [{
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "key": "",
    }]

# Do not silently spend SMS credits. Live sending needs provider credentials and
# an explicit production backend choice; the DB master switch is an extra gate.
SMS_BACKEND = os.environ.get("PRODUCTION_SMS_BACKEND", "console").strip().lower()
if SMS_BACKEND not in {"console", "semaphore"}:
    raise ImproperlyConfigured("PRODUCTION_SMS_BACKEND must be console or semaphore.")
NOTIFICATION_ENABLED = {
    "websocket": True,
    "email": os.environ.get("PRODUCTION_EMAIL_ENABLED", "False") == "True",
    "sms": SMS_BACKEND == "semaphore",
}
