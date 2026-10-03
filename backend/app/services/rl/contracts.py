"""Contracts and schemas for the DBZenith Reinforcement Learning Optimization Engine.

All state representations are strictly sanitized before passing to the RL agent.
Raw SQL literals, production row data, and unmasked identifiers are strictly forbidden.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class ActionType(IntEnum):
    """Discrete optimization actions supported by the RL engine."""
    NO_OP = 0
    CREATE_INDEX = 1
    DROP_INDEX = 2
    REWRITE_QUERY = 3
    PARTITION_TABLE = 4
    CHANGE_JOIN_STRATEGY = 5

    @classmethod
    def from_name(cls, name: str) -> ActionType:
        normalized = name.strip().upper()
        for action in cls:
            if action.name == normalized:
                return action
        raise ValueError(f"Unknown ActionType: {name}")


class WorkloadStatistics(BaseModel):
    """Sanitized workload volume, execution, and concurrency statistics."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_calls: int = Field(ge=0, default=1000)
    mean_exec_time_ms: float = Field(ge=0.0, default=25.0)
    query_frequency_per_minute: float = Field(ge=0.0, default=60.0)
    read_write_ratio: float = Field(ge=0.0, le=1.0, default=0.8)
    active_connections: int = Field(ge=0, default=10)


class QueryPerformance(BaseModel):
    """Sanitized execution latency, variance, and cache/buffer performance."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    p50_latency_ms: float = Field(ge=0.0, default=15.0)
    p95_latency_ms: float = Field(ge=0.0, default=85.0)
    slow_query_ratio: float = Field(ge=0.0, le=1.0, default=0.05)
    buffer_hit_ratio: float = Field(ge=0.0, le=1.0, default=0.95)
    temp_blks_ratio: float = Field(ge=0.0, le=1.0, default=0.0)


class PlanFeatures(BaseModel):
    """Sanitized execution plan structural, node-type, and cost metrics."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_plan_cost: float = Field(ge=0.0, default=500.0)
    seq_scan_fraction: float = Field(ge=0.0, le=1.0, default=0.4)
    index_scan_fraction: float = Field(ge=0.0, le=1.0, default=0.4)
    nested_loop_fraction: float = Field(ge=0.0, le=1.0, default=0.1)
    hash_join_fraction: float = Field(ge=0.0, le=1.0, default=0.1)
    est_to_actual_row_ratio: float = Field(ge=0.0, default=1.0)


class ExistingIndexes(BaseModel):
    """Sanitized index counts, disk consumption, and utilization efficiency."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_count: int = Field(ge=0, default=5)
    total_index_size_mb: float = Field(ge=0.0, default=25.0)
    redundant_index_count: int = Field(ge=0, default=0)
    index_utilization_ratio: float = Field(ge=0.0, le=1.0, default=0.85)


class RecommendationHistory(BaseModel):
    """Audit of past recommendations and approval/rejection rates."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    approved_count: int = Field(ge=0, default=2)
    rejected_count: int = Field(ge=0, default=1)
    pending_count: int = Field(ge=0, default=0)
    last_action_idx: int = Field(ge=0, le=5, default=0)


class SandboxResults(BaseModel):
    """Measurements and validation outcomes from previous sandbox simulations."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    last_improvement_pct: float = Field(default=0.0)
    last_validation_status: float = Field(ge=0.0, le=1.0, default=1.0)
    last_speedup_factor: float = Field(ge=0.0, default=1.0)
    consecutive_sandbox_failures: int = Field(ge=0, default=0)


class StorageImpact(BaseModel):
    """Storage overhead and capacity utilization metrics."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_db_size_mb: float = Field(ge=0.0, default=500.0)
    estimated_new_index_size_mb: float = Field(ge=0.0, default=12.0)
    storage_budget_utilization: float = Field(ge=0.0, le=1.0, default=0.35)


class WritePenalty(BaseModel):
    """Write overhead, maintenance burden, and DML frequency metrics."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    write_ops_per_minute: float = Field(ge=0.0, default=120.0)
    table_update_rate: float = Field(ge=0.0, le=1.0, default=0.2)
    write_overhead_score: float = Field(ge=0.0, le=1.0, default=0.15)


class RegressionSignals(BaseModel):
    """Signals detecting plan regressions, latency regressions, or risk spikes."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    regression_detected: float = Field(ge=0.0, le=1.0, default=0.0)
    latency_spike_ratio: float = Field(ge=0.0, default=1.0)
    buffer_spike_ratio: float = Field(ge=0.0, default=1.0)
    risk_level: float = Field(ge=0.0, le=1.0, default=0.1)


class SanitizedState(BaseModel):
    """Full sanitized state consumed by the RL environment and agent.

    Strictly satisfies the 9 required categories without exposing raw SQL or data.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    workload_statistics: WorkloadStatistics = Field(default_factory=WorkloadStatistics)
    query_performance: QueryPerformance = Field(default_factory=QueryPerformance)
    plan_features: PlanFeatures = Field(default_factory=PlanFeatures)
    existing_indexes: ExistingIndexes = Field(default_factory=ExistingIndexes)
    recommendation_history: RecommendationHistory = Field(default_factory=RecommendationHistory)
    sandbox_results: SandboxResults = Field(default_factory=SandboxResults)
    storage_impact: StorageImpact = Field(default_factory=StorageImpact)
    write_penalty: WritePenalty = Field(default_factory=WritePenalty)
    regression_signals: RegressionSignals = Field(default_factory=RegressionSignals)

    def to_vector(self) -> np.ndarray:
        """Converts sanitized state to a normalized 38-dimensional float32 vector."""
        ws = self.workload_statistics
        qp = self.query_performance
        pf = self.plan_features
        ei = self.existing_indexes
        rh = self.recommendation_history
        sr = self.sandbox_results
        si = self.storage_impact
        wp = self.write_penalty
        rs = self.regression_signals

        vec = [
            # Workload statistics (5)
            float(np.log1p(ws.total_calls) / 10.0),
            float(ws.mean_exec_time_ms / 100.0),
            float(ws.query_frequency_per_minute / 200.0),
            float(ws.read_write_ratio),
            float(ws.active_connections / 50.0),

            # Query performance (5)
            float(qp.p50_latency_ms / 100.0),
            float(qp.p95_latency_ms / 300.0),
            float(qp.slow_query_ratio),
            float(qp.buffer_hit_ratio),
            float(qp.temp_blks_ratio),

            # Plan features (6)
            float(np.log1p(pf.total_plan_cost) / 10.0),
            float(pf.seq_scan_fraction),
            float(pf.index_scan_fraction),
            float(pf.nested_loop_fraction),
            float(pf.hash_join_fraction),
            float(min(pf.est_to_actual_row_ratio / 5.0, 2.0)),

            # Existing indexes (4)
            float(ei.index_count / 20.0),
            float(ei.total_index_size_mb / 200.0),
            float(ei.redundant_index_count / 5.0),
            float(ei.index_utilization_ratio),

            # Recommendation history (4)
            float(rh.approved_count / 10.0),
            float(rh.rejected_count / 10.0),
            float(rh.pending_count / 5.0),
            float(rh.last_action_idx / 5.0),

            # Sandbox results (4)
            float(sr.last_improvement_pct / 100.0),
            float(sr.last_validation_status),
            float(min(sr.last_speedup_factor / 5.0, 2.0)),
            float(sr.consecutive_sandbox_failures / 5.0),

            # Storage impact (3)
            float(si.total_db_size_mb / 2000.0),
            float(si.estimated_new_index_size_mb / 100.0),
            float(si.storage_budget_utilization),

            # Write penalty (3)
            float(wp.write_ops_per_minute / 500.0),
            float(wp.table_update_rate),
            float(wp.write_overhead_score),

            # Regression signals (4)
            float(rs.regression_detected),
            float(min(rs.latency_spike_ratio / 3.0, 2.0)),
            float(min(rs.buffer_spike_ratio / 3.0, 2.0)),
            float(rs.risk_level),
        ]
        return np.array(vec, dtype=np.float32)

    @classmethod
    def state_dim(cls) -> int:
        return 38


class RLRecommendation(BaseModel):
    """Recommendation contract generated from an RL action."""
    action_type: ActionType
    action_name: str
    target_table: str = "telemetry_demo_orders"
    target_columns: list[str] = Field(default_factory=lambda: ["customer_id", "status"])
    proposed_change: str
    reason: str
    expected_benefit_pct: float
    risk_score: float
    requires_approval: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MeasuredSandboxResult(BaseModel):
    """Concrete empirical result measured in the isolated sandbox.

    Never reflects production mutations; sandbox is ephemeral and fully cleaned.
    """
    baseline_latency_ms: float
    proposed_latency_ms: float
    latency_improvement_pct: float
    baseline_throughput_qps: float
    proposed_throughput_qps: float
    throughput_improvement_pct: float
    storage_delta_mb: float
    write_overhead_score: float
    cpu_usage_delta_pct: float
    regression_detected: bool
    risk_score: float
    sandbox_status: str = "success"
    error_message: str | None = None


class RewardBreakdown(BaseModel):
    """Multi-objective reward breakdown explaining how the net reward was computed."""
    latency_reward: float
    throughput_reward: float
    storage_penalty: float
    write_penalty: float
    cpu_penalty: float
    regression_penalty: float
    risk_penalty: float
    net_reward: float
