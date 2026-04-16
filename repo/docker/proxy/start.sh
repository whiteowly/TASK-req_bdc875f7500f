#!/bin/sh
# Wait for the runtime-secrets bootstrap to materialize the TLS cert/key,
# then exec nginx in the foreground.
set -eu

while [ ! -s /run/runtime-secrets/tls_cert.pem ] \
   || [ ! -s /run/runtime-secrets/tls_key.pem ]; do
  echo "[proxy] waiting for tls cert/key..."
  sleep 1
done

exec nginx -g "daemon off;"
