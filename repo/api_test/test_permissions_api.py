"""Permission grant endpoint."""
def test_admin_can_grant_permission(authed_client, make_user):
    admin, _, _ = authed_client(roles=("administrator",))
    target = make_user("target_perm", "StrongPass!1234", roles=("user",))
    res = admin.post(
        "/api/v1/permissions/grants",
        {"principal_type": "user", "principal_id": target.id, "capability": "tickets:write"},
        format="json",
    )
    assert res.status_code == 201


def test_grant_audit_export_explicitly_blocked(authed_client, make_user):
    admin, _, _ = authed_client(roles=("administrator",))
    target = make_user("target_audit", "StrongPass!1234", roles=("user",))
    res = admin.post(
        "/api/v1/permissions/grants",
        {"principal_type": "user", "principal_id": target.id, "capability": "audit:export "},
        format="json",
    )
    # Defensive guard: cannot delegate audit:export via grants.
    assert res.status_code == 400


def test_operations_cannot_grant(authed_client, make_user):
    ops, _, _ = authed_client(roles=("operations",))
    target = make_user("target_op", "StrongPass!1234", roles=("user",))
    res = ops.post(
        "/api/v1/permissions/grants",
        {"principal_type": "user", "principal_id": target.id, "capability": "tickets:write"},
        format="json",
    )
    assert res.status_code == 403
