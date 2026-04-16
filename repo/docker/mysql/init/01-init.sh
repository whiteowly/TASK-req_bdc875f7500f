#!/usr/bin/env sh
# Wait for the runtime secrets bootstrap to write its files, then create the
# governanceiq application user with the generated password.
set -eu

while [ ! -s /run/runtime-secrets/mysql_user_password ]; do
  sleep 1
done

PASS="$(cat /run/runtime-secrets/mysql_user_password)"
mysql -uroot -p"$(cat /run/runtime-secrets/mysql_root_password)" <<SQL
CREATE DATABASE IF NOT EXISTS governanceiq CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS test_governanceiq CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'governanceiq'@'%' IDENTIFIED BY '${PASS}';
GRANT ALL PRIVILEGES ON governanceiq.* TO 'governanceiq'@'%';
GRANT ALL PRIVILEGES ON test_governanceiq.* TO 'governanceiq'@'%';
-- ``REPLICATION CLIENT`` is required for ``SHOW BINARY LOGS``, used by
-- the PITR planner (apps/platform_common/backup.py::list_binlogs).
GRANT REPLICATION CLIENT ON *.* TO 'governanceiq'@'%';
FLUSH PRIVILEGES;
SQL
