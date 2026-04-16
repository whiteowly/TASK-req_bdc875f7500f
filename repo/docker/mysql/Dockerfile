FROM mysql:8.0

# The mysql image reads MYSQL_ROOT_PASSWORD_FILE / MYSQL_PASSWORD_FILE from
# files mounted at runtime. We rely on the bootstrap volume to provide them.

ENV MYSQL_ROOT_PASSWORD_FILE=/run/runtime-secrets/mysql_root_password \
    MYSQL_PASSWORD_FILE=/run/runtime-secrets/mysql_user_password

COPY docker/mysql/init/01-init.sh /docker-entrypoint-initdb.d/01-init.sh
RUN chmod +x /docker-entrypoint-initdb.d/01-init.sh
