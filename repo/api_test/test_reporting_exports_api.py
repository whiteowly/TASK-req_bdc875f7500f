"""Reports + exports API tests including row splitting."""
import secrets

import pytest

from apps.analytics.models import ReportRun
from apps.catalog.models import DatasetRow
from apps.exports import services as export_services
from apps.exports.models import ExportJob


def _approved_ds(client, code):
    ds = client.post("/api/v1/datasets", {"code": code, "display_name": code}, format="json").json()
    client.post(f"/api/v1/datasets/{ds['id']}/fields",
                {"field_key": "name", "display_name": "N", "data_type": "string"},
                format="json")
    client.patch(f"/api/v1/datasets/{ds['id']}",
                 {"approval_state": "approved"}, format="json", HTTP_IF_MATCH='"1"')
    return ds


def test_create_report_def_then_run(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "rep_a")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"name": "x"})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"name": "y"})
    rdef = client.post(
        "/api/v1/reports/definitions",
        {"name": "rep_a_def", "dataset_id": ds["id"]},
        format="json",
    )
    assert rdef.status_code == 201
    run = client.post(
        "/api/v1/reports/runs",
        {"report_definition_id": rdef.json()["id"], "filters": {}, "time_window": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )
    assert run.status_code == 202
    assert run.json()["total_rows"] == 2


def test_user_role_outside_scope_cannot_run(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(ops, "rep_scope")
    rdef = ops.post(
        "/api/v1/reports/definitions",
        {"name": "rep_scope_def", "dataset_id": ds["id"],
         "permission_scope": {"user_ids": ["usr_other_only"]}},
        format="json",
    ).json()
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        "/api/v1/reports/runs",
        {"report_definition_id": rdef["id"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )
    assert res.status_code == 403


def test_export_job_creation_creates_files(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "exp_a")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"name": "alpha"})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"name": "beta"})
    rdef = client.post(
        "/api/v1/reports/definitions",
        {"name": "exp_a_def", "dataset_id": ds["id"]}, format="json",
    ).json()
    run = client.post(
        "/api/v1/reports/runs",
        {"report_definition_id": rdef["id"]}, format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    ).json()
    res = client.post(
        f"/api/v1/reports/runs/{run['id']}/exports",
        {"format": "csv"}, format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["file_count"] == 1
    assert body["total_rows"] == 2


def test_export_split_into_multiple_parts_when_over_cap(authed_client, tmp_path, settings):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "exp_big")
    rdef = client.post(
        "/api/v1/reports/definitions",
        {"name": "exp_big_def", "dataset_id": ds["id"]}, format="json",
    ).json()
    # Build a run with a snapshot over the row cap to exercise multi-file split.
    rows = [{"name": f"row-{i}"} for i in range(export_services.ROW_CAP_PER_FILE + 7)]
    run = ReportRun.objects.create(
        report_definition_id=rdef["id"], total_rows=len(rows), rows_snapshot=rows, status="complete"
    )
    settings.EXPORT_STORAGE_DIR = tmp_path / "exports"
    res = client.post(
        f"/api/v1/reports/runs/{run.id}/exports",
        {"format": "csv"}, format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["file_count"] == 2
    assert body["total_rows"] == export_services.ROW_CAP_PER_FILE + 7


def test_expired_export_files_listing_returns_410(authed_client, settings, tmp_path):
    from datetime import timedelta
    from django.utils import timezone

    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "exp_exp")
    rdef = client.post(
        "/api/v1/reports/definitions",
        {"name": "exp_exp_def", "dataset_id": ds["id"]}, format="json",
    ).json()
    settings.EXPORT_STORAGE_DIR = tmp_path / "exports2"
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"name": "z"})
    run = client.post(
        "/api/v1/reports/runs",
        {"report_definition_id": rdef["id"]}, format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    ).json()
    j = client.post(
        f"/api/v1/reports/runs/{run['id']}/exports",
        {"format": "csv"}, format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    ).json()
    ExportJob.objects.filter(pk=j["export_job_id"]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    res = client.get(f"/api/v1/exports/{j['export_job_id']}/files")
    assert res.status_code == 410
    assert res.json()["error"]["code"] == "export_expired"
