"""Audit and monitoring HTTP views."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.platform_common.audit import write_audit
from apps.platform_common.errors import Forbidden, ValidationFailure
from apps.platform_common.permissions import (
    require_authenticated,
    require_capability,
)

from . import services
from .models import EVENT_TYPES, AuditExportJob, AuditLog, EventLog


def _audit_repr(a: AuditLog) -> Dict[str, Any]:
    return {
        "id": a.id,
        "actor_user_id": a.actor_user_id,
        "action": a.action,
        "object_type": a.object_type,
        "object_id": a.object_id,
        "request_id": a.request_id,
        "created_at": a.created_at.isoformat(),
        "payload_after": a.payload_after,
    }


@api_view(["GET"])
def metrics(request):
    require_capability(request, "monitoring:read")
    window = request.query_params.get("window_minutes")
    try:
        win = int(window) if window else 60 * 24
    except ValueError as exc:
        raise ValidationFailure("window_minutes must be int") from exc
    return Response(services.compute_metrics(window_minutes=win))


@api_view(["POST"])
def post_event(request):
    require_capability(request, "monitoring:write_event")
    payload = request.data or {}
    et = payload.get("event_type")
    if et not in EVENT_TYPES:
        raise ValidationFailure(
            "invalid event_type", details={"allowed": list(EVENT_TYPES)}
        )
    EventLog.objects.create(
        event_type=et,
        actor_user_id=payload.get("actor_user_id") or (request.actor.id if request.actor else ""),
        dataset_id=payload.get("dataset_id") or "",
        payload=payload.get("payload") or {},
    )
    return Response({"recorded": True}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def audit_logs(request):
    require_capability(request, "audit:read")
    qs = AuditLog.objects.all().order_by("-created_at")[:200]
    return Response({"audit_logs": [_audit_repr(a) for a in qs]})


@api_view(["POST"])
def audit_export(request):
    # Audit export remains administrator-only.
    require_capability(request, "audit:export")
    payload = request.data or {}
    start = payload.get("start")
    end = payload.get("end")
    if not start or not end:
        raise ValidationFailure("start and end ISO timestamps required")
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValidationFailure("start/end must be ISO-8601") from exc

    qs = AuditLog.objects.filter(created_at__gte=s, created_at__lte=e).order_by("created_at")
    rows = [_audit_repr(a) for a in qs]
    job = AuditExportJob.objects.create(
        requested_by=request.actor.id,
        range_start=s,
        range_end=e,
        record_count=len(rows),
        payload=rows,
    )
    write_audit(
        actor=request.actor,
        action="audit.export",
        object_type="audit_export_job",
        object_id=job.id,
        request=request,
        payload_after={"start": start, "end": end, "record_count": job.record_count},
    )
    return Response(
        {
            "audit_export_id": job.id,
            "record_count": job.record_count,
            "start": start,
            "end": end,
            "created_at": job.created_at.isoformat(),
        },
        status=status.HTTP_202_ACCEPTED,
    )
