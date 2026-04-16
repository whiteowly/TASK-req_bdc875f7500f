"""Content read authorization tests.

Proves that authenticated users lacking content:read_published AND
content:read_all capabilities are denied access to content read endpoints.
"""
import pytest

from apps.authorization.services import resolve_capabilities
from apps.identity.services import create_user, ensure_seed_roles, login


def _make_no_content_client(authed_client):
    """Create an authenticated user that has NO content read capabilities.

    We use direct PermissionGrant to give them only 'datasets:read' so they
    are authenticated but lack content:read_published and content:read_all.
    """
    from apps.identity.models import PermissionGrant, Role, User, UserRole
    from rest_framework.test import APIClient
    import secrets

    ensure_seed_roles()
    username = f"nocontent_{secrets.token_hex(4)}"
    password = "TestPass!1234"
    # Create user with NO roles (no inherited capabilities).
    user = User.objects.create(
        username=username,
        password_hash=__import__("apps.identity.services", fromlist=["hash_password"]).hash_password(password),
    )
    # Grant only datasets:read so user is valid but has no content caps.
    PermissionGrant.objects.create(
        principal_type="user",
        principal_id=user.id,
        capability="datasets:read",
        granted_by="test",
    )
    _, token = login(username=username, password=password)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client, user


def _entry(client, ctype="poetry", slug="authztest"):
    res = client.post(
        "/api/v1/content/entries",
        {"content_type": ctype, "slug": slug, "title": slug.title()},
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()


def _add_version(client, entry_id, body="hello world"):
    res = client.post(
        f"/api/v1/content/entries/{entry_id}/versions",
        {"body": body},
        format="json",
    )
    assert res.status_code == 201
    return res.json()


def test_no_content_cap_user_denied_list_entries(authed_client):
    """User without content:read_published is denied GET /content/entries."""
    nocontent_client, _ = _make_no_content_client(authed_client)
    res = nocontent_client.get("/api/v1/content/entries")
    assert res.status_code == 403


def test_no_content_cap_user_denied_entry_detail(authed_client):
    """User without content:read_published is denied GET /content/entries/{id}."""
    ops, _, _ = authed_client(roles=("operations",))
    e = _entry(ops, "poetry", "authz_detail")
    v = _add_version(ops, e["id"])
    ops.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v["id"], "reason": "publish for auth test"},
        format="json", HTTP_IF_MATCH='"1"',
    )

    nocontent_client, _ = _make_no_content_client(authed_client)
    res = nocontent_client.get(f"/api/v1/content/entries/{e['id']}")
    assert res.status_code == 403


def test_no_content_cap_user_denied_versions_list(authed_client):
    """User without content:read_published is denied GET /content/entries/{id}/versions."""
    ops, _, _ = authed_client(roles=("operations",))
    e = _entry(ops, "poetry", "authz_ver")
    _add_version(ops, e["id"])

    nocontent_client, _ = _make_no_content_client(authed_client)
    res = nocontent_client.get(f"/api/v1/content/entries/{e['id']}/versions")
    assert res.status_code == 403


def test_user_role_with_read_published_succeeds(authed_client):
    """A 'user' role holder has content:read_published and can list entries."""
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.get("/api/v1/content/entries")
    assert res.status_code == 200


def test_operations_role_with_read_all_succeeds(authed_client):
    """An 'operations' role holder has content:read_all and can list entries."""
    ops, _, _ = authed_client(roles=("operations",))
    res = ops.get("/api/v1/content/entries")
    assert res.status_code == 200
