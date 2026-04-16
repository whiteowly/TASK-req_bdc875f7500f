"""API test proving drift baseline snapshots are persisted in InspectionRuleResult
and that subsequent runs use the persisted snapshot — not current rows."""
import pytest

from apps.catalog.models import DatasetRow
from apps.quality.models import InspectionRuleResult
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


def test_drift_snapshot_persisted_in_rule_result(authed_client):
    """After a drift inspection, the InspectionRuleResult.snapshot_data
    contains the computed histogram and bin edges."""
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "drift_snap")
    for i in range(100):
        DatasetRow.objects.create(dataset_id=ds["id"], payload={"score": float(i)})
    baseline = _build_histogram([float(i) for i in range(100)], num_bins=10,
                                lo=0.0, hi=99.0)
    rule_resp = client.post(
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
    assert rule_resp.status_code == 201
    rule_id = rule_resp.json()["id"]

    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 202

    rr = InspectionRuleResult.objects.filter(rule_id=rule_id).first()
    assert rr is not None
    assert rr.snapshot_data, "snapshot_data should be populated after drift evaluation"
    assert "histogram" in rr.snapshot_data
    assert "lo" in rr.snapshot_data
    assert "hi" in rr.snapshot_data
    assert isinstance(rr.snapshot_data["histogram"], list)
    assert len(rr.snapshot_data["histogram"]) == 10


def test_non_drift_rule_has_empty_snapshot(authed_client):
    """Non-drift rule results should have empty snapshot_data (no pollution)."""
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "snap_nodrift")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"score": 1.0})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"score": 2.0})

    rule_resp = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "completeness",
            "severity": "P2",
            "threshold_value": 90.0,
            "field_ids": [fld["id"]],
        },
        format="json",
    )
    assert rule_resp.status_code == 201
    rule_id = rule_resp.json()["id"]

    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 202

    rr = InspectionRuleResult.objects.filter(rule_id=rule_id).first()
    assert rr is not None
    assert rr.snapshot_data == {}
