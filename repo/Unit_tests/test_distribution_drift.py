"""Distribution drift (PSI) evaluation — real implementation tests."""
import pytest

from apps.quality.services import (
    _build_histogram,
    _psi,
    evaluate_distribution_drift,
)

pytestmark = pytest.mark.no_db


def test_identical_distributions_zero_psi():
    # Same data, same bin edges → PSI = 0.
    baseline = _build_histogram([1.0, 2.0, 3.0, 4.0, 5.0], num_bins=5, lo=1.0, hi=5.0)
    current = _build_histogram([1.0, 2.0, 3.0, 4.0, 5.0], num_bins=5, lo=1.0, hi=5.0)
    psi = _psi(baseline, current)
    assert abs(psi) < 1e-6


def test_shifted_distribution_positive_psi():
    # Baseline in [0,5], current in [4,6] → strong drift.
    # Both histogrammed on shared range [0,6].
    baseline = _build_histogram([1.0, 2.0, 3.0, 4.0, 5.0], num_bins=5, lo=0.0, hi=6.0)
    current = _build_histogram([4.0, 4.5, 5.0, 5.5, 6.0], num_bins=5, lo=0.0, hi=6.0)
    psi = _psi(baseline, current)
    assert psi > 0.1  # significant drift


def test_build_histogram_uniform():
    vals = list(range(100))
    hist = _build_histogram(vals, num_bins=10)
    assert len(hist) == 10
    assert all(abs(h - 0.1) < 0.02 for h in hist)


def test_build_histogram_constant():
    hist = _build_histogram([5.0] * 50, num_bins=5)
    assert hist[0] == 1.0
    assert sum(hist) == 1.0


def test_evaluate_drift_no_baseline_passes():
    rows = [{"v": i} for i in range(5)]
    compliance, passed, measured, breach = evaluate_distribution_drift(
        rows, ["v"], {}, dataset_id="",
    )
    assert passed is True
    assert compliance == 1.0


def test_evaluate_drift_with_explicit_baseline_pass():
    rows = [{"v": float(i)} for i in range(100)]
    # Baseline built from the same range — PSI ≈ 0.
    baseline = _build_histogram([float(i) for i in range(100)], num_bins=10, lo=0.0, hi=99.0)
    compliance, passed, measured, breach = evaluate_distribution_drift(
        rows, ["v"], {"baseline": baseline, "baseline_lo": 0.0, "baseline_hi": 99.0},
        dataset_id="",
    )
    assert passed is True
    assert measured < 0.01


def test_evaluate_drift_with_shifted_baseline_fails():
    # baseline in [0,50), current in [50,100) — same shared range [0,100].
    baseline = _build_histogram([float(i) for i in range(50)], num_bins=10, lo=0.0, hi=100.0)
    rows = [{"v": float(i)} for i in range(50, 100)]
    compliance, passed, measured, breach = evaluate_distribution_drift(
        rows, ["v"], {"baseline": baseline, "baseline_lo": 0.0, "baseline_hi": 100.0},
        dataset_id="",
    )
    assert passed is False
    assert measured > 0.1


def test_evaluate_drift_empty_rows_passes():
    compliance, passed, measured, breach = evaluate_distribution_drift(
        [], ["v"], {}, dataset_id="",
    )
    assert passed is True
    assert compliance == 1.0


def test_evaluate_drift_no_field_keys_passes():
    compliance, passed, measured, breach = evaluate_distribution_drift(
        [{"v": 1}], [], {}, dataset_id="",
    )
    assert passed is True
