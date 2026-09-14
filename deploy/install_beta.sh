#!/usr/bin/env bash
# Run in the Pi terminal: sudo bash /home/gohmotech/capstone/deploy/install_beta.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this installer with sudo in the Raspberry Pi terminal.' >&2
    exit 1
fi

project=/home/gohmotech/capstone
python_bin="$project/.venv/bin/python"
beta_data=/home/gohmotech/.local/share/gohmotech-beta
beta_env=/home/gohmotech/.config/gohmotech/beta.env
backup_dir="/var/backups/gohmotech-beta/$(date -u +%Y%m%dT%H%M%SZ)"
test -f "$beta_env"
test -x "$python_bin"
cd "$project"

echo 'Validating the prepared beta configuration...'
runuser -u gohmotech -- "$python_bin" manage.py check --deploy --settings=config.beta
bash -n "$project/deploy/install_beta.sh"
install -d -m 700 "$backup_dir"
tar --exclude='./.git' --exclude='./.venv' --exclude='./venv' \
    --exclude='./.env' --exclude='./.env.*' --exclude='*.local.env' \
    --exclude='./media' --exclude='./protected_media' --exclude='./private_support_uploads' \
    --exclude='./staticfiles' --exclude='./tmp' --exclude='./.claude' \
    --exclude='./.codex' --exclude='./.agents' --exclude='__pycache__' \
    -czf "$backup_dir/source.tar.gz" .
install -m 600 "$beta_env" "$backup_dir/beta.env"
"$python_bin" -m pip freeze > "$backup_dir/requirements-installed.txt"
chmod 600 "$backup_dir/requirements-installed.txt"

new_nginx=0
if ! command -v nginx >/dev/null 2>&1; then
    new_nginx=1
fi
echo 'Installing nginx and Redis from the configured Debian repositories...'
apt-get update
apt-get install -y nginx redis-server
systemctl enable --now mariadb redis-server

echo 'Checking the dedicated beta database...'
if ! runuser -u gohmotech -- env DJANGO_SETTINGS_MODULE=config.beta "$python_bin" -c \
    'import django; django.setup(); from django.db import connection; connection.ensure_connection()' \
    >/dev/null 2>&1; then
    "$python_bin" deploy/provision_beta_database.py
fi
# Always back up the beta database before migrations, including on later runs.
"$python_bin" - "$beta_env" "$backup_dir/database.sql" <<'PY'
import os
import subprocess
import sys
import tempfile
from dotenv import dotenv_values

config = dotenv_values(sys.argv[1])
with tempfile.NamedTemporaryFile(mode='w', prefix='gohmotech-db-', delete=True) as defaults:
    os.chmod(defaults.name, 0o600)
    # Generated credentials contain only hex; fixed database/user identifiers.
    defaults.write('[client]\nuser=gohmotech_beta\nhost=127.0.0.1\npassword=' + config['BETA_DB_PASSWORD'] + '\n')
    defaults.flush()
    with open(sys.argv[2], 'xb') as backup:
        os.chmod(sys.argv[2], 0o600)
        subprocess.run(['mariadb-dump', '--defaults-extra-file=' + defaults.name,
                        '--single-transaction', '--skip-lock-tables', 'gohmotech_beta'],
                       stdout=backup, check=True)
PY
runuser -u gohmotech -- "$python_bin" manage.py migrate --noinput --settings=config.beta
runuser -u gohmotech -- "$python_bin" manage.py collectstatic --noinput --settings=config.beta
runuser -u gohmotech -- "$python_bin" deploy/preflight.py

echo 'Installing the loopback-only web origin...'
install -d -m 755 /var/www/gohmotech-beta/static
cp -a "$beta_data/static/." /var/www/gohmotech-beta/static/
chown -R root:root /var/www/gohmotech-beta/static
find /var/www/gohmotech-beta/static -type d -exec chmod 755 {} +
find /var/www/gohmotech-beta/static -type f -exec chmod 644 {} +
for target in /etc/nginx/conf.d/gohmotech-beta.conf /etc/systemd/system/gohmotech-beta.service; do
    if [ -e "$target" ]; then
        cp -a "$target" "$backup_dir/$(basename "$target")"
    fi
done
install -m 644 deploy/nginx-beta.conf /etc/nginx/conf.d/gohmotech-beta.conf
install -m 644 deploy/gohmotech-beta.service /etc/systemd/system/gohmotech-beta.service
# Disable only the default site created by this fresh nginx package install.
# An nginx installation that existed before this script is left alone.
if [ "$new_nginx" -eq 1 ] && [ -L /etc/nginx/sites-enabled/default ]; then
    mv /etc/nginx/sites-enabled/default "$backup_dir/nginx-default-site-link"
fi
nginx -t
systemd-analyze verify /etc/systemd/system/gohmotech-beta.service
systemctl daemon-reload
systemctl enable --now gohmotech-beta
systemctl restart gohmotech-beta
systemctl enable --now nginx
systemctl reload nginx

echo 'Checking marketplace, static assets, and blocked hardware endpoints...'
"$python_bin" deploy/smoke_beta.py
echo "Private release/configuration/database backup: $backup_dir"
echo 'Local beta installed. Public DNS/tunnel setup is still required.'
echo 'Create the beta administrator with:'
echo '  .venv/bin/python manage.py createsuperuser --settings=config.beta'
