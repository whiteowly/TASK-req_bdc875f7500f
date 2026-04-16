"""OCC enforcement on quality inspection schedule update path.

Create is ergonomic (no If-Match needed). Update (upsert hitting existing
record) requires If-Match and enforces optimistic concurrency.
"""


def _approved_ds(client, code):
    ds = client.post("/api/v1/datasets",
                     {"code": code, "display_name": code}, format="json").json()
    return ds


def test_create_schedule_no_if_match_required(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sched_occ_create")
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code == 201
    assert res.json()["version"] == 1


def test_update_requires_if_match(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sched_occ_update")
    client.post("/api/v1/quality/schedules",
                {"dataset_id": ds["id"]}, format="json")
    # Second POST to same dataset triggers update path — requires If-Match.
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"], "cron_expr": "30 3 * * *"},
                      format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "if_match_required"


def test_update_with_stale_version_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sched_occ_stale")
    client.post("/api/v1/quality/schedules",
                {"dataset_id": ds["id"]}, format="json")
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"], "cron_expr": "30 3 * * *"},
                      format="json", HTTP_IF_MATCH='"99"')
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "version_conflict"


def test_update_with_correct_version_succeeds(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(client, "sched_occ_ok")
    created = client.post("/api/v1/quality/schedules",
                          {"dataset_id": ds["id"]}, format="json").json()
    assert created["version"] == 1
    updated = client.post("/api/v1/quality/schedules",
                          {"dataset_id": ds["id"], "cron_expr": "30 3 * * *"},
                          format="json", HTTP_IF_MATCH='"1"')
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["cron_expr"] == "30 3 * * *"
