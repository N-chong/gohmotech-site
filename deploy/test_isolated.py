"""Run beta/regression tests with disposable storage and no live providers."""

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
from django.conf import settings

with tempfile.TemporaryDirectory(prefix='gohmotech-tests-') as directory:
    # Channels resolves roles in a worker thread. A process-local in-memory
    # database is invisible there, so use a disposable file-backed database.
    settings.DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(Path(directory) / 'test.sqlite3'),
        }
    }
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.SMS_BACKEND = 'console'
    settings.WEATHER_ENABLED = False
    settings.MEDIA_ROOT = Path(directory) / 'media'
    settings.PRIVATE_SUPPORT_ROOT = Path(directory) / 'support'
    settings.PROTECTED_MODELS_ROOT = Path(directory) / 'models'
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    django.setup()
    from django.test.runner import DiscoverRunner
    labels = sys.argv[1:] or ['config.test_beta_deployment', 'iot', 'marketplace', 'analytics', 'sms', 'dashboard']
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests(labels)
raise SystemExit(bool(failures))
