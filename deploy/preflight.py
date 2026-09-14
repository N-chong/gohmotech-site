"""Read-only checks against configured beta services; does not send messages."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.beta'

import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from redis import Redis

call_command('check', deploy=True, fail_level='WARNING')
with connection.cursor() as cursor:
    cursor.execute('SELECT 1')
executor = MigrationExecutor(connection)
if executor.migration_plan(executor.loader.graph.leaf_nodes()):
    raise SystemExit('Pending beta database migrations; apply them before release.')
Redis.from_url(settings.CACHES['default']['LOCATION']).ping()
if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:
    raise SystemExit('Configure beta SMTP before enabling public signup.')
if not (Path(settings.STATIC_ROOT) / 'admin/css/base.css').is_file():
    raise SystemExit('Run collectstatic for the beta settings before release.')
print('Beta settings, database, migrations, Redis, SMTP configuration, and collected assets checked.')
print('SMTP delivery, reverse proxy, TLS, and end-to-end browser workflows still require verification.')
