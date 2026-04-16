#!/usr/bin/env bash
# Operator-facing wrapper: produce an encrypted backup right now.
# Designed to be invoked as a cron job (nightly) on the host that runs the
# api container, e.g.: ``0 1 * * * /app/scripts/backup_now.sh``.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm -e SKIP_MIGRATE=1 api python manage.py run_backup "$@"
