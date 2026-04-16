"""Quality schedule listing + listing of inspections."""
def _approved_ds(client, code):
    ds = client.post("/api/v1/datasets", {"code": code, "display_name": code}, format="json").json()
    return ds


def test_list_schedules(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    ds = _approved_ds(ops, "sch_a")
    ops.post("/api/v1/quality/schedules", {"dataset_id": ds["id"]}, format="json")
    res = ops.get("/api/v1/quality/schedules")
    assert res.status_code == 200
    assert any(s["dataset_id"] == ds["id"] for s in res.json()["schedules"])


def test_list_inspections(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    res = ops.get("/api/v1/quality/inspections")
    assert res.status_code == 200
    assert isinstance(res.json()["inspections"], list)
