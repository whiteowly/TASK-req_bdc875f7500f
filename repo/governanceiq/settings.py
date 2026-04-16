"""Django settings for the GovernanceIQ backend.

All runtime configuration is read from environment variables or runtime secret
files mounted into the container by the local bootstrap path. There are no
checked-in `.env` files anywhere in the repo, and no hardcoded credentials.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _read_secret(env_name: str, file_env_name: str, *, generate_if_missing: bool = False) -> str:
    """Read a secret from an env var or a file pointed to by an env var.

    Falls back to a randomly generated value when ``generate_if_missing`` is
    set and nothing is provided. The generated value lives only in the current
    process — it is never written back to disk by this function.
    """
    direct = os.environ.get(env_name)
    if direct:
        return direct
    file_path = os.environ.get(file_env_name)
    if file_path and os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    if generate_if_missing:
        return secrets.token_urlsafe(64)
    return ""


SECRET_KEY = _read_secret(
    "DJANGO_SECRET_KEY",
    "DJANGO_SECRET_KEY_FILE",
    generate_if_missing=True,
)

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,[::1],api,testserver",
    ).split(",")
    if h.strip()
]

# Application definition
INSTALLED_APPS = [
    "rest_framework",
    "apps.platform_common",
    "apps.identity",
    "apps.authorization",
    "apps.catalog",
    "apps.lineage",
    "apps.quality",
    "apps.tickets",
    "apps.content",
    "apps.analytics",
    "apps.exports",
    "apps.audit_monitoring",
]

MIDDLEWARE = [
    "apps.platform_common.middleware.RequestIdMiddleware",
    "apps.platform_common.middleware.AuthenticationMiddleware",
    "apps.platform_common.middleware.RateLimitMiddleware",
    "apps.platform_common.middleware.IdempotencyMiddleware",
    "apps.platform_common.middleware.ErrorHandlingMiddleware",
]

ROOT_URLCONF = "governanceiq.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "governanceiq.wsgi.application"

# Database
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "governanceiq")
MYSQL_USER = os.environ.get("MYSQL_USER", "governanceiq")
MYSQL_PASSWORD = _read_secret(
    "MYSQL_PASSWORD",
    "MYSQL_PASSWORD_FILE",
)
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": MYSQL_DATABASE,
        "USER": MYSQL_USER,
        "PASSWORD": MYSQL_PASSWORD,
        "HOST": MYSQL_HOST,
        "PORT": MYSQL_PORT,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'",
        },
        "TEST": {
            "NAME": os.environ.get("MYSQL_TEST_DATABASE", "test_governanceiq"),
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_unicode_ci",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Argon2id is the documented hashing algorithm for user passwords.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TZ", "UTC")
USE_I18N = False
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.platform_common.errors.exception_handler",
    "UNAUTHENTICATED_USER": None,
}

# Field encryption key (AES-256-GCM). Loaded from runtime secret mount or env.
DATA_ENCRYPTION_KEY = _read_secret(
    "DATA_ENCRYPTION_KEY",
    "DATA_ENCRYPTION_KEY_FILE",
    generate_if_missing=True,
)
DATA_ENCRYPTION_KEY_ID = os.environ.get("DATA_ENCRYPTION_KEY_ID", "k1")

# Idempotency / OCC / rate limit defaults
IDEMPOTENCY_WINDOW_SECONDS = 24 * 60 * 60
SESSION_TTL_SECONDS = 8 * 60 * 60
RATE_LIMIT_PER_USER_PER_MIN = 120
RATE_LIMIT_PER_IP_PER_MIN = 30

# Local storage paths for exports/backups
EXPORT_STORAGE_DIR = Path(os.environ.get("EXPORT_STORAGE_DIR", "/var/lib/governanceiq/exports"))
BACKUP_STORAGE_DIR = Path(os.environ.get("BACKUP_STORAGE_DIR", "/var/lib/governanceiq/backups"))

# Nightly backup schedule (in-service scheduler default; overridable via env)
BACKUP_CRON_EXPR = os.environ.get("BACKUP_CRON_EXPR", "0 1 * * *")
BACKUP_CRON_TZ = os.environ.get("BACKUP_CRON_TZ", TIME_ZONE or "UTC")

# Logging — single console stream, structured-friendly format.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s level=%(levelname)s name=%(name)s req=%(request_id)s msg=%(message)s",
        },
    },
    "filters": {
        "request_id": {
            "()": "apps.platform_common.logging_utils.RequestIdFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
