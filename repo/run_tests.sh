#!/usr/bin/env bash
# Single broad test command for the GovernanceIQ project.
#
# By default this runs the full pytest suite (Unit_tests/ + api_test/) inside
# Docker against a real MySQL container. There are no mock or in-memory
# substitutions: API tests exercise the real Django app against MySQL, and
# the unit tests run real domain code without monkeypatching.
#
# When ``RUN_TESTS_LOCAL=1`` is set, the same suite runs against a locally
# reachable MySQL (helpful for fast iteration where the developer already
# manages MySQL outside of Docker). The local mode requires the same
# environment variables that the Docker entrypoint generates.
set -euo pipefail

cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[run_tests] error: neither 'docker compose' nor 'docker-compose' is available" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[run_tests] error: docker daemon is not reachable" >&2
  exit 1
fi

if [ "${RUN_TESTS_LOCAL:-0}" = "1" ]; then
  echo "[run_tests] running locally against MYSQL_HOST=${MYSQL_HOST:-127.0.0.1}"
  python -m pytest -q "$@"
  exit $?
fi

cleanup() {
  "${COMPOSE_CMD[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${COMPOSE_CMD[@]}" down -v >/dev/null 2>&1 || true
"${COMPOSE_CMD[@]}" build api db proxy
"${COMPOSE_CMD[@]}" up -d bootstrap db
"${COMPOSE_CMD[@]}" run --rm -e SKIP_MIGRATE=1 api python manage.py wait_for_db --timeout 90
"${COMPOSE_CMD[@]}" run --rm -e SKIP_MIGRATE=1 api python manage.py migrate --noinput
"${COMPOSE_CMD[@]}" run --rm -e SKIP_MIGRATE=1 api python -m pytest -q "$@"
