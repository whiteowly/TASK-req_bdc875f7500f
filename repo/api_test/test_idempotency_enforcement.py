"""Enforce Idempotency-Key header on duplicate-prone POST routes.

These tests prove that the middleware rejects requests missing the header
with a ``400 idempotency_key_required`` envelope, and that existing
replay/conflict behavior still works when the header IS present.
"""
import secrets

import pytest


def test_tickets_create_requires_idempotency_key(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post("/api/v1/tickets", {"title": "t1"}, format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "idempotency_key_required"


def test_tickets_create_with_key_succeeds(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post("/api/v1/tickets", {"title": "t1"}, format="json",
                      HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    assert res.status_code == 201


def test_reports_runs_requires_idempotency_key(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = client.post("/api/v1/datasets",
                     {"code": "idem_ds", "display_name": "I"}, format="json").json()
    rdef = client.post("/api/v1/reports/definitions",
                       {"name": "idem_def", "dataset_id": ds["id"]},
                       format="json").json()
    res = client.post("/api/v1/reports/runs",
                      {"report_definition_id": rdef["id"]}, format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "idempotency_key_required"


def test_reports_runs_with_key_succeeds(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = client.post("/api/v1/datasets",
                     {"code": "idem_ds2", "display_name": "I"}, format="json").json()
    rdef = client.post("/api/v1/reports/definitions",
                       {"name": "idem_def2", "dataset_id": ds["id"]},
                       format="json").json()
    res = client.post("/api/v1/reports/runs",
                      {"report_definition_id": rdef["id"]}, format="json",
                      HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    assert res.status_code == 202


def test_exports_requires_idempotency_key(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    ds = client.post("/api/v1/datasets",
                     {"code": "idem_exp", "display_name": "I"}, format="json").json()
    rdef = client.post("/api/v1/reports/definitions",
                       {"name": "idem_exp_def", "dataset_id": ds["id"]},
                       format="json").json()
    run = client.post("/api/v1/reports/runs",
                      {"report_definition_id": rdef["id"]}, format="json",
                      HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8)).json()
    res = client.post(f"/api/v1/reports/runs/{run['id']}/exports",
                      {"format": "csv"}, format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "idempotency_key_required"


def test_backfills_requires_idempotency_key(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    t = client.post("/api/v1/tickets", {"title": "bf"},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8)).json()
    res = client.post(f"/api/v1/tickets/{t['id']}/backfills",
                      {"input_fingerprint": "sha256:x", "parameters": {}},
                      format="json")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "idempotency_key_required"


def test_replay_returns_same_response(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    key = secrets.token_hex(8)
    a = client.post("/api/v1/tickets", {"title": "replay"}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key)
    b = client.post("/api/v1/tickets", {"title": "replay"}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key)
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] == b.json()["id"]


def test_conflict_on_key_reuse_with_different_payload(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    key = secrets.token_hex(8)
    a = client.post("/api/v1/tickets", {"title": "first"}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key)
    b = client.post("/api/v1/tickets", {"title": "different"}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key)
    assert a.status_code == 201
    assert b.status_code == 409
    assert b.json()["error"]["code"] == "idempotency_key_conflict"
