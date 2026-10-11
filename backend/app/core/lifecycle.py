"""End-to-End Optimization Lifecycle & Impact Calculation Engine for DBZenith.

Defines:
- Explicit recommendation lifecycle states and backend transition guards.
- Baseline telemetry window capture (latency percentiles, sample size, throughput, errors, I/O).
- Post-change observation validation (distinguishing production observations, sandbox benchmarks, and synthetic demo data).
- Safe impact percentage calculation handling missing data, zero baselines, query fingerprint mismatches,
  and incomparable time windows without dividing by zero or fabricating outcomes.
- Confidence, variability, and non-causal attribution disclaimers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.provenance import (
    ProvenanceBadgeLabel,
    ProvenanceState,
    badge_for_state,
    compute_query_fingerprint,
    sanitize_collection_error,
    sanitize_source_identifier,
)


class LifecycleState(str, Enum):
    DETECTED = "detected"
    ANALYZED = "analyzed"
    PROPOSED = "proposed"
    SIMULATED = "simulated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    READY_FOR_DEPLOYMENT = "ready_for_deployment"
    APPLIED = "applied"
    VALIDATION_PENDING = "validation_pending"
    VERIFIED_SUCCESSFUL = "verified_successful"
    REGRESSED = "regressed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


PRE_DECISION_STATES: set[str] = {
    LifecycleState.DETECTED.value,
    LifecycleState.ANALYZED.value,
    LifecycleState.PROPOSED.value,
    LifecycleState.SIMULATED.value,
    LifecycleState.AWAITING_APPROVAL.value,
}

OUTCOME_STATES: set[str] = {
    LifecycleState.VERIFIED_SUCCESSFUL.value,
    LifecycleState.REGRESSED.value,
    LifecycleState.FAILED.value,
    LifecycleState.INCONCLUSIVE.value,
}

# States that CANNOT be set via a generic status/transition field without dedicated evidence/validation
EVIDENCE_GATED_STATES: set[str] = {
    LifecycleState.APPLIED.value,
    LifecycleState.VERIFIED_SUCCESSFUL.value,
    LifecycleState.REGRESSED.value,
    LifecycleState.FAILED.value,
    LifecycleState.INCONCLUSIVE.value,
}

ALLOWED_LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    LifecycleState.DETECTED.value: {
        LifecycleState.ANALYZED.value,
        LifecycleState.PROPOSED.value,
        LifecycleState.SIMULATED.value,
        LifecycleState.AWAITING_APPROVAL.value,
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
    },
    LifecycleState.ANALYZED.value: {
        LifecycleState.PROPOSED.value,
        LifecycleState.SIMULATED.value,
        LifecycleState.AWAITING_APPROVAL.value,
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
    },
    LifecycleState.PROPOSED.value: {
        LifecycleState.SIMULATED.value,
        LifecycleState.AWAITING_APPROVAL.value,
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
    },
    LifecycleState.SIMULATED.value: {
        LifecycleState.SIMULATED.value,
        LifecycleState.AWAITING_APPROVAL.value,
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
    },
    LifecycleState.AWAITING_APPROVAL.value: {
        LifecycleState.SIMULATED.value,
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
    },
    LifecycleState.APPROVED.value: {
        LifecycleState.READY_FOR_DEPLOYMENT.value,
        LifecycleState.APPLIED.value,
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.REJECTED.value: set(),  # Terminal state
    LifecycleState.READY_FOR_DEPLOYMENT.value: {
        LifecycleState.APPLIED.value,
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.FAILED.value,
    },
    LifecycleState.APPLIED.value: {
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.VALIDATION_PENDING.value: {
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.VERIFIED_SUCCESSFUL.value: {
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.REGRESSED.value: {
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.INCONCLUSIVE.value: {
        LifecycleState.VALIDATION_PENDING.value,
        LifecycleState.VERIFIED_SUCCESSFUL.value,
        LifecycleState.REGRESSED.value,
        LifecycleState.FAILED.value,
        LifecycleState.INCONCLUSIVE.value,
    },
    LifecycleState.FAILED.value: {
        LifecycleState.READY_FOR_DEPLOYMENT.value,
        LifecycleState.VALIDATION_PENDING.value,
    },
}


CAUSALITY_DISCLAIMER = (
    "Observed post-change metrics reflect telemetry correlation across collection windows. "
    "Latency or throughput differences after deployment may be influenced by workload volume, "
    "parameter distribution, buffer pool state, or concurrent database activity and do not "
    "alone establish single-factor causal proof."
)


def is_valid_transition(current_state: str, target_state: str) -> bool:
    """Returns True if transitioning from current_state to target_state is permitted by the state machine."""
    cur = (current_state or LifecycleState.AWAITING_APPROVAL.value).lower()
    tgt = (target_state or "").lower()
    allowed = ALLOWED_LIFECYCLE_TRANSITIONS.get(cur, set())
    return tgt in allowed


def status_for_lifecycle_state(lifecycle_state: str, current_status: str = "pending") -> str:
    """Maps a detailed lifecycle state to the top-level governance status ('pending', 'approved', 'rejected')."""
    st = (lifecycle_state or "").lower()
    if st in PRE_DECISION_STATES:
        return "pending"
    if st == LifecycleState.REJECTED.value:
        return "rejected"
    if st in {
        LifecycleState.APPROVED.value,
        LifecycleState.READY_FOR_DEPLOYMENT.value,
        LifecycleState.APPLIED.value,
        LifecycleState.VALIDATION_PENDING.value,
        *OUTCOME_STATES,
    }:
        return "approved"
    return current_status or "pending"


def _parse_iso_datetime(val: Any) -> datetime | None:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def build_observation_window_metrics(
    *,
    query_id: int | None = None,
    normalized_query: str | None = None,
    query_fingerprint: str | None = None,
    captured_at: datetime | str | None = None,
    window_seconds: float | None = None,
    calls: int | None = None,
    mean_exec_time_ms: float | None = None,
    min_exec_time_ms: float | None = None,
    max_exec_time_ms: float | None = None,
    p50_latency_ms: float | None = None,
    p95_latency_ms: float | None = None,
    p99_latency_ms: float | None = None,
    total_exec_time_ms: float | None = None,
    rows: int | None = None,
    shared_blks_hit: int | None = None,
    shared_blks_read: int | None = None,
    temp_blks_read: int | None = None,
    temp_blks_written: int | None = None,
    blk_read_time_ms: float | None = None,
    blk_write_time_ms: float | None = None,
    query_frequency_per_minute: float | None = None,
    error_count: int = 0,
    source_identifier: str | None = None,
    provenance_state: str = ProvenanceState.LIVE_TELEMETRY.value,
    is_synthetic: bool = False,
    is_measured: bool = True,
    environment: str = "production",
) -> dict[str, Any]:
    """Constructs a standardized telemetry observation window for baseline or post-change comparison."""
    cap_dt = _parse_iso_datetime(captured_at)
    fp = query_fingerprint or (compute_query_fingerprint(normalized_query) if normalized_query else None)
    clean_source = sanitize_source_identifier(source_identifier) if source_identifier else None

    sample_size = int(calls) if calls is not None else 0
    mean_ms = float(mean_exec_time_ms) if mean_exec_time_ms is not None else None
    min_ms = float(min_exec_time_ms) if min_exec_time_ms is not None else mean_ms
    max_ms = float(max_exec_time_ms) if max_exec_time_ms is not None else mean_ms
    win_sec = float(window_seconds) if window_seconds is not None else None

    # Estimate percentiles & variability when raw histogram isn't provided by pg_stat_statements
    if p50_latency_ms is not None:
        p50_ms = float(p50_latency_ms)
    elif mean_ms is not None and min_ms is not None:
        p50_ms = round(min_ms + 0.45 * max(0.0, mean_ms - min_ms), 3)
    else:
        p50_ms = mean_ms

    if p95_latency_ms is not None:
        p95_ms = float(p95_latency_ms)
    elif mean_ms is not None and max_ms is not None:
        p95_ms = round(mean_ms + 0.65 * max(0.0, max_ms - mean_ms), 3)
    else:
        p95_ms = mean_ms

    if p99_latency_ms is not None:
        p99_ms = float(p99_latency_ms)
    elif mean_ms is not None and max_ms is not None:
        p99_ms = round(mean_ms + 0.88 * max(0.0, max_ms - mean_ms), 3)
    else:
        p99_ms = max_ms

    # Variability metrics
    if min_ms is not None and max_ms is not None and max_ms >= min_ms:
        range_ms = round(max_ms - min_ms, 3)
        # Approximate sample standard deviation from range (Wan et al. range/4 heuristic)
        est_stddev = round(range_ms / 4.0, 3) if sample_size > 1 else 0.0
    else:
        range_ms = 0.0
        est_stddev = 0.0

    cv = (
        round(est_stddev / mean_ms, 4)
        if (mean_ms is not None and mean_ms > 0 and est_stddev is not None)
        else None
    )

    # Throughput
    if win_sec is not None and win_sec > 0 and sample_size >= 0:
        throughput_qps = round(sample_size / win_sec, 4)
        throughput_qpm = round(throughput_qps * 60.0, 3)
    elif query_frequency_per_minute is not None and query_frequency_per_minute >= 0:
        throughput_qpm = round(float(query_frequency_per_minute), 3)
        throughput_qps = round(throughput_qpm / 60.0, 4)
    else:
        throughput_qps = None
        throughput_qpm = None

    hit = int(shared_blks_hit or 0)
    read = int(shared_blks_read or 0)
    total_blks = hit + read
    cache_hit_ratio = round(hit / total_blks, 4) if total_blks > 0 else None

    eff_prov = ProvenanceState.SYNTHETIC_DEMO.value if is_synthetic else provenance_state
    eff_measured = False if is_synthetic else bool(is_measured)

    return {
        "query_id": query_id,
        "query_fingerprint": fp,
        "captured_at": cap_dt.isoformat() if cap_dt else None,
        "window_seconds": win_sec,
        "sample_size": sample_size,
        "mean_latency_ms": round(mean_ms, 3) if mean_ms is not None else None,
        "min_latency_ms": round(min_ms, 3) if min_ms is not None else None,
        "max_latency_ms": round(max_ms, 3) if max_ms is not None else None,
        "p50_latency_ms": round(p50_ms, 3) if p50_ms is not None else None,
        "p95_latency_ms": round(p95_ms, 3) if p95_ms is not None else None,
        "p99_latency_ms": round(p99_ms, 3) if p99_ms is not None else None,
        "total_exec_time_ms": round(float(total_exec_time_ms), 3) if total_exec_time_ms is not None else None,
        "throughput_qps": throughput_qps,
        "throughput_qpm": throughput_qpm,
        "rows": int(rows) if rows is not None else 0,
        "error_count": int(error_count or 0),
        "variability": {
            "range_ms": range_ms,
            "estimated_stddev_ms": est_stddev,
            "coefficient_of_variation": cv,
        },
        "resource_indicators": {
            "shared_blks_hit": hit,
            "shared_blks_read": read,
            "cache_hit_ratio": cache_hit_ratio,
            "temp_blks_read": int(temp_blks_read or 0),
            "temp_blks_written": int(temp_blks_written or 0),
            "blk_read_time_ms": round(float(blk_read_time_ms or 0.0), 3),
            "blk_write_time_ms": round(float(blk_write_time_ms or 0.0), 3),
        },
        "source_identifier": clean_source,
        "provenance_state": eff_prov,
        "provenance_badge": badge_for_state(eff_prov),
        "is_synthetic": bool(is_synthetic),
        "is_measured": eff_measured,
        "environment": "synthetic_demo" if is_synthetic else environment,
    }


def _safe_pct_improvement(before: float | None, after: float | None) -> float | None:
    """Computes percentage reduction ((before - after) / before * 100) safely; returns None if before <= 0 or missing."""
    if before is None or after is None:
        return None
    if not math.isfinite(before) or not math.isfinite(after):
        return None
    if before <= 0:
        return None
    return round(((before - after) / before) * 100.0, 2)


def _safe_pct_delta(before: float | None, after: float | None) -> float | None:
    """Computes signed percentage change ((after - before) / before * 100) safely; returns None if before <= 0."""
    if before is None or after is None:
        return None
    if not math.isfinite(before) or not math.isfinite(after):
        return None
    if before <= 0:
        return None
    return round(((after - before) / before) * 100.0, 2)


def calculate_impact_and_uncertainty(
    baseline: dict[str, Any] | None,
    post_change: dict[str, Any] | None,
    *,
    baseline_cost: float | None = None,
    proposed_cost: float | None = None,
    min_sample_size: int = 1,
) -> dict[str, Any]:
    """Calculates before/after impact, comparability checks, outcome classification, and uncertainty metrics.

    Strictly handles:
    - Missing baseline or post-change data
    - Zero or negative baseline values (never divides by zero)
    - Query fingerprint mismatches
    - Incomparable time windows or ordering inversions
    - Failed validation (error_count > 0)
    - Synthetic vs sandbox vs live production provenance
    """
    incomparability_reasons: list[str] = []
    uncertainty_notes: list[str] = [CAUSALITY_DISCLAIMER]

    if not baseline or not isinstance(baseline, dict):
        incomparability_reasons.append("missing_baseline_data")
    if not post_change or not isinstance(post_change, dict):
        incomparability_reasons.append("missing_comparison_data")

    if incomparability_reasons:
        return {
            "is_comparable": False,
            "incomparability_reasons": incomparability_reasons,
            "outcome_classification": LifecycleState.INCONCLUSIVE.value,
            "environment": (post_change or {}).get("environment", "unvalidated") if isinstance(post_change, dict) else "unvalidated",
            "is_synthetic": bool((baseline or {}).get("is_synthetic") or (post_change or {}).get("is_synthetic")),
            "is_measured": False,
            "latency_improvement_pct": None,
            "latency_delta_pct": None,
            "latency_delta_ms": None,
            "p95_latency_improvement_pct": None,
            "cost_improvement_pct": _safe_pct_improvement(baseline_cost, proposed_cost),
            "throughput_change_pct": None,
            "io_read_reduction_pct": None,
            "confidence_assessment": {
                "sample_count_before": int((baseline or {}).get("sample_size") or 0) if isinstance(baseline, dict) else 0,
                "sample_count_after": int((post_change or {}).get("sample_size") or 0) if isinstance(post_change, dict) else 0,
                "window_seconds_before": (baseline or {}).get("window_seconds") if isinstance(baseline, dict) else None,
                "window_seconds_after": (post_change or {}).get("window_seconds") if isinstance(post_change, dict) else None,
                "variability_before_cv": None,
                "variability_after_cv": None,
                "provenance_before": (baseline or {}).get("provenance_state") if isinstance(baseline, dict) else None,
                "provenance_after": (post_change or {}).get("provenance_state") if isinstance(post_change, dict) else None,
                "causality_disclaimer": CAUSALITY_DISCLAIMER,
                "uncertainty_notes": uncertainty_notes,
            },
        }

    assert baseline is not None and post_change is not None

    # Check validation failure / errors first
    post_errors = int(post_change.get("error_count") or 0)
    if post_errors > 0 or post_change.get("validation_failed") is True:
        return {
            "is_comparable": False,
            "incomparability_reasons": ["post_change_execution_errors"],
            "outcome_classification": LifecycleState.FAILED.value,
            "environment": post_change.get("environment", "production"),
            "is_synthetic": bool(baseline.get("is_synthetic") or post_change.get("is_synthetic")),
            "is_measured": bool(post_change.get("is_measured")) and not bool(post_change.get("is_synthetic")),
            "latency_improvement_pct": None,
            "latency_delta_pct": None,
            "latency_delta_ms": None,
            "p95_latency_improvement_pct": None,
            "cost_improvement_pct": _safe_pct_improvement(baseline_cost, proposed_cost),
            "throughput_change_pct": None,
            "io_read_reduction_pct": None,
            "error_message": sanitize_collection_error(post_change.get("error_message")) or f"Validation observed {post_errors} execution error(s).",
            "confidence_assessment": {
                "sample_count_before": int(baseline.get("sample_size") or 0),
                "sample_count_after": int(post_change.get("sample_size") or 0),
                "window_seconds_before": baseline.get("window_seconds"),
                "window_seconds_after": post_change.get("window_seconds"),
                "variability_before_cv": (baseline.get("variability") or {}).get("coefficient_of_variation"),
                "variability_after_cv": (post_change.get("variability") or {}).get("coefficient_of_variation"),
                "provenance_before": baseline.get("provenance_state"),
                "provenance_after": post_change.get("provenance_state"),
                "causality_disclaimer": CAUSALITY_DISCLAIMER,
                "uncertainty_notes": uncertainty_notes,
            },
        }

    # 1. Check query fingerprint match
    fp_before = baseline.get("query_fingerprint")
    fp_after = post_change.get("query_fingerprint")
    if fp_before and fp_after and fp_before != fp_after:
        incomparability_reasons.append("query_fingerprint_mismatch")
        uncertainty_notes.append(
            f"Query fingerprint changed between baseline ({fp_before}) and post-change ({fp_after}); metrics are not directly comparable."
        )

    # 2. Check baseline and comparison latency values
    mean_before = baseline.get("mean_latency_ms")
    mean_after = post_change.get("mean_latency_ms")
    if mean_before is None:
        incomparability_reasons.append("missing_baseline_latency")
    elif float(mean_before) <= 0:
        incomparability_reasons.append("zero_baseline_latency")
        uncertainty_notes.append("Baseline mean latency is zero or non-positive; percentage speedup cannot be calculated.")

    if mean_after is None:
        incomparability_reasons.append("missing_comparison_latency")
    elif float(mean_after) < 0:
        incomparability_reasons.append("invalid_comparison_latency")

    # 3. Check sample counts
    samples_before = int(baseline.get("sample_size") or 0)
    samples_after = int(post_change.get("sample_size") or 0)
    if samples_before < min_sample_size or samples_after < min_sample_size:
        incomparability_reasons.append("insufficient_sample_size")
        uncertainty_notes.append(
            f"Sample count (before={samples_before}, after={samples_after}) is below minimum threshold ({min_sample_size})."
        )

    # 4. Check time windows & chronological ordering
    win_before = baseline.get("window_seconds")
    win_after = post_change.get("window_seconds")
    if win_before is not None and win_after is not None:
        wb = float(win_before)
        wa = float(win_after)
        if wb <= 0 or wa <= 0:
            incomparability_reasons.append("incomparable_time_window")
        else:
            ratio = max(wb, wa) / min(wb, wa)
            if ratio > 24.0:
                incomparability_reasons.append("incomparable_time_window")
                uncertainty_notes.append(
                    f"Collection window duration differs significantly ({wb}s vs {wa}s; ratio {ratio:.1f}x)."
                )

    cap_before = _parse_iso_datetime(baseline.get("captured_at"))
    cap_after = _parse_iso_datetime(post_change.get("captured_at"))
    if cap_before and cap_after and cap_after < cap_before:
        incomparability_reasons.append("post_change_timestamp_precedes_baseline")
        uncertainty_notes.append("Post-change collection timestamp precedes the baseline observation timestamp.")

    is_synthetic = bool(baseline.get("is_synthetic") or post_change.get("is_synthetic"))
    is_measured = bool(post_change.get("is_measured")) and not is_synthetic
    if is_synthetic:
        uncertainty_notes.append("Metrics include synthetic demo data and do not represent live production execution.")
    elif not is_measured:
        uncertainty_notes.append("Post-change values are planner cost estimates rather than measured execution timings.")

    is_comparable = len(incomparability_reasons) == 0

    latency_improvement_pct = (
        _safe_pct_improvement(float(mean_before), float(mean_after))
        if is_comparable and mean_before is not None and mean_after is not None
        else None
    )
    latency_delta_pct = (
        _safe_pct_delta(float(mean_before), float(mean_after))
        if is_comparable and mean_before is not None and mean_after is not None
        else None
    )
    latency_delta_ms = (
        round(float(mean_after) - float(mean_before), 3)
        if is_comparable and mean_before is not None and mean_after is not None and float(mean_before) > 0
        else None
    )

    p95_before = baseline.get("p95_latency_ms")
    p95_after = post_change.get("p95_latency_ms")
    p95_improvement_pct = (
        _safe_pct_improvement(float(p95_before), float(p95_after))
        if is_comparable and p95_before is not None and p95_after is not None
        else None
    )

    qps_before = baseline.get("throughput_qps")
    qps_after = post_change.get("throughput_qps")
    throughput_change_pct = (
        _safe_pct_delta(float(qps_before), float(qps_after))
        if is_comparable and qps_before is not None and qps_after is not None
        else None
    )

    res_before = baseline.get("resource_indicators") or {}
    res_after = post_change.get("resource_indicators") or {}
    reads_before = res_before.get("shared_blks_read")
    reads_after = res_after.get("shared_blks_read")
    io_read_reduction_pct = (
        _safe_pct_improvement(float(reads_before), float(reads_after))
        if is_comparable and reads_before is not None and reads_after is not None
        else None
    )

    cv_before = (baseline.get("variability") or {}).get("coefficient_of_variation")
    cv_after = (post_change.get("variability") or {}).get("coefficient_of_variation")
    high_variability = bool(
        (cv_before is not None and float(cv_before) > 1.25)
        or (cv_after is not None and float(cv_after) > 1.25)
    )
    if high_variability:
        uncertainty_notes.append(
            "High latency variability detected within the observation window; larger sample sizes are recommended."
        )

    # Determine outcome classification
    if not is_comparable or latency_improvement_pct is None:
        outcome = LifecycleState.INCONCLUSIVE.value
    elif latency_improvement_pct <= -5.0:
        # Mean latency increased by >= 5% -> regression
        outcome = LifecycleState.REGRESSED.value
    elif not is_measured and not is_synthetic:
        # Unmeasured hypothetical estimate cannot be classified as verified_successful
        outcome = LifecycleState.INCONCLUSIVE.value
        uncertainty_notes.append("Unmeasured planner estimates cannot be marked as verified successful outcomes.")
    elif latency_improvement_pct >= 5.0:
        if high_variability and latency_improvement_pct < 15.0:
            outcome = LifecycleState.INCONCLUSIVE.value
            uncertainty_notes.append(
                "Observed latency improvement is smaller than measurement variability margin."
            )
        else:
            outcome = LifecycleState.VERIFIED_SUCCESSFUL.value
    else:
        outcome = LifecycleState.INCONCLUSIVE.value
        uncertainty_notes.append(
            f"Observed latency change ({latency_improvement_pct:+.2f}%) is within the +/-5% noise threshold."
        )

    return {
        "is_comparable": is_comparable,
        "incomparability_reasons": incomparability_reasons,
        "outcome_classification": outcome,
        "environment": "synthetic_demo" if is_synthetic else post_change.get("environment", "production"),
        "is_synthetic": is_synthetic,
        "is_measured": is_measured,
        "latency_improvement_pct": latency_improvement_pct,
        "latency_delta_pct": latency_delta_pct,
        "latency_delta_ms": latency_delta_ms,
        "p95_latency_improvement_pct": p95_improvement_pct,
        "cost_improvement_pct": _safe_pct_improvement(baseline_cost, proposed_cost),
        "throughput_change_pct": throughput_change_pct,
        "io_read_reduction_pct": io_read_reduction_pct,
        "confidence_assessment": {
            "sample_count_before": samples_before,
            "sample_count_after": samples_after,
            "window_seconds_before": win_before,
            "window_seconds_after": win_after,
            "variability_before_cv": cv_before,
            "variability_after_cv": cv_after,
            "high_variability": high_variability,
            "provenance_before": baseline.get("provenance_state"),
            "provenance_after": post_change.get("provenance_state"),
            "causality_disclaimer": CAUSALITY_DISCLAIMER,
            "uncertainty_notes": uncertainty_notes,
        },
    }


def ensure_lifecycle_schema(engine: Engine) -> None:
    """Idempotently adds Phase 5 lifecycle and impact columns to existing tables if missing."""
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception:
        return

    json_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
    ts_type = "TIMESTAMPTZ" if engine.dialect.name == "postgresql" else "DATETIME"

    table_columns: dict[str, list[tuple[str, str]]] = {
        "optimization_recommendations": [
            ("lifecycle_state", "VARCHAR(64) NOT NULL DEFAULT 'awaiting_approval'"),
            ("candidate_simulation_id", "BIGINT"),
            ("baseline_metrics", json_type),
            ("post_change_metrics", json_type),
            ("impact_summary", json_type),
            ("deployment_details", json_type),
            ("decided_by", "VARCHAR(128)"),
            ("decided_at", ts_type),
            ("decision_reason", "TEXT"),
            ("applied_at", ts_type),
            ("validated_at", ts_type),
        ],
        "recommendation_audit_events": [
            ("actor_id", "VARCHAR(64)"),
            ("actor_username", "VARCHAR(128)"),
            ("actor_role", "VARCHAR(32)"),
            ("previous_lifecycle_state", "VARCHAR(64)"),
            ("new_lifecycle_state", "VARCHAR(64)"),
        ],
    }

    with engine.begin() as conn:
        for table_name, cols in table_columns.items():
            if table_name not in existing_tables:
                continue
            try:
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            except Exception:
                continue
            for col_name, col_ddl in cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}"))
        # Widen status/action columns on PostgreSQL if needed
        if engine.dialect.name == "postgresql":
            if "optimization_recommendations" in existing_tables:
                conn.execute(
                    text("ALTER TABLE optimization_recommendations ALTER COLUMN status TYPE VARCHAR(64)")
                )
            if "recommendation_audit_events" in existing_tables:
                conn.execute(
                    text("ALTER TABLE recommendation_audit_events ALTER COLUMN action TYPE VARCHAR(64)")
                )
                conn.execute(
                    text("ALTER TABLE recommendation_audit_events ALTER COLUMN previous_status TYPE VARCHAR(64)")
                )
                conn.execute(
                    text("ALTER TABLE recommendation_audit_events ALTER COLUMN new_status TYPE VARCHAR(64)")
                )
