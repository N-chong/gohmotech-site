"""Create private beta configuration once, without altering development data."""

import json
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values

project = Path(__file__).resolve().parents[1]
config_dir = Path('/home/gohmotech/.config/gohmotech')
config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
env_path = config_dir / 'beta.env'
if env_path.exists():
    raise SystemExit('Beta environment already exists; refusing to overwrite its credentials.')

development = dotenv_values(project / '.env')
data_root = Path('/home/gohmotech/.local/share/gohmotech-beta')
for directory in ('media', 'static', 'private_support', 'private_inquiries', 'protected_models', 'releases'):
    (data_root / directory).mkdir(parents=True, exist_ok=True, mode=0o700)

values = {
    'BETA_SECRET_KEY': secrets.token_urlsafe(64),
    'BETA_ALLOWED_HOSTS': 'gohmotech.site,www.gohmotech.site',
    'BETA_DB_NAME': 'gohmotech_beta',
    'BETA_DB_USER': 'gohmotech_beta',
    'BETA_DB_PASSWORD': secrets.token_hex(32),
    'BETA_DB_HOST': '127.0.0.1',
    'BETA_DB_PORT': '3306',
    'BETA_DATA_ROOT': str(data_root),
    'BETA_REDIS_URL': 'redis://127.0.0.1:6379/2',
    'BETA_CELERY_BROKER_URL': 'redis://127.0.0.1:6379/3',
    'BETA_EMAIL_HOST': development.get('EMAIL_HOST', ''),
    'BETA_EMAIL_PORT': development.get('EMAIL_PORT', '587'),
    'BETA_EMAIL_USER': development.get('EMAIL_HOST_USER', ''),
    'BETA_EMAIL_PASSWORD': development.get('EMAIL_HOST_PASSWORD', ''),
    'BETA_FROM_EMAIL': development.get('DEFAULT_FROM_EMAIL') or development.get('EMAIL_HOST_USER', ''),
    'BETA_GOOGLE_CLIENT_ID': development.get('GOOGLE_OAUTH_CLIENT_ID', ''),
    'BETA_GOOGLE_CLIENT_SECRET': development.get('GOOGLE_OAUTH_CLIENT_SECRET', ''),
}
with os.fdopen(os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
    for key, value in values.items():
        output.write(f'{key}={json.dumps(str(value or ""))}\n')
print('Created private beta environment and separate data directories. No messages sent.')
