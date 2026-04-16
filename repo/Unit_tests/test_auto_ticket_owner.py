"""Auto-created failed-check tickets must include owner + remediation actions.

Tests cover:
- Owner assignment from dataset metadata owner.
- Fallback to operations user, then administrator.
- Remediation action created for each ticket.
- Due date still defaults to 7 days.
- Negative path: no users at all → owner is NULL but ticket still created.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.models import Dataset, DatasetField, DatasetMetadata, DatasetRow
from apps.identity.models import User
from apps.identity.services import ensure_seed_roles
from apps.platform_common.ids import new_id
from apps.quality.models import InspectionRun, InspectionSchedule, QualityRule, QualityRuleField
from apps.quality.services import run_inspection
from apps.tickets.models import IssueTicket, RemediationAction, TicketTransition
from apps.tickets.services import (
    _resolve_ticket_owner,
    auto_create_tickets_for_failed_inspection,
    default_due_date,
)


@pytest.fixture
def seed_roles(db):
    ensure_seed_roles()


@pytest.fixture
def dataset_with_p0(db):
    """Dataset with a P0 completeness rule that will fail (50% < 100%)."""
    ds = Dataset.objects.create(code="auto_tkt_ds", display_name="Auto Ticket DS")
    field = DatasetField.objects.create(
        dataset=ds, field_key="v", display_name="V", data_type="string",
    )
    rule = QualityRule.objects.create(
        dataset=ds, rule_type="completeness", severity="P0",
        threshold_value=100.0, config={},
    )
    QualityRuleField.objects.create(rule=rule, field=field)
    # One row with None, one with value → 50% completeness < 100% threshold → P0 fail.
    DatasetRow.objects.create(dataset=ds, payload={"v": None})
    DatasetRow.objects.create(dataset=ds, payload={"v": "ok"})
    return ds


def _make_user(username, roles=(), active=True):
    from django.contrib.auth.hashers import make_password
    from apps.identity.models import Role, UserRole
    u = User.objects.create(username=username, password_hash=make_password("Test1234!abc"), is_active=active)
    for rname in roles:
        role = Role.objects.get(name=rname)
        UserRole.objects.create(user=u, role=role)
    return u


def test_auto_ticket_includes_owner_from_metadata(seed_roles, dataset_with_p0):
    owner_user = _make_user("metadata_owner", roles=("operations",))
    DatasetMetadata.objects.create(
        dataset=dataset_with_p0, owner="metadata_owner",
        retention_class="standard", sensitivity_level="high",
    )
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        assert t.owner_user_id == owner_user.id


def test_auto_ticket_owner_falls_back_to_operations(seed_roles, dataset_with_p0):
    ops_user = _make_user("ops_fallback", roles=("operations",))
    # No metadata → owner lookup by username fails → fallback to operations
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        assert t.owner_user_id == ops_user.id


def test_auto_ticket_owner_falls_back_to_administrator(seed_roles, dataset_with_p0):
    admin_user = _make_user("admin_fallback", roles=("administrator",))
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        assert t.owner_user_id == admin_user.id


def test_auto_ticket_owner_null_when_no_users(seed_roles, dataset_with_p0):
    """No users exist → owner is NULL but ticket is still created."""
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        assert t.owner_user is None


def test_auto_ticket_has_remediation_action(seed_roles, dataset_with_p0):
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        actions = RemediationAction.objects.filter(ticket=t)
        assert actions.count() >= 1
        action = actions.first()
        assert action.action_type == "investigate_and_fix"
        assert action.status == "pending"
        assert action.created_by == "system"


def test_auto_ticket_due_date_is_7_days(seed_roles, dataset_with_p0):
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    expected = default_due_date()
    for t in tickets:
        assert t.due_date == expected


def test_auto_ticket_has_transition_record(seed_roles, dataset_with_p0):
    run = run_inspection(dataset=dataset_with_p0, actor_id="test", trigger_mode="manual")
    tickets = IssueTicket.objects.filter(inspection_run=run)
    assert tickets.exists()
    for t in tickets:
        transitions = TicketTransition.objects.filter(ticket=t)
        assert transitions.count() >= 1
        assert transitions.first().reason == "auto-created from failed P0 inspection result"
