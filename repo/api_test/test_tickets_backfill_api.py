"""Tickets, transitions, remediation, backfill API tests with idempotency."""
import secrets

import pytest


def _create_ticket(client, title="t1"):
    return client.post(
        "/api/v1/tickets",
        {"title": title},
        format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )


def test_create_ticket_happy(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = _create_ticket(client)
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["state"] == "open"
    assert body["due_date"] is not None
    assert body["version"] == 1


def test_anonymous_cannot_create_ticket(api_client):
    res = api_client.post("/api/v1/tickets", {"title": "t1"}, format="json")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_user_role_cannot_create_ticket(authed_client):
    client, _, _ = authed_client(roles=("user",))
    res = client.post("/api/v1/tickets", {"title": "t1"}, format="json",
                      HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_validation_missing_title(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post("/api/v1/tickets", {}, format="json",
                      HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "validation_error"


def test_transition_happy(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    t = _create_ticket(client).json()
    res = client.post(
        f"/api/v1/tickets/{t['id']}/transition",
        {"to_state": "in_progress", "reason": "assigned to ETL owner"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 200
    assert res.json()["state"] == "in_progress"


def test_invalid_transition_from_open_to_closed(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    t = _create_ticket(client).json()
    res = client.post(
        f"/api/v1/tickets/{t['id']}/transition",
        {"to_state": "closed", "reason": "trying to skip"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "invalid_state_transition"


def test_transition_version_conflict(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    t = _create_ticket(client).json()
    res = client.post(
        f"/api/v1/tickets/{t['id']}/transition",
        {"to_state": "in_progress", "reason": "stale"},
        format="json",
        HTTP_IF_MATCH='"99"',
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "version_conflict"


def test_idempotent_ticket_creation_replays_response(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    key = secrets.token_hex(8)
    payload = {"title": "idem-test"}
    a = client.post("/api/v1/tickets", payload, format="json", HTTP_IDEMPOTENCY_KEY=key)
    b = client.post("/api/v1/tickets", payload, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] == b.json()["id"]


def test_idempotent_ticket_with_different_payload_conflict(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    key = secrets.token_hex(8)
    a = client.post("/api/v1/tickets", {"title": "first"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    b = client.post("/api/v1/tickets", {"title": "different"}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key)
    assert a.status_code == 201
    assert b.status_code == 409
    assert b.json()["error"]["code"] == "idempotency_key_conflict"


def test_backfill_idempotent_and_reinspection_linked(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    # Build ticket with a dataset attached so reinspection has something to do.
    ds = client.post("/api/v1/datasets", {"code": "bf_ds", "display_name": "BF"}, format="json").json()
    t = client.post(
        "/api/v1/tickets",
        {"title": "fix-rows", "dataset_id": ds["id"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    ).json()
    fp = "sha256:abc"
    a = client.post(f"/api/v1/tickets/{t['id']}/backfills",
                    {"input_fingerprint": fp, "parameters": {"affected_record_count": 10}},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    b = client.post(f"/api/v1/tickets/{t['id']}/backfills",
                    {"input_fingerprint": fp, "parameters": {"affected_record_count": 10}},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8))
    assert a.status_code == 201
    # Same (ticket, fingerprint) -> deduped at the domain layer; second call returns 200.
    assert b.status_code == 200
    body = a.json()
    assert body["post_fix_inspection_run_id"]


def test_assign_ticket(authed_client, make_user):
    client, _, _ = authed_client(roles=("operations",))
    other = make_user("ops_other", "StrongPass!1234", roles=("operations",))
    t = _create_ticket(client).json()
    res = client.post(
        f"/api/v1/tickets/{t['id']}/assign",
        {"user_id": other.id},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 200
    assert res.json()["owner_user_id"] == other.id
