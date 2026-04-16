from __future__ import annotations

from django.db import models

from apps.catalog.models import Dataset
from apps.identity.models import User
from apps.platform_common.ids import new_id


def _rpt_id() -> str:
    return new_id("rpt")


def _rrn_id() -> str:
    return new_id("rrn")


def _rsd_id() -> str:
    return new_id("rsd")


def _default_timezone() -> str:
    from django.conf import settings
    return settings.TIME_ZONE or "UTC"


class ReportDefinition(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_rpt_id, editable=False)
    name = models.CharField(max_length=255, unique=True)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="report_definitions")
    filter_schema = models.JSONField(default=dict, blank=True)
    time_window_schema = models.JSONField(default=dict, blank=True)
    permission_scope = models.JSONField(default=dict, blank=True)
    query_plan = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "report_definitions"


class ReportRun(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_rrn_id, editable=False)
    report_definition = models.ForeignKey(ReportDefinition, on_delete=models.CASCADE, related_name="runs")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    resolved_filters = models.JSONField(default=dict, blank=True)
    resolved_time_window = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default="complete")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    total_rows = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    rows_snapshot = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "report_runs"


class ReportSchedule(models.Model):
    """Recurring scheduled execution of a report definition.

    The scheduler enqueues a ``ReportRun`` for the bound definition each time
    the cron expression fires; this model is the persistent first-class
    record of those schedules and is exposed by ``/reports/schedules``.
    """

    id = models.CharField(primary_key=True, max_length=40, default=_rsd_id, editable=False)
    report_definition = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="schedules"
    )
    cron_expr = models.CharField(max_length=64, default="0 3 * * *")
    timezone = models.CharField(max_length=64, default=_default_timezone)
    active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="report_schedules_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "report_schedules"
        indexes = [models.Index(fields=["active", "next_run_at"])]
