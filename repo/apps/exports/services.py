"""Export job creation, multipart row splitting, and retention."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import timedelta
from pathlib import Path
from typing import Iterable, List, Tuple

from django.conf import settings
from django.utils import timezone

from apps.platform_common.errors import (
    DomainRuleViolation,
    ExportExpired,
    NotFound,
    ValidationFailure,
)

from .models import ExportFile, ExportJob


ROW_CAP_PER_FILE = 250_000
EXPORT_RETENTION_DAYS = 30


def split_rows(total_rows: int) -> List[Tuple[int, int]]:
    """Return ``[(part_number, row_count), ...]`` for ``total_rows``.

    Each part holds at most :data:`ROW_CAP_PER_FILE` rows. Exposed for unit
    testing the splitter independent of any IO.
    """
    if total_rows < 0:
        raise ValueError("total_rows must be non-negative")
    parts = []
    full = total_rows // ROW_CAP_PER_FILE
    rem = total_rows % ROW_CAP_PER_FILE
    n = 1
    for _ in range(full):
        parts.append((n, ROW_CAP_PER_FILE))
        n += 1
    if rem > 0 or total_rows == 0:
        parts.append((n, rem))
    return parts


def _write_csv(path: Path, rows: List[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    with path.open("wb") as out:
        buf = io.StringIO()
        writer = None
        if rows:
            fieldnames = sorted({k for r in rows for k in r.keys()})
            writer = csv.DictWriter(buf, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        data = buf.getvalue().encode("utf-8")
        out.write(data)
        h.update(data)
    return h.hexdigest()


def _write_xlsx(path: Path, rows: List[dict]) -> str:
    """Write a real XLSX workbook (Office Open XML, .xlsx) using openpyxl.

    The resulting file is a valid ZIP-packaged XLSX with one worksheet whose
    first row is the header (sorted union of input keys) and subsequent rows
    are the data values. The file is then SHA-256 checksummed.
    """
    from openpyxl import Workbook  # local import to keep module import light

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook(write_only=False)
    ws = wb.active
    ws.title = "data"
    if rows:
        fieldnames = sorted({k for r in rows for k in r.keys()})
        ws.append(fieldnames)
        for r in rows:
            ws.append([r.get(fn) for fn in fieldnames])
    else:
        ws.append([])
    wb.save(str(path))
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_export(*, report_run, fmt: str, requested_by) -> ExportJob:
    if fmt not in ExportJob.FORMATS:
        raise ValidationFailure("invalid export format",
                                details={"allowed": list(ExportJob.FORMATS)})
    rows = list(report_run.rows_snapshot or [])
    job = ExportJob.objects.create(
        report_run=report_run,
        format=fmt,
        status="running",
        total_rows=len(rows),
        expires_at=timezone.now() + timedelta(days=EXPORT_RETENTION_DAYS),
        requested_by=requested_by,
    )
    parts = split_rows(len(rows))
    base_dir = Path(settings.EXPORT_STORAGE_DIR) / job.id
    for part_no, count in parts:
        chunk = rows[(part_no - 1) * ROW_CAP_PER_FILE : (part_no - 1) * ROW_CAP_PER_FILE + count]
        ext = "csv" if fmt == "csv" else "xlsx"
        path = base_dir / f"part-{part_no:04d}.{ext}"
        checksum = _write_csv(path, chunk) if fmt == "csv" else _write_xlsx(path, chunk)
        ExportFile.objects.create(
            export_job=job,
            part_number=part_no,
            row_count=count,
            path=str(path),
            checksum_sha256=checksum,
        )
    job.file_count = len(parts)
    job.status = "complete"
    job.completed_at = timezone.now()
    job.save(update_fields=["file_count", "status", "completed_at"])
    return job


def assert_not_expired(job: ExportJob) -> None:
    if job.expires_at <= timezone.now():
        raise ExportExpired("Export has expired", details={"export_job_id": job.id})


def expire_old_jobs(now=None) -> int:
    now = now or timezone.now()
    qs = ExportJob.objects.filter(expires_at__lte=now).exclude(status="expired")
    n = qs.count()
    qs.update(status="expired")
    return n
