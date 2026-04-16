"""Restore a previously-produced encrypted backup into a target database."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.platform_common.backup import restore_from_backup


class Command(BaseCommand):
    help = "Decrypt and apply an encrypted backup artifact into a target database."

    def add_arguments(self, parser):
        parser.add_argument("artifact_path")
        parser.add_argument("--target-database", required=True)

    def handle(self, *args, **options):
        p = Path(options["artifact_path"])
        if not p.exists():
            raise CommandError(f"artifact not found: {p}")
        restore_from_backup(p, target_database=options["target_database"])
        self.stdout.write(self.style.SUCCESS(
            f"restored {p} into {options['target_database']}"
        ))
