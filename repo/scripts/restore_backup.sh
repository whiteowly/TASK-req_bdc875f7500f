#!/usr/bin/env bash
# Operator-facing wrapper: restore a previously produced encrypted backup
# into the configured MySQL database.
#
# Usage:
#   ./scripts/restore_backup.sh <artifact_path_inside_container> [--target-database X]
#
# The artifact path must already be present on the backup_storage volume.
set -euo pipefail
if [ "$#" -lt 1 ]; then
  echo "usage: $0 <artifact_path_inside_container> [--target-database NAME]" >&2
  exit 2
fi
cd "$(dirname "$0")/.."
docker compose run --rm -e SKIP_MIGRATE=1 api python manage.py restore_backup "$@"
