"""Inspection result immutability — model-layer enforcement tests.

Proves that:
- InspectionRuleResult cannot be updated after creation (save raises).
- InspectionRuleResult cannot be deleted (delete raises).
- Completed InspectionRun cannot be updated (save raises).
- Completed InspectionRun cannot be deleted (delete raises).
"""

import pytest

from django.core.exceptions import ValidationError

from apps.catalog.models import Dataset, DatasetField, DatasetRow
from apps.quality.models import (
    InspectionRuleResult,
    InspectionRun,
    QualityRule,
    QualityRuleField,
)
from apps.quality.services import run_inspection


def _setup_dataset_with_rule(db):
    """Create a minimal dataset + completeness rule + rows for inspection."""
    ds = Dataset.objects.create(code="immut_test", display_name="Immutability Test")
    fld = DatasetField.objects.create(
        dataset=ds,
        field_key="val",
        display_name="val",
        data_type="integer",
    )
    DatasetRow.objects.create(dataset=ds, payload={"val": 1})
    DatasetRow.objects.create(dataset=ds, payload={"val": 2})
    rule = QualityRule.objects.create(
        dataset=ds,
        rule_type="completeness",
        severity="P1",
        threshold_value=90.0,
    )
    QualityRuleField.objects.create(rule=rule, field=fld)
    return ds, rule


# ---------------------------------------------------------------------------
# InspectionRuleResult immutability
# ---------------------------------------------------------------------------


def test_rule_result_update_raises_validation_error(db):
    """Updating an existing InspectionRuleResult must raise ValidationError."""
    ds, rule = _setup_dataset_with_rule(db)
    run = run_inspection(dataset=ds)
    rr = run.results.first()
    assert rr is not None

    rr.measured_value = 999.0
    with pytest.raises(ValidationError) as exc_info:
        rr.save()
    assert "immutable" in str(exc_info.value).lower()


def test_rule_result_delete_raises_validation_error(db):
    """Deleting an InspectionRuleResult must raise ValidationError."""
    ds, rule = _setup_dataset_with_rule(db)
    run = run_inspection(dataset=ds)
    rr = run.results.first()
    assert rr is not None

    with pytest.raises(ValidationError) as exc_info:
        rr.delete()
    msg = str(exc_info.value).lower()
    assert "immutable" in msg or "cannot be deleted" in msg


def test_rule_result_save_fields_rejected(db):
    """Even save(update_fields=[...]) on an existing result must be blocked."""
    ds, rule = _setup_dataset_with_rule(db)
    run = run_inspection(dataset=ds)
    rr = run.results.first()
    assert rr is not None

    rr.passed = not rr.passed
    with pytest.raises(ValidationError):
        rr.save(update_fields=["passed"])


# ---------------------------------------------------------------------------
# Completed InspectionRun immutability
# ---------------------------------------------------------------------------


def test_completed_run_update_raises_validation_error(db):
    """Updating a completed InspectionRun must raise ValidationError."""
    ds, rule = _setup_dataset_with_rule(db)
    run = run_inspection(dataset=ds)
    assert run.status == "complete"

    run.quality_score = 0.0
    with pytest.raises(ValidationError) as exc_info:
        run.save()
    assert "immutable" in str(exc_info.value).lower()


def test_completed_run_delete_raises_validation_error(db):
    """Deleting a completed InspectionRun must raise ValidationError."""
    ds, rule = _setup_dataset_with_rule(db)
    run = run_inspection(dataset=ds)
    assert run.status == "complete"

    with pytest.raises(ValidationError) as exc_info:
        run.delete()
    msg = str(exc_info.value).lower()
    assert "immutable" in msg or "cannot be deleted" in msg


def test_running_run_can_be_finalized(db):
    """A run in 'running' status should be finalizable to 'complete'.
    This proves the immutability guard doesn't block the initial
    running→complete transition."""
    ds, _ = _setup_dataset_with_rule(db)
    # run_inspection creates the run as running then finalizes it to complete
    # — if this succeeds the guard allows the transition.
    run = run_inspection(dataset=ds)
    assert run.status == "complete"
    assert run.quality_score is not None
