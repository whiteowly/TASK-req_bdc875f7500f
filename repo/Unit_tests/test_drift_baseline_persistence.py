"""Distribution drift baseline persistence — proves the baseline comes from
prior persisted inspection snapshots, NOT from re-reading current rows.

These tests exercise the pure-logic path (``no_db`` where possible) and the
persistence path (DB required).
"""
import pytest

from apps.quality.services import (
    _build_histogram,
    _psi,
    evaluate_distribution_drift,
)

pytestmark = pytest.mark.no_db


def test_snapshot_stored_after_evaluation():
    """After evaluating drift with an explicit baseline, the function
    records the current histogram in _last_snapshot for persistence."""
    rows = [{"v": float(i)} for i in range(100)]
    baseline = _build_histogram([float(i) for i in range(100)], num_bins=10,
                                lo=0.0, hi=99.0)
    evaluate_distribution_drift._last_snapshot = {}
    evaluate_distribution_drift(
        rows, ["v"],
        {"baseline": baseline, "baseline_lo": 0.0, "baseline_hi": 99.0},
        dataset_id="",
    )
    snap = evaluate_distribution_drift._last_snapshot
    assert "histogram" in snap
    assert "lo" in snap
    assert "hi" in snap
    assert len(snap["histogram"]) == 10
    assert snap["values_count"] == 100


def test_snapshot_stored_even_when_inactive():
    """When no baseline exists (insufficient history), the function still
    stores a snapshot so future runs can bootstrap from it."""
    rows = [{"v": float(i)} for i in range(20)]
    evaluate_distribution_drift._last_snapshot = {}
    compliance, passed, measured, breach = evaluate_distribution_drift(
        rows, ["v"], {}, dataset_id="",
    )
    assert passed is True  # inactive
    assert compliance == 1.0
    snap = evaluate_distribution_drift._last_snapshot
    assert "histogram" in snap
    assert snap["values_count"] == 20


def test_baseline_from_history_not_current_rows():
    """Prove the fundamental fix: with an explicit baseline that differs from
    the current data, PSI is non-zero.  The old bug would have made
    baseline == current (both from current rows) yielding PSI == 0."""
    # Baseline established when data was in [0, 50).
    baseline_hist = _build_histogram(
        [float(i) for i in range(50)], num_bins=10, lo=0.0, hi=100.0,
    )
    # Current data has shifted to [50, 100).
    current_rows = [{"v": float(i)} for i in range(50, 100)]
    compliance, passed, measured, breach = evaluate_distribution_drift(
        current_rows, ["v"],
        {"baseline": baseline_hist, "baseline_lo": 0.0, "baseline_hi": 100.0},
        dataset_id="",
    )
    assert measured > 0.1, "PSI should be significant when distributions differ"
    assert passed is False
