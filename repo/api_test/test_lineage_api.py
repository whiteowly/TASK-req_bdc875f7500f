"""Lineage edges + graph traversal."""
import pytest


def _ds(client, code):
    return client.post("/api/v1/datasets", {"code": code, "display_name": code}, format="json").json()


def test_lineage_create_and_graph(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    a = _ds(client, "lineage_a")
    b = _ds(client, "lineage_b")
    c = _ds(client, "lineage_c")
    res = client.post("/api/v1/lineage/edges", {
        "upstream_dataset_id": a["id"], "downstream_dataset_id": b["id"],
        "relation_type": "transform", "observed_at": "2026-04-15T01:00:00Z"
    }, format="json")
    assert res.status_code == 201
    res2 = client.post("/api/v1/lineage/edges", {
        "upstream_dataset_id": b["id"], "downstream_dataset_id": c["id"],
        "relation_type": "copy", "observed_at": "2026-04-15T01:30:00Z"
    }, format="json")
    assert res2.status_code == 201

    graph = client.get(f"/api/v1/lineage/graph?dataset_id={a['id']}&direction=downstream&depth=3").json()
    assert c["id"] in graph["nodes"]
    assert len(graph["edges"]) == 2

    upstream = client.get(f"/api/v1/lineage/graph?dataset_id={c['id']}&direction=upstream&depth=2").json()
    assert a["id"] in upstream["nodes"]


def test_lineage_invalid_relation_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    a = _ds(client, "lineage_x")
    b = _ds(client, "lineage_y")
    res = client.post("/api/v1/lineage/edges", {
        "upstream_dataset_id": a["id"], "downstream_dataset_id": b["id"],
        "relation_type": "select_all", "observed_at": "2026-04-15T01:00:00Z"
    }, format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "validation_error"


def test_lineage_user_role_cannot_write(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    a = _ds(ops, "lineage_p")
    b = _ds(ops, "lineage_q")
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post("/api/v1/lineage/edges", {
        "upstream_dataset_id": a["id"], "downstream_dataset_id": b["id"],
        "relation_type": "transform", "observed_at": "2026-04-15T01:00:00Z"
    }, format="json")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"
