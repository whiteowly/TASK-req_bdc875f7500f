"""Export job HTTP views."""
from __future__ import annotations

from typing import Any, Dict

from django.http import FileResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.analytics.models import ReportRun
from apps.platform_common.audit import write_audit
from apps.platform_common.errors import (
    ExportExpired,
    Forbidden,
    NotFound,
    ValidationFailure,
)
from apps.platform_common.permissions import (
    has_capability,
    require_authenticated,
    require_capability,
)

from . import services
from .models import ExportFile, ExportJob


def _job_repr(j: ExportJob) -> Dict[str, Any]:
    return {
        "export_job_id": j.id,
        "format": j.format,
        "total_rows": j.total_rows,
        "file_count": j.file_count,
        "status": j.status,
        "expires_at": j.expires_at.isoformat(),
        "requested_by": j.requested_by_id,
        "created_at": j.created_at.isoformat(),
    }


def _file_repr(f: ExportFile) -> Dict[str, Any]:
    return {
        "id": f.id,
        "part_number": f.part_number,
        "row_count": f.row_count,
        "checksum_sha256": f.checksum_sha256,
    }


def _can_access_job(request, j: ExportJob) -> bool:
    if has_capability(request, "exports:read_all"):
        return True
    return j.requested_by_id == request.actor.id


@api_view(["POST"])
def create_export(request, run_id: str):
    require_capability(request, "exports:write")
    try:
        run = ReportRun.objects.get(id=run_id)
    except ReportRun.DoesNotExist as exc:
        raise NotFound("Report run not found") from exc
    payload = request.data or {}
    fmt = (payload.get("format") or "csv").lower()
    job = services.create_export(report_run=run, fmt=fmt, requested_by=request.actor)
    write_audit(
        actor=request.actor,
        action="exports.create",
        object_type="export_job",
        object_id=job.id,
        request=request,
        payload_after={"run_id": run.id, "format": fmt, "total_rows": job.total_rows},
    )
    return Response(_job_repr(job), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def export_detail(request, export_job_id: str):
    require_authenticated(request)
    try:
        j = ExportJob.objects.get(id=export_job_id)
    except ExportJob.DoesNotExist as exc:
        raise NotFound("Export not found") from exc
    if not _can_access_job(request, j):
        raise Forbidden("Export outside permission scope")
    return Response(_job_repr(j))


@api_view(["GET"])
def export_files(request, export_job_id: str):
    require_authenticated(request)
    try:
        j = ExportJob.objects.get(id=export_job_id)
    except ExportJob.DoesNotExist as exc:
        raise NotFound("Export not found") from exc
    if not _can_access_job(request, j):
        raise Forbidden("Export outside permission scope")
    services.assert_not_expired(j)
    files = list(j.files.order_by("part_number"))
    return Response({"files": [_file_repr(f) for f in files]})


@api_view(["GET"])
def download_file(request, export_job_id: str, part_number: int):
    require_authenticated(request)
    try:
        j = ExportJob.objects.get(id=export_job_id)
    except ExportJob.DoesNotExist as exc:
        raise NotFound("Export not found") from exc
    if not _can_access_job(request, j):
        raise Forbidden("Export outside permission scope")
    services.assert_not_expired(j)
    try:
        f = j.files.get(part_number=int(part_number))
    except ExportFile.DoesNotExist as exc:
        raise NotFound("Export file part not found") from exc
    return FileResponse(open(f.path, "rb"), as_attachment=True, filename=f"part-{f.part_number:04d}")
