"""Governed dataset query API tests."""
import pytest

from apps.catalog.models import Dataset, DatasetRow


def _setup(client, code="cohorts"):
    ds = client.post("/api/v1/datasets", {"code": code, "display_name": code}, format="json").json()
    client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": "program", "display_name": "P", "data_type": "string"},
        format="json",
    )
    client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": "gpa", "display_name": "G", "data_type": "decimal"},
        format="json",
    )
    # Approve so the user role can query.
    client.patch(
        f"/api/v1/datasets/{ds['id']}",
        {"approval_state": "approved"}, format="json",
        HTTP_IF_MATCH='"1"',
    )
    return ds


def _seed(ds_id):
    DatasetRow.objects.create(dataset_id=ds_id, payload={"program": "CS", "gpa": 3.7})
    DatasetRow.objects.create(dataset_id=ds_id, payload={"program": "Math", "gpa": 3.5})
    DatasetRow.objects.create(dataset_id=ds_id, payload={"program": "Bio", "gpa": 3.1})


def test_governed_query_happy_path(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _setup(ops, code="cohorts_q")
    _seed(ds["id"])
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {
            "select": ["program", "gpa"],
            "filters": [{"field": "gpa", "op": "gte", "value": 3.5}],
            "sort": [{"field": "gpa", "direction": "desc"}],
            "limit": 10,
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    rows = res.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["program"] == "CS"
    assert res.json()["applied_scope"]["approved_only"] is True


def test_query_rejects_sql_like_filter_value(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _setup(ops, code="cohorts_sqli")
    _seed(ds["id"])
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {
            "filters": [{"field": "program", "op": "eq", "value": "DROP TABLE users"}],
        },
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "sql_like_rejected"


def test_query_unapproved_dataset_forbidden_for_user(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    # Build but don't approve
    ds = ops.post("/api/v1/datasets", {"code": "draft_ds", "display_name": "X"}, format="json").json()
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {"select": [], "filters": [], "sort": [], "limit": 10},
        format="json",
    )
    # User cannot read the dataset at all (not approved) → forbidden
    assert res.status_code == 403


def test_query_limit_validation(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _setup(ops, code="cohorts_limit")
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {"limit": 999999, "filters": [], "sort": []},
        format="json",
    )
    assert res.status_code == 400


def test_query_too_many_filters_returns_422(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _setup(ops, code="cohorts_filters")
    user_client, _, _ = authed_client(roles=("user",))
    filters = [{"field": "program", "op": "eq", "value": f"X{i}"} for i in range(25)]
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {"filters": filters, "sort": [], "limit": 10},
        format="json",
    )
    assert res.status_code == 422


def test_unknown_field_rejected(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _setup(ops, code="cohorts_unknown")
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/analytics/datasets/{ds['id']}/query",
        {"filters": [{"field": "ssn", "op": "eq", "value": "x"}]},
        format="json",
    )
    assert res.status_code == 400
