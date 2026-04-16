#!/usr/bin/env bash
# Operator-facing wrapper for point-in-time recovery.
#
# Usage:
#   ./scripts/pitr_restore.sh --target-time 2026-04-15T16:30:00Z \
#                             --target-database gi_pitr [--dry-run]
#
# Prerequisite (one-off): create the target database via:
#   docker compose exec api python manage.py create_pitr_database --database-name gi_pitr
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm -e SKIP_MIGRATE=1 \
  -e MYSQL_ROOT_PASSWORD_FILE=/run/runtime-secrets/mysql_root_password \
  api python manage.py run_pitr "$@"
