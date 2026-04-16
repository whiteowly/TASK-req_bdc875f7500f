"""Generate any missing runtime secrets/cert material into the secrets dir.

Idempotent. Used by the bootstrap container. Production deployments must
replace these files with material from the deployment platform's
secret/cert-management path; this command exists for the
``docker compose up --build`` local-dev workflow.
"""

import os
import secrets
import string
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.platform_common.tls import ensure_files


SECRETS = [
    ("django_secret_key", 64),
    ("data_encryption_key", 64),
    ("mysql_root_password", 32),
    ("mysql_user_password", 32),
    ("backup_encryption_key", 64),
]


def _rand(n: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


class Command(BaseCommand):
    help = "Ensure runtime secrets and the local TLS cert/key exist."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=os.environ.get("RUNTIME_SECRETS_DIR", "/run/runtime-secrets"),
        )

    def handle(self, *args, **options):
        d = Path(options["dir"])
        d.mkdir(parents=True, exist_ok=True)
        for name, size in SECRETS:
            target = d / name
            if not target.exists() or target.stat().st_size == 0:
                target.write_text(_rand(size))
                mode = (
                    0o644
                    if name in ("mysql_root_password", "mysql_user_password")
                    else 0o600
                )
                target.chmod(mode)
                self.stdout.write(self.style.SUCCESS(f"generated {name}"))
            else:
                mode = (
                    0o644
                    if name in ("mysql_root_password", "mysql_user_password")
                    else 0o600
                )
                target.chmod(mode)

        wrote_tls = ensure_files(str(d / "tls_cert.pem"), str(d / "tls_key.pem"))
        if wrote_tls:
            self.stdout.write(
                self.style.SUCCESS("generated tls_cert.pem + tls_key.pem")
            )
        self.stdout.write(self.style.SUCCESS("runtime bootstrap done"))
