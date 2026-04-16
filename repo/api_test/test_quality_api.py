"""Quality rules, inspections, schedules + scoring/gate end-to-end."""
import pytest

from apps.catalog.models import DatasetRow


def _ds_with_field(client, code, field_key="value", data_type="integer"):
    ds = client.post("/api/v1/datasets", {"code": code, "display_name": code}, format="json").json()
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": field_key, "display_name": field_key, "data_type": data_type, "is_queryable": True},
        format="json",
    ).json()
    return ds, fld


def test_create_rule_and_trigger_inspection(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "qcheck_a")
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"value": 1})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"value": 2})
    DatasetRow.objects.create(dataset_id=ds["id"], payload={"value": None})

    rule = client.post(
        "/api/v1/quality/rules",
        {"dataset_id": ds["id"], "rule_type": "completeness", "severity": "P0",
         "threshold_value": 90.0, "field_ids": [fld["id"]], "config": {}},
        format="json",
    )
    assert rule.status_code == 201, rule.content

    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 202
    body = res.json()
    assert body["weights"] == {"P0": 50, "P1": 30, "P2": 15, "P3": 5}
    # 2/3 present = 66.67% < 90 threshold => fail P0 => gate_pass false
    assert body["gate_pass"] is False
    assert body["failed_p0_count"] == 1


def test_inspection_invalid_dataset_returns_404(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post("/api/v1/quality/inspections/trigger",
                      {"dataset_id": "dts_nonexistent"}, format="json")
    assert res.status_code == 404


def test_create_rule_validation_error(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _ds_with_field(client, "qcheck_v")
    bad = client.post(
        "/api/v1/quality/rules",
        {"dataset_id": ds["id"], "rule_type": "bogus", "severity": "P0",
         "threshold_value": 99.0, "field_ids": []},
        format="json",
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_error"
    assert "allowed" in bad.json()["error"]["details"]


def test_user_role_cannot_create_rule(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(ops, "qcheck_perm")
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        "/api/v1/quality/rules",
        {"dataset_id": ds["id"], "rule_type": "completeness", "severity": "P1",
         "threshold_value": 95.0, "field_ids": [fld["id"]]},
        format="json",
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_schedule_default_cron_applied(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, _ = _ds_with_field(client, "qcheck_sched")
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code in (200, 201)
    body = res.json()
    assert body["cron_expr"] == "0 2 * * *"


def test_rule_patch_requires_if_match(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds, fld = _ds_with_field(client, "qcheck_patch")
    rule = client.post(
        "/api/v1/quality/rules",
        {"dataset_id": ds["id"], "rule_type": "completeness", "severity": "P2",
         "threshold_value": 80.0, "field_ids": [fld["id"]]},
        format="json",
    ).json()
    bad = client.patch(f"/api/v1/quality/rules/{rule['id']}",
                       {"threshold_value": 90.0}, format="json")
    assert bad.status_code == 400
    ok = client.patch(f"/api/v1/quality/rules/{rule['id']}",
                      {"threshold_value": 90.0}, format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200
