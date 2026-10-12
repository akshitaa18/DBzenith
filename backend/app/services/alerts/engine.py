"""Deterministic Workload & Query Regression Alert Engine (Phase 8 Feature B).

Implements:
1. Configurable threshold rules for supported deterministic metrics (latency, errors, throughput, I/O & temp disk resources).
2. Explicit rejection and reporting of unsupported metrics or predictive anomaly claims.
3. Historical baseline calculation with minimum baseline and comparison sample counts.
4. Multi-sample consecutive breach verification to avoid triggering on a single noisy measurement unless explicitly configured.
5. Alert deduplication (updating last_observed_at and occurrence_count without creating duplicate active alerts),
   post-resolution cooldown windows, and automatic recovery/resolution states.
6. Full acknowledgment and resolution lifecycle with immutable AlertAuditEvent and SecurityAuditEvent records.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.provenance import (
    ProvenanceState,
    badge_for_state,
    compute_query_fingerprint,
    sanitize_source_identifier,
)
from app.models.alert import AlertAuditEvent, WorkloadAlert, WorkloadAlertRule
from app.models.security import SecurityAuditEvent
from app.models.workload import QueryStatistic, WorkloadSnapshot

SUPPORTED_ALERT_METRICS: dict[str, dict[str, Any]] = {
    "mean_exec_time_ms": {
        "label": "Mean Query Execution Latency (ms)",
        "unit": "ms",
        "category": "latency",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Average execution latency per call from pg_stat_statements / query_statistics.",
    },
    "max_exec_time_ms": {
        "label": "Maximum Query Execution Latency (ms)",
        "unit": "ms",
        "category": "latency",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Peak execution latency observed in the snapshot window.",
    },
    "total_exec_time_ms": {
        "label": "Total Workload Execution Time (ms)",
        "unit": "ms",
        "category": "latency",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Cumulative execution time across calls within the snapshot.",
    },
    "calls_per_minute": {
        "label": "Query Throughput / Call Frequency (calls/min)",
        "unit": "calls/min",
        "category": "throughput",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Execution call rate per minute.",
    },
    "shared_blks_read": {
        "label": "Shared Buffer Disk Reads (blocks)",
        "unit": "blocks",
        "category": "resource_io",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Physical disk block reads missing shared buffer cache.",
    },
    "temp_blks_written": {
        "label": "Temp Disk Spill Written (blocks)",
        "unit": "blocks",
        "category": "resource_memory",
        "scopes": ["query", "workload"],
        "default_operator": "abs_above",
        "description": "Temporary disk blocks written due to sort/hash work_mem spills.",
    },
    "blk_read_time_ms": {
        "label": "Block Read I/O Time (ms)",
        "unit": "ms",
        "category": "resource_io",
        "scopes": ["query", "workload"],
        "default_operator": "pct_increase",
        "description": "Time spent reading data blocks from disk (when track_io_timing is enabled).",
    },
    "collection_errors": {
        "label": "Telemetry & Execution Error Count",
        "unit": "errors",
        "category": "errors",
        "scopes": ["workload"],
        "default_operator": "abs_above",
        "description": "Number of telemetry collection or database probe errors recorded in snapshots.",
    },
}

VALID_COMPARISON_OPERATORS = {"pct_increase", "abs_above", "pct_decrease", "both"}
VALID_ALERT_SEVERITIES = {"critical", "high", "warning", "info"}
VALID_ALERT_SCOPES = {"query", "workload"}


def validate_alert_rule_params(
    *,
    metric_name: str,
    comparison_operator: str = "pct_increase",
    scope: str = "query",
    threshold_value: float = 50.0,
    min_baseline_samples: int = 3,
    min_comparison_samples: int = 2,
    consecutive_breaches_required: int = 2,
    cooldown_seconds: int = 1800,
    severity: str = "high",
) -> None:
    if metric_name not in SUPPORTED_ALERT_METRICS:
        supported_list = ", ".join(sorted(SUPPORTED_ALERT_METRICS.keys()))
        raise ValueError(
            f"Unsupported alert metric '{metric_name}'. "
            f"DBZenith uses deterministic telemetry rules only. Supported metrics: {supported_list}"
        )
    if comparison_operator not in VALID_COMPARISON_OPERATORS:
        raise ValueError(
            f"Unsupported comparison_operator '{comparison_operator}'. "
            f"Allowed: {', '.join(sorted(VALID_COMPARISON_OPERATORS))}"
        )
    if scope not in VALID_ALERT_SCOPES:
        raise ValueError(f"Unsupported scope '{scope}'. Allowed: query, workload")
    metric_meta = SUPPORTED_ALERT_METRICS[metric_name]
    if scope not in metric_meta["scopes"]:
        raise ValueError(
            f"Metric '{metric_name}' only supports scope(s): {', '.join(metric_meta['scopes'])}"
        )
    if threshold_value < 0:
        raise ValueError("threshold_value must be non-negative.")
    if min_baseline_samples < 1:
        raise ValueError("min_baseline_samples must be at least 1.")
    if min_comparison_samples < 1:
        raise ValueError("min_comparison_samples must be at least 1.")
    if consecutive_breaches_required < 1:
        raise ValueError("consecutive_breaches_required must be at least 1.")
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative.")
    if severity not in VALID_ALERT_SEVERITIES:
        raise ValueError(f"Unsupported severity '{severity}'. Allowed: critical, high, warning, info")


def ensure_default_alert_rules(db: Session) -> list[WorkloadAlertRule]:
    """Seeds default deterministic regression alert rules if none exist."""
    existing = db.scalars(select(WorkloadAlertRule).order_by(WorkloadAlertRule.id)).all()
    if existing:
        return list(existing)

    defaults = [
        WorkloadAlertRule(
            rule_key="default_query_latency_regression",
            name="Query Mean Latency Regression (+50%)",
            description=(
                "Triggers when a query fingerprint's mean execution latency increases by at least 50% "
                "over its historical baseline (minimum 80ms absolute latency) across 2+ consecutive observations."
            ),
            metric_name="mean_exec_time_ms",
            scope="query",
            comparison_operator="pct_increase",
            threshold_value=50.0,
            min_absolute_value=80.0,
            baseline_window_seconds=86400,
            comparison_window_seconds=3600,
            min_baseline_samples=2,
            min_comparison_samples=2,
            consecutive_breaches_required=2,
            allow_single_measurement=False,
            cooldown_seconds=1800,
            auto_resolve=True,
            recovery_threshold_pct=15.0,
            severity="critical",
            enabled=True,
            created_by="system",
        ),
        WorkloadAlertRule(
            rule_key="default_query_shared_reads_surge",
            name="Shared Buffer Disk Read Surge (+100%)",
            description=(
                "Triggers when physical shared_blks_read for a query fingerprint doubles (+100%) "
                "over baseline (minimum 500 blocks) across 2+ consecutive observations."
            ),
            metric_name="shared_blks_read",
            scope="query",
            comparison_operator="pct_increase",
            threshold_value=100.0,
            min_absolute_value=500.0,
            baseline_window_seconds=86400,
            comparison_window_seconds=3600,
            min_baseline_samples=2,
            min_comparison_samples=2,
            consecutive_breaches_required=2,
            allow_single_measurement=False,
            cooldown_seconds=1800,
            auto_resolve=True,
            recovery_threshold_pct=20.0,
            severity="high",
            enabled=True,
            created_by="system",
        ),
        WorkloadAlertRule(
            rule_key="default_query_temp_disk_spill",
            name="Temp Disk Spill Threshold (>200 blocks)",
            description=(
                "Triggers when sort or hash operations spill more than 200 temporary blocks to disk "
                "across 2+ consecutive observations."
            ),
            metric_name="temp_blks_written",
            scope="query",
            comparison_operator="abs_above",
            threshold_value=200.0,
            min_absolute_value=200.0,
            baseline_window_seconds=86400,
            comparison_window_seconds=3600,
            min_baseline_samples=2,
            min_comparison_samples=2,
            consecutive_breaches_required=2,
            allow_single_measurement=False,
            cooldown_seconds=1800,
            auto_resolve=True,
            recovery_threshold_pct=None,
            severity="warning",
            enabled=True,
            created_by="system",
        ),
        WorkloadAlertRule(
            rule_key="default_telemetry_collection_errors",
            name="Telemetry Collector Error Alert",
            description="Triggers when a workload snapshot records a collection or database probe error.",
            metric_name="collection_errors",
            scope="workload",
            comparison_operator="abs_above",
            threshold_value=1.0,
            min_absolute_value=1.0,
            baseline_window_seconds=86400,
            comparison_window_seconds=3600,
            min_baseline_samples=1,
            min_comparison_samples=1,
            consecutive_breaches_required=1,
            allow_single_measurement=True,
            cooldown_seconds=900,
            auto_resolve=True,
            recovery_threshold_pct=None,
            severity="high",
            enabled=True,
            created_by="system",
        ),
    ]
    for r in defaults:
        db.add(r)
    db.commit()
    return db.scalars(select(WorkloadAlertRule).order_by(WorkloadAlertRule.id)).all()


class RegressionAlertEngine:
    """Evaluates deterministic workload and query regression rules with deduplication, cooldowns, and recovery."""

    def evaluate(
        self,
        db: Session,
        *,
        rule_ids: list[int] | None = None,
        now_override: datetime | None = None,
    ) -> dict[str, Any]:
        now = now_override or datetime.now(timezone.utc)
        ensure_default_alert_rules(db)

        stmt = select(WorkloadAlertRule).where(WorkloadAlertRule.enabled.is_(True))
        if rule_ids:
            stmt = stmt.where(WorkloadAlertRule.id.in_(rule_ids))
        rules = db.scalars(stmt.order_by(WorkloadAlertRule.id)).all()

        snapshots = db.scalars(
            select(WorkloadSnapshot).order_by(WorkloadSnapshot.captured_at.asc(), WorkloadSnapshot.id.asc())
        ).all()
        query_rows = db.scalars(
            select(QueryStatistic).order_by(QueryStatistic.snapshot_id.asc(), QueryStatistic.id.asc())
        ).all()

        # Group query rows by fingerprint in chronological snapshot order
        by_fingerprint: dict[str, list[QueryStatistic]] = {}
        for q in query_rows:
            fp = q.query_fingerprint or compute_query_fingerprint(q.normalized_query)
            by_fingerprint.setdefault(fp, []).append(q)

        triggered_alerts: list[WorkloadAlert] = []
        deduplicated_alerts: list[WorkloadAlert] = []
        auto_resolved_alerts: list[WorkloadAlert] = []
        suppressed_evaluations: list[dict[str, Any]] = []
        insufficient_history_items: list[dict[str, Any]] = []
        unsupported_metrics: list[dict[str, Any]] = []

        for rule in rules:
            if rule.metric_name not in SUPPORTED_ALERT_METRICS:
                unsupported_metrics.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "metric_name": rule.metric_name,
                        "reason_code": "unsupported_metric",
                        "detail": (
                            f"Metric '{rule.metric_name}' is not supported. "
                            f"Supported deterministic metrics: {', '.join(sorted(SUPPORTED_ALERT_METRICS.keys()))}"
                        ),
                    }
                )
                continue

            if rule.scope == "workload":
                self._evaluate_workload_series(
                    db=db,
                    rule=rule,
                    snapshots=snapshots,
                    now=now,
                    triggered_alerts=triggered_alerts,
                    deduplicated_alerts=deduplicated_alerts,
                    auto_resolved_alerts=auto_resolved_alerts,
                    suppressed_evaluations=suppressed_evaluations,
                    insufficient_history_items=insufficient_history_items,
                )
            else:
                for fp, series in by_fingerprint.items():
                    if rule.query_fingerprint_filter and rule.query_fingerprint_filter.strip():
                        flt = rule.query_fingerprint_filter.strip().lower()
                        q_sql_low = (series[-1].normalized_query or "").lower()
                        if flt != fp.lower() and flt not in q_sql_low and flt != str(series[-1].query_id):
                            continue
                    self._evaluate_query_series(
                        db=db,
                        rule=rule,
                        query_fingerprint=fp,
                        series=series,
                        now=now,
                        triggered_alerts=triggered_alerts,
                        deduplicated_alerts=deduplicated_alerts,
                        auto_resolved_alerts=auto_resolved_alerts,
                        suppressed_evaluations=suppressed_evaluations,
                        insufficient_history_items=insufficient_history_items,
                    )

        db.commit()
        return {
            "evaluated_at": now.isoformat(),
            "rules_evaluated": len(rules),
            "triggered_count": len(triggered_alerts),
            "deduplicated_count": len(deduplicated_alerts),
            "auto_resolved_count": len(auto_resolved_alerts),
            "triggered_alert_ids": [a.id for a in triggered_alerts],
            "deduplicated_alert_ids": [a.id for a in deduplicated_alerts],
            "auto_resolved_alert_ids": [a.id for a in auto_resolved_alerts],
            "suppressed_evaluations": suppressed_evaluations,
            "insufficient_history": insufficient_history_items,
            "unsupported_metrics": unsupported_metrics,
        }

    def _extract_query_metric(self, q: QueryStatistic, metric_name: str) -> float:
        if metric_name == "mean_exec_time_ms":
            return float(q.mean_exec_time_ms or 0.0)
        if metric_name == "max_exec_time_ms":
            return float(q.max_exec_time_ms or 0.0)
        if metric_name == "total_exec_time_ms":
            return float(q.total_exec_time_ms or 0.0)
        if metric_name == "calls_per_minute":
            return float(q.query_frequency_per_minute or 0.0)
        if metric_name == "shared_blks_read":
            return float(q.shared_blks_read or 0)
        if metric_name == "temp_blks_written":
            return float(q.temp_blks_written or 0)
        if metric_name == "blk_read_time_ms":
            return float(q.blk_read_time_ms or 0.0)
        return 0.0

    def _extract_workload_metric(self, s: WorkloadSnapshot, metric_name: str) -> float:
        if metric_name == "total_exec_time_ms":
            return float(s.total_exec_time_ms or 0.0)
        if metric_name == "mean_exec_time_ms":
            calls = max(1, int(s.total_calls or 0))
            return round(float(s.total_exec_time_ms or 0.0) / calls, 3)
        if metric_name == "calls_per_minute":
            win = max(1.0, float(s.window_seconds or 60.0))
            return round(float(s.total_calls or 0) / win * 60.0, 2)
        if metric_name == "collection_errors":
            return 1.0 if (s.collection_status == "error" or bool(s.collection_error)) else 0.0
        return 0.0

    def _check_breach(
        self,
        *,
        value: float,
        baseline: float,
        operator: str,
        threshold: float,
        min_abs: float,
    ) -> tuple[bool, float]:
        if value < min_abs and operator in ("pct_increase", "abs_above", "both"):
            return False, 0.0

        if baseline > 0:
            pct_change = round(((value - baseline) / baseline) * 100.0, 2)
        else:
            pct_change = 100.0 if value > 0 else 0.0

        if operator == "abs_above":
            return value >= threshold, pct_change
        if operator == "pct_increase":
            return baseline > 0 and pct_change >= threshold, pct_change
        if operator == "pct_decrease":
            drop_pct = -pct_change
            return baseline > 0 and drop_pct >= threshold, pct_change
        if operator == "both":
            return (value >= threshold and (baseline <= 0 or pct_change >= threshold)), pct_change
        return False, pct_change

    def _partition_series(
        self,
        series: list[Any],
        rule: WorkloadAlertRule,
    ) -> tuple[list[Any], list[Any]]:
        req_comp = 1 if rule.allow_single_measurement else max(rule.min_comparison_samples, rule.consecutive_breaches_required)
        total_needed = rule.min_baseline_samples + req_comp
        if len(series) < total_needed:
            if len(series) >= rule.min_baseline_samples + 1:
                return series[: rule.min_baseline_samples], series[rule.min_baseline_samples :]
            return series, []
        return series[:-req_comp], series[-req_comp:]

    def _evaluate_query_series(
        self,
        *,
        db: Session,
        rule: WorkloadAlertRule,
        query_fingerprint: str,
        series: list[QueryStatistic],
        now: datetime,
        triggered_alerts: list[WorkloadAlert],
        deduplicated_alerts: list[WorkloadAlert],
        auto_resolved_alerts: list[WorkloadAlert],
        suppressed_evaluations: list[dict[str, Any]],
        insufficient_history_items: list[dict[str, Any]],
    ) -> None:
        dedup_key = f"rule:{rule.id}:metric:{rule.metric_name}:fp:{query_fingerprint}"
        req_breaches = 1 if rule.allow_single_measurement else max(2, int(rule.consecutive_breaches_required or 2))
        req_comp = 1 if rule.allow_single_measurement else max(int(rule.min_comparison_samples or 1), req_breaches)

        # Check if an active/acknowledged alert already exists and whether the latest sample recovered
        active_alert = db.scalar(
            select(WorkloadAlert).where(
                WorkloadAlert.dedup_key == dedup_key,
                WorkloadAlert.status.in_(["active", "acknowledged"]),
            )
        )

        if len(series) < rule.min_baseline_samples + 1:
            insufficient_history_items.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "metric_name": rule.metric_name,
                    "query_fingerprint": query_fingerprint,
                    "reason_code": "insufficient_baseline_samples",
                    "observed_total_samples": len(series),
                    "required_baseline_samples": rule.min_baseline_samples,
                    "required_comparison_samples": req_comp,
                    "detail": (
                        f"Query fingerprint '{query_fingerprint}' has {len(series)} observation(s), "
                        f"fewer than the required {rule.min_baseline_samples} baseline + {req_comp} comparison samples."
                    ),
                }
            )
            return

        baseline_obs, comp_obs = self._partition_series(series, rule)

        if len(baseline_obs) < rule.min_baseline_samples:
            insufficient_history_items.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "metric_name": rule.metric_name,
                    "query_fingerprint": query_fingerprint,
                    "reason_code": "insufficient_baseline_samples",
                    "observed_baseline_samples": len(baseline_obs),
                    "required_baseline_samples": rule.min_baseline_samples,
                    "observed_comparison_samples": len(comp_obs),
                    "required_comparison_samples": req_comp,
                    "detail": (
                        f"Insufficient baseline history ({len(baseline_obs)} < {rule.min_baseline_samples} samples) "
                        f"for query fingerprint '{query_fingerprint}'."
                    ),
                }
            )
            return

        # Compute reference baseline from initial baseline window and any non-breaching historical observations
        anchor_pool = series[: rule.min_baseline_samples]
        anchor_values = [self._extract_query_metric(x, rule.metric_name) for x in anchor_pool]
        anchor_median = round(float(median(anchor_values)), 3) if anchor_values else 0.0

        base_pool = list(anchor_pool)
        for extra_obs in series[rule.min_baseline_samples : len(series) - len(comp_obs)]:
            extra_val = self._extract_query_metric(extra_obs, rule.metric_name)
            extra_breached, _ = self._check_breach(
                value=extra_val,
                baseline=anchor_median,
                operator=rule.comparison_operator,
                threshold=rule.threshold_value,
                min_abs=rule.min_absolute_value,
            )
            if not extra_breached:
                base_pool.append(extra_obs)

        baseline_values = [self._extract_query_metric(x, rule.metric_name) for x in base_pool]
        baseline_val = round(float(median(baseline_values)), 3) if baseline_values else 0.0

        # Count consecutive breaches at the tail of the series
        consecutive_breaches = 0
        latest_pct_change = 0.0
        for obs in reversed(series[rule.min_baseline_samples :]):
            val = self._extract_query_metric(obs, rule.metric_name)
            breached, pct = self._check_breach(
                value=val,
                baseline=baseline_values[0] if len(baseline_values) == 1 else baseline_val,
                operator=rule.comparison_operator,
                threshold=rule.threshold_value,
                min_abs=rule.min_absolute_value,
            )
            if breached:
                consecutive_breaches += 1
                if consecutive_breaches == 1:
                    latest_pct_change = pct
            else:
                break

        latest_obs = series[-1]
        latest_val = round(self._extract_query_metric(latest_obs, rule.metric_name), 3)

        # Case 1: Latest observation did NOT breach -> check for auto-resolution of existing active alert
        if consecutive_breaches == 0:
            if active_alert is not None and rule.auto_resolve:
                prev_status = active_alert.status
                active_alert.status = "resolved"
                active_alert.resolved_at = now
                active_alert.resolved_by = "system:auto_recovery"
                active_alert.resolution_type = "auto_recovered"
                active_alert.resolution_reason = (
                    f"Metric '{rule.metric_name}' recovered to {latest_val} "
                    f"(baseline: {baseline_val}, threshold: {rule.threshold_value})."
                )
                active_alert.current_value = latest_val
                active_alert.last_observed_at = now
                db.add(
                    AlertAuditEvent(
                        alert_id=active_alert.id,
                        rule_id=rule.id,
                        action="auto_resolved",
                        previous_status=prev_status,
                        new_status="resolved",
                        actor_id="system",
                        actor_username="system:auto_recovery",
                        actor_role="SYSTEM",
                        reason=active_alert.resolution_reason,
                        details={
                            "recovered_value": latest_val,
                            "baseline_value": baseline_val,
                            "query_fingerprint": query_fingerprint,
                        },
                    )
                )
                auto_resolved_alerts.append(active_alert)
            return

        # Case 2: Breached on fewer consecutive samples than required (single noisy measurement guard)
        if consecutive_breaches < req_breaches:
            suppressed_evaluations.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "metric_name": rule.metric_name,
                    "query_fingerprint": query_fingerprint,
                    "reason_code": "single_noisy_measurement_suppressed",
                    "consecutive_breaches": consecutive_breaches,
                    "required_consecutive_breaches": req_breaches,
                    "baseline_value": baseline_val,
                    "current_value": latest_val,
                    "detail": (
                        f"Suppressed single/transient spike on '{query_fingerprint}': "
                        f"observed {consecutive_breaches} consecutive breach(es), "
                        f"but rule requires {req_breaches} consecutive breaches."
                    ),
                }
            )
            return

        # Case 3: Confirmed regression (consecutive_breaches >= req_breaches)
        affected_entry = {
            "query_id": latest_obs.query_id,
            "query_fingerprint": query_fingerprint,
            "normalized_query": (latest_obs.normalized_query or "")[:240],
            "calls": latest_obs.calls,
            "mean_exec_time_ms": round(float(latest_obs.mean_exec_time_ms or 0.0), 2),
        }
        evidence_payload = {
            "metric_name": rule.metric_name,
            "metric_unit": SUPPORTED_ALERT_METRICS[rule.metric_name]["unit"],
            "comparison_operator": rule.comparison_operator,
            "baseline_value": baseline_val,
            "current_value": latest_val,
            "threshold_value": rule.threshold_value,
            "deviation_pct": latest_pct_change,
            "baseline_sample_count": len(base_pool),
            "comparison_sample_count": consecutive_breaches,
            "consecutive_breaches": consecutive_breaches,
            "baseline_samples": [round(v, 2) for v in baseline_values[-5:]],
            "recent_breach_samples": [
                round(self._extract_query_metric(x, rule.metric_name), 2)
                for x in series[-consecutive_breaches:]
            ],
            "query_id": latest_obs.query_id,
            "query_fingerprint": query_fingerprint,
            "normalized_query": (latest_obs.normalized_query or "")[:240],
            "provenance_state": latest_obs.provenance_state or ProvenanceState.LIVE_TELEMETRY.value,
            "is_synthetic": bool(latest_obs.is_synthetic),
        }

        # 3a. Deduplication: update existing active/acknowledged alert without creating a second alert
        if active_alert is not None:
            active_alert.last_observed_at = now
            active_alert.occurrence_count = int(active_alert.occurrence_count or 1) + 1
            active_alert.consecutive_breaches = consecutive_breaches
            active_alert.current_value = latest_val
            active_alert.deviation_pct = latest_pct_change
            active_alert.comparison_sample_count = consecutive_breaches
            active_alert.evidence = evidence_payload
            deduplicated_alerts.append(active_alert)
            return

        # 3b. Cooldown check against recently resolved alerts for the same dedup_key
        recent_resolved = db.scalar(
            select(WorkloadAlert)
            .where(
                WorkloadAlert.dedup_key == dedup_key,
                WorkloadAlert.status == "resolved",
            )
            .order_by(desc(WorkloadAlert.resolved_at), desc(WorkloadAlert.id))
            .limit(1)
        )
        if recent_resolved is not None and recent_resolved.resolved_at is not None and rule.cooldown_seconds > 0:
            res_at = (
                recent_resolved.resolved_at
                if recent_resolved.resolved_at.tzinfo
                else recent_resolved.resolved_at.replace(tzinfo=timezone.utc)
            )
            elapsed_since_resolve = (now - res_at).total_seconds()
            if elapsed_since_resolve < rule.cooldown_seconds:
                suppressed_evaluations.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "metric_name": rule.metric_name,
                        "query_fingerprint": query_fingerprint,
                        "reason_code": "cooldown_active",
                        "cooldown_seconds": rule.cooldown_seconds,
                        "cooldown_remaining_seconds": round(rule.cooldown_seconds - elapsed_since_resolve, 1),
                        "detail": (
                            f"Alert for '{query_fingerprint}' was resolved {round(elapsed_since_resolve, 1)}s ago; "
                            f"cooldown window ({rule.cooldown_seconds}s) is active."
                        ),
                    }
                )
                return

        # 3c. Create new active alert
        unit = SUPPORTED_ALERT_METRICS[rule.metric_name]["unit"]
        title = f"{rule.name}: {query_fingerprint} ({latest_val} {unit})"
        summary = (
            f"Query fingerprint '{query_fingerprint}' (Query #{latest_obs.query_id}) breached rule '{rule.name}': "
            f"{rule.metric_name} rose from baseline {baseline_val} {unit} to {latest_val} {unit} "
            f"({latest_pct_change:+.1f}%) across {consecutive_breaches} consecutive observation(s)."
        )
        new_alert = WorkloadAlert(
            rule_id=rule.id,
            dedup_key=dedup_key,
            status="active",
            severity=rule.severity,
            metric_name=rule.metric_name,
            scope="query",
            title=title,
            summary=summary,
            started_at=now,
            last_observed_at=now,
            occurrence_count=1,
            consecutive_breaches=consecutive_breaches,
            baseline_value=baseline_val,
            current_value=latest_val,
            threshold_value=rule.threshold_value,
            deviation_pct=latest_pct_change,
            baseline_sample_count=len(base_pool),
            comparison_sample_count=consecutive_breaches,
            affected_query_fingerprints=[affected_entry],
            evidence=evidence_payload,
            provenance_state=latest_obs.provenance_state or ProvenanceState.LIVE_TELEMETRY.value,
            source_identifier=latest_obs.source_identifier or sanitize_source_identifier(get_settings().database_url),
            is_synthetic=bool(latest_obs.is_synthetic),
        )
        db.add(new_alert)
        db.flush()
        db.add(
            AlertAuditEvent(
                alert_id=new_alert.id,
                rule_id=rule.id,
                action="triggered",
                previous_status=None,
                new_status="active",
                actor_id="system",
                actor_username="system:alert_engine",
                actor_role="SYSTEM",
                reason=summary,
                details={
                    "dedup_key": dedup_key,
                    "baseline_value": baseline_val,
                    "current_value": latest_val,
                    "deviation_pct": latest_pct_change,
                    "consecutive_breaches": consecutive_breaches,
                },
            )
        )
        triggered_alerts.append(new_alert)

    def _evaluate_workload_series(
        self,
        *,
        db: Session,
        rule: WorkloadAlertRule,
        snapshots: list[WorkloadSnapshot],
        now: datetime,
        triggered_alerts: list[WorkloadAlert],
        deduplicated_alerts: list[WorkloadAlert],
        auto_resolved_alerts: list[WorkloadAlert],
        suppressed_evaluations: list[dict[str, Any]],
        insufficient_history_items: list[dict[str, Any]],
    ) -> None:
        dedup_key = f"rule:{rule.id}:metric:{rule.metric_name}:scope:workload"
        req_breaches = 1 if rule.allow_single_measurement else max(2, int(rule.consecutive_breaches_required or 2))

        active_alert = db.scalar(
            select(WorkloadAlert).where(
                WorkloadAlert.dedup_key == dedup_key,
                WorkloadAlert.status.in_(["active", "acknowledged"]),
            )
        )

        if len(snapshots) < rule.min_baseline_samples:
            insufficient_history_items.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "metric_name": rule.metric_name,
                    "query_fingerprint": None,
                    "reason_code": "insufficient_baseline_samples",
                    "observed_total_samples": len(snapshots),
                    "required_baseline_samples": rule.min_baseline_samples,
                    "detail": (
                        f"Workload has {len(snapshots)} snapshot(s), fewer than required {rule.min_baseline_samples}."
                    ),
                }
            )
            return

        values = [self._extract_workload_metric(s, rule.metric_name) for s in snapshots]
        base_slice = values[:-req_breaches] if len(values) > req_breaches else values[:1]
        baseline_val = round(float(median(base_slice)), 3) if base_slice else 0.0

        consecutive_breaches = 0
        latest_pct = 0.0
        for s in reversed(snapshots):
            val = self._extract_workload_metric(s, rule.metric_name)
            breached, pct = self._check_breach(
                value=val,
                baseline=baseline_val,
                operator=rule.comparison_operator,
                threshold=rule.threshold_value,
                min_abs=rule.min_absolute_value,
            )
            if breached:
                consecutive_breaches += 1
                if consecutive_breaches == 1:
                    latest_pct = pct
            else:
                break

        latest_snap = snapshots[-1]
        latest_val = round(self._extract_workload_metric(latest_snap, rule.metric_name), 3)

        if consecutive_breaches == 0:
            if active_alert is not None and rule.auto_resolve:
                prev_status = active_alert.status
                active_alert.status = "resolved"
                active_alert.resolved_at = now
                active_alert.resolved_by = "system:auto_recovery"
                active_alert.resolution_type = "auto_recovered"
                active_alert.resolution_reason = f"Workload metric '{rule.metric_name}' recovered to {latest_val}."
                active_alert.current_value = latest_val
                active_alert.last_observed_at = now
                db.add(
                    AlertAuditEvent(
                        alert_id=active_alert.id,
                        rule_id=rule.id,
                        action="auto_resolved",
                        previous_status=prev_status,
                        new_status="resolved",
                        actor_id="system",
                        actor_username="system:auto_recovery",
                        actor_role="SYSTEM",
                        reason=active_alert.resolution_reason,
                        details={"recovered_value": latest_val, "baseline_value": baseline_val},
                    )
                )
                auto_resolved_alerts.append(active_alert)
            return

        if consecutive_breaches < req_breaches:
            suppressed_evaluations.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "metric_name": rule.metric_name,
                    "query_fingerprint": None,
                    "reason_code": "single_noisy_measurement_suppressed",
                    "consecutive_breaches": consecutive_breaches,
                    "required_consecutive_breaches": req_breaches,
                    "baseline_value": baseline_val,
                    "current_value": latest_val,
                    "detail": (
                        f"Suppressed workload spike on '{rule.metric_name}': "
                        f"{consecutive_breaches} < {req_breaches} consecutive breaches."
                    ),
                }
            )
            return

        evidence_payload = {
            "metric_name": rule.metric_name,
            "metric_unit": SUPPORTED_ALERT_METRICS[rule.metric_name]["unit"],
            "comparison_operator": rule.comparison_operator,
            "baseline_value": baseline_val,
            "current_value": latest_val,
            "threshold_value": rule.threshold_value,
            "deviation_pct": latest_pct,
            "baseline_sample_count": len(base_slice),
            "comparison_sample_count": consecutive_breaches,
            "consecutive_breaches": consecutive_breaches,
            "snapshot_id": latest_snap.id,
            "collection_error": latest_snap.collection_error,
        }

        if active_alert is not None:
            active_alert.last_observed_at = now
            active_alert.occurrence_count = int(active_alert.occurrence_count or 1) + 1
            active_alert.consecutive_breaches = consecutive_breaches
            active_alert.current_value = latest_val
            active_alert.deviation_pct = latest_pct
            active_alert.evidence = evidence_payload
            deduplicated_alerts.append(active_alert)
            return

        recent_resolved = db.scalar(
            select(WorkloadAlert)
            .where(WorkloadAlert.dedup_key == dedup_key, WorkloadAlert.status == "resolved")
            .order_by(desc(WorkloadAlert.resolved_at), desc(WorkloadAlert.id))
            .limit(1)
        )
        if recent_resolved is not None and recent_resolved.resolved_at is not None and rule.cooldown_seconds > 0:
            res_at = (
                recent_resolved.resolved_at
                if recent_resolved.resolved_at.tzinfo
                else recent_resolved.resolved_at.replace(tzinfo=timezone.utc)
            )
            elapsed = (now - res_at).total_seconds()
            if elapsed < rule.cooldown_seconds:
                suppressed_evaluations.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "metric_name": rule.metric_name,
                        "query_fingerprint": None,
                        "reason_code": "cooldown_active",
                        "cooldown_seconds": rule.cooldown_seconds,
                        "cooldown_remaining_seconds": round(rule.cooldown_seconds - elapsed, 1),
                        "detail": f"Workload alert resolved {round(elapsed, 1)}s ago; cooldown active.",
                    }
                )
                return

        unit = SUPPORTED_ALERT_METRICS[rule.metric_name]["unit"]
        title = f"{rule.name}: {latest_val} {unit}"
        summary = (
            f"Workload metric '{rule.metric_name}' breached rule '{rule.name}' "
            f"(current: {latest_val} {unit}, baseline: {baseline_val} {unit})."
            + (f" Error: {latest_snap.collection_error}" if latest_snap.collection_error else "")
        )
        new_alert = WorkloadAlert(
            rule_id=rule.id,
            dedup_key=dedup_key,
            status="active",
            severity=rule.severity,
            metric_name=rule.metric_name,
            scope="workload",
            title=title,
            summary=summary,
            started_at=now,
            last_observed_at=now,
            occurrence_count=1,
            consecutive_breaches=consecutive_breaches,
            baseline_value=baseline_val,
            current_value=latest_val,
            threshold_value=rule.threshold_value,
            deviation_pct=latest_pct,
            baseline_sample_count=len(base_slice),
            comparison_sample_count=consecutive_breaches,
            affected_query_fingerprints=[],
            evidence=evidence_payload,
            provenance_state=latest_snap.provenance_state or ProvenanceState.LIVE_TELEMETRY.value,
            source_identifier=latest_snap.source_identifier or sanitize_source_identifier(get_settings().database_url),
            is_synthetic=bool(latest_snap.is_synthetic),
        )
        db.add(new_alert)
        db.flush()
        db.add(
            AlertAuditEvent(
                alert_id=new_alert.id,
                rule_id=rule.id,
                action="triggered",
                previous_status=None,
                new_status="active",
                actor_id="system",
                actor_username="system:alert_engine",
                actor_role="SYSTEM",
                reason=summary,
                details=evidence_payload,
            )
        )
        triggered_alerts.append(new_alert)
