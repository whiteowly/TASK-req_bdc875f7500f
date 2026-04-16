from __future__ import annotations

from django.db import models

from apps.platform_common.ids import new_id


def _aud_id() -> str:
    return new_id("aud")


def _auex_id() -> str:
    return new_id("auex")


EVENT_TYPES = (
    "ingestion_success",
    "ingestion_failure",
    "inspection_success",
    "inspection_failure",
    "export_success",
    "export_failure",
    "recommendation_impression",
    "recommendation_click",
)


class AuditLog(models.Model):
    """Append-only audit ledger.

    The ``save()`` and ``delete()`` paths are blocked at the model layer to
    enforce immutability beyond create.
    """

    id = models.CharField(primary_key=True, max_length=40, default=_aud_id, editable=False)
    actor_user_id = models.CharField(max_length=40, blank=True, default="")
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.CharField(max_length=64, blank=True, default="")
    payload_before = models.JSONField(default=dict, blank=True)
    payload_after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["actor_user_id", "created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def save(self, *args, **kwargs):  # type: ignore[override]
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise RuntimeError("audit_logs is append-only; updates are not permitted")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise RuntimeError("audit_logs is append-only; deletes are not permitted")


class EventLog(models.Model):
    """Local-only event log used for monitoring metrics + recommendation CTR."""

    id = models.BigAutoField(primary_key=True)
    event_type = models.CharField(max_length=64)
    event_ts = models.DateTimeField(auto_now_add=True)
    actor_user_id = models.CharField(max_length=40, blank=True, default="")
    dataset_id = models.CharField(max_length=40, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "event_logs"
        indexes = [models.Index(fields=["event_type", "event_ts"])]


class MetricRollup(models.Model):
    id = models.BigAutoField(primary_key=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    metric_name = models.CharField(max_length=64)
    metric_value = models.FloatField()
    dimensions = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metric_rollups"


class AuditExportJob(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_auex_id, editable=False)
    requested_by = models.CharField(max_length=40)
    range_start = models.DateTimeField()
    range_end = models.DateTimeField()
    record_count = models.IntegerField(default=0)
    payload = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_export_jobs"
