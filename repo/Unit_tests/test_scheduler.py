"""Real scheduler tick: due ReportSchedule and InspectionSchedule records
actually fire and produce runs, ``next_run_at`` advances, and
``last_enqueued_at`` is set."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from django.utils import timezone as dj_tz

from apps.analytics.models import (
    ReportDefinition,
    ReportRun,
    ReportSchedule,
)
from apps.catalog.models import Dataset, DatasetRow
from apps.platform_common.cron import next_fire
from apps.platform_common.scheduler import (
    initialize_pending_schedules,
    tick_all,
    tick_inspection_schedules,
    tick_report_schedules,
)
from apps.quality.models import (
    InspectionRun,
    InspectionSchedule,
    QualityRule,
    QualityRuleField,
)


# ---------------------------------------------------------------------------
# Cron evaluator
# ---------------------------------------------------------------------------

def test_next_fire_resolves_default_inspection_schedule():
    base = datetime(2026, 4, 15, 1, 30, tzinfo=timezone.utc)
    nxt = next_fire("0 2 * * *", tz="UTC", now=base)
    assert nxt == datetime(2026, 4, 15, 2, 0, tzinfo=timezone.utc)


def test_next_fire_default_report_schedule():
    base = datetime(2026, 4, 15, 4, 0, tzinfo=timezone.utc)
    nxt = next_fire("0 3 * * *", tz="UTC", now=base)
    # Already past 03:00 today → should fire tomorrow 03:00.
    assert nxt == datetime(2026, 4, 16, 3, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Inspection schedules
# ---------------------------------------------------------------------------

@pytest.fixture
def inspectable_dataset(db):
    ds = Dataset.objects.create(code="sched_inspectable", display_name="x")
    rule = QualityRule.objects.create(
        dataset=ds, rule_type="completeness", severity="P0",
        threshold_value=90.0, config={},
    )
    DatasetRow.objects.create(dataset=ds, payload={"v": 1})
    DatasetRow.objects.create(dataset=ds, payload={"v": 2})
    return ds


def test_due_inspection_schedule_fires_and_creates_run(db, inspectable_dataset):
    past = dj_tz.now() - timedelta(minutes=5)
    sched = InspectionSchedule.objects.create(
        dataset=inspectable_dataset,
        cron_expr="0 2 * * *",
        timezone="UTC",
        active=True,
        next_run_at=past,
    )
    fired = tick_inspection_schedules()
    assert len(fired) == 1
    assert fired[0]["schedule_id"] == sched.id
    # An InspectionRun was created for that dataset.
    runs = InspectionRun.objects.filter(dataset=inspectable_dataset, trigger_mode="scheduled")
    assert runs.count() == 1
    # next_run_at advanced into the future.
    sched.refresh_from_db()
    assert sched.next_run_at > dj_tz.now()
    assert sched.last_enqueued_at is not None


def test_inspection_schedule_not_due_does_nothing(db, inspectable_dataset):
    future = dj_tz.now() + timedelta(hours=1)
    InspectionSchedule.objects.create(
        dataset=inspectable_dataset,
        cron_expr="0 2 * * *",
        timezone="UTC",
        active=True,
        next_run_at=future,
    )
    fired = tick_inspection_schedules()
    assert fired == []
    assert InspectionRun.objects.filter(dataset=inspectable_dataset, trigger_mode="scheduled").count() == 0


def test_inactive_inspection_schedule_skipped(db, inspectable_dataset):
    InspectionSchedule.objects.create(
        dataset=inspectable_dataset,
        cron_expr="0 2 * * *",
        timezone="UTC",
        active=False,
        next_run_at=dj_tz.now() - timedelta(minutes=5),
    )
    assert tick_inspection_schedules() == []


# ---------------------------------------------------------------------------
# Report schedules
# ---------------------------------------------------------------------------

@pytest.fixture
def reportable_definition(db):
    ds = Dataset.objects.create(
        code="sched_reportable", display_name="r", approval_state="approved"
    )
    DatasetRow.objects.create(dataset=ds, payload={"name": "alpha"})
    DatasetRow.objects.create(dataset=ds, payload={"name": "beta"})
    return ReportDefinition.objects.create(
        name="sched_def", dataset=ds, filter_schema={}, time_window_schema={},
        permission_scope={}, query_plan={},
    )


def test_due_report_schedule_creates_run(db, reportable_definition):
    past = dj_tz.now() - timedelta(minutes=5)
    sched = ReportSchedule.objects.create(
        report_definition=reportable_definition,
        cron_expr="0 3 * * *",
        timezone="UTC",
        active=True,
        next_run_at=past,
    )
    fired = tick_report_schedules()
    assert len(fired) == 1
    assert fired[0]["schedule_id"] == sched.id
    runs = ReportRun.objects.filter(report_definition=reportable_definition)
    assert runs.count() == 1
    run = runs.first()
    assert run.total_rows == 2
    sched.refresh_from_db()
    assert sched.next_run_at > dj_tz.now()
    assert sched.last_enqueued_at is not None


def test_initialize_pending_schedules_populates_next_run_at(db, inspectable_dataset, reportable_definition):
    InspectionSchedule.objects.create(
        dataset=inspectable_dataset, cron_expr="0 2 * * *", timezone="UTC",
        active=True, next_run_at=None,
    )
    ReportSchedule.objects.create(
        report_definition=reportable_definition, cron_expr="0 3 * * *",
        timezone="UTC", active=True, next_run_at=None,
    )
    n = initialize_pending_schedules()
    assert n == 2
    assert InspectionSchedule.objects.filter(next_run_at__isnull=True).count() == 0
    assert ReportSchedule.objects.filter(next_run_at__isnull=True).count() == 0


def test_tick_all_runs_both_kinds(db, inspectable_dataset, reportable_definition):
    past = dj_tz.now() - timedelta(minutes=10)
    InspectionSchedule.objects.create(
        dataset=inspectable_dataset, cron_expr="0 2 * * *", timezone="UTC",
        active=True, next_run_at=past,
    )
    ReportSchedule.objects.create(
        report_definition=reportable_definition, cron_expr="0 3 * * *",
        timezone="UTC", active=True, next_run_at=past,
    )
    result = tick_all()
    assert len(result["inspections"]) == 1
    assert len(result["reports"]) == 1


def test_repeat_tick_does_not_double_fire(db, inspectable_dataset):
    past = dj_tz.now() - timedelta(minutes=5)
    InspectionSchedule.objects.create(
        dataset=inspectable_dataset, cron_expr="0 2 * * *", timezone="UTC",
        active=True, next_run_at=past,
    )
    first = tick_inspection_schedules()
    assert len(first) == 1
    # Second tick: next_run_at is already in the future after the first call,
    # so the schedule must not fire again.
    second = tick_inspection_schedules()
    assert second == []
