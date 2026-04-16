"""Quality rule, inspection, and schedule HTTP views."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.models import Dataset, DatasetField
from apps.platform_common.audit import write_audit
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import NotFound, ValidationFailure
from apps.platform_common.permissions import require_capability

from . import services
from .models import (
    InspectionRun,
    InspectionRuleResult,
    InspectionSchedule,
    QualityRule,
    QualityRuleField,
)


def _rule_repr(r: QualityRule) -> Dict[str, Any]:
    field_ids = list(r.rule_fields.values_list("field_id", flat=True))
    return {
        "id": r.id,
        "dataset_id": r.dataset_id,
        "rule_type": r.rule_type,
        "severity": r.severity,
        "threshold_value": r.threshold_value,
        "field_ids": field_ids,
        "config": r.config,
        "active": r.active,
        "version": r.version,
    }


def _result_repr(rr: InspectionRuleResult) -> Dict[str, Any]:
    return {
        "id": rr.id,
        "rule_id": rr.rule_id,
        "measured_value": rr.measured_value,
        "threshold_snapshot": rr.threshold_snapshot,
        "severity_snapshot": rr.severity_snapshot,
        "weight_snapshot": rr.weight_snapshot,
        "passed": rr.passed,
        "breach_delta": rr.breach_delta,
    }


def _inspection_repr(ins: InspectionRun) -> Dict[str, Any]:
    results = list(ins.results.all().order_by("rule_id"))
    failed_p0 = sum(1 for r in results if r.severity_snapshot == "P0" and not r.passed)
    return {
        "id": ins.id,
        "dataset_id": ins.dataset_id,
        "trigger_mode": ins.trigger_mode,
        "started_at": ins.started_at.isoformat(),
        "ended_at": ins.ended_at.isoformat() if ins.ended_at else None,
        "quality_score": ins.quality_score,
        "gate_pass": ins.gate_pass,
        "failed_p0_count": failed_p0,
        "weights": services.DEFAULT_WEIGHTS,
        "status": ins.status,
        "rule_results": [_result_repr(r) for r in results],
    }


@api_view(["GET", "POST"])
def rules(request):
    require_capability(request, "quality:read")
    if request.method == "GET":
        ds = request.query_params.get("dataset_id")
        qs = QualityRule.objects.all().order_by("-created_at")
        if ds:
            qs = qs.filter(dataset_id=ds)
        return Response({"rules": [_rule_repr(r) for r in qs[:200]]})

    require_capability(request, "quality:write")
    payload = request.data or {}
    dataset_id = payload.get("dataset_id")
    rule_type = payload.get("rule_type")
    severity = payload.get("severity")
    threshold = payload.get("threshold_value")
    field_ids = payload.get("field_ids") or []
    config = payload.get("config") or {}

    if rule_type not in QualityRule.RULE_TYPES:
        raise ValidationFailure(
            "invalid rule_type", details={"allowed": list(QualityRule.RULE_TYPES)}
        )
    if severity not in QualityRule.SEVERITY:
        raise ValidationFailure(
            "invalid severity", details={"allowed": list(QualityRule.SEVERITY)}
        )
    if threshold is None:
        raise ValidationFailure("threshold_value required")

    FIELD_REQUIRED_TYPES = ("completeness", "uniqueness", "numeric_range", "distribution_drift")
    if rule_type in FIELD_REQUIRED_TYPES and not field_ids:
        raise ValidationFailure(
            "field_ids required for this rule type",
            details={"rule_type": rule_type, "required": True},
        )
    try:
        ds = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc

    rule = QualityRule.objects.create(
        dataset=ds,
        rule_type=rule_type,
        severity=severity,
        threshold_value=float(threshold),
        config=config,
        created_by=request.actor.id,
    )
    if field_ids:
        existing_field_ids = set(
            DatasetField.objects.filter(dataset=ds, id__in=field_ids).values_list("id", flat=True)
        )
        missing = set(field_ids) - existing_field_ids
        if missing:
            raise ValidationFailure(
                "field_ids reference unknown fields", details={"missing": sorted(missing)}
            )
        for fid in field_ids:
            QualityRuleField.objects.create(rule=rule, field_id=fid)
    write_audit(
        actor=request.actor,
        action="quality.create_rule",
        object_type="quality_rule",
        object_id=rule.id,
        request=request,
        payload_after={"dataset_id": ds.id, "rule_type": rule_type, "severity": severity},
    )
    return Response(_rule_repr(rule), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
def rule_detail(request, rule_id: str):
    require_capability(request, "quality:write")
    try:
        rule = QualityRule.objects.get(id=rule_id)
    except QualityRule.DoesNotExist as exc:
        raise NotFound("Rule not found") from exc
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(rule.version, expected)
    payload = request.data or {}
    fields_changed = []
    if "threshold_value" in payload:
        rule.threshold_value = float(payload["threshold_value"])
        fields_changed.append("threshold_value")
    if "active" in payload:
        rule.active = bool(payload["active"])
        fields_changed.append("active")
    if "severity" in payload:
        if payload["severity"] not in QualityRule.SEVERITY:
            raise ValidationFailure("invalid severity")
        rule.severity = payload["severity"]
        fields_changed.append("severity")
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    rule.version += 1
    rule.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="quality.update_rule",
        object_type="quality_rule",
        object_id=rule.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_rule_repr(rule))


@api_view(["POST"])
def trigger_inspection(request):
    require_capability(request, "quality:trigger")
    payload = request.data or {}
    dataset_id = payload.get("dataset_id")
    if not dataset_id:
        raise ValidationFailure("dataset_id required")
    try:
        ds = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc
    run = services.run_inspection(dataset=ds, actor_id=request.actor.id, trigger_mode="manual")
    write_audit(
        actor=request.actor,
        action="quality.trigger_inspection",
        object_type="inspection_run",
        object_id=run.id,
        request=request,
        payload_after={"dataset_id": ds.id, "gate_pass": run.gate_pass, "score": run.quality_score},
    )
    return Response(_inspection_repr(run), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def list_inspections(request):
    require_capability(request, "quality:read")
    qs = InspectionRun.objects.all().order_by("-started_at")[:100]
    return Response({"inspections": [{
        "id": i.id, "dataset_id": i.dataset_id, "quality_score": i.quality_score,
        "gate_pass": i.gate_pass, "status": i.status,
        "started_at": i.started_at.isoformat(),
    } for i in qs]})


@api_view(["GET"])
def inspection_detail(request, inspection_id: str):
    require_capability(request, "quality:read")
    try:
        ins = InspectionRun.objects.get(id=inspection_id)
    except InspectionRun.DoesNotExist as exc:
        raise NotFound("Inspection not found") from exc
    return Response(_inspection_repr(ins))


@api_view(["GET", "POST"])
def schedules(request):
    require_capability(request, "quality:read")
    if request.method == "GET":
        qs = InspectionSchedule.objects.all().order_by("-updated_at")[:200]
        return Response({"schedules": [{
            "id": s.id,
            "dataset_id": s.dataset_id,
            "cron_expr": s.cron_expr,
            "timezone": s.timezone,
            "active": s.active,
            "version": s.version,
        } for s in qs]})

    require_capability(request, "schedules:write")
    payload = request.data or {}
    dataset_id = payload.get("dataset_id")
    if not dataset_id:
        raise ValidationFailure("dataset_id required")
    try:
        ds = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc
    from django.conf import settings as django_settings
    from apps.platform_common.cron import is_valid as cron_is_valid, next_fire

    cron = payload.get("cron_expr") or "0 2 * * *"
    tz = payload.get("timezone") or django_settings.TIME_ZONE or "UTC"
    if not cron_is_valid(cron):
        raise ValidationFailure(
            "cron_expr must be a valid 5-field cron expression",
            code="invalid_cron",
        )
    next_at = next_fire(cron, tz=tz)
    sched, created = InspectionSchedule.objects.get_or_create(
        dataset=ds,
        defaults={
            "cron_expr": cron,
            "timezone": tz,
            "active": True,
            "next_run_at": next_at,
        },
    )
    if not created:
        # Upsert hit an existing schedule — enforce OCC on the update path.
        from apps.platform_common.concurrency import check_version, parse_if_match

        expected = parse_if_match(request.headers.get("If-Match"))
        check_version(sched.version, expected)
        sched.cron_expr = cron
        sched.timezone = tz
        sched.active = bool(payload.get("active", sched.active))
        sched.next_run_at = next_at
        sched.version += 1
        sched.save()
    write_audit(
        actor=request.actor,
        action="quality.upsert_schedule",
        object_type="inspection_schedule",
        object_id=sched.id,
        request=request,
        payload_after={"dataset_id": ds.id, "cron_expr": cron, "timezone": tz},
    )
    return Response(
        {
            "id": sched.id,
            "dataset_id": sched.dataset_id,
            "cron_expr": sched.cron_expr,
            "timezone": sched.timezone,
            "active": sched.active,
            "version": sched.version,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
