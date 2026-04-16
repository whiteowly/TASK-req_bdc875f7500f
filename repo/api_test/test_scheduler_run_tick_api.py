"""End-to-end scheduler verification via the API surface.

Creates schedules through the public REST endpoints, backdates their
``next_run_at`` so they are due, calls the in-process tick, and asserts
that real persisted runs were produced and the schedule advanced.
"""
from datetime import timedelta

from django.utils import timezone

from apps.analytics.models import ReportRun, ReportSchedule
from apps.catalog.models import DatasetRow
from apps.platform_common.scheduler import tick_all
from apps.quality.models import InspectionRun, InspectionSchedule


def _approved_ds(client, code):
    ds = client.post("/api/v1/datasets",
                     {"code": code, "display_name": code}, format="json").json()
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": "v", "display_name": "V", "data_type": "integer"},
        format="json",
    ).json()
    client.patch(f"/api/v1/datasets/{ds['id']}",
                 {"approval_state": "approved"}, format="json", HTTP_IF_MATCH='"1"')
    return ds, fld


def test_quality_schedule_fires_via_api_then_tick(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _approved_ds(client, "tick_quality")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"v": 1})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"v": 2})
    client.post(
        "/api/v1/quality/rules",
        {"dataset_id": ds["id"], "rule_type": "completeness", "severity": "P0",
         "threshold_value": 90.0, "field_ids": [fld["id"]]},
        format="json",
    )
    sched_res = client.post(
        "/api/v1/quality/schedules",
        {"dataset_id": ds["id"], "cron_expr": "0 2 * * *", "timezone": "UTC"},
        format="json",
    )
    assert sched_res.status_code == 201
    sched_id = sched_res.json()["id"]
    # Backdate so the next tick treats it as due.
    InspectionSchedule.objects.filter(id=sched_id).update(
        next_run_at=timezone.now() - timedelta(minutes=10)
    )
    fired = tick_all()
    assert len(fired["inspections"]) == 1
    assert fired["inspections"][0]["schedule_id"] == sched_id
    runs = InspectionRun.objects.filter(dataset_id=ds["id"], trigger_mode="scheduled")
    assert runs.count() == 1
    sched = InspectionSchedule.objects.get(id=sched_id)
    assert sched.next_run_at > timezone.now()
    assert sched.last_enqueued_at is not None


def test_report_schedule_fires_via_api_then_tick(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _approved_ds(client, "tick_report")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"v": 7})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"v": 9})
    rdef = client.post(
        "/api/v1/reports/definitions",
        {"name": "tick_report_def", "dataset_id": ds["id"]}, format="json",
    ).json()
    sched_res = client.post(
        "/api/v1/reports/schedules",
        {"report_definition_id": rdef["id"], "cron_expr": "0 3 * * *"},
        format="json",
    )
    assert sched_res.status_code == 201
    body = sched_res.json()
    # Schedule should ship with a populated next_run_at on creation.
    assert body["next_run_at"] is not None
    sched_id = body["id"]
    ReportSchedule.objects.filter(id=sched_id).update(
        next_run_at=timezone.now() - timedelta(minutes=10)
    )
    before = ReportRun.objects.filter(report_definition_id=rdef["id"]).count()
    fired = tick_all()
    assert len(fired["reports"]) == 1
    assert fired["reports"][0]["schedule_id"] == sched_id
    after = ReportRun.objects.filter(report_definition_id=rdef["id"]).count()
    assert after == before + 1
    new_run = ReportRun.objects.filter(report_definition_id=rdef["id"]).order_by("-created_at").first()
    assert new_run.total_rows == 2
    sched = ReportSchedule.objects.get(id=sched_id)
    assert sched.next_run_at > timezone.now()
    assert sched.last_enqueued_at is not None
