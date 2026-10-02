#!/usr/bin/env bash
set -euo pipefail
# Reuse the narrow installer, rolling back to the already deployed v3 fix.
exec bash /home/gohmotech/capstone/deploy/install_camera_realtime.sh /tmp/gohmotech-camera-sse-backup-MAk1jR9P
