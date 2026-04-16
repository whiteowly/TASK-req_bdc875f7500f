"""API-level test proving inspection results are immutable.

Verifies that:
- Triggering an inspection succeeds (create path works).
- The returned rule results exist in the DB and match the API response.
- Direct model-layer tampering with results raises ValidationError.
"""

import pytest

from django.core.exceptions import ValidationError

from apps.catalog.models import DatasetRow
from apps.quality.models import InspectionRuleResult, InspectionRun


def _ds_with_field(client, code):
    ds = client.post(
        "/api/v1/datasets", {"code": code, "display_name": code}, format="json"
    ).json()
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {
            "field_key": "val",
            "display_name": "val",
            "data_type": "integer",
            "is_queryable": True,
        },
        format="json",
    ).json()
    return ds, fld


def test_inspection_results_immutable_after_creation(authed_client):
    """Run a real inspection via API, then prove the persisted
    InspectionRuleResult cannot be updated or deleted."""
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "immut_api")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"val": 1})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"val": 2})

    client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "completeness",
            "severity": "P1",
            "threshold_value": 90.0,
            "field_ids": [fld["id"]],
        },
        format="json",
    )

    res = client.post(
        "/api/v1/quality/inspections/trigger", {"dataset_id": ds["id"]}, format="json"
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "complete"
    assert len(body["rule_results"]) > 0

    # Verify the result row exists in DB
    rr_id = body["rule_results"][0]["id"]
    rr = InspectionRuleResult.objects.get(pk=rr_id)

    # Attempt update → must raise
    rr.measured_value = 999.0
    with pytest.raises(ValidationError) as exc_info:
        rr.save()
    assert "immutable" in str(exc_info.value).lower()

    # Attempt delete → must raise
    with pytest.raises(ValidationError) as exc_info:
        rr.delete()
    msg = str(exc_info.value).lower()
    assert "immutable" in msg or "cannot be deleted" in msg


def test_completed_inspection_run_immutable_via_api(authed_client):
    """Run a real inspection via API, then prove the completed
    InspectionRun itself cannot be modified."""
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "immut_run_api")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"val": 1})

    client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "completeness",
            "severity": "P2",
            "threshold_value": 50.0,
            "field_ids": [fld["id"]],
        },
        format="json",
    )

    res = client.post(
        "/api/v1/quality/inspections/trigger", {"dataset_id": ds["id"]}, format="json"
    )
    assert res.status_code == 202
    run_id = res.json()["id"]
    run = InspectionRun.objects.get(pk=run_id)
    assert run.status == "complete"

    # Attempt to modify completed run → must raise
    run.gate_pass = not run.gate_pass
    with pytest.raises(ValidationError) as exc_info:
        run.save()
    assert "immutable" in str(exc_info.value).lower()
