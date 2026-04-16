"""Analytics, report definition, run, and governed query views."""
from __future__ import annotations

from typing import Any, Dict

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.models import Dataset
from apps.platform_common.audit import write_audit
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import Forbidden, NotFound, ValidationFailure
from apps.platform_common.permissions import (
    has_capability,
    require_authenticated,
    require_capability,
)

from . import services
from .models import ReportDefinition, ReportRun, ReportSchedule


def _def_repr(d: ReportDefinition) -> Dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "dataset_id": d.dataset_id,
        "filter_schema": d.filter_schema,
        "time_window_schema": d.time_window_schema,
        "permission_scope": d.permission_scope,
        "version": d.version,
    }


def _run_repr(r: ReportRun) -> Dict[str, Any]:
    return {
        "id": r.id,
        "report_definition_id": r.report_definition_id,
        "requested_by": r.requested_by_id,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "total_rows": r.total_rows,
        "resolved_filters": r.resolved_filters,
        "resolved_time_window": r.resolved_time_window,
    }


def _scope_allows(request, definition: ReportDefinition) -> bool:
    if has_capability(request, "reports:write"):
        return True
    scope = definition.permission_scope or {}
    allowed_users = scope.get("user_ids")
    if isinstance(allowed_users, list) and allowed_users:
        return request.actor.id in allowed_users
    # Default: all authenticated users with reports:read can run if no scope
    return True


@api_view(["POST"])
def query_dataset(request, dataset_id: str):
    require_capability(request, "datasets:query")
    try:
        ds = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc
    payload = request.data or {}
    allow_unapproved = has_capability(request, "datasets:write")
    result = services.execute_query(dataset=ds, payload=payload, allow_unapproved=allow_unapproved)
    return Response(result)


@api_view(["GET", "POST"])
def definitions(request):
    require_capability(request, "reports:read")
    if request.method == "GET":
        qs = ReportDefinition.objects.all().order_by("name")
        if not has_capability(request, "reports:write"):
            qs = [d for d in qs if _scope_allows(request, d)]
        return Response({"definitions": [_def_repr(d) for d in qs[:200]]})

    require_capability(request, "reports:write")
    payload = request.data or {}
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValidationFailure("name required")
    try:
        ds = Dataset.objects.get(id=payload.get("dataset_id"))
    except Dataset.DoesNotExist as exc:
        raise NotFound("Dataset not found") from exc
    if ReportDefinition.objects.filter(name=name).exists():
        raise ValidationFailure("name already exists")
    d = ReportDefinition.objects.create(
        name=name,
        dataset=ds,
        filter_schema=payload.get("filter_schema") or {},
        time_window_schema=payload.get("time_window_schema") or {},
        permission_scope=payload.get("permission_scope") or {},
        query_plan=payload.get("query_plan") or {},
        created_by=request.actor,
    )
    write_audit(
        actor=request.actor,
        action="reports.create_definition",
        object_type="report_definition",
        object_id=d.id,
        request=request,
        payload_after={"name": name},
    )
    return Response(_def_repr(d), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
def definition_detail(request, definition_id: str):
    require_capability(request, "reports:write")
    try:
        d = ReportDefinition.objects.get(id=definition_id)
    except ReportDefinition.DoesNotExist as exc:
        raise NotFound("Report definition not found") from exc
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(d.version, expected)
    payload = request.data or {}
    fields_changed = []
    for f in ("filter_schema", "time_window_schema", "permission_scope", "query_plan"):
        if f in payload:
            setattr(d, f, payload[f])
            fields_changed.append(f)
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    d.version += 1
    d.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="reports.update_definition",
        object_type="report_definition",
        object_id=d.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_def_repr(d))


@api_view(["POST"])
def run_report(request):
    require_capability(request, "reports:run")
    payload = request.data or {}
    def_id = payload.get("report_definition_id")
    if not def_id:
        raise ValidationFailure("report_definition_id required")
    try:
        d = ReportDefinition.objects.get(id=def_id)
    except ReportDefinition.DoesNotExist as exc:
        raise NotFound("Report definition not found") from exc
    if not _scope_allows(request, d):
        raise Forbidden("Report definition outside permission scope")
    # Execute as a governed query against the bound dataset.
    filters = []
    for k, v in (payload.get("filters") or {}).items():
        filters.append({"field": k, "op": "eq", "value": v})
    query_payload = {"select": [], "filters": filters, "sort": [], "limit": services.MAX_LIMIT}
    result = services.execute_query(
        dataset=d.dataset,
        payload=query_payload,
        allow_unapproved=has_capability(request, "datasets:write"),
    )
    run = ReportRun.objects.create(
        report_definition=d,
        requested_by=request.actor,
        resolved_filters=payload.get("filters") or {},
        resolved_time_window=payload.get("time_window") or {},
        status="complete",
        ended_at=timezone.now(),
        total_rows=result["row_count"],
        rows_snapshot=result["rows"],
    )
    write_audit(
        actor=request.actor,
        action="reports.run",
        object_type="report_run",
        object_id=run.id,
        request=request,
        payload_after={"definition_id": d.id, "rows": run.total_rows},
    )
    return Response(_run_repr(run), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def run_detail(request, run_id: str):
    require_capability(request, "reports:read")
    try:
        run = ReportRun.objects.select_related("report_definition").get(id=run_id)
    except ReportRun.DoesNotExist as exc:
        raise NotFound("Run not found") from exc
    if not _scope_allows(request, run.report_definition):
        raise Forbidden("Run outside permission scope")
    return Response(_run_repr(run))


def _sched_repr(s: ReportSchedule) -> Dict[str, Any]:
    return {
        "id": s.id,
        "report_definition_id": s.report_definition_id,
        "cron_expr": s.cron_expr,
        "timezone": s.timezone,
        "active": s.active,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_enqueued_at": s.last_enqueued_at.isoformat() if s.last_enqueued_at else None,
        "version": s.version,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _validate_cron(expr: str) -> None:
    from apps.platform_common.cron import is_valid

    parts = expr.strip().split()
    if len(parts) != 5 or not is_valid(expr):
        raise ValidationFailure(
            "cron_expr must be a valid 5-field cron expression",
            code="invalid_cron",
        )


@api_view(["GET", "POST"])
def schedules(request):
    """List or create persisted schedules for report definitions."""
    if request.method == "GET":
        require_capability(request, "reports:read")
        qs = ReportSchedule.objects.all().order_by("-updated_at")
        def_id = request.query_params.get("report_definition_id")
        if def_id:
            qs = qs.filter(report_definition_id=def_id)
        if not has_capability(request, "reports:write"):
            qs = [s for s in qs if _scope_allows(request, s.report_definition)]
        return Response({"schedules": [_sched_repr(s) for s in qs[:200]]})

    require_capability(request, "reports:write")
    payload = request.data or {}
    def_id = payload.get("report_definition_id")
    cron = (payload.get("cron_expr") or "0 3 * * *").strip()
    from django.conf import settings as django_settings
    tz = (payload.get("timezone") or django_settings.TIME_ZONE or "UTC").strip()
    active = bool(payload.get("active", True))
    if not def_id:
        raise ValidationFailure("report_definition_id required")
    _validate_cron(cron)
    try:
        d = ReportDefinition.objects.get(id=def_id)
    except ReportDefinition.DoesNotExist as exc:
        raise NotFound("Report definition not found") from exc
    from apps.platform_common.cron import next_fire

    s = ReportSchedule.objects.create(
        report_definition=d,
        cron_expr=cron,
        timezone=tz,
        active=active,
        created_by=request.actor,
        next_run_at=next_fire(cron, tz=tz),
    )
    write_audit(
        actor=request.actor,
        action="reports.create_schedule",
        object_type="report_schedule",
        object_id=s.id,
        request=request,
        payload_after={
            "report_definition_id": d.id,
            "cron_expr": cron,
            "timezone": tz,
            "active": active,
        },
    )
    return Response(_sched_repr(s), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def schedule_detail(request, schedule_id: str):
    require_capability(request, "reports:read")
    try:
        s = ReportSchedule.objects.select_related("report_definition").get(id=schedule_id)
    except ReportSchedule.DoesNotExist as exc:
        raise NotFound("Schedule not found") from exc
    if not _scope_allows(request, s.report_definition):
        raise Forbidden("Schedule outside permission scope")
    if request.method == "GET":
        return Response(_sched_repr(s))

    require_capability(request, "reports:write")
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(s.version, expected)
    payload = request.data or {}
    from apps.platform_common.cron import next_fire

    fields_changed = []
    cron_or_tz_changed = False
    if "cron_expr" in payload:
        cron = (payload["cron_expr"] or "").strip()
        _validate_cron(cron)
        s.cron_expr = cron
        fields_changed.append("cron_expr")
        cron_or_tz_changed = True
    if "timezone" in payload:
        from django.conf import settings as django_settings
        s.timezone = (payload["timezone"] or django_settings.TIME_ZONE or "UTC").strip()
        fields_changed.append("timezone")
        cron_or_tz_changed = True
    if "active" in payload:
        s.active = bool(payload["active"])
        fields_changed.append("active")
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    if cron_or_tz_changed:
        # Recompute the next firing instant whenever cron or timezone shifts.
        s.next_run_at = next_fire(s.cron_expr, tz=s.timezone)
        fields_changed.append("next_run_at")
    s.version += 1
    s.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="reports.update_schedule",
        object_type="report_schedule",
        object_id=s.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_sched_repr(s))
