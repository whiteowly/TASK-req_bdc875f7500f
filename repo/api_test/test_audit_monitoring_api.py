"""Audit log + monitoring metrics API tests."""

import pytest

from apps.audit_monitoring.models import EventLog


def test_audit_export_admin_only(authed_client):
    admin, _, _ = authed_client(roles=("administrator",))
    res = admin.post(
        "/api/v1/audit/exports",
        {"start": "2026-01-01T00:00:00Z", "end": "2026-12-31T23:59:59Z"},
        format="json",
    )
    assert res.status_code == 202
    assert "audit_export_id" in res.json()


def test_audit_export_forbidden_for_operations(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    res = ops.post(
        "/api/v1/audit/exports",
        {"start": "2026-01-01T00:00:00Z", "end": "2026-12-31T23:59:59Z"},
        format="json",
    )
    assert res.status_code == 403


def test_audit_export_forbidden_for_user(authed_client):
    uc, _, _ = authed_client(roles=("user",))
    res = uc.post(
        "/api/v1/audit/exports",
        {"start": "2026-01-01T00:00:00Z", "end": "2026-12-31T23:59:59Z"},
        format="json",
    )
    assert res.status_code == 403


def test_audit_logs_admin_can_read(authed_client):
    admin, _, _ = authed_client(roles=("administrator",))
    res = admin.get("/api/v1/audit/logs")
    assert res.status_code == 200
    body = res.json()
    assert "audit_logs" in body
    assert isinstance(body["audit_logs"], list)
    if body["audit_logs"]:
        entry = body["audit_logs"][0]
        assert "action" in entry
        assert "actor_user_id" in entry
        assert "created_at" in entry


def test_post_event_validation(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    bad = ops.post("/api/v1/monitoring/events", {"event_type": "bogus"}, format="json")
    assert bad.status_code == 400
    good = ops.post(
        "/api/v1/monitoring/events", {"event_type": "ingestion_success"}, format="json"
    )
    assert good.status_code == 201


def test_metrics_compute_ctr_from_local_events(authed_client, db):
    ops, _, _ = authed_client(roles=("operations",))
    for _ in range(10):
        EventLog.objects.create(event_type="recommendation_impression", payload={})
    for _ in range(2):
        EventLog.objects.create(event_type="recommendation_click", payload={})
    res = ops.get("/api/v1/monitoring/metrics")
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation_impressions"] == 10
    assert body["recommendation_clicks"] == 2
    assert body["recommendation_ctr"] == 0.2


def test_audit_log_immutability(db):
    """Direct test that AuditLog rejects updates and deletes."""
    from apps.audit_monitoring.models import AuditLog

    a = AuditLog.objects.create(
        actor_user_id="x", action="t", object_type="o", object_id="1"
    )
    a.action = "tampered"
    with pytest.raises(RuntimeError):
        a.save()
    with pytest.raises(RuntimeError):
        a.delete()
