"""Monitoring metrics computation from local-only event logs."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict

from django.db.models import Count
from django.utils import timezone

from .models import EventLog


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den > 0 else 0.0


def compute_metrics(window_minutes: int = 60 * 24) -> Dict[str, float]:
    end = timezone.now()
    start = end - timedelta(minutes=window_minutes)
    qs = EventLog.objects.filter(event_ts__gte=start, event_ts__lte=end)
    counts = qs.values("event_type").annotate(n=Count("id"))
    by_type = {row["event_type"]: row["n"] for row in counts}

    ingest_ok = by_type.get("ingestion_success", 0)
    ingest_fail = by_type.get("ingestion_failure", 0)
    inspect_ok = by_type.get("inspection_success", 0)
    inspect_fail = by_type.get("inspection_failure", 0)
    export_ok = by_type.get("export_success", 0)
    export_fail = by_type.get("export_failure", 0)
    impressions = by_type.get("recommendation_impression", 0)
    clicks = by_type.get("recommendation_click", 0)

    # Backup schedule visibility
    backup_info = _backup_schedule_info()

    return {
        "ingestion_success_rate": _ratio(ingest_ok, ingest_ok + ingest_fail),
        "inspection_success_rate": _ratio(inspect_ok, inspect_ok + inspect_fail),
        "export_success_rate": _ratio(export_ok, export_ok + export_fail),
        "recommendation_impressions": impressions,
        "recommendation_clicks": clicks,
        "recommendation_ctr": _ratio(clicks, impressions),
        "window_minutes": window_minutes,
        "backup_schedule": backup_info,
    }


def _backup_schedule_info() -> Dict:
    try:
        from apps.platform_common.models import BackupScheduleState
        state = BackupScheduleState.get_or_create_singleton()
        return {
            "active": state.active,
            "cron_expr": state.cron_expr,
            "next_run_at": state.next_run_at.isoformat() if state.next_run_at else None,
            "last_run_at": state.last_run_at.isoformat() if state.last_run_at else None,
            "last_run_status": state.last_run_status or None,
            "last_run_label": state.last_run_label or None,
        }
    except Exception:
        return {}
