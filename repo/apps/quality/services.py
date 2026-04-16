"""Quality scoring, gate logic, and inspection execution."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Dataset, DatasetField, DatasetRow
from apps.platform_common.errors import NotFound, ValidationFailure

from .models import (
    InspectionRun,
    InspectionRuleResult,
    InspectionSchedule,
    QualityRule,
    QualityRuleField,
)

DEFAULT_WEIGHTS = {"P0": 50, "P1": 30, "P2": 15, "P3": 5}


# ---------------------------------------------------------------------------
# Pure-logic scoring + gate (the unit tests below exercise these directly)
# ---------------------------------------------------------------------------

def severity_weight(severity: str) -> int:
    return DEFAULT_WEIGHTS[severity]


def compute_score_and_gate(results: Iterable[Dict[str, Any]]) -> Tuple[float, bool, int]:
    """Take an iterable of dicts ``{severity, weight, compliance, passed}``.

    Returns ``(quality_score, gate_pass, failed_p0_count)``.
    """
    total_w = 0
    weighted = 0.0
    failed_p0 = 0
    for r in results:
        w = int(r.get("weight") or severity_weight(r["severity"]))
        compliance = max(0.0, min(1.0, float(r.get("compliance", 0.0))))
        total_w += w
        weighted += w * compliance
        if r["severity"] == "P0" and not bool(r.get("passed", False)):
            failed_p0 += 1
    score = round(100.0 * weighted / total_w, 2) if total_w > 0 else 0.0
    gate_pass = failed_p0 == 0
    return score, gate_pass, failed_p0


# ---------------------------------------------------------------------------
# Rule execution against persisted dataset rows
# ---------------------------------------------------------------------------

def _value_for(payload: dict, key: str):
    parts = key.split(".")
    cur: Any = payload
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def evaluate_completeness(rows: List[dict], field_keys: List[str]) -> Tuple[float, float]:
    """Return ``(percent_present, breach_or_zero)``.

    A field is considered present when value is not None and not the empty
    string. Compliance is the average presence rate across selected fields.
    """
    if not rows or not field_keys:
        return 1.0, 0.0
    present = 0
    total = 0
    for r in rows:
        for fk in field_keys:
            total += 1
            v = _value_for(r, fk)
            if v is not None and v != "":
                present += 1
    rate = present / total if total else 1.0
    return rate, max(0.0, 1.0 - rate)


def evaluate_uniqueness(rows: List[dict], field_keys: List[str]) -> Tuple[float, float]:
    if not rows or not field_keys:
        return 1.0, 0.0
    seen: dict = {}
    dupes = 0
    for r in rows:
        key = tuple(_value_for(r, fk) for fk in field_keys)
        seen[key] = seen.get(key, 0) + 1
    for _, n in seen.items():
        if n > 1:
            dupes += n - 1
    ratio = dupes / len(rows) if rows else 0.0
    compliance = 1.0 - ratio
    return compliance, ratio


def evaluate_numeric_range(rows: List[dict], field_keys: List[str], cfg: dict) -> Tuple[float, float]:
    if not rows or not field_keys:
        return 1.0, 0.0
    lo = cfg.get("min")
    hi = cfg.get("max")
    out = 0
    total = 0
    for r in rows:
        for fk in field_keys:
            v = _value_for(r, fk)
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                out += 1
                total += 1
                continue
            total += 1
            if lo is not None and num < float(lo):
                out += 1
            elif hi is not None and num > float(hi):
                out += 1
    ratio = out / total if total else 0.0
    return 1.0 - ratio, ratio


def evaluate_consistency(rows: List[dict], cfg: dict) -> Tuple[float, float]:
    """Apply allowlisted predicates to each row.

    Predicate format: ``[{"field": "x", "op": "=", "value": 1}, ...]``
    Allowed ops: =, !=, <, <=, >, >=, in, not_in.
    """
    if not rows:
        return 1.0, 0.0
    preds = cfg.get("predicates") or []
    if not preds:
        return 1.0, 0.0
    allowed_ops = {"=", "!=", "<", "<=", ">", ">=", "in", "not_in"}
    bad = 0
    for r in rows:
        for p in preds:
            op = p.get("op")
            if op not in allowed_ops:
                raise ValidationFailure("invalid consistency op", details={"op": op})
            v = _value_for(r, p.get("field"))
            target = p.get("value")
            ok = False
            try:
                if op == "=":
                    ok = v == target
                elif op == "!=":
                    ok = v != target
                elif op == "<":
                    ok = v is not None and v < target
                elif op == "<=":
                    ok = v is not None and v <= target
                elif op == ">":
                    ok = v is not None and v > target
                elif op == ">=":
                    ok = v is not None and v >= target
                elif op == "in":
                    ok = v in (target or [])
                elif op == "not_in":
                    ok = v not in (target or [])
            except TypeError:
                ok = False
            if not ok:
                bad += 1
                break
    ratio = bad / len(rows) if rows else 0.0
    return 1.0 - ratio, ratio


# ---------------------------------------------------------------------------
# Distribution drift (Population Stability Index)
# ---------------------------------------------------------------------------

MIN_BASELINE_RUNS = 10
PSI_EPSILON = 1e-6  # smoothing term to avoid log(0)
DEFAULT_NUM_BINS = 10


def _build_histogram(values: List[float], num_bins: int = DEFAULT_NUM_BINS,
                     *, lo: Optional[float] = None, hi: Optional[float] = None) -> List[float]:
    """Return a probability vector of length ``num_bins``.

    When ``lo``/``hi`` are supplied the bin edges are fixed (required for
    PSI so baseline and current share the same edges). Values outside
    ``[lo, hi]`` are clamped into the first/last bin.
    """
    if not values:
        return [1.0 / num_bins] * num_bins
    if lo is None:
        lo = min(values)
    if hi is None:
        hi = max(values)
    if lo == hi:
        vec = [0.0] * num_bins
        vec[0] = 1.0
        return vec
    width = (hi - lo) / num_bins
    counts = [0] * num_bins
    for v in values:
        idx = int((v - lo) / width)
        idx = max(0, min(idx, num_bins - 1))
        counts[idx] += 1
    n = float(len(values))
    return [c / n for c in counts]


def _psi(baseline: List[float], current: List[float]) -> float:
    """Compute Population Stability Index between two probability vectors."""
    import math

    psi_val = 0.0
    for b, c in zip(baseline, current):
        b = max(b, PSI_EPSILON)
        c = max(c, PSI_EPSILON)
        psi_val += (c - b) * math.log(c / b)
    return psi_val


def build_baseline_from_history(dataset_id: str, field_key: str,
                                min_runs: int = MIN_BASELINE_RUNS,
                                rule_id: str = "") -> Optional[Dict[str, Any]]:
    """Return a persisted baseline from prior completed inspection results.

    Looks up the ``snapshot_data`` stored on the most recent completed
    inspection rule result for the given rule/field.  Returns a dict with
    keys ``histogram``, ``lo``, ``hi`` when a valid snapshot is available,
    or ``None`` when fewer than ``min_runs`` completed inspections exist
    (rule stays inactive).
    """
    past_runs = (
        InspectionRun.objects
        .filter(dataset_id=dataset_id, status="complete")
        .order_by("-ended_at")[:min_runs]
    )
    if past_runs.count() < min_runs:
        return None

    # Read persisted histogram from the most recent completed result for
    # this rule.  Fall back to aggregating across prior results if no
    # single snapshot has all fields.
    if rule_id:
        latest_result = (
            InspectionRuleResult.objects
            .filter(
                inspection_run__dataset_id=dataset_id,
                inspection_run__status="complete",
                rule_id=rule_id,
            )
            .exclude(snapshot_data={})
            .order_by("-inspection_run__ended_at")
            .first()
        )
        if latest_result and latest_result.snapshot_data:
            snap = latest_result.snapshot_data
            hist = snap.get("histogram")
            if hist and isinstance(hist, list):
                return {
                    "histogram": hist,
                    "lo": snap.get("lo", 0.0),
                    "hi": snap.get("hi", 1.0),
                }
    return None


def evaluate_distribution_drift(
    rows: List[dict],
    field_keys: List[str],
    cfg: dict,
    *,
    dataset_id: str = "",
    rule_id: str = "",
) -> Tuple[float, bool, float, float]:
    """Evaluate distribution drift using PSI.

    ``cfg`` may contain:
    - ``baseline``: explicit baseline histogram (list of floats)
    - ``num_bins``: bin count (default 10)

    If no explicit baseline is provided, the function reads a persisted
    baseline snapshot from the most recent prior completed inspection.
    If insufficient history exists, the rule passes inactively
    (compliance=1, passed=True).

    Returns ``(compliance, passed, measured_psi, breach_delta)``.

    The caller should persist the ``current_snapshot`` attribute set on this
    function's return so future runs can use it as baseline.
    """
    num_bins = int(cfg.get("num_bins", DEFAULT_NUM_BINS))
    baseline = cfg.get("baseline")

    if not field_keys:
        return 1.0, True, 0.0, 0.0

    fk = field_keys[0]
    current_vals = []
    for r in rows:
        v = _value_for(r, fk)
        if v is not None:
            try:
                current_vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if not current_vals:
        return 1.0, True, 0.0, 0.0

    # Determine bin edges for the current histogram (used both for PSI
    # comparison and for persisting the snapshot).
    cur_lo = min(current_vals)
    cur_hi = max(current_vals)

    base_lo = cfg.get("baseline_lo")
    base_hi = cfg.get("baseline_hi")

    if baseline is None and dataset_id:
        history = build_baseline_from_history(
            dataset_id, fk, rule_id=rule_id,
        )
        if history is not None:
            baseline = history["histogram"]
            base_lo = history["lo"]
            base_hi = history["hi"]

    if baseline is None:
        # Not enough history — rule stays inactive.  Still persist a
        # snapshot so future runs can use it as baseline.
        current_hist = _build_histogram(current_vals, num_bins=num_bins,
                                        lo=cur_lo, hi=cur_hi)
        evaluate_distribution_drift._last_snapshot = {
            "histogram": current_hist,
            "lo": cur_lo,
            "hi": cur_hi,
            "values_count": len(current_vals),
        }
        return 1.0, True, 0.0, 0.0

    if base_lo is None or base_hi is None:
        base_lo = cur_lo
        base_hi = cur_hi
    current_hist = _build_histogram(
        current_vals, num_bins=len(baseline), lo=base_lo, hi=base_hi,
    )
    psi_val = _psi(baseline, current_hist)

    measured = round(psi_val, 6)
    compliance = max(0.0, 1.0 - psi_val)

    # Persist current histogram for use as future baseline.
    evaluate_distribution_drift._last_snapshot = {
        "histogram": current_hist,
        "lo": base_lo,
        "hi": base_hi,
        "values_count": len(current_vals),
    }

    return compliance, measured <= 0.0, measured, 0.0  # breach set by caller


# Module-level init so the attribute always exists.
evaluate_distribution_drift._last_snapshot = {}  # type: ignore[attr-defined]


def run_inspection(*, dataset: Dataset, actor_id: str = "",
                   trigger_mode: str = "manual") -> InspectionRun:
    rules = list(QualityRule.objects.filter(dataset=dataset, active=True))
    rows = list(DatasetRow.objects.filter(dataset=dataset).values_list("payload", flat=True))

    run = InspectionRun.objects.create(
        dataset=dataset, trigger_mode=trigger_mode, status="running", created_by=actor_id
    )
    result_dicts = []
    with transaction.atomic():
        for rule in rules:
            field_keys = list(
                rule.rule_fields.select_related("field").values_list("field__field_key", flat=True)
            )
            cfg = rule.config or {}
            if rule.rule_type == "completeness":
                compliance, ratio = evaluate_completeness(rows, field_keys)
                threshold_pct = float(rule.threshold_value) / 100.0
                passed = compliance * 100.0 >= rule.threshold_value
                breach = max(0.0, threshold_pct - compliance) * 100.0
                measured = compliance * 100.0
            elif rule.rule_type == "uniqueness":
                compliance, dup_ratio = evaluate_uniqueness(rows, field_keys)
                # threshold_value: max acceptable duplicate ratio percent (0..100)
                passed = dup_ratio * 100.0 <= rule.threshold_value
                breach = max(0.0, dup_ratio * 100.0 - rule.threshold_value)
                measured = dup_ratio * 100.0
            elif rule.rule_type == "numeric_range":
                compliance, out_ratio = evaluate_numeric_range(rows, field_keys, cfg)
                passed = out_ratio * 100.0 <= rule.threshold_value
                breach = max(0.0, out_ratio * 100.0 - rule.threshold_value)
                measured = out_ratio * 100.0
            elif rule.rule_type == "consistency":
                compliance, bad_ratio = evaluate_consistency(rows, cfg)
                passed = bad_ratio * 100.0 <= rule.threshold_value
                breach = max(0.0, bad_ratio * 100.0 - rule.threshold_value)
                measured = bad_ratio * 100.0
            elif rule.rule_type == "distribution_drift":
                evaluate_distribution_drift._last_snapshot = {}
                compliance, passed, measured, breach = evaluate_distribution_drift(
                    rows, field_keys, cfg,
                    dataset_id=str(dataset.id),
                    rule_id=str(rule.id),
                )
                threshold_psi = float(rule.threshold_value)
                passed = measured <= threshold_psi
                breach = max(0.0, measured - threshold_psi)
            else:
                compliance, passed, measured, breach = 0.0, False, 0.0, 100.0

            weight = severity_weight(rule.severity)
            snapshot = {}
            if rule.rule_type == "distribution_drift":
                snapshot = evaluate_distribution_drift._last_snapshot or {}
            InspectionRuleResult.objects.create(
                inspection_run=run,
                rule=rule,
                measured_value=measured,
                threshold_snapshot=rule.threshold_value,
                severity_snapshot=rule.severity,
                weight_snapshot=weight,
                passed=passed,
                breach_delta=breach,
                snapshot_data=snapshot,
            )
            result_dicts.append({
                "severity": rule.severity,
                "weight": weight,
                "compliance": compliance,
                "passed": passed,
            })

        score, gate_pass, _ = compute_score_and_gate(result_dicts)
        run.quality_score = score
        run.gate_pass = gate_pass
        run.status = "complete"
        run.ended_at = timezone.now()
        run.save(update_fields=["quality_score", "gate_pass", "status", "ended_at"])

    # Auto-ticket creation on failed gate (one ticket per failed P0 result).
    if not run.gate_pass:
        from apps.tickets.services import auto_create_tickets_for_failed_inspection
        auto_create_tickets_for_failed_inspection(run)
    return run
