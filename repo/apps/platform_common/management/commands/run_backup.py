"""Run an encrypted MySQL backup to local attached storage."""
from django.core.management.base import BaseCommand

from apps.platform_common.backup import run_backup


class Command(BaseCommand):
    help = "Produce an encrypted backup artifact + manifest under BACKUP_STORAGE_DIR."

    def add_arguments(self, parser):
        parser.add_argument("--label", default=None)

    def handle(self, *args, **options):
        m = run_backup(label=options["label"])
        self.stdout.write(self.style.SUCCESS(
            f"backup ok: {m['artifact_path']} ({m['plaintext_bytes']} plaintext bytes)"
        ))
        self.stdout.write(f"manifest: {m['manifest_path']}")
