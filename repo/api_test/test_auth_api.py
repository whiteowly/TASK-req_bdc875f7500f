"""Real API tests for /auth/* endpoints — exercise the live Django app."""
from rest_framework.test import APIClient

from apps.identity import services


def _create_user(roles=("user",), username="alice"):
    services.ensure_seed_roles()
    services.create_user(username=username, password="StrongPass!1234", roles=roles)


def test_login_happy_path(db):
    _create_user(roles=("operations",))
    c = APIClient()
    res = c.post("/api/v1/auth/login",
                 {"username": "alice", "password": "StrongPass!1234"}, format="json")
    assert res.status_code == 200, res.content
    body = res.json()
    assert "token" in body
    assert "expires_at" in body
    assert "operations" in body["user"]["roles"]


def test_login_bad_credentials_returns_401(db):
    _create_user()
    c = APIClient()
    res = c.post("/api/v1/auth/login",
                 {"username": "alice", "password": "wrong"}, format="json")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


def test_login_missing_field_returns_400(db):
    c = APIClient()
    res = c.post("/api/v1/auth/login", {"username": "alice"}, format="json")
    assert res.status_code == 400


def test_logout_revokes_session(db):
    _create_user()
    c = APIClient()
    res = c.post("/api/v1/auth/login",
                 {"username": "alice", "password": "StrongPass!1234"}, format="json")
    token = res.json()["token"]
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    out = c.post("/api/v1/auth/logout")
    assert out.status_code == 200
    # Now a follow-up call must be unauthorized.
    again = c.get("/api/v1/auth/sessions")
    assert again.status_code == 401


def test_sessions_listing_and_revoke(db):
    _create_user()
    c = APIClient()
    token = c.post("/api/v1/auth/login",
                   {"username": "alice", "password": "StrongPass!1234"}, format="json").json()["token"]
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    res = c.get("/api/v1/auth/sessions")
    assert res.status_code == 200
    body = res.json()
    assert "sessions" in body
    assert isinstance(body["sessions"], list)
    assert len(body["sessions"]) >= 1
    s = body["sessions"][0]
    assert "id" in s
    assert "user_id" in s
    assert "expires_at" in s
    assert "is_active" in s
    sid = s["id"]
    rev = c.post(f"/api/v1/auth/sessions/{sid}/revoke")
    assert rev.status_code == 200
    assert rev.json()["revoked"] is True
