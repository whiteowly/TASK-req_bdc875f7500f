"""Users and roles management endpoints (administrator-only)."""
import pytest


def test_administrator_can_create_user(authed_client):
    client, _, _ = authed_client(roles=("administrator",))
    res = client.post(
        "/api/v1/users",
        {"username": "newuser", "password": "StrongPass!1234", "roles": ["operations"]},
        format="json",
    )
    assert res.status_code == 201, res.content
    assert "operations" in res.json()["roles"]


def test_operations_cannot_create_user(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post(
        "/api/v1/users",
        {"username": "x", "password": "StrongPass!1234"},
        format="json",
    )
    assert res.status_code == 403


def test_user_cannot_list_users(authed_client):
    client, _, _ = authed_client(roles=("user",))
    res = client.get("/api/v1/users")
    assert res.status_code == 403


def test_anonymous_cannot_list_users(api_client):
    res = api_client.get("/api/v1/users")
    assert res.status_code == 401


def test_create_then_assign_roles(authed_client):
    client, _, _ = authed_client(roles=("administrator",))
    created = client.post(
        "/api/v1/users",
        {"username": "second", "password": "StrongPass!1234"},
        format="json",
    )
    assert created.status_code == 201
    uid = created.json()["id"]
    res = client.post(f"/api/v1/users/{uid}/roles", {"roles": ["administrator"]}, format="json")
    assert res.status_code == 200
    assert "administrator" in res.json()["roles"]


def test_patch_user_requires_if_match(authed_client):
    client, _, _ = authed_client(roles=("administrator",))
    created = client.post(
        "/api/v1/users",
        {"username": "third", "password": "StrongPass!1234"},
        format="json",
    )
    uid = created.json()["id"]
    # Missing If-Match
    bad = client.patch(f"/api/v1/users/{uid}",
                       {"is_active": False}, format="json")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "if_match_required"
    # Wrong version
    wrong = client.patch(f"/api/v1/users/{uid}", {"is_active": False},
                         format="json", HTTP_IF_MATCH='"99"')
    assert wrong.status_code == 409
    # Correct
    ok = client.patch(f"/api/v1/users/{uid}", {"is_active": False},
                      format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200
