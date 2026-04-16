"""Catalog domain services."""
from __future__ import annotations

from typing import Iterable

from apps.platform_common.errors import Conflict, NotFound, ValidationFailure

from .models import Dataset, DatasetField, DatasetMetadata


SENSITIVITY = {"low", "medium", "high", "restricted"}


def create_dataset(*, code: str, display_name: str, created_by: str) -> Dataset:
    if not code or not display_name:
        raise ValidationFailure("code and display_name required")
    if Dataset.objects.filter(code=code).exists():
        raise Conflict("Dataset code already exists", code="dataset_code_conflict")
    return Dataset.objects.create(code=code, display_name=display_name, created_by=created_by)


def add_field(*, dataset: Dataset, field_key: str, display_name: str,
              data_type: str = "string", is_queryable: bool = True) -> DatasetField:
    if data_type not in DatasetField.DATA_TYPES:
        raise ValidationFailure("invalid data_type", details={"allowed": list(DatasetField.DATA_TYPES)})
    if DatasetField.objects.filter(dataset=dataset, field_key=field_key).exists():
        raise Conflict("Field already exists for dataset", code="field_conflict")
    return DatasetField.objects.create(
        dataset=dataset,
        field_key=field_key,
        display_name=display_name,
        data_type=data_type,
        is_queryable=is_queryable,
    )


def upsert_metadata(*, dataset: Dataset, owner: str, retention_class: str,
                    sensitivity_level: str, updated_by: str) -> DatasetMetadata:
    if not owner or not retention_class or not sensitivity_level:
        raise ValidationFailure("owner, retention_class, sensitivity_level all required")
    if sensitivity_level not in SENSITIVITY:
        raise ValidationFailure(
            "invalid sensitivity_level",
            details={"allowed": sorted(SENSITIVITY)},
        )
    md, created = DatasetMetadata.objects.get_or_create(
        dataset=dataset,
        defaults={
            "owner": owner,
            "retention_class": retention_class,
            "sensitivity_level": sensitivity_level,
            "updated_by": updated_by,
        },
    )
    if not created:
        md.owner = owner
        md.retention_class = retention_class
        md.sensitivity_level = sensitivity_level
        md.updated_by = updated_by
        md.version += 1
        md.save()
    return md
