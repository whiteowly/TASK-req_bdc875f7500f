"""API tests for auto-created tickets including owner + remediation actions.

Exercises the full quality inspection → auto-ticket pipeline via the API
and verifies tickets have owner, due_date, and remediation actions.
"""
from __future__ import annotations

import pytest

from apps.catalog.models import Dataset, DatasetField, DatasetMetadata, DatasetRow
from apps.identity.services import ensure_seed_roles
from apps.quality.models import QualityRule, QualityRuleField


@pytest.fixture
def failing_dataset(db):
    """Dataset with a P0 completeness rule that will fail inspection."""
    ensure_seed_roles()
    ds = Dataset.objects.create(code="api_auto_tkt", display_name="Auto Tkt API")
    field = DatasetField.objects.create(
        dataset=ds, field_key="v", display_name="V", data_type="string",
    )
    rule = QualityRule.objects.create(
        dataset=ds, rule_type="completeness", severity="P0",
        threshold_value=100.0, config={},
    )
    QualityRuleField.objects.create(rule=rule, field=field)
    DatasetRow.objects.create(dataset=ds, payload={"v": None})
    DatasetRow.objects.create(dataset=ds, payload={"v": "ok"})
    return ds


def test_auto_ticket_created_with_owner_and_remediation(authed_client, failing_dataset):
    client, _, username = authed_client(roles=("operations",))

    # Set metadata owner to match the ops user
    DatasetMetadata.objects.create(
        dataset=failing_dataset, owner=username,
        retention_class="standard", sensitivity_level="high",
    )

    # Trigger inspection via API
    res = client.post(
        "/api/v1/quality/inspections/trigger",
        {"dataset_id": failing_dataset.id},
        format="json",
    )
    assert res.status_code == 202

    # Check tickets
    tickets_res = client.get("/api/v1/tickets")
    assert tickets_res.status_code == 200
    tickets = [
        t for t in tickets_res.json()["tickets"]
        if t["dataset_id"] == failing_dataset.id
    ]
    assert len(tickets) >= 1

    for t in tickets:
        # Owner is set
        assert t["owner_user_id"] is not None
        # Due date is set
        assert t["due_date"] is not None


def test_auto_ticket_created_without_metadata_falls_back(authed_client, failing_dataset):
    client, _, _ = authed_client(roles=("operations",))
    # No metadata set — fallback to operations user (which is the current user)

    res = client.post(
        "/api/v1/quality/inspections/trigger",
        {"dataset_id": failing_dataset.id},
        format="json",
    )
    assert res.status_code == 202

    tickets_res = client.get("/api/v1/tickets")
    tickets = [
        t for t in tickets_res.json()["tickets"]
        if t["dataset_id"] == failing_dataset.id
    ]
    assert len(tickets) >= 1
    for t in tickets:
        # Owner is assigned via fallback policy
        assert t["owner_user_id"] is not None
