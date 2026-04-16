"""Diagnostic that confirms the PITR retention contract on the running server."""
from django.core.management.base import BaseCommand

from apps.platform_common.backup import (
    PITR_RETENTION_DAYS,
    binlog_format,
    binlog_retention_seconds,
    list_binlogs,
)


class Command(BaseCommand):
    help = "Show binlog format/retention and the available binlog files."

    def handle(self, *args, **options):
        self.stdout.write(f"required_pitr_days={PITR_RETENTION_DAYS}")
        self.stdout.write(f"binlog_format={binlog_format()}")
        self.stdout.write(f"binlog_expire_logs_seconds={binlog_retention_seconds()}")
        for name, size in list_binlogs():
            self.stdout.write(f"binlog={name} bytes={size}")
