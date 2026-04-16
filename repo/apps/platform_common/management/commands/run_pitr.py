"""Point-in-time recovery into a target database.

Picks the latest backup at or before ``--target-time``, restores it into
``--target-database``, and applies binlogs up to ``--target-time`` using
``mysqlbinlog --read-from-remote-server``.
"""
import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from apps.platform_common.backup import run_pitr


class Command(BaseCommand):
    help = "Restore + binlog-replay the database to a target point in time."

    def add_arguments(self, parser):
        parser.add_argument(
            "--target-time", required=True,
            help="Target instant in ISO-8601 (e.g. 2026-04-15T16:30:00Z)."
        )
        parser.add_argument("--target-database", required=True,
                            help="Database name to restore into. Must exist.")
        parser.add_argument(
            "--source-database",
            default=None,
            help=(
                "Original database name (defaults to the database recorded "
                "in the chosen backup manifest). When this differs from "
                "--target-database, mysqlbinlog --rewrite-db remaps events "
                "into the target database."
            ),
        )
        parser.add_argument("--dry-run", action="store_true",
                            help="Show the plan without executing.")
        parser.add_argument("--json", action="store_true",
                            help="Emit the plan/result as JSON on stdout.")

    def handle(self, *args, **options):
        try:
            t = datetime.fromisoformat(options["target_time"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommandError(f"--target-time must be ISO-8601: {exc}") from exc
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        try:
            result = run_pitr(
                target_time=t,
                target_database=options["target_database"],
                source_database=options["source_database"],
                dry_run=options["dry_run"],
            )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
            return
        action = "PLAN" if options["dry_run"] else "APPLIED"
        self.stdout.write(self.style.SUCCESS(
            f"PITR {action}: target_time={result['target_time']} "
            f"target_database={result['target_database']} "
            f"base_backup={result['base_backup_label']} "
            f"binlogs={len(result['binlogs'])}"
        ))
        if not options["dry_run"]:
            self.stdout.write(
                f"  binlog_bytes_applied={result.get('binlog_bytes_applied', 0)}"
            )
