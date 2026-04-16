"""Block until the configured database accepts connections.

Used by the Docker entrypoint and by ``./run_tests.sh`` so we never race the
MySQL container during ``docker compose up --build``.
"""
import time

from django.core.management.base import BaseCommand
from django.db import OperationalError, connection


class Command(BaseCommand):
    help = "Wait for the configured database to accept connections."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, **options) -> None:
        deadline = time.time() + options["timeout"]
        while True:
            try:
                connection.ensure_connection()
                self.stdout.write(self.style.SUCCESS("database ready"))
                return
            except OperationalError as exc:
                if time.time() >= deadline:
                    raise SystemExit(f"database not ready within timeout: {exc}")
                time.sleep(1)
