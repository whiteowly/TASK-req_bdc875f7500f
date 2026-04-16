from __future__ import annotations

from django.db import models

from apps.analytics.models import ReportRun
from apps.identity.models import User
from apps.platform_common.ids import new_id


def _exp_id() -> str:
    return new_id("exp")


def _exf_id() -> str:
    return new_id("exf")


class ExportJob(models.Model):
    FORMATS = ("csv", "xlsx")
    STATUSES = ("queued", "running", "complete", "failed", "expired")

    id = models.CharField(primary_key=True, max_length=40, default=_exp_id, editable=False)
    report_run = models.ForeignKey(ReportRun, on_delete=models.CASCADE, related_name="exports")
    format = models.CharField(max_length=8)
    status = models.CharField(max_length=16, default="queued")
    total_rows = models.IntegerField(default=0)
    file_count = models.IntegerField(default=0)
    expires_at = models.DateTimeField()
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "export_jobs"


class ExportFile(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_exf_id, editable=False)
    export_job = models.ForeignKey(ExportJob, on_delete=models.CASCADE, related_name="files")
    part_number = models.IntegerField()
    row_count = models.IntegerField()
    path = models.CharField(max_length=1024)
    checksum_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "export_files"
        unique_together = (("export_job", "part_number"),)
