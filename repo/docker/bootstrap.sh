#!/usr/bin/env sh
# Local-development runtime bootstrap.
#
# Generates ephemeral runtime secrets AND a self-signed TLS cert/key into a
# Docker volume mount so that the api/proxy/db containers can start without
# any checked-in `.env` files and without operator-side `export ...`. This
# is for LOCAL DEVELOPMENT ONLY — production must source secret material and
# real TLS certificates from the deployment platform's
# secret/cert-management path (Vault, KMS, ACME, etc).
set -eu

SECRETS_DIR="${RUNTIME_SECRETS_DIR:-/run/runtime-secrets}"
mkdir -p "$SECRETS_DIR"

# Delegate to the Django management command so cert generation is real
# (cryptography-based RSA-2048 X.509) and shares the exact same code path
# that production tests cover.
cd /app
RUNTIME_SECRETS_DIR="$SECRETS_DIR" python manage.py bootstrap_runtime --dir "$SECRETS_DIR"
echo "[bootstrap] runtime secrets + TLS material ensured under $SECRETS_DIR"
