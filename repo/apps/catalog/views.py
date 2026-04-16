"""Catalog HTTP views (datasets, fields, metadata)."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.platform_common.audit import write_audit
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import Forbidden, NotFound, ValidationFailure
from apps.platform_common.permissions import (
    has_capability,
    require_capability,
)

from . import services
from .models import Dataset, DatasetField, DatasetMetadata


def _ds_repr(d: Dataset) -> Dict[str, Any]:
    return {
        "id": d.id,
        "code": d.code,
        "display_name": d.display_name,
        "approval_state": d.approval_state,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        "version": d.version,
    }


def _field_repr(f: DatasetField) -> Dict[str, Any]:
    return {
        "id": f.id,
        "dataset_id": f.dataset_id,
        "field_key": f.field_key,
        "display_name": f.display_name,
        "data_type": f.data_type,
        "is_queryable": f.is_queryable,
        "version": f.version,
    }


def _md_repr(md: DatasetMetadata) -> Dict[str, Any]:
    return {
        "dataset_id": md.dataset_id,
        "owner": md.owner,
        "retention_class": md.retention_class,
        "sensitivity_level": md.sensitivity_level,
        "version": md.version,
        "updated_at": md.updated_at.isoformat(),
    }


def _can_read_dataset(request, ds: Dataset) -> bool:
    if has_capability(request, "datasets:write"):
        return True
    return ds.approval_state == "approved"


@api_view(["GET", "POST"])
def datasets(request):
    if request.method == "GET":
        require_capability(request, "datasets:read")
        qs = Dataset.objects.all().order_by("code")
        if not has_capability(request, "datasets:write"):
            qs = qs.filter(approval_state="approved")
        return Response({"datasets": [_ds_repr(d) for d in qs[:200]]})

    require_capability(request, "datasets:write")
    payload = request.data or {}
    ds = services.create_dataset(
        code=(payload.get("code") or "").strip(),
        display_name=(payload.get("display_name") or "").strip(),
        created_by=request.actor.id,
    )
    write_audit(
        actor=request.actor,
        action="datasets.create",
        object_type="dataset",
        object_id=ds.id,
        request=request,
        payload_after={"code": ds.code, "display_name": ds.display_name},
    )
    return Response(_ds_repr(ds), status=status.HTTP_201_CREATED)


def _get_dataset(dataset_id: str) -> Dataset:
    try:
        return Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc


@api_view(["GET", "PATCH"])
def dataset_detail(request, dataset_id: str):
    require_capability(request, "datasets:read")
    ds = _get_dataset(dataset_id)
    if not _can_read_dataset(request, ds):
        raise Forbidden("Dataset is not approved for non-operations roles")
    if request.method == "GET":
        return Response(_ds_repr(ds))

    require_capability(request, "datasets:write")
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(ds.version, expected)
    payload = request.data or {}
    fields_changed = []
    if "display_name" in payload:
        new_name = (payload.get("display_name") or "").strip()
        if not new_name:
            raise ValidationFailure("display_name cannot be empty")
        ds.display_name = new_name
        fields_changed.append("display_name")
    if "approval_state" in payload:
        new_state = payload["approval_state"]
        if new_state not in Dataset.APPROVAL_STATES:
            raise ValidationFailure("invalid approval_state",
                                    details={"allowed": list(Dataset.APPROVAL_STATES)})
        ds.approval_state = new_state
        fields_changed.append("approval_state")
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    ds.version += 1
    ds.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="datasets.update",
        object_type="dataset",
        object_id=ds.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_ds_repr(ds))


@api_view(["GET", "POST"])
def dataset_fields(request, dataset_id: str):
    require_capability(request, "datasets:read")
    ds = _get_dataset(dataset_id)
    if not _can_read_dataset(request, ds):
        raise Forbidden("Dataset is not approved for non-operations roles")
    if request.method == "GET":
        fields = list(ds.fields.all().order_by("field_key"))
        return Response({"fields": [_field_repr(f) for f in fields]})

    require_capability(request, "datasets:write")
    payload = request.data or {}
    field = services.add_field(
        dataset=ds,
        field_key=(payload.get("field_key") or "").strip(),
        display_name=(payload.get("display_name") or "").strip(),
        data_type=payload.get("data_type") or "string",
        is_queryable=bool(payload.get("is_queryable", True)),
    )
    write_audit(
        actor=request.actor,
        action="datasets.add_field",
        object_type="dataset_field",
        object_id=field.id,
        request=request,
        payload_after={"dataset_id": ds.id, "field_key": field.field_key},
    )
    return Response(_field_repr(field), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def dataset_metadata(request, dataset_id: str):
    require_capability(request, "datasets:read")
    ds = _get_dataset(dataset_id)
    if not _can_read_dataset(request, ds):
        raise Forbidden("Dataset is not approved for non-operations roles")
    if request.method == "GET":
        try:
            md = ds.metadata
        except DatasetMetadata.DoesNotExist as exc:
            raise NotFound("Metadata not set for dataset") from exc
        return Response(_md_repr(md))

    require_capability(request, "metadata:write")
    payload = request.data or {}
    try:
        existing = ds.metadata
        expected = parse_if_match(request.headers.get("If-Match"))
        check_version(existing.version, expected)
    except DatasetMetadata.DoesNotExist:
        # On first set, If-Match is not required (no version exists yet).
        pass
    md = services.upsert_metadata(
        dataset=ds,
        owner=(payload.get("owner") or "").strip(),
        retention_class=(payload.get("retention_class") or "").strip(),
        sensitivity_level=(payload.get("sensitivity_level") or "").strip(),
        updated_by=request.actor.id,
    )
    write_audit(
        actor=request.actor,
        action="metadata.update",
        object_type="dataset_metadata",
        object_id=md.id,
        request=request,
        payload_after={
            "owner": md.owner,
            "retention_class": md.retention_class,
            "sensitivity_level": md.sensitivity_level,
        },
    )
    return Response(_md_repr(md))
