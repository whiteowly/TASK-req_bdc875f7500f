#!/usr/bin/env sh
set -eu

# Ensure runtime secrets are present (no checked-in .env files).
/app/docker/bootstrap.sh

# Wait for the database before applying migrations.
if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  python /app/manage.py wait_for_db --timeout 90
  python /app/manage.py migrate --noinput
  python /app/manage.py seed_roles || true
fi

exec "$@"
