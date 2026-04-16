"""API test proving login records session IP via centralized client_ip helper,
not via X-Forwarded-For."""
import pytest

from apps.identity.models import Session


def test_login_session_records_real_ip_not_xff(authed_client, api_client):
    """Login with X-Real-IP set should record that IP in the session,
    ignoring any X-Forwarded-For header."""
    from apps.identity.services import create_user, ensure_seed_roles

    ensure_seed_roles()
    username = "ip_test_user"
    password = "TestPass!1234"
    create_user(username=username, password=password, roles=("user",))

    res = api_client.post(
        "/api/v1/auth/login",
        {"username": username, "password": password},
        format="json",
        HTTP_X_REAL_IP="10.0.0.99",
        HTTP_X_FORWARDED_FOR="8.8.8.8, 10.0.0.99",
    )
    assert res.status_code == 200
    token = res.json()["token"]

    # Check that the session was recorded with X-Real-IP (10.0.0.99)
    from apps.identity.services import token_hash
    session = Session.objects.get(token_hash=token_hash(token))
    assert session.ip == "10.0.0.99", (
        f"Session IP should be X-Real-IP (10.0.0.99), got {session.ip}"
    )


def test_login_session_uses_remote_addr_without_real_ip(api_client):
    """Without X-Real-IP, login should use REMOTE_ADDR — not XFF."""
    from apps.identity.services import create_user, ensure_seed_roles

    ensure_seed_roles()
    username = "ip_test_user2"
    password = "TestPass!1234"
    create_user(username=username, password=password, roles=("user",))

    res = api_client.post(
        "/api/v1/auth/login",
        {"username": username, "password": password},
        format="json",
        # No X-Real-IP; only XFF (should be ignored)
        HTTP_X_FORWARDED_FOR="8.8.8.8",
    )
    assert res.status_code == 200
    token = res.json()["token"]

    from apps.identity.services import token_hash
    session = Session.objects.get(token_hash=token_hash(token))
    # Should NOT be 8.8.8.8 (the spoofed XFF).
    assert session.ip != "8.8.8.8", "Session IP must not come from X-Forwarded-For"
