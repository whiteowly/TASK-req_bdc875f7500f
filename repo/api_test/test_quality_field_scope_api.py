"""Quality rule field scope validation tests.

Proves that field-dependent rule types (completeness, uniqueness,
numeric_range, distribution_drift) reject creation without field_ids.
"""
import pytest


def _ds_with_field(client, code):
    ds = client.post("/api/v1/datasets",
                     {"code": code, "display_name": code}, format="json").json()
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": "val", "display_name": "val", "data_type": "integer", "is_queryable": True},
        format="json",
    ).json()
    return ds, fld


FIELD_REQUIRED_TYPES = ("completeness", "uniqueness", "numeric_range", "distribution_drift")


@pytest.mark.parametrize("rule_type", FIELD_REQUIRED_TYPES)
def test_field_required_rule_rejects_empty_field_ids(authed_client, rule_type):
    """Creating a rule of a field-dependent type with no field_ids must fail."""
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _ds_with_field(client, f"scope_{rule_type}")
    res = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": rule_type,
            "severity": "P1",
            "threshold_value": 50.0,
            "field_ids": [],
        },
        format="json",
    )
    assert res.status_code == 400, f"{rule_type} should require field_ids"
    assert "field_ids" in res.json()["error"]["message"].lower()


@pytest.mark.parametrize("rule_type", FIELD_REQUIRED_TYPES)
def test_field_required_rule_rejects_missing_field_ids(authed_client, rule_type):
    """Creating a rule with omitted field_ids (None) must also fail."""
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _ds_with_field(client, f"scope_none_{rule_type}")
    res = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": rule_type,
            "severity": "P2",
            "threshold_value": 50.0,
            # field_ids omitted entirely
        },
        format="json",
    )
    assert res.status_code == 400, f"{rule_type} should require field_ids"


def test_consistency_rule_allows_empty_field_ids(authed_client):
    """Consistency rules don't require field_ids (they use config predicates)."""
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _ds_with_field(client, "scope_consistency")
    res = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": "consistency",
            "severity": "P3",
            "threshold_value": 50.0,
            "field_ids": [],
            "config": {"predicates": [{"field": "val", "op": "=", "value": 1}]},
        },
        format="json",
    )
    assert res.status_code == 201, "consistency should allow empty field_ids"


@pytest.mark.parametrize("rule_type", FIELD_REQUIRED_TYPES)
def test_field_required_rule_succeeds_with_valid_fields(authed_client, rule_type):
    """Field-dependent rules succeed when valid field_ids are provided."""
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, f"scope_ok_{rule_type}")
    cfg = {}
    if rule_type == "numeric_range":
        cfg = {"min": 0, "max": 100}
    res = client.post(
        "/api/v1/quality/rules",
        {
            "dataset_id": ds["id"],
            "rule_type": rule_type,
            "severity": "P1",
            "threshold_value": 50.0,
            "field_ids": [fld["id"]],
            "config": cfg,
        },
        format="json",
    )
    assert res.status_code == 201, f"{rule_type} should succeed with valid field_ids"
