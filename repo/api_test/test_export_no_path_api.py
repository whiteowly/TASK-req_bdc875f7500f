"""API tests: export file list must NOT expose internal storage paths.

Proves:
- Export file list payloads do not contain ``path`` field.
- Safe identifiers (id, part_number, checksum_sha256) are still present.
"""
from __future__ import annotations

import pytest

from apps.analytics.models import ReportDefinition, ReportRun
from apps.catalog.models import Dataset, DatasetRow
from apps.exports.models import ExportFile, ExportJob


def _setup_export(db, authed_client):
    """Create a complete export job with files via the API."""
    client, _, _ = authed_client(roles=("administrator",))
    ds = Dataset.objects.create(code="exp_path_ds", display_name="Exp Path", approval_state="approved")
    DatasetRow.objects.create(dataset=ds, payload={"name": "a"})
    DatasetRow.objects.create(dataset=ds, payload={"name": "b"})
    defn = ReportDefinition.objects.create(
        name="exp_path_def", dataset=ds, filter_schema={},
        time_window_schema={}, permission_scope={}, query_plan={},
    )
    # Create a report run
    run_res = client.post(
        "/api/v1/reports/runs",
        {"report_definition_id": defn.id},
        format="json",
        HTTP_IDEMPOTENCY_KEY="exp-path-key-1",
    )
    assert run_res.status_code in (201, 202), run_res.content
    run_id = run_res.json()["id"]

    # Create export
    export_res = client.post(
        f"/api/v1/reports/runs/{run_id}/exports",
        {"format": "csv"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="exp-path-key-2",
    )
    assert export_res.status_code == 201, export_res.content
    export_id = export_res.json()["export_job_id"]
    return client, export_id


def test_export_files_do_not_expose_path(authed_client, db):
    client, export_id = _setup_export(db, authed_client)
    files_res = client.get(f"/api/v1/exports/{export_id}/files")
    assert files_res.status_code == 200
    data = files_res.json()
    for f in data.get("files", []):
        assert "path" not in f, f"File payload must not contain 'path', got: {f}"
        # Safe fields should still be present
        assert "id" in f
        assert "part_number" in f
        assert "checksum_sha256" in f


def test_export_detail_does_not_expose_path(authed_client, db):
    client, export_id = _setup_export(db, authed_client)
    detail_res = client.get(f"/api/v1/exports/{export_id}")
    assert detail_res.status_code == 200
    data = detail_res.json()
    assert "path" not in data
