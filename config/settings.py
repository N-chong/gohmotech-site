"""  
Django settings for KaMoTech project.
Configured for MySQL database.
"""

from pathlib import Path
import os
import logging
from dotenv import load_dotenv
import sys

# PyMySQL as MySQL driver
import pymysql
pymysql.install_as_MySQLdb()
# Patch version check for Django compatibility
pymysql.version_info = (2, 2, 4, "final", 0)

# Development settings may use the project-local .env. Hardened deployment
# modules load their explicit private environment first and set this guard so
# unrelated development credentials cannot leak into the live process.
if os.environ.get('DJANGO_SKIP_PROJECT_DOTENV') != '1':
    load_dotenv()

# Apply Python 3.14 compatibility patch for Django admin
if sys.version_info >= (3, 14):
    try:
        from config.django_py314_patch import patch_django_context
        patch_django_context()
    except Exception as e:
        logging.getLogger(__name__).warning("Python 3.14 patch failed: %s", e)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Accepted marketplace reservations expire automatically when marketplace pages
# are visited. This avoids requiring a scheduler for the capstone deployment.
MARKETPLACE_RESERVATION_HOLD_HOURS = max(
    1, int(os.getenv("MARKETPLACE_RESERVATION_HOLD_HOURS", "72"))
)

# Allow all hosts in development, restrict in production
if DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

CSRF_TRUSTED_ORIGINS = [
    'https://gohmotech.site',
    'https://www.gohmotech.site',
]
# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Authentication and Google OAuth/OpenID Connect
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'django_filters',
    'channels',           # WebSocket support
    'django_celery_results',  # Store Celery task results in database
    'django_celery_beat',     # Celery Beat scheduler using database
    
    # Local apps (KaMoTech)
    'dashboard',      # Main dashboard
    'iot',           # IoT devices & sensors
    'ml_models',     # ML detection models
    'feeding',       # Automated feeding system
    'analytics',     # Analytics & reports
    'security',      # Unified alerts/notifications, person detection
    'sms',           # SMS notifications (Semaphore) — daily, alerts, reminders
    'marketplace',   # Goat listings, inquiries, reservations, pickup, and sales
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'marketplace.middleware.FarmRoleAccessMiddleware',
    'marketplace.middleware.MarketplaceBuyerAccessMiddleware',
    'marketplace.middleware.MarketplaceProfileCompletionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'security.context_processors.notifications',
                'marketplace.context_processors.marketplace_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database - MySQL Configuration
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('MYSQL_DB_NAME', 'goat_monitoring'),
        'USER': os.getenv('MYSQL_DB_USER', 'root'),
        'PASSWORD': os.getenv('MYSQL_DB_PASSWORD', ''),
        'HOST': os.getenv('MYSQL_DB_HOST', 'localhost'),
        'PORT': os.getenv('MYSQL_DB_PORT', '3306'),
        'CONN_MAX_AGE': 60,  # Reuse connections for 60 seconds
        'CONN_HEALTH_CHECKS': True,  # Check connection health before reuse
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Set timezone to Philippines (fixes ESP32 time sync issue)
TIME_ZONE = 'Asia/Manila'

# Use timezone-aware datetimes
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Goat camera captures are submitted as base64 form fields. Keep Django's form
# parser aligned with the authenticated upload limit enforced by nginx.
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Support evidence is deliberately outside MEDIA_ROOT so it cannot be fetched
# through the development media route. Downloads always pass through an
# authenticated, ticket-scoped view.
PRIVATE_SUPPORT_ROOT = BASE_DIR / 'private_support_uploads'

# Authentication Configuration
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Keep username login available for existing farm/admin accounts while all new
# marketplace registrations use email. The built-in User.username remains an
# internal identifier and avoids a high-risk user-model swap.
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_SIGNUP_FORM_CLASS = 'marketplace.forms.MarketplaceSignupForm'
ACCOUNT_SIGNUP_REDIRECT_URL = '/marketplace/goats/'
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_VERIFICATION = os.getenv(
    'ACCOUNT_EMAIL_VERIFICATION',
    'none' if DEBUG else 'mandatory',
)
ACCOUNT_EMAIL_SUBJECT_PREFIX = '[GoHMotech] '
ACCOUNT_LOGOUT_ON_GET = False

# Google verifies the email claim. Matching that verified address to one local
# account avoids duplicates and stores Google's stable subject ID by connecting
# the SocialAccount. OAuth access/refresh tokens are not retained.
GOOGLE_OAUTH_CLIENT_ID = os.getenv('GOOGLE_OAUTH_CLIENT_ID', '').strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_REQUESTS_TIMEOUT = 10
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
        'EMAIL_AUTHENTICATION': True,
    }
}
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS['google']['APPS'] = [
        {
            'client_id': GOOGLE_OAUTH_CLIENT_ID,
            'secret': GOOGLE_OAUTH_CLIENT_SECRET,
            'key': '',
        }
    ]

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}


# CORS Settings
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000'
).split(',')


# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Django Channels Configuration (for WebSockets)
ASGI_APPLICATION = 'config.asgi.application'

# CHANNEL_LAYERS - Temporarily disabled (requires Redis)
# To enable real-time WebSocket features:
# 1. Install and start Redis: https://redis.io/download
# 2. Uncomment the configuration below
# 3. Restart the server

# CHANNEL_LAYERS = {
#     'default': {
#         'BACKEND': 'channels_redis.core.RedisChannelLayer',
#         'CONFIG': {
#             'hosts': [(os.getenv('REDIS_HOST', 'localhost'), int(os.getenv('REDIS_PORT', '6379')))],
#         },
#     },
# }

# In-memory channel layer (for development without Redis)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# Cache Configuration
# DatabaseCache is intentionally used instead of the default per-process
# LocMemCache: the automation master toggle is written by the web process
# (api_toggle_automation -> cache.set('automation_enabled', ...)) and must be
# read by the Celery worker/beat process that runs the schedule. A per-process
# in-memory cache is invisible across that boundary, so disabling automation in
# the UI would silently NOT stop the scheduler. A DB-backed cache is shared by
# all processes. Run `python manage.py createcachetable` once to create the
# backing table. (Celery's CELERY_CACHE_BACKEND='django-cache' also uses this.)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
    },
}

# Celery Configuration (for background tasks)
# Redis broker for Windows - simpler and more reliable than django-db broker
# If Redis is not installed, the django-db broker has compatibility issues on Windows
# Download Redis for Windows: https://github.com/microsoftarchive/redis/releases
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'  # Store results in Django database
CELERY_CACHE_BACKEND = 'django-cache'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Manila'  # Change to your local timezone

# MQTT Configuration (for IoT devices)
MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST', 'localhost')
MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', '1883'))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')

# Interim authentication for legacy ESP32 HTTP endpoints. Leave empty to deny
# every device request; do not reuse a Wi-Fi, database, MQTT, or Django secret.
IOT_DEVICE_API_KEY = os.getenv('IOT_DEVICE_API_KEY', '').strip()

# Weather Configuration (Open-Meteo, free/no API key)
WEATHER_ENABLED = os.getenv('WEATHER_ENABLED', 'True') == 'True'
WEATHER_LATITUDE = float(os.getenv('WEATHER_LATITUDE', '14.5995'))
WEATHER_LONGITUDE = float(os.getenv('WEATHER_LONGITUDE', '120.9842'))
WEATHER_CACHE_TTL_MINUTES = int(os.getenv('WEATHER_CACHE_TTL_MINUTES', '15'))

# ML Model Configuration
ML_MODEL_PATH = os.getenv('ML_MODEL_PATH', 'static/models/goat_detector.h5')
CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '0.5'))
NMS_IOU_THRESHOLD = float(os.getenv('NMS_IOU_THRESHOLD', '0.45'))
USE_GPU = os.getenv('USE_GPU', 'False') == 'True'

# Person Detection Configuration
# Live person detection runs alongside goat detection on each frame. The cooldown
# coalesces a burst of frames into one PersonDetection row + one alert per camera
# (see security.services.record_person_detection); the threshold gates weak boxes.
PERSON_DETECTION_COOLDOWN_SECONDS = int(os.getenv('PERSON_DETECTION_COOLDOWN_SECONDS', '30'))
PERSON_CONFIDENCE_THRESHOLD = float(os.getenv('PERSON_CONFIDENCE_THRESHOLD', '0.5'))

# Email Configuration
# Configure these settings to enable email notifications
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')  # e.g., smtp.gmail.com
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')  # Your email address
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')  # App password or email password
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', EMAIL_HOST_USER)  # Where to send admin notifications

# For development: Use console backend to print emails instead of sending
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Notification Configuration
NOTIFICATION_ENABLED = {
    'websocket': True,  # Always enabled (uses Django Channels)
    'email': os.getenv('EMAIL_ENABLED', 'False') == 'True',  # Enable if email configured
    'sms': os.getenv('SMS_ENABLED', 'False') == 'True',  # Enable if Twilio configured
}

# SMS Configuration (Optional - requires Twilio account)
TWILIO_ENABLED = os.getenv('TWILIO_ENABLED', 'False') == 'True'
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')  # Your Twilio number
ADMIN_PHONE_NUMBER = os.getenv('ADMIN_PHONE_NUMBER', '')  # Where to send SMS alerts

# ---------------------------------------------------------------------------
# Semaphore SMS Configuration (Philippine SMS gateway — https://semaphore.co)
# ---------------------------------------------------------------------------
# SECURITY: the API key and sender name are read from environment variables
# only. They are NEVER stored in the database and NEVER exposed to the frontend.
#
# SMS_BACKEND selects the provider client used by the `sms` app:
#   'console'   — development/test mode. Logs messages WITHOUT calling Semaphore,
#                 so the whole Daily / Alert / Reminder workflow can be tested
#                 end-to-end without spending credits. This is the default.
#   'semaphore' — live sending through the Semaphore API (set once approved).
SMS_BACKEND = os.getenv('SMS_BACKEND', 'console')
SEMAPHORE_API_KEY = os.getenv('SEMAPHORE_API_KEY', '')
SEMAPHORE_SENDER_NAME = os.getenv('SEMAPHORE_SENDER_NAME', '')
SEMAPHORE_API_URL = os.getenv(
    'SEMAPHORE_API_URL', 'https://api.semaphore.co/api/v4/messages')
SEMAPHORE_ACCOUNT_URL = os.getenv(
    'SEMAPHORE_ACCOUNT_URL', 'https://api.semaphore.co/api/v4/account')
