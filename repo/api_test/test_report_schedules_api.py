"""Persisted ReportSchedule lifecycle and permission cases."""
import secrets


def _approved_ds(client, code):
    ds = client.post("/api/v1/datasets",
                     {"code": code, "display_name": code}, format="json").json()
    client.post(f"/api/v1/datasets/{ds['id']}/fields",
                {"field_key": "x", "display_name": "X", "data_type": "string"},
                format="json")
    client.patch(f"/api/v1/datasets/{ds['id']}",
                 {"approval_state": "approved"}, format="json", HTTP_IF_MATCH='"1"')
    return ds


def _rdef(client, ds_id, name=None):
    return client.post(
        "/api/v1/reports/definitions",
        {"name": name or f"def_{secrets.token_hex(3)}", "dataset_id": ds_id},
        format="json",
    ).json()


def test_create_schedule_happy(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sch_a")
    rdef = _rdef(client, ds["id"])
    res = client.post(
        "/api/v1/reports/schedules",
        {"report_definition_id": rdef["id"], "cron_expr": "30 4 * * *", "timezone": "UTC"},
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["cron_expr"] == "30 4 * * *"
    assert body["active"] is True
    assert body["version"] == 1
    assert body["id"].startswith("rsd_")


def test_create_schedule_invalid_cron_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sch_b")
    rdef = _rdef(client, ds["id"])
    res = client.post(
        "/api/v1/reports/schedules",
        {"report_definition_id": rdef["id"], "cron_expr": "not a cron"},
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_cron"


def test_create_schedule_missing_definition_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post(
        "/api/v1/reports/schedules",
        {"report_definition_id": "rpt_does_not_exist", "cron_expr": "0 3 * * *"},
        format="json",
    )
    assert res.status_code == 404


def test_user_role_cannot_create_schedule(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(ops, "sch_c")
    rdef = _rdef(ops, ds["id"])
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        "/api/v1/reports/schedules",
        {"report_definition_id": rdef["id"], "cron_expr": "0 3 * * *"},
        format="json",
    )
    assert res.status_code == 403


def test_list_schedules_returns_persisted_rows(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sch_d")
    rdef = _rdef(client, ds["id"])
    a = client.post("/api/v1/reports/schedules",
                    {"report_definition_id": rdef["id"], "cron_expr": "10 1 * * *"},
                    format="json").json()
    b = client.post("/api/v1/reports/schedules",
                    {"report_definition_id": rdef["id"], "cron_expr": "20 2 * * *"},
                    format="json").json()
    listing = client.get(f"/api/v1/reports/schedules?report_definition_id={rdef['id']}").json()
    ids = {s["id"] for s in listing["schedules"]}
    assert {a["id"], b["id"]}.issubset(ids)


def test_get_schedule_detail(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sch_e")
    rdef = _rdef(client, ds["id"])
    s = client.post("/api/v1/reports/schedules",
                    {"report_definition_id": rdef["id"], "cron_expr": "0 3 * * *"},
                    format="json").json()
    res = client.get(f"/api/v1/reports/schedules/{s['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == s["id"]


def test_patch_schedule_requires_if_match_and_increments_version(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sch_f")
    rdef = _rdef(client, ds["id"])
    s = client.post("/api/v1/reports/schedules",
                    {"report_definition_id": rdef["id"], "cron_expr": "0 3 * * *"},
                    format="json").json()
    bad = client.patch(f"/api/v1/reports/schedules/{s['id']}",
                       {"active": False}, format="json")
    assert bad.status_code == 400
    wrong = client.patch(f"/api/v1/reports/schedules/{s['id']}",
                         {"active": False}, format="json", HTTP_IF_MATCH='"99"')
    assert wrong.status_code == 409
    ok = client.patch(f"/api/v1/reports/schedules/{s['id']}",
                      {"active": False, "cron_expr": "5 5 * * *"},
                      format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200
    body = ok.json()
    assert body["active"] is False
    assert body["cron_expr"] == "5 5 * * *"
    assert body["version"] == 2
