"""Real scheduler tick logic.

Two cron-driven schedule tables exist in the system:

- ``apps.quality.models.InspectionSchedule`` — default cron ``0 2 * * *``
  (nightly at 02:00 in the schedule's local timezone)
- ``apps.analytics.models.ReportSchedule`` — default cron ``0 3 * * *``

A scheduler "tick" finds active schedules whose ``next_run_at`` is in the
past, fires the associated work (real ``InspectionRun`` for quality,
real ``ReportRun`` for reports), and advances ``next_run_at`` /
``last_enqueued_at``. The same code is exercised by tests and by the
long-running ``scheduler`` container in docker-compose.
"""
from __future__ import annotations

from datetime import timezone as dt_timezone
from typing import Dict, List

from django.db import transaction
from django.utils import timezone

from .cron import next_fire


def _ensure_next_run_at(schedule, *, now=None) -> None:
    if schedule.next_run_at is None:
        schedule.next_run_at = next_fire(
            schedule.cron_expr, tz=schedule.timezone, now=now,
        )
        schedule.save(update_fields=["next_run_at"])


def initialize_pending_schedules(now=None) -> int:
    """Backfill ``next_run_at`` for any active schedule that is missing it.

    Idempotent. Useful at scheduler startup so an operator doesn't need to
    PATCH each schedule manually after creation.
    """
    from apps.analytics.models import ReportSchedule
    from apps.quality.models import InspectionSchedule

    n = 0
    for s in InspectionSchedule.objects.filter(active=True, next_run_at__isnull=True):
        _ensure_next_run_at(s, now=now)
        n += 1
    for s in ReportSchedule.objects.filter(active=True, next_run_at__isnull=True):
        _ensure_next_run_at(s, now=now)
        n += 1
    return n


def tick_inspection_schedules(now=None) -> List[Dict[str, str]]:
    """Fire every due inspection schedule.

    Returns a list of dicts ``{schedule_id, dataset_id, inspection_run_id,
    next_run_at}`` describing the work that ran.
    """
    from apps.quality.models import InspectionSchedule
    from apps.quality.services import run_inspection

    now = now or timezone.now()
    out: List[Dict[str, str]] = []
    due = list(
        InspectionSchedule.objects.select_related("dataset")
        .filter(active=True, next_run_at__lte=now)
    )
    for s in due:
        with transaction.atomic():
            run = run_inspection(
                dataset=s.dataset, actor_id="scheduler", trigger_mode="scheduled"
            )
            s.last_enqueued_at = now
            s.next_run_at = next_fire(s.cron_expr, tz=s.timezone, now=now)
            s.version += 1
            s.save(update_fields=["last_enqueued_at", "next_run_at", "version", "updated_at"])
        out.append({
            "schedule_id": s.id,
            "dataset_id": s.dataset_id,
            "inspection_run_id": run.id,
            "next_run_at": s.next_run_at.isoformat(),
        })
    return out


def tick_report_schedules(now=None) -> List[Dict[str, str]]:
    """Fire every due report schedule, creating a ``ReportRun`` for each."""
    from apps.analytics.models import ReportSchedule, ReportRun
    from apps.analytics.services import execute_query, MAX_LIMIT

    now = now or timezone.now()
    out: List[Dict[str, str]] = []
    due = list(
        ReportSchedule.objects.select_related("report_definition")
        .filter(active=True, next_run_at__lte=now)
    )
    for s in due:
        d = s.report_definition
        with transaction.atomic():
            # Execute the same governed query path the synchronous
            # POST /reports/runs endpoint uses, so scheduled runs are
            # equivalent in behavior to operator-triggered runs.
            result = execute_query(
                dataset=d.dataset,
                payload={"select": [], "filters": [], "sort": [], "limit": MAX_LIMIT},
                allow_unapproved=True,
            )
            run = ReportRun.objects.create(
                report_definition=d,
                requested_by=None,
                resolved_filters={},
                resolved_time_window={},
                status="complete",
                ended_at=now,
                total_rows=result["row_count"],
                rows_snapshot=result["rows"],
            )
            s.last_enqueued_at = now
            s.next_run_at = next_fire(s.cron_expr, tz=s.timezone, now=now)
            s.version += 1
            s.save(update_fields=["last_enqueued_at", "next_run_at", "version", "updated_at"])
        out.append({
            "schedule_id": s.id,
            "report_definition_id": d.id,
            "report_run_id": run.id,
            "rows": str(run.total_rows),
            "next_run_at": s.next_run_at.isoformat(),
        })
    return out


def tick_backup_schedule(now=None) -> Dict[str, str]:
    """Run the nightly backup if the backup schedule is due.

    Returns a dict with backup details if a backup ran, or an empty dict.
    """
    import logging

    from .models import BackupScheduleState

    now = now or timezone.now()
    state = BackupScheduleState.get_or_create_singleton()
    if not state.active:
        return {}

    # Initialize next_run_at if missing.
    if state.next_run_at is None:
        state.next_run_at = next_fire(state.cron_expr, tz=state.timezone, now=now)
        state.save(update_fields=["next_run_at"])
        return {}

    if state.next_run_at > now:
        return {}

    log = logging.getLogger(__name__)
    with transaction.atomic():
        state = BackupScheduleState.objects.select_for_update().get(pk=1)
        if state.next_run_at is None or state.next_run_at > now:
            return {}

        try:
            from .backup import run_backup
            manifest = run_backup()
            state.last_run_status = "success"
            state.last_run_label = manifest.get("label", "")
        except Exception as exc:
            log.exception("scheduled backup failed: %s", exc)
            state.last_run_status = "failed"
            state.last_run_label = ""

        state.last_run_at = now
        state.next_run_at = next_fire(state.cron_expr, tz=state.timezone, now=now)
        state.save(update_fields=[
            "last_run_at", "last_run_status", "last_run_label", "next_run_at",
        ])

    return {
        "status": state.last_run_status,
        "label": state.last_run_label,
        "next_run_at": state.next_run_at.isoformat(),
    }


def tick_all(now=None) -> Dict[str, List[Dict[str, str]]]:
    """One full scheduler tick: initialize, fire schedules, and run backup."""
    initialize_pending_schedules(now=now)
    backup_result = tick_backup_schedule(now=now)
    return {
        "inspections": tick_inspection_schedules(now=now),
        "reports": tick_report_schedules(now=now),
        "backup": backup_result,
    }
