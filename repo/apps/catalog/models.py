"""Datasets, fields, metadata, and the row store used by governed query."""
from __future__ import annotations

from django.db import models

from apps.platform_common.fields import EncryptedTextField
from apps.platform_common.ids import new_id


def _ds_id() -> str:
    return new_id("dts")


def _fld_id() -> str:
    return new_id("fld")


def _dmd_id() -> str:
    return new_id("dmd")


class Dataset(models.Model):
    APPROVAL_STATES = ("draft", "approved", "deprecated")

    id = models.CharField(primary_key=True, max_length=40, default=_ds_id, editable=False)
    code = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=255)
    approval_state = models.CharField(max_length=16, default="draft")
    created_by = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "datasets"


class DatasetField(models.Model):
    DATA_TYPES = ("string", "integer", "decimal", "boolean", "date", "datetime")

    id = models.CharField(primary_key=True, max_length=40, default=_fld_id, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="fields")
    field_key = models.CharField(max_length=64)
    display_name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=16, default="string")
    is_queryable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "dataset_fields"
        unique_together = (("dataset", "field_key"),)


class DatasetMetadata(models.Model):
    SENSITIVITY_LEVELS = ("low", "medium", "high", "restricted")

    id = models.CharField(primary_key=True, max_length=40, default=_dmd_id, editable=False)
    dataset = models.OneToOneField(Dataset, on_delete=models.CASCADE, related_name="metadata")
    owner = EncryptedTextField(max_length=1024)
    retention_class = models.CharField(max_length=64)
    sensitivity_level = models.CharField(max_length=16)
    updated_by = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "dataset_metadata"


class DatasetRow(models.Model):
    """Generic governed row store. Real persisted rows used by the governed
    query API. Each row is a small JSON blob keyed by field_key.
    """

    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="rows")
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dataset_rows"
        indexes = [models.Index(fields=["dataset", "id"])]
