#!/usr/bin/env bash
# Deploy the account tutorial and approved-seller welcome banner to production.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo 'Run: sudo bash /home/gohmotech/capstone/deploy/install_onboarding.sh' >&2
    exit 1
fi

project=/home/gohmotech/capstone
python_bin="$project/.venv/bin/python"
nginx_static=/var/www/gohmotech-production/static
backup_dir="/var/backups/gohmotech-onboarding/$(date -u +%Y%m%dT%H%M%SZ)"
cd "$project"

run_app() {
    runuser -u gohmotech -- env DJANGO_SETTINGS_MODULE=config.production "$python_bin" "$@"
}

# Validate the current source and migration plan before modifying production.
run_app manage.py check --deploy --settings=config.production
run_app manage.py migrate dashboard --plan --settings=config.production
static_root=$(run_app -c 'from django.conf import settings; print(settings.STATIC_ROOT)')
test -d "$static_root"
test -d "$nginx_static"
systemctl is-active --quiet gohmotech-production

install -d -m 700 "$backup_dir"
assets=(css/onboarding.css js/onboarding.js marketplace/seller-welcome.css)
sources=(static/css/onboarding.css static/js/onboarding.js marketplace/static/marketplace/seller-welcome.css)
for image in static/images/onboarding/goat_*.png; do
    assets+=("images/onboarding/${image##*/}")
    sources+=("$image")
done
for index in "${!assets[@]}"; do
    test -s "${sources[$index]}"
    target="$nginx_static/${assets[$index]}"
    if [ -f "$target" ]; then
        install -D -m 600 "$target" "$backup_dir/nginx/${assets[$index]}"
    fi
    target="$static_root/${assets[$index]}"
    if [ -f "$target" ]; then
        install -D -m 600 "$target" "$backup_dir/collected/${assets[$index]}"
    fi
done

# This migration adds only the account tutorial table; it leaves existing tables
# and account completion state intact on subsequent runs.
run_app manage.py migrate dashboard --noinput --settings=config.production
for index in "${!assets[@]}"; do
    install -D -m 644 -o gohmotech -g gohmotech "${sources[$index]}" "$static_root/${assets[$index]}"
    install -D -m 644 -o root -g root "${sources[$index]}" "$nginx_static/${assets[$index]}"
done

# Existing nginx routing already serves these paths. Only the web app needs a
# restart; workers, the scheduler, and BLE receiver retain their current state.
systemctl restart gohmotech-production
run_app deploy/smoke_production.py
run_app deploy/verify_onboarding_deployment.py
printf 'Onboarding and seller welcome banner deployed. Static backups: %s\n' "$backup_dir"
