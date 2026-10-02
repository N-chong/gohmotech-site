#!/usr/bin/env bash
# Run as the normal Pi user. Only btmon needs administrator privileges.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo 'Run this script as gohmotech without sudo; it will request sudo for the capture.' >&2
    exit 1
fi

for program in btmon sudo timeout systemctl journalctl; do
    if ! command -v "$program" >/dev/null; then
        echo "Required command is unavailable: $program" >&2
        exit 1
    fi
done

systemctl --user is-active --quiet gohmotech-ble-scanner.service
echo 'Administrator authentication is needed only to read Bluetooth controller packets.'
sudo -v

umask 077
report_dir=$(mktemp -d /tmp/gohmotech-ble-controller.XXXXXX)
started_at=$(date --iso-8601=seconds)
echo "Capturing Bluetooth for 30 seconds. Report: $report_dir"

sudo -n timeout --signal=INT 30s btmon -i hci0 -T \
    > "$report_dir/controller.log" 2>&1 &
capture_pid=$!

# Capture the scan setup commands as well as subsequent advertisements.
sleep 1
if ! systemctl --user restart gohmotech-ble-scanner.service; then
    echo 'Scanner restart failed; the controller capture will still finish.' >&2
fi

capture_status=0
wait "$capture_pid" || capture_status=$?
journalctl _SYSTEMD_USER_UNIT=gohmotech-ble-scanner.service \
    --since "$started_at" --no-pager > "$report_dir/scanner.log"
systemctl --user is-active gohmotech-ble-scanner.service \
    > "$report_dir/service-status.txt" || true

if [ "$capture_status" -ne 0 ] && [ "$capture_status" -ne 124 ]; then
    echo "Controller capture failed (exit $capture_status). See $report_dir/controller.log" >&2
    exit "$capture_status"
fi

echo "Capture finished. Report: $report_dir"
echo 'Tell Codex the capture finished so it can inspect the local report.'
