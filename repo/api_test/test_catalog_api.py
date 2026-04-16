"""Datasets, fields, metadata API tests."""
import pytest


def _create_ds(client, code="cohorts_2025"):
    res = client.post("/api/v1/datasets", {"code": code, "display_name": "C25"}, format="json")
    assert res.status_code == 201, res.content
    return res.json()


def test_create_dataset_happy(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    body = _create_ds(client)
    assert body["id"].startswith("dts_")
    assert body["approval_state"] == "draft"
    assert body["version"] == 1


def test_user_role_cannot_create_dataset(authed_client):
    client, _, _ = authed_client(roles=("user",))
    res = client.post("/api/v1/datasets", {"code": "x", "display_name": "y"}, format="json")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_user_only_sees_approved_datasets(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    draft = _create_ds(ops, code="draft_one")
    appr = _create_ds(ops, code="appr_one")
    res = ops.patch(
        f"/api/v1/datasets/{appr['id']}",
        {"approval_state": "approved"}, format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 200
    user_client, _, _ = authed_client(roles=("user",))
    listing = user_client.get("/api/v1/datasets").json()
    codes = [d["code"] for d in listing["datasets"]]
    assert "appr_one" in codes
    assert "draft_one" not in codes


def test_dataset_patch_requires_if_match(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _create_ds(client)
    bad = client.patch(f"/api/v1/datasets/{ds['id']}", {"display_name": "X"}, format="json")
    assert bad.status_code == 400


def test_add_field_then_set_metadata(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _create_ds(client, code="meta_test")
    fld = client.post(f"/api/v1/datasets/{ds['id']}/fields",
                      {"field_key": "student_id", "display_name": "Student ID", "data_type": "string"},
                      format="json")
    assert fld.status_code == 201
    assert fld.json()["id"].startswith("fld_")
    md = client.patch(f"/api/v1/datasets/{ds['id']}/metadata",
                      {"owner": "registrar_office", "retention_class": "R7Y", "sensitivity_level": "high"},
                      format="json")
    assert md.status_code == 200
    body = md.json()
    assert body["owner"] == "registrar_office"
    assert body["retention_class"] == "R7Y"
    assert body["sensitivity_level"] == "high"


def test_metadata_validation_missing_field(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _create_ds(client, code="meta_validate")
    bad = client.patch(f"/api/v1/datasets/{ds['id']}/metadata",
                       {"owner": "x", "retention_class": "y"},
                       format="json")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_error"


def test_invalid_sensitivity_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _create_ds(client, code="meta_sensitivity")
    bad = client.patch(
        f"/api/v1/datasets/{ds['id']}/metadata",
        {"owner": "o", "retention_class": "r", "sensitivity_level": "ultra"},
        format="json",
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_error"


def test_dataset_code_conflict(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    _create_ds(client, code="dup_code")
    res = client.post("/api/v1/datasets", {"code": "dup_code", "display_name": "x"}, format="json")
    assert res.status_code == 409
