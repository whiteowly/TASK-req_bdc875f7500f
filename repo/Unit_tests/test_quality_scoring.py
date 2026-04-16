"""Unit tests for quality scoring and the P0 hard-fail gate.

These call into the real domain functions in
``apps.quality.services``. No mocks/monkeypatching.
"""
import pytest

from apps.quality.services import (
    DEFAULT_WEIGHTS,
    compute_score_and_gate,
    severity_weight,
)

pytestmark = pytest.mark.no_db


def test_default_weights_match_spec():
    assert DEFAULT_WEIGHTS == {"P0": 50, "P1": 30, "P2": 15, "P3": 5}


def test_score_all_pass_returns_100():
    results = [
        {"severity": "P0", "weight": 50, "compliance": 1.0, "passed": True},
        {"severity": "P1", "weight": 30, "compliance": 1.0, "passed": True},
        {"severity": "P2", "weight": 15, "compliance": 1.0, "passed": True},
        {"severity": "P3", "weight": 5, "compliance": 1.0, "passed": True},
    ]
    score, gate, failed_p0 = compute_score_and_gate(results)
    assert score == 100.0
    assert gate is True
    assert failed_p0 == 0


def test_weighted_average_rounding():
    # 50*0.8 + 30*1.0 + 15*1.0 + 5*1.0 = 40 + 30 + 15 + 5 = 90; total weight 100 -> 90.0
    results = [
        {"severity": "P0", "weight": 50, "compliance": 0.8, "passed": True},
        {"severity": "P1", "weight": 30, "compliance": 1.0, "passed": True},
        {"severity": "P2", "weight": 15, "compliance": 1.0, "passed": True},
        {"severity": "P3", "weight": 5, "compliance": 1.0, "passed": True},
    ]
    score, gate, _ = compute_score_and_gate(results)
    assert score == 90.0
    assert gate is True  # P0 still passed


def test_p0_breach_forces_gate_fail_even_with_high_score():
    results = [
        {"severity": "P0", "weight": 50, "compliance": 0.99, "passed": False},
        {"severity": "P1", "weight": 30, "compliance": 1.0, "passed": True},
        {"severity": "P2", "weight": 15, "compliance": 1.0, "passed": True},
    ]
    score, gate, failed_p0 = compute_score_and_gate(results)
    assert gate is False
    assert failed_p0 == 1
    # Score is still computed; the gate is the override.
    assert score > 90.0


def test_compliance_clamped_to_unit_interval():
    score, _, _ = compute_score_and_gate(
        [{"severity": "P3", "weight": 5, "compliance": 5.0, "passed": True}]
    )
    assert score == 100.0


def test_empty_results_returns_zero():
    score, gate, failed = compute_score_and_gate([])
    assert score == 0.0
    assert gate is True
    assert failed == 0


def test_severity_weight_lookup():
    assert severity_weight("P0") == 50
    assert severity_weight("P3") == 5
    with pytest.raises(KeyError):
        severity_weight("PX")
