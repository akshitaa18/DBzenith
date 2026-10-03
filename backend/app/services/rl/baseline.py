"""Baseline policies for comparison against the trainable RL agent.

Includes:
1. BaselinePolicy: deterministic, rule-based expert heuristic.
2. RandomPolicy: uniform random baseline.
"""

from __future__ import annotations

import numpy as np
from app.services.rl.contracts import ActionType, SanitizedState


class BaselinePolicy:
    """Deterministic, rule-based optimization policy reflecting classical DBA heuristics."""

    def __init__(self, name: str = "rule_based_baseline") -> None:
        self.name = name

    def select_action(self, state: SanitizedState | np.ndarray) -> ActionType:
        """Selects an action based on deterministic database performance rules."""
        if isinstance(state, np.ndarray):
            # Parse salient components from 38-dim vector
            # vec indices:
            # 11: seq_scan_fraction
            # 13: nested_loop_fraction
            # 18: redundant_index_count
            # 29: write_overhead_score
            # 32: regression_detected
            seq_scan_fraction = float(state[11])
            nested_loop_fraction = float(state[13])
            redundant_index_count = float(state[18])
            write_overhead_score = float(state[29])
            regression_detected = float(state[32])
            p95_latency_ms = float(state[6] * 300.0)

            if regression_detected > 0.5:
                return ActionType.NO_OP

            if redundant_index_count > 0.1:
                return ActionType.DROP_INDEX

            if seq_scan_fraction > 0.45 and write_overhead_score < 0.5:
                return ActionType.CREATE_INDEX

            if nested_loop_fraction > 0.25 and p95_latency_ms > 80.0:
                return ActionType.CHANGE_JOIN_STRATEGY

            if seq_scan_fraction > 0.3:
                return ActionType.REWRITE_QUERY

            return ActionType.NO_OP

        # Structured SanitizedState path
        if state.regression_signals.regression_detected > 0.5:
            return ActionType.NO_OP

        if state.existing_indexes.redundant_index_count > 0:
            return ActionType.DROP_INDEX

        if (
            state.plan_features.seq_scan_fraction > 0.4
            and state.write_penalty.write_overhead_score < 0.6
            and state.existing_indexes.index_count < 10
        ):
            return ActionType.CREATE_INDEX

        if (
            state.plan_features.nested_loop_fraction > 0.25
            and state.query_performance.p95_latency_ms > 90.0
        ):
            return ActionType.CHANGE_JOIN_STRATEGY

        if state.query_performance.slow_query_ratio > 0.08:
            return ActionType.REWRITE_QUERY

        if (
            state.storage_impact.total_db_size_mb > 600.0
            and state.query_performance.p95_latency_ms > 120.0
        ):
            return ActionType.PARTITION_TABLE

        return ActionType.NO_OP


class RandomPolicy:
    """Uniform random baseline policy."""

    def __init__(self, seed: int | None = None, name: str = "random_baseline") -> None:
        self.name = name
        self.rng = np.random.default_rng(seed)

    def select_action(self, state: Any) -> ActionType:
        return ActionType(int(self.rng.integers(0, len(ActionType))))
