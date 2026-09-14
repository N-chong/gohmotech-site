"""Isolated HTTPS beta settings. Start with deploy/beta.env.example."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

_env_file = Path(os.environ.get('BETA_ENV_FILE', '/home/gohmotech/.config/gohmotech/beta.env'))
if _env_file.is_file():
    load_dotenv(_env_file, override=True)

from .settings import *  # noqa: E402,F403


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(f'{name} must be configured for the public beta.')
    return value


DEBUG = False
SECRET_KEY = required('BETA_SECRET_KEY')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('BETA_SECRET_KEY must be a strong, independently generated secret.')
ALLOWED_HOSTS = [host.strip() for host in required('BETA_ALLOWED_HOSTS').split(',')]
if any(not host or '*' in host or '/' in host or ':' in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured('BETA_ALLOWED_HOSTS must contain explicit hostnames.')
CSRF_TRUSTED_ORIGINS = [f'https://{host}' for host in ALLOWED_HOSTS]
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
SECURE_SSL_REDIRECT = True
# Daphne binds only to loopback behind the supplied nginx configuration, which
# overwrites this header. Do not expose Daphne directly to untrusted clients.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_NAME = 'gohmotech_beta_session'
CSRF_COOKIE_NAME = 'gohmotech_beta_csrf'
# Reset links are bearer credentials; keep their public-beta lifetime short.
PASSWORD_RESET_TIMEOUT = 3600
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Deliberately avoid imposing HTTPS on unknown subdomains or enrolling this
# initial beta in browser preload lists. Revisit after domain ownership review.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.mysql',
    'NAME': required('BETA_DB_NAME'),
    'USER': required('BETA_DB_USER'),
    'PASSWORD': required('BETA_DB_PASSWORD'),
    'HOST': os.environ.get('BETA_DB_HOST', '127.0.0.1'),
    'PORT': os.environ.get('BETA_DB_PORT', '3306'),
    'CONN_MAX_AGE': 0,
    'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
}}
_data_root = Path(required('BETA_DATA_ROOT')).resolve()
MEDIA_ROOT = _data_root / 'media'
STATIC_ROOT = _data_root / 'static'
PRIVATE_SUPPORT_ROOT = _data_root / 'private_support'
PROTECTED_MODELS_ROOT = _data_root / 'protected_models'
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
ROOT_URLCONF = 'config.beta_urls'

_redis = os.environ.get('BETA_REDIS_URL', 'redis://127.0.0.1:6379/2')
CHANNEL_LAYERS = {'default': {
    'BACKEND': 'channels_redis.core.RedisChannelLayer',
    'CONFIG': {'hosts': [_redis], 'prefix': 'gohmotech-beta'},
}}
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
    'LOCATION': _redis,
    'KEY_PREFIX': 'gohmotech-beta',
}}
CELERY_BROKER_URL = os.environ.get('BETA_CELERY_BROKER_URL', 'redis://127.0.0.1:6379/3')
IOT_DEVICE_API_KEY = os.environ.get('BETA_IOT_DEVICE_API_KEY', '').strip()
# This web beta does not run workers or Beat. Existing hardware schedulers must
# be repaired and bench-tested before introducing a beta worker service.
SMS_BACKEND = 'console'
TWILIO_ENABLED = False
NOTIFICATION_ENABLED = {'websocket': True, 'email': False, 'sms': False}
# Public signup needs verified email. Never inherit development's "none".
ACCOUNT_EMAIL_VERIFICATION = os.environ.get('BETA_EMAIL_VERIFICATION', 'mandatory').strip().lower()
if ACCOUNT_EMAIL_VERIFICATION not in {'mandatory', 'optional', 'none'}:
    raise ImproperlyConfigured('BETA_EMAIL_VERIFICATION must be mandatory, optional, or none.')
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('BETA_EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('BETA_EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('BETA_EMAIL_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('BETA_EMAIL_PASSWORD', '')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get('BETA_FROM_EMAIL', EMAIL_HOST_USER)
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('BETA_GOOGLE_CLIENT_ID', '')
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('BETA_GOOGLE_CLIENT_SECRET', '')
SOCIALACCOUNT_PROVIDERS = {'google': {
    'SCOPE': ['profile', 'email'],
    'AUTH_PARAMS': {'access_type': 'online'},
    'OAUTH_PKCE_ENABLED': True,
    'EMAIL_AUTHENTICATION': True,
}}
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS['google']['APPS'] = [{
        'client_id': GOOGLE_OAUTH_CLIENT_ID, 'secret': GOOGLE_OAUTH_CLIENT_SECRET, 'key': '',
    }]

MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(
    MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware') + 1,
    'config.beta_access.PublicBetaAccessMiddleware',
)
