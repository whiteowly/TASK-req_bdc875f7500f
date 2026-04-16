"""API-level test for distribution_drift rules triggering real PSI evaluation."""
import pytest

from apps.catalog.models import DatasetRow
from apps.quality.services import _build_histogram


def _ds_with_field(client, code, field_key="score", data_type="decimal"):
    ds = client.post("/api/v1/datasets",
                     {"code": code, "display_name": code}, format="json").json()
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": field_key, "display_name": field_key, "data_type": data_type},
        format="json",
    ).json()
    return ds, fld


def test_drift_rule_pass_with_matching_distribution(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "drift_pass")
    for i in range(100):
        DatasetRow.objects.create(dataset_id=ds["id"], payload={"score": float(i)})
    baseline = _build_histogram([float(i) for i in range(100)], num_bins=10,
                                lo=0.0, hi=99.0)
    rule = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "distribution_drift",
            "severity": "P1",
            "threshold_value": 0.2,
            "field_ids": [fld["id"]],
            "config": {"baseline": baseline, "num_bins": 10,
                       "baseline_lo": 0.0, "baseline_hi": 99.0},
        },
        format="json",
    )
    assert rule.status_code == 201, rule.content
    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 202
    body = res.json()
    assert body["gate_pass"] is True


def test_drift_rule_fail_with_shifted_distribution(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "drift_fail")
    # Rows in [50,150) but baseline in [0,50) on shared range [0,150].
    for i in range(50, 150):
        DatasetRow.objects.create(dataset_id=ds["id"], payload={"score": float(i)})
    baseline = _build_histogram([float(i) for i in range(50)], num_bins=10,
                                lo=0.0, hi=150.0)
    rule = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "distribution_drift",
            "severity": "P0",
            "threshold_value": 0.1,
            "field_ids": [fld["id"]],
            "config": {"baseline": baseline, "num_bins": 10,
                       "baseline_lo": 0.0, "baseline_hi": 150.0},
        },
        format="json",
    )
    assert rule.status_code == 201, rule.content
    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 202
    body = res.json()
    assert body["gate_pass"] is False
    assert body["failed_p0_count"] >= 1
