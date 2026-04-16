from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.catalog.models import Dataset
from apps.platform_common.ids import new_id


def _led_id() -> str:
    return new_id("led")


class LineageEdge(models.Model):
    RELATIONS = ("transform", "copy", "join", "aggregate", "ingest")

    id = models.CharField(primary_key=True, max_length=40, default=_led_id, editable=False)
    upstream_dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="downstream_edges")
    downstream_dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="upstream_edges")
    relation_type = models.CharField(max_length=32)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "lineage_edges"
        indexes = [
            models.Index(fields=["upstream_dataset", "recorded_at"]),
            models.Index(fields=["downstream_dataset", "recorded_at"]),
        ]
