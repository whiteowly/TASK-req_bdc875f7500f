FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc default-libmysqlclient-dev pkg-config wget gnupg ca-certificates lsb-release \
      libaio1 libmecab2 libnuma1 \
      docker.io docker-compose \
 && rm -rf /var/lib/apt/lists/*

# Install Oracle's MySQL community client (mysql, mysqldump, mysqlbinlog).
# Oracle's mysqlbinlog is required because MariaDB's variant cannot stream
# binlogs from a MySQL 8 server (it reports 'unrecognized MariaDB version').
# The binlog stream is the PITR backbone in apps/platform_common/backup.py.
#
# We pin specific .deb files from the MySQL community archive so the build
# is deterministic and not affected by Oracle's apt-repo signing-key
# rotations. These are official upstream artifacts pulled by exact version.
ARG MYSQL_VERSION=8.0.39
ARG MYSQL_DEB_HOST=https://downloads.mysql.com/archives/get/p/23/file
RUN set -eux; \
    cd /tmp; \
    for pkg in \
        mysql-common_${MYSQL_VERSION}-1debian12_amd64.deb \
        mysql-community-client-plugins_${MYSQL_VERSION}-1debian12_amd64.deb \
        libmysqlclient21_${MYSQL_VERSION}-1debian12_amd64.deb \
        mysql-community-client-core_${MYSQL_VERSION}-1debian12_amd64.deb \
        mysql-community-client_${MYSQL_VERSION}-1debian12_amd64.deb \
        mysql-community-server-core_${MYSQL_VERSION}-1debian12_amd64.deb ; do \
      wget -q "${MYSQL_DEB_HOST}/${pkg}" -O "/tmp/${pkg}"; \
    done; \
    DEBIAN_FRONTEND=noninteractive dpkg -i \
      mysql-common_*.deb \
      mysql-community-client-plugins_*.deb \
      libmysqlclient21_*.deb \
      mysql-community-client-core_*.deb \
      mysql-community-client_*.deb \
      mysql-community-server-core_*.deb; \
    rm -f /tmp/*.deb

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

RUN chmod +x /app/docker/entrypoint.sh /app/docker/bootstrap.sh /app/init_db.sh /app/run_tests.sh || true

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "governanceiq.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--certfile", "/run/runtime-secrets/tls_cert.pem", "--keyfile", "/run/runtime-secrets/tls_key.pem"]
