"""Prepare private production configuration/data without changing live services."""

import os
import secrets
import shutil
from pathlib import Path

from dotenv import dotenv_values, set_key


beta_env = Path("/home/gohmotech/.config/gohmotech/beta.env")
production_env = Path("/home/gohmotech/.config/gohmotech/production.env")
production_data = Path("/home/gohmotech/.local/share/gohmotech-production")

if production_env.exists():
    raise SystemExit("Production environment already exists; refusing to overwrite it.")
source = dotenv_values(beta_env)
required = (
    "BETA_ALLOWED_HOSTS", "BETA_DB_NAME", "BETA_DB_USER",
    "BETA_DB_PASSWORD", "BETA_DATA_ROOT",
)
if any(not (source.get(name) or "").strip() for name in required):
    raise SystemExit("The private beta environment is incomplete.")

production_env.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
descriptor = os.open(production_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(descriptor)

values = {
    "PRODUCTION_SECRET_KEY": secrets.token_urlsafe(64),
    "PRODUCTION_ALLOWED_HOSTS": source["BETA_ALLOWED_HOSTS"],
    "PRODUCTION_DB_NAME": source["BETA_DB_NAME"],
    "PRODUCTION_DB_USER": source["BETA_DB_USER"],
    "PRODUCTION_DB_PASSWORD": source["BETA_DB_PASSWORD"],
    "PRODUCTION_DB_HOST": source.get("BETA_DB_HOST") or "127.0.0.1",
    "PRODUCTION_DB_PORT": source.get("BETA_DB_PORT") or "3306",
    "PRODUCTION_DATA_ROOT": str(production_data),
    "PRODUCTION_REDIS_URL": source.get("BETA_REDIS_URL") or "redis://127.0.0.1:6379/2",
    "PRODUCTION_CELERY_BROKER_URL": source.get("BETA_CELERY_BROKER_URL") or "redis://127.0.0.1:6379/3",
    "PRODUCTION_IOT_DEVICE_API_KEY": source.get("BETA_IOT_DEVICE_API_KEY") or "",
    "PRODUCTION_EMAIL_HOST": source.get("BETA_EMAIL_HOST") or "",
    "PRODUCTION_EMAIL_PORT": source.get("BETA_EMAIL_PORT") or "587",
    "PRODUCTION_EMAIL_USER": source.get("BETA_EMAIL_USER") or "",
    "PRODUCTION_EMAIL_PASSWORD": source.get("BETA_EMAIL_PASSWORD") or "",
    "PRODUCTION_FROM_EMAIL": source.get("BETA_FROM_EMAIL") or "",
    "PRODUCTION_EMAIL_VERIFICATION": source.get("BETA_EMAIL_VERIFICATION") or "mandatory",
    "PRODUCTION_GOOGLE_CLIENT_ID": source.get("BETA_GOOGLE_CLIENT_ID") or "",
    "PRODUCTION_GOOGLE_CLIENT_SECRET": source.get("BETA_GOOGLE_CLIENT_SECRET") or "",
    "PRODUCTION_SMS_BACKEND": "console",
    "PRODUCTION_EMAIL_ENABLED": "False",
}
for key, value in values.items():
    set_key(str(production_env), key, str(value), quote_mode="always")
production_env.chmod(0o600)

beta_data = Path(source["BETA_DATA_ROOT"]).resolve()
production_data.mkdir(parents=True, exist_ok=False, mode=0o700)
for name in ("media", "static", "private_support", "private_inquiries", "protected_models"):
    source_dir = beta_data / name
    destination = production_data / name
    if source_dir.is_dir():
        shutil.copytree(source_dir, destination)
    else:
        destination.mkdir(mode=0o700)

print(f"Production environment prepared: {production_env}")
print(f"Production data prepared: {production_data}")
print(f"Legacy device key configured: {bool(values['PRODUCTION_IOT_DEVICE_API_KEY'])}")
print("SMS live sending enabled: False")
print("Live services changed: False")
