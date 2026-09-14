#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo 'Run with sudo from the Raspberry Pi terminal.' >&2
    exit 1
fi

project=/home/gohmotech/capstone
python_bin="$project/.venv/bin/python"
production_env=/home/gohmotech/.config/gohmotech/production.env
production_data=/home/gohmotech/.local/share/gohmotech-production
backup_dir="/var/backups/gohmotech-production-cutover/$(date -u +%Y%m%dT%H%M%SZ)"
old_nginx=/etc/nginx/conf.d/gohmotech-beta.conf
new_nginx=/etc/nginx/conf.d/gohmotech-production.conf
cutover_started=0
was_production_active=0
if systemctl is-active --quiet gohmotech-production; then
    was_production_active=1
fi

rollback() {
    if [ "$cutover_started" -ne 1 ]; then
        return
    fi
    set +e
    systemctl disable --now gohmotech-production
    if [ -e "$new_nginx" ]; then
        mv "$new_nginx" "$backup_dir/gohmotech-production.conf.failed"
    fi
    if [ -e "$backup_dir/gohmotech-production.conf" ]; then
        cp -a "$backup_dir/gohmotech-production.conf" "$new_nginx"
    elif [ -e "$backup_dir/gohmotech-beta.conf.disabled" ]; then
        cp -a "$backup_dir/gohmotech-beta.conf.disabled" "$old_nginx"
    elif [ -e "$backup_dir/gohmotech-beta.conf" ]; then
        cp -a "$backup_dir/gohmotech-beta.conf" "$old_nginx"
    fi
    nginx -t && systemctl reload nginx
    if [ "$was_production_active" -eq 1 ]; then
        if [ -e "$backup_dir/gohmotech-production.service" ]; then
            cp -a "$backup_dir/gohmotech-production.service" /etc/systemd/system/gohmotech-production.service
            systemctl daemon-reload
        fi
        systemctl enable --now gohmotech-production
        echo "Production update failed; prior production service restored from $backup_dir" >&2
    else
        systemctl enable --now gohmotech-beta
        echo "Production cutover failed; beta service restored from $backup_dir" >&2
    fi
}
trap rollback ERR

test -f "$production_env"
test -x "$python_bin"
cd "$project"

install -d -m 700 "$backup_dir"
install -m 600 "$production_env" "$backup_dir/production.env"
for target in "$old_nginx" "$new_nginx" /etc/systemd/system/gohmotech-beta.service /etc/systemd/system/gohmotech-production.service; do
    if [ -e "$target" ]; then
        cp -a "$target" "$backup_dir/$(basename "$target")"
    fi
done

runuser -u gohmotech -- "$python_bin" manage.py check --deploy --settings=config.production
runuser -u gohmotech -- "$python_bin" manage.py showmigrations --plan --settings=config.production >/dev/null
runuser -u gohmotech -- "$python_bin" manage.py collectstatic --noinput --settings=config.production

install -d -m 755 /var/www/gohmotech-production/static
cp -a "$production_data/static/." /var/www/gohmotech-production/static/
chown -R root:root /var/www/gohmotech-production/static
find /var/www/gohmotech-production/static -type d -exec chmod 755 {} +
find /var/www/gohmotech-production/static -type f -exec chmod 644 {} +

install -m 644 deploy/gohmotech-production.service /etc/systemd/system/gohmotech-production.service
install -m 644 deploy/nginx-production.conf "$new_nginx"
cutover_started=1
if [ -e "$old_nginx" ]; then
    mv "$old_nginx" "$backup_dir/gohmotech-beta.conf.disabled"
fi

nginx -t
systemd-analyze verify /etc/systemd/system/gohmotech-production.service
systemctl daemon-reload
systemctl disable --now gohmotech-beta
systemctl enable --now gohmotech-production
systemctl reload nginx

"$python_bin" deploy/smoke_production.py
cutover_started=0
trap - ERR
echo "Production cutover completed. Rollback files: $backup_dir"
