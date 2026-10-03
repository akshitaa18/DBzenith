"""Gymnasium-compatible environment for the DBZenith RL Optimization Engine.

Enforces the strict safety pipeline:
RL -> recommendation -> sandbox -> measured result -> reward

CRITICAL SAFETY INVARIANT:
The RL agent is strictly prohibited from mutating the production database.
All proposed changes are evaluated in an isolated sandbox.
"""

from __future__ import annotations

import copy
from typing import Any
import gymnasium as gym
from gymnasium import spaces
import numpy as np

from app.services.rl.contracts import (
    ActionType,
    ExistingIndexes,
    MeasuredSandboxResult,
    PlanFeatures,
    QueryPerformance,
    RecommendationHistory,
    RegressionSignals,
    RLRecommendation,
    SandboxResults,
    SanitizedState,
    StorageImpact,
    WorkloadStatistics,
    WritePenalty,
)
from app.services.rl.reward import RewardCalculator


class ProductionMutationForbiddenError(RuntimeError):
    """Raised when any code attempts to execute optimization changes against production."""
    pass


class DatabaseOptimizationEnv(gym.Env):
    """Gymnasium environment modeling database workload tuning under sandbox safety.

    Observation space: Box(38,), normalized representation of 9 sanitized categories.
    Action space: Discrete(6), matching ActionType enum:
        0: NO_OP
        1: CREATE_INDEX
        2: DROP_INDEX
        3: REWRITE_QUERY
        4: PARTITION_TABLE
        5: CHANGE_JOIN_STRATEGY
    """

    metadata = {"render_modes": ["human", "json"]}

    def __init__(
        self,
        max_steps_per_episode: int = 20,
        reward_calculator: RewardCalculator | None = None,
        production_db_guard: bool = True,
        seed: int | None = None,
    ) -> None:
        super().__init__()
        self.max_steps_per_episode = max_steps_per_episode
        self.reward_calculator = reward_calculator or RewardCalculator()
        self.production_db_guard = production_db_guard

        # Action space: 6 discrete optimization actions
        self.action_space = spaces.Discrete(len(ActionType))

        # Observation space: 38 normalized continuous features
        self.observation_space = spaces.Box(
            low=-10.0,
            high=10.0,
            shape=(SanitizedState.state_dim(),),
            dtype=np.float32,
        )

        self._state: SanitizedState = SanitizedState()
        self._current_step: int = 0
        self._np_random: np.random.Generator = np.random.default_rng(seed)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self._np_random = np.random.default_rng(seed)

        self._current_step = 0
        self._state = self._generate_initial_state()
        obs = self._state.to_vector()
        info = {
            "step": self._current_step,
            "production_modified": False,
            "sanitized_state": self._state.model_dump(),
        }
        return obs, info

    def step(self, action: int | ActionType) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if not self.action_space.contains(int(action)):
            raise ValueError(f"Invalid action {action} for action space {self.action_space}")

        action_type = ActionType(int(action))
        self._current_step += 1

        # =====================================================================
        # STEP 1 & 2: RL Action -> Optimization Recommendation
        # =====================================================================
        recommendation = self._synthesize_recommendation(action_type, self._state)

        # =====================================================================
        # SAFETY INVARIANT CHECK: Never allow RL to touch production
        # =====================================================================
        self._assert_production_safety(recommendation)

        # =====================================================================
        # STEP 3: Sandbox Simulation -> Measured Result
        # =====================================================================
        measured_result = self._execute_sandbox_simulation(recommendation, self._state)

        # =====================================================================
        # STEP 4: Measured Result -> Multi-Objective Reward
        # =====================================================================
        reward_breakdown = self.reward_calculator.compute(measured_result)
        reward = reward_breakdown.net_reward

        # =====================================================================
        # STEP 5: State Transition from Measured Outcome
        # =====================================================================
        self._state = self._transition_state(self._state, action_type, measured_result)
        obs = self._state.to_vector()

        terminated = self._check_termination(measured_result)
        truncated = self._current_step >= self.max_steps_per_episode

        info = {
            "step": self._current_step,
            "action": action_type.name,
            "recommendation": recommendation.model_dump(),
            "measured_result": measured_result.model_dump(),
            "reward_breakdown": reward_breakdown.model_dump(),
            "production_modified": False,
        }

        return obs, reward, terminated, truncated, info

    def _assert_production_safety(self, recommendation: RLRecommendation) -> None:
        """Enforces that recommendations never target or mutate production databases."""
        if not self.production_db_guard:
            return

        # Verification: target must be sanitized, action must require approval or sandbox execution
        if not recommendation.requires_approval:
            raise ProductionMutationForbiddenError("RL actions must always require approval before any production apply.")

        # Ensure no direct DDL is ever directed to production
        if "DROP DATABASE" in recommendation.proposed_change.upper() or "TRUNCATE" in recommendation.proposed_change.upper():
            raise ProductionMutationForbiddenError("Destructive production mutations are strictly forbidden.")

    def _synthesize_recommendation(
        self,
        action: ActionType,
        state: SanitizedState,
    ) -> RLRecommendation:
        """Transforms an RL discrete action into a typed OptimizationRecommendation."""
        if action == ActionType.NO_OP:
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                proposed_change="NO_OP",
                reason="Workload is operating within expected boundaries; no change required.",
                expected_benefit_pct=0.0,
                risk_score=0.0,
            )

        if action == ActionType.CREATE_INDEX:
            col = "customer_id" if state.plan_features.seq_scan_fraction > 0.3 else "order_date"
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                target_table="telemetry_demo_orders",
                target_columns=[col],
                proposed_change=f"CREATE INDEX CONCURRENTLY idx_rl_{col} ON telemetry_demo_orders ({col});",
                reason=f"Sequential scan ratio is {state.plan_features.seq_scan_fraction:.2f}; index on {col} expected to convert seq scans to index scans.",
                expected_benefit_pct=min(state.plan_features.seq_scan_fraction * 65.0, 70.0),
                risk_score=0.2 + 0.3 * state.write_penalty.write_overhead_score,
            )

        if action == ActionType.DROP_INDEX:
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                target_table="telemetry_demo_orders",
                target_columns=["redundant_idx"],
                proposed_change="DROP INDEX CONCURRENTLY IF EXISTS idx_telemetry_demo_orders_redundant;",
                reason="Redundant index detected consuming disk and adding write overhead.",
                expected_benefit_pct=10.0,
                risk_score=0.1 if state.existing_indexes.redundant_index_count > 0 else 0.8,
            )

        if action == ActionType.REWRITE_QUERY:
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                target_table="telemetry_demo_orders",
                target_columns=["*"],
                proposed_change="REWRITE: Project explicit columns instead of SELECT * and pushdown predicates.",
                reason="Query exhibits wide projected rows and low buffer efficiency.",
                expected_benefit_pct=25.0,
                risk_score=0.15,
            )

        if action == ActionType.PARTITION_TABLE:
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                target_table="telemetry_demo_orders",
                target_columns=["order_date"],
                proposed_change="PARTITION TABLE telemetry_demo_orders BY RANGE (order_date);",
                reason="Table size and time-range predicate frequency justify date partitioning.",
                expected_benefit_pct=35.0,
                risk_score=0.6,  # Higher risk structural change
            )

        if action == ActionType.CHANGE_JOIN_STRATEGY:
            return RLRecommendation(
                action_type=action,
                action_name=action.name,
                target_table="telemetry_demo_orders",
                target_columns=["join_predicate"],
                proposed_change="SET LOCAL enable_nestloop = off; -- Prefer hash or merge join for large relation scans",
                reason="High-loop nested loop join detected contributing to elevated p95 latency.",
                expected_benefit_pct=30.0,
                risk_score=0.25,
            )

        raise ValueError(f"Unhandled action {action}")

    def _execute_sandbox_simulation(
        self,
        recommendation: RLRecommendation,
        state: SanitizedState,
    ) -> MeasuredSandboxResult:
        """Simulates recommendation in the isolated sandbox, returning measured performance.

        In production, calls SandboxSimulator via SANDBOX_DATABASE_URL with HypoPG.
        In the environment, models realistic PostgreSQL optimizer dynamics.
        """
        action = recommendation.action_type

        # Default baseline numbers
        base_lat = state.query_performance.mean_exec_time_ms if hasattr(state.query_performance, "mean_exec_time_ms") else state.workload_statistics.mean_exec_time_ms
        base_qps = max(1000.0 / max(base_lat, 1.0), 1.0)

        if action == ActionType.NO_OP:
            return MeasuredSandboxResult(
                baseline_latency_ms=base_lat,
                proposed_latency_ms=base_lat,
                latency_improvement_pct=0.0,
                baseline_throughput_qps=base_qps,
                proposed_throughput_qps=base_qps,
                throughput_improvement_pct=0.0,
                storage_delta_mb=0.0,
                write_overhead_score=0.0,
                cpu_usage_delta_pct=0.0,
                regression_detected=False,
                risk_score=0.0,
                sandbox_status="success",
            )

        if action == ActionType.CREATE_INDEX:
            # If sequential scans are high, index yields large improvement
            seq_fraction = state.plan_features.seq_scan_fraction
            write_ops = state.write_penalty.write_ops_per_minute

            # Diminishing returns or regression if too many indexes exist
            if state.existing_indexes.index_count >= 15:
                # Regression: optimizer picks poor index or write penalty crushes performance
                improvement = -15.0
                proposed_lat = base_lat * 1.15
                regression = True
                write_score = 0.8
            else:
                improvement = float(self._np_random.uniform(25.0, 55.0) * (seq_fraction + 0.3))
                improvement = min(improvement, 75.0)
                proposed_lat = base_lat * (1.0 - improvement / 100.0)
                regression = False
                write_score = float(min(0.1 + (write_ops / 1000.0) * 0.4, 1.0))

            storage_mb = float(state.storage_impact.estimated_new_index_size_mb + self._np_random.uniform(1.0, 5.0))
            proposed_qps = max(1000.0 / max(proposed_lat, 0.5), 1.0)
            thr_improvement = float(((proposed_qps - base_qps) / base_qps) * 100.0)

            return MeasuredSandboxResult(
                baseline_latency_ms=round(base_lat, 2),
                proposed_latency_ms=round(proposed_lat, 2),
                latency_improvement_pct=round(improvement, 2),
                baseline_throughput_qps=round(base_qps, 2),
                proposed_throughput_qps=round(proposed_qps, 2),
                throughput_improvement_pct=round(thr_improvement, 2),
                storage_delta_mb=round(storage_mb, 2),
                write_overhead_score=round(write_score, 2),
                cpu_usage_delta_pct=round(-improvement * 0.4, 2),
                regression_detected=regression,
                risk_score=recommendation.risk_score,
                sandbox_status="success",
            )

        if action == ActionType.DROP_INDEX:
            if state.existing_indexes.redundant_index_count > 0:
                # Successful removal of unused index: saves storage, reduces write penalty
                saved_mb = -18.0
                write_reduction = -0.2
                improvement = 5.0
                regression = False
            else:
                # Dropping an active index causes severe plan regression!
                saved_mb = -15.0
                write_reduction = -0.1
                improvement = -60.0
                regression = True

            proposed_lat = base_lat * (1.0 - improvement / 100.0)
            proposed_qps = max(1000.0 / max(proposed_lat, 0.5), 1.0)
            thr_improvement = float(((proposed_qps - base_qps) / base_qps) * 100.0)

            return MeasuredSandboxResult(
                baseline_latency_ms=round(base_lat, 2),
                proposed_latency_ms=round(proposed_lat, 2),
                latency_improvement_pct=round(improvement, 2),
                baseline_throughput_qps=round(base_qps, 2),
                proposed_throughput_qps=round(proposed_qps, 2),
                throughput_improvement_pct=round(thr_improvement, 2),
                storage_delta_mb=round(saved_mb, 2),
                write_overhead_score=round(max(write_reduction, 0.0), 2),
                cpu_usage_delta_pct=round(-improvement * 0.2, 2),
                regression_detected=regression,
                risk_score=0.1 if not regression else 0.9,
                sandbox_status="success",
            )

        if action == ActionType.REWRITE_QUERY:
            improvement = float(self._np_random.uniform(15.0, 35.0))
            proposed_lat = base_lat * (1.0 - improvement / 100.0)
            proposed_qps = max(1000.0 / max(proposed_lat, 0.5), 1.0)
            thr_improvement = float(((proposed_qps - base_qps) / base_qps) * 100.0)

            return MeasuredSandboxResult(
                baseline_latency_ms=round(base_lat, 2),
                proposed_latency_ms=round(proposed_lat, 2),
                latency_improvement_pct=round(improvement, 2),
                baseline_throughput_qps=round(base_qps, 2),
                proposed_throughput_qps=round(proposed_qps, 2),
                throughput_improvement_pct=round(thr_improvement, 2),
                storage_delta_mb=0.0,
                write_overhead_score=0.0,
                cpu_usage_delta_pct=round(-improvement * 0.5, 2),
                regression_detected=False,
                risk_score=0.15,
                sandbox_status="success",
            )

        if action == ActionType.PARTITION_TABLE:
            # Good if table size is large; bad if small table with high partition overhead
            if state.storage_impact.total_db_size_mb > 300.0:
                improvement = float(self._np_random.uniform(25.0, 45.0))
                regression = False
            else:
                improvement = -10.0
                regression = True

            proposed_lat = base_lat * (1.0 - improvement / 100.0)
            proposed_qps = max(1000.0 / max(proposed_lat, 0.5), 1.0)
            thr_improvement = float(((proposed_qps - base_qps) / base_qps) * 100.0)

            return MeasuredSandboxResult(
                baseline_latency_ms=round(base_lat, 2),
                proposed_latency_ms=round(proposed_lat, 2),
                latency_improvement_pct=round(improvement, 2),
                baseline_throughput_qps=round(base_qps, 2),
                proposed_throughput_qps=round(proposed_qps, 2),
                throughput_improvement_pct=round(thr_improvement, 2),
                storage_delta_mb=5.0,  # partition metadata overhead
                write_overhead_score=0.25,
                cpu_usage_delta_pct=round(-improvement * 0.3, 2),
                regression_detected=regression,
                risk_score=0.5,
                sandbox_status="success",
            )

        if action == ActionType.CHANGE_JOIN_STRATEGY:
            if state.plan_features.nested_loop_fraction > 0.2:
                improvement = float(self._np_random.uniform(20.0, 40.0))
                regression = False
            else:
                improvement = -12.0
                regression = True

            proposed_lat = base_lat * (1.0 - improvement / 100.0)
            proposed_qps = max(1000.0 / max(proposed_lat, 0.5), 1.0)
            thr_improvement = float(((proposed_qps - base_qps) / base_qps) * 100.0)

            return MeasuredSandboxResult(
                baseline_latency_ms=round(base_lat, 2),
                proposed_latency_ms=round(proposed_lat, 2),
                latency_improvement_pct=round(improvement, 2),
                baseline_throughput_qps=round(base_qps, 2),
                proposed_throughput_qps=round(proposed_qps, 2),
                throughput_improvement_pct=round(thr_improvement, 2),
                storage_delta_mb=0.0,
                write_overhead_score=0.0,
                cpu_usage_delta_pct=round(-improvement * 0.35, 2),
                regression_detected=regression,
                risk_score=0.25,
                sandbox_status="success",
            )

        raise ValueError(f"Unhandled simulation action {action}")

    def _transition_state(
        self,
        current_state: SanitizedState,
        action: ActionType,
        result: MeasuredSandboxResult,
    ) -> SanitizedState:
        """Computes the next sanitized state based on action and sandbox outcome."""
        new_ws = current_state.workload_statistics.model_dump()
        new_qp = current_state.query_performance.model_dump()
        new_pf = current_state.plan_features.model_dump()
        new_ei = current_state.existing_indexes.model_dump()
        new_rh = current_state.recommendation_history.model_dump()
        new_sr = current_state.sandbox_results.model_dump()
        new_si = current_state.storage_impact.model_dump()
        new_wp = current_state.write_penalty.model_dump()
        new_rs = current_state.regression_signals.model_dump()

        # Update recommendation history
        if action != ActionType.NO_OP:
            if result.regression_detected:
                new_rh["rejected_count"] += 1
            else:
                new_rh["approved_count"] += 1
        new_rh["last_action_idx"] = int(action)

        # Update sandbox results
        new_sr["last_improvement_pct"] = result.latency_improvement_pct
        new_sr["last_validation_status"] = 0.0 if result.regression_detected else 1.0
        new_sr["last_speedup_factor"] = round(max(result.proposed_throughput_qps / max(result.baseline_throughput_qps, 0.1), 0.1), 2)
        if result.regression_detected:
            new_sr["consecutive_sandbox_failures"] += 1
        else:
            new_sr["consecutive_sandbox_failures"] = 0

        # Update regression signals
        new_rs["regression_detected"] = 1.0 if result.regression_detected else 0.0
        new_rs["latency_spike_ratio"] = round(result.proposed_latency_ms / max(result.baseline_latency_ms, 0.1), 2)
        new_rs["risk_level"] = result.risk_score

        # Specific action adjustments
        if action == ActionType.CREATE_INDEX and not result.regression_detected:
            new_pf["seq_scan_fraction"] = max(new_pf["seq_scan_fraction"] - 0.2, 0.05)
            new_pf["index_scan_fraction"] = min(new_pf["index_scan_fraction"] + 0.2, 0.95)
            new_ei["index_count"] += 1
            new_ei["total_index_size_mb"] += result.storage_delta_mb
            new_si["total_db_size_mb"] += result.storage_delta_mb
            new_wp["write_overhead_score"] = min(new_wp["write_overhead_score"] + 0.05, 1.0)
            new_qp["p50_latency_ms"] = max(new_qp["p50_latency_ms"] * 0.8, 2.0)
            new_qp["p95_latency_ms"] = max(new_qp["p95_latency_ms"] * 0.75, 5.0)

        elif action == ActionType.DROP_INDEX and not result.regression_detected:
            new_ei["index_count"] = max(new_ei["index_count"] - 1, 1)
            new_ei["redundant_index_count"] = max(new_ei["redundant_index_count"] - 1, 0)
            new_ei["total_index_size_mb"] = max(new_ei["total_index_size_mb"] + result.storage_delta_mb, 1.0)
            new_si["total_db_size_mb"] = max(new_si["total_db_size_mb"] + result.storage_delta_mb, 10.0)
            new_wp["write_overhead_score"] = max(new_wp["write_overhead_score"] - 0.08, 0.02)

        elif action == ActionType.CHANGE_JOIN_STRATEGY and not result.regression_detected:
            new_pf["nested_loop_fraction"] = max(new_pf["nested_loop_fraction"] - 0.15, 0.02)
            new_pf["hash_join_fraction"] = min(new_pf["hash_join_fraction"] + 0.15, 0.8)
            new_qp["p95_latency_ms"] = max(new_qp["p95_latency_ms"] * 0.8, 5.0)

        elif action == ActionType.REWRITE_QUERY and not result.regression_detected:
            new_qp["buffer_hit_ratio"] = min(new_qp["buffer_hit_ratio"] + 0.03, 0.99)
            new_qp["p50_latency_ms"] = max(new_qp["p50_latency_ms"] * 0.85, 2.0)

        elif action == ActionType.PARTITION_TABLE and not result.regression_detected:
            new_pf["total_plan_cost"] = max(new_pf["total_plan_cost"] * 0.7, 50.0)
            new_qp["p95_latency_ms"] = max(new_qp["p95_latency_ms"] * 0.7, 5.0)

        return SanitizedState(
            workload_statistics=WorkloadStatistics(**new_ws),
            query_performance=QueryPerformance(**new_qp),
            plan_features=PlanFeatures(**new_pf),
            existing_indexes=ExistingIndexes(**new_ei),
            recommendation_history=RecommendationHistory(**new_rh),
            sandbox_results=SandboxResults(**new_sr),
            storage_impact=StorageImpact(**new_si),
            write_penalty=WritePenalty(**new_wp),
            regression_signals=RegressionSignals(**new_rs),
        )

    def _check_termination(self, result: MeasuredSandboxResult) -> bool:
        """Determines if the episode terminates early (e.g. repeated severe regressions)."""
        if self._state.sandbox_results.consecutive_sandbox_failures >= 3:
            return True
        return False

    def _generate_initial_state(self) -> SanitizedState:
        """Generates a realistic initial sanitized state for an episode."""
        seq_frac = float(self._np_random.uniform(0.3, 0.8))
        idx_frac = 1.0 - seq_frac
        redundant_count = int(self._np_random.choice([0, 1, 2], p=[0.6, 0.3, 0.1]))

        return SanitizedState(
            workload_statistics=WorkloadStatistics(
                total_calls=int(self._np_random.integers(500, 5000)),
                mean_exec_time_ms=float(self._np_random.uniform(20.0, 120.0)),
                query_frequency_per_minute=float(self._np_random.uniform(30.0, 180.0)),
                read_write_ratio=float(self._np_random.uniform(0.7, 0.95)),
                active_connections=int(self._np_random.integers(5, 30)),
            ),
            query_performance=QueryPerformance(
                p50_latency_ms=float(self._np_random.uniform(10.0, 50.0)),
                p95_latency_ms=float(self._np_random.uniform(60.0, 250.0)),
                slow_query_ratio=float(self._np_random.uniform(0.02, 0.15)),
                buffer_hit_ratio=float(self._np_random.uniform(0.85, 0.98)),
                temp_blks_ratio=float(self._np_random.uniform(0.0, 0.05)),
            ),
            plan_features=PlanFeatures(
                total_plan_cost=float(self._np_random.uniform(300.0, 2500.0)),
                seq_scan_fraction=seq_frac,
                index_scan_fraction=idx_frac,
                nested_loop_fraction=float(self._np_random.uniform(0.1, 0.4)),
                hash_join_fraction=float(self._np_random.uniform(0.1, 0.4)),
                est_to_actual_row_ratio=float(self._np_random.uniform(0.8, 1.5)),
            ),
            existing_indexes=ExistingIndexes(
                index_count=int(self._np_random.integers(3, 8)),
                total_index_size_mb=float(self._np_random.uniform(20.0, 80.0)),
                redundant_index_count=redundant_count,
                index_utilization_ratio=float(self._np_random.uniform(0.6, 0.9)),
            ),
            recommendation_history=RecommendationHistory(
                approved_count=int(self._np_random.integers(1, 5)),
                rejected_count=int(self._np_random.integers(0, 2)),
                pending_count=0,
                last_action_idx=0,
            ),
            sandbox_results=SandboxResults(
                last_improvement_pct=0.0,
                last_validation_status=1.0,
                last_speedup_factor=1.0,
                consecutive_sandbox_failures=0,
            ),
            storage_impact=StorageImpact(
                total_db_size_mb=float(self._np_random.uniform(400.0, 1200.0)),
                estimated_new_index_size_mb=float(self._np_random.uniform(10.0, 30.0)),
                storage_budget_utilization=float(self._np_random.uniform(0.2, 0.5)),
            ),
            write_penalty=WritePenalty(
                write_ops_per_minute=float(self._np_random.uniform(50.0, 300.0)),
                table_update_rate=float(self._np_random.uniform(0.05, 0.25)),
                write_overhead_score=float(self._np_random.uniform(0.1, 0.3)),
            ),
            regression_signals=RegressionSignals(
                regression_detected=0.0,
                latency_spike_ratio=1.0,
                buffer_spike_ratio=1.0,
                risk_level=float(self._np_random.uniform(0.05, 0.2)),
            ),
        )
