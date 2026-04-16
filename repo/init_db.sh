#!/usr/bin/env bash
# Initialize MySQL state for the GovernanceIQ project.
#
# This script is the single project-standard database initialization path. It
# runs against the running ``db`` service in docker-compose, applies all
# migrations, and seeds the canonical role rows. Designed to be safe to
# re-run.
set -euo pipefail

cd "$(dirname "$0")"

echo "[init_db] ensuring docker-compose stack is up..."
docker compose up -d --wait bootstrap db

echo "[init_db] applying Django migrations..."
docker compose run --rm api python manage.py migrate --noinput

echo "[init_db] seeding canonical roles..."
docker compose run --rm api python manage.py seed_roles

echo "[init_db] done."
