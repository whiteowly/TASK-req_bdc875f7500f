#!/usr/bin/env bash
# Install a host crontab entry that triggers the nightly encrypted backup at
# 01:00 local time. Idempotent: re-running replaces the existing entry.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
LINE="0 1 * * * ${HERE}/scripts/backup_now.sh >> ${HERE}/var/backup.log 2>&1"
mkdir -p "${HERE}/var"
( crontab -l 2>/dev/null | grep -v '/scripts/backup_now.sh' ; echo "$LINE" ) | crontab -
echo "[install_backup_cron] crontab updated:"
crontab -l | grep backup_now.sh
