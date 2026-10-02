#!/usr/bin/env bash
# Narrow production deployment: no migrations, hardware, tunnel, or Nginx changes.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this script with sudo from the Raspberry Pi terminal.' >&2
    exit 1
fi
project=/home/gohmotech/capstone
python_bin="$project/.venv/bin/python"
backup_dir="/var/backups/gohmotech-camera-realtime/$(date -u +%Y%m%dT%H%M%SZ)"
served=/var/www/gohmotech-production/static/js/live-camera.js
collected=/home/gohmotech/.local/share/gohmotech-production/static/js/live-camera.js
source_backup="${1:-/tmp/gohmotech-camera-backup-dJ3Lm6YN}"
cd "$project"
test -f "$source_backup/iot/views.py"
test -f "$served"
systemctl is-active --quiet gohmotech-production
install -d -m 700 "$backup_dir"
cp -a "$source_backup/." "$backup_dir/"
cp -a "$served" "$backup_dir/live-camera.served.js"
cp -a /etc/nginx/conf.d/gohmotech-production.conf "$backup_dir/nginx-active.conf"
cp -a /etc/systemd/system/gohmotech-production.service "$backup_dir/production-service.conf"
runuser -u gohmotech -- "$python_bin" manage.py check --deploy --settings=config.production
nginx -t
rollback() {
    trap - ERR
    set +e
    for file in iot/camera_utils.py iot/views.py iot/templates/iot/dashboard_modern.html iot/templates/iot/camera_detail.html; do
        cp -a "$backup_dir/$file" "$project/$file"
    done
    cp -a "$backup_dir/live-camera.served.js" "$served"
    install -o gohmotech -g gohmotech -m 644 "$backup_dir/live-camera.served.js" "$collected"
    systemctl restart gohmotech-production
    echo "Camera update failed; prior application/static files restored. Backup: $backup_dir" >&2
}
trap rollback ERR
# Existing storage serves unhashed files directly; publish only the changed asset.
install -o gohmotech -g gohmotech -m 644 static/js/live-camera.js "$collected"
install -o root -g root -m 644 static/js/live-camera.js "$served"
systemctl restart gohmotech-production
systemctl is-active --quiet gohmotech-production
runuser -u gohmotech -- "$python_bin" deploy/smoke_production.py
systemctl show gohmotech-production -p ActiveState -p SubState -p MainPID
echo "Camera update deployed; backup: $backup_dir"
