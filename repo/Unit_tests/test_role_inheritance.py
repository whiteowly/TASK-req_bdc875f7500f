"""Hierarchical role inheritance: administrator ⊃ operations ⊃ user."""
from apps.authorization.services import (
    ADMIN_CAPS,
    OPERATIONS_CAPS,
    USER_CAPS,
    caps_for_role,
    resolve_capabilities,
)
from apps.identity.services import (
    assign_roles,
    create_user,
    ensure_seed_roles,
)


def test_user_has_only_user_caps():
    caps = caps_for_role("user")
    assert "datasets:read" in caps
    assert "datasets:write" not in caps
    assert "audit:export" not in caps


def test_operations_inherits_user_caps():
    caps = caps_for_role("operations")
    assert USER_CAPS.issubset(caps)
    assert "tickets:write" in caps
    assert "audit:export" not in caps


def test_administrator_inherits_operations_and_user_and_admin_caps():
    caps = caps_for_role("administrator")
    assert USER_CAPS.issubset(caps)
    assert OPERATIONS_CAPS.issubset(caps)
    assert ADMIN_CAPS.issubset(caps)
    assert "audit:export" in caps  # explicitly admin-only


def test_audit_export_not_in_user_or_operations():
    assert "audit:export" not in caps_for_role("user")
    assert "audit:export" not in caps_for_role("operations")


def test_resolve_capabilities_for_real_user(db):
    ensure_seed_roles()
    u = create_user(username="ops_a", password="StrongPass!1234", roles=["operations"])
    role_names, caps = resolve_capabilities(u)
    assert "operations" in role_names
    assert "tickets:write" in caps
    assert "audit:export" not in caps
