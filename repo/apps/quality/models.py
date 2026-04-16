from __future__ import annotations

from django.db import models

from django.core.exceptions import ValidationError

from apps.catalog.models import Dataset, DatasetField
from apps.platform_common.ids import new_id


def _qrl_id() -> str:
    return new_id("qrl")


def _ins_id() -> str:
    return new_id("ins")


def _irr_id() -> str:
    return new_id("irr")


def _isd_id() -> str:
    return new_id("isd")


def _default_timezone() -> str:
    from django.conf import settings
    return settings.TIME_ZONE or "UTC"


class QualityRule(models.Model):
    RULE_TYPES = ("completeness", "consistency", "uniqueness", "numeric_range", "distribution_drift")
    SEVERITY = ("P0", "P1", "P2", "P3")

    id = models.CharField(primary_key=True, max_length=40, default=_qrl_id, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="quality_rules")
    rule_type = models.CharField(max_length=32)
    severity = models.CharField(max_length=4)
    threshold_value = models.FloatField()
    config = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "quality_rules"


class QualityRuleField(models.Model):
    id = models.BigAutoField(primary_key=True)
    rule = models.ForeignKey(QualityRule, on_delete=models.CASCADE, related_name="rule_fields")
    field = models.ForeignKey(DatasetField, on_delete=models.CASCADE, related_name="rule_attachments")

    class Meta:
        db_table = "quality_rule_fields"
        unique_together = (("rule", "field"),)


class InspectionRun(models.Model):
    STATUS = ("queued", "running", "complete", "failed")

    id = models.CharField(primary_key=True, max_length=40, default=_ins_id, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="inspections")
    trigger_mode = models.CharField(max_length=16, default="manual")  # manual|scheduled
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    quality_score = models.FloatField(null=True, blank=True)
    gate_pass = models.BooleanField(default=False)
    status = models.CharField(max_length=16, default="queued")
    created_by = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        db_table = "inspection_runs"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            # Allow updates only while the DB row is not yet complete.
            try:
                db_status = (
                    InspectionRun.objects
                    .values_list("status", flat=True)
                    .get(pk=self.pk)
                )
            except InspectionRun.DoesNotExist:
                db_status = None
            if db_status == "complete":
                raise ValidationError(
                    "Completed inspection runs are immutable.",
                    code="immutable_inspection_run",
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == "complete":
            raise ValidationError(
                "Completed inspection runs cannot be deleted.",
                code="immutable_inspection_run",
            )
        super().delete(*args, **kwargs)


class InspectionRuleResult(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_irr_id, editable=False)
    inspection_run = models.ForeignKey(InspectionRun, on_delete=models.CASCADE, related_name="results")
    rule = models.ForeignKey(QualityRule, on_delete=models.CASCADE, related_name="results")
    measured_value = models.FloatField()
    threshold_snapshot = models.FloatField()
    severity_snapshot = models.CharField(max_length=4)
    weight_snapshot = models.IntegerField()
    passed = models.BooleanField()
    breach_delta = models.FloatField(default=0.0)
    snapshot_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inspection_rule_results"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Inspection rule results are immutable once created.",
                code="immutable_rule_result",
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Inspection rule results cannot be deleted.",
            code="immutable_rule_result",
        )


class InspectionSchedule(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_isd_id, editable=False)
    dataset = models.OneToOneField(Dataset, on_delete=models.CASCADE, related_name="schedule")
    cron_expr = models.CharField(max_length=64, default="0 2 * * *")
    timezone = models.CharField(max_length=64, default=_default_timezone)
    active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "inspection_schedules"
        indexes = [models.Index(fields=["active", "next_run_at"])]
