"""Direct tests for completeness/uniqueness/numeric_range/consistency rule logic."""
import pytest

from apps.quality.services import (
    evaluate_completeness,
    evaluate_consistency,
    evaluate_numeric_range,
    evaluate_uniqueness,
)

pytestmark = pytest.mark.no_db


def test_completeness_full_presence():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    rate, breach = evaluate_completeness(rows, ["a", "b"])
    assert rate == 1.0
    assert breach == 0.0


def test_completeness_partial_presence():
    rows = [{"a": 1, "b": ""}, {"a": None, "b": "y"}]
    rate, _ = evaluate_completeness(rows, ["a", "b"])
    assert rate == 0.5


def test_uniqueness_no_duplicates():
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    compliance, ratio = evaluate_uniqueness(rows, ["id"])
    assert compliance == 1.0
    assert ratio == 0.0


def test_uniqueness_with_duplicates():
    rows = [{"id": 1}, {"id": 1}, {"id": 2}]
    _, ratio = evaluate_uniqueness(rows, ["id"])
    # 1 dupe out of 3 rows = 0.333...
    assert round(ratio, 3) == 0.333


def test_numeric_range_in_bounds():
    rows = [{"v": 5}, {"v": 10}]
    compliance, ratio = evaluate_numeric_range(rows, ["v"], {"min": 0, "max": 100})
    assert compliance == 1.0
    assert ratio == 0.0


def test_numeric_range_out_of_bounds():
    rows = [{"v": -1}, {"v": 50}, {"v": 200}]
    _, ratio = evaluate_numeric_range(rows, ["v"], {"min": 0, "max": 100})
    assert round(ratio, 3) == round(2 / 3, 3)


def test_consistency_predicate_pass():
    rows = [{"a": 1}, {"a": 1}]
    compliance, ratio = evaluate_consistency(
        rows, {"predicates": [{"field": "a", "op": "=", "value": 1}]}
    )
    assert compliance == 1.0
    assert ratio == 0.0


def test_consistency_predicate_violation_counts():
    rows = [{"a": 1}, {"a": 2}, {"a": 1}]
    _, ratio = evaluate_consistency(
        rows, {"predicates": [{"field": "a", "op": "=", "value": 1}]}
    )
    assert round(ratio, 3) == round(1 / 3, 3)


def test_consistency_rejects_unallowed_op():
    from apps.platform_common.errors import ValidationFailure

    rows = [{"a": 1}]
    with pytest.raises(ValidationFailure):
        evaluate_consistency(
            rows, {"predicates": [{"field": "a", "op": "raw_sql", "value": "DROP TABLE x"}]}
        )
