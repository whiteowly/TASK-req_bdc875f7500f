"""Long-running scheduler: tick every ``--interval`` seconds.

Used by the ``scheduler`` service in docker-compose so the offline backend
ships with a real, self-contained scheduler — no external cron daemon
required. Operators may also prefer the host crontab; in that case run
``run_scheduler_tick`` once a minute instead.
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.platform_common.scheduler import tick_all


log = logging.getLogger(__name__)


class _Stop:
    def __init__(self):
        self.stop = False
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def _handle(self, *_):
        self.stop = True


def _column_exists(table: str, column: str) -> bool:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s "
            "AND column_name = %s",
            [table, column],
        )
        return cur.fetchone()[0] > 0


class Command(BaseCommand):
    help = "Run the scheduler in a loop, ticking every --interval seconds."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=60)

    def _wait_for_schema(self, stop):
        from django.db import close_old_connections

        # Wait until the api container's migration has fully applied the
        # latest schema — checking both the tables AND the
        # ``last_enqueued_at`` column that was added in migration 0002.
        deadline = time.time() + 300
        while not stop.stop and time.time() < deadline:
            try:
                if (_column_exists("inspection_schedules", "last_enqueued_at")
                        and _column_exists("report_schedules", "last_enqueued_at")):
                    return
            except Exception:
                pass
            finally:
                close_old_connections()
            self.stdout.write("waiting for schema...")
            time.sleep(3)

    def handle(self, *args, **options):
        interval = max(5, int(options["interval"]))
        stop = _Stop()
        # Wait until the api container has migrated the schema so the
        # scheduler doesn't crash-loop reading from a not-yet-existent
        # `inspection_schedules` table.
        from django.core.management import call_command

        call_command("wait_for_db", "--timeout", "60")
        self._wait_for_schema(stop)
        self.stdout.write(self.style.SUCCESS(
            f"scheduler loop running every {interval}s — Ctrl-C to stop"
        ))
        while not stop.stop:
            try:
                result = tick_all()
                fired = len(result["inspections"]) + len(result["reports"])
                if fired:
                    self.stdout.write(
                        f"tick fired {fired} schedule(s): "
                        f"{len(result['inspections'])} inspection(s), "
                        f"{len(result['reports'])} report(s)"
                    )
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("scheduler tick failed: %s", exc)
            finally:
                close_old_connections()
            for _ in range(interval):
                if stop.stop:
                    break
                time.sleep(1)
        self.stdout.write("scheduler loop stopped")
