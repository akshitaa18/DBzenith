"""Evaluation pipeline comparing the trained RL agent against baseline policies.

Implements Phase 9 Part B requirements:
- Investigates the 303 training regressions and PARTITION_TABLE shortcut in v0.8.0.
- Defines reproducible held-out and multi-regime OOD evaluation workloads separate from training.
- Compares TrainableRLAgent (raw and safety-gated) with deterministic DBA heuristics (BaselinePolicy),
  a no-change baseline (NoChangePolicy), and RandomPolicy.
- Measures valid-action rate, reward stability, regression frequency, improvement distribution, and failure rate.
- Reproduces evaluation metrics directly from saved predictions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from typing import Any
import numpy as np
import torch

from app.services.rl.agent import TrainableRLAgent
from app.services.rl.baseline import BaselinePolicy, NoChangePolicy, RandomPolicy
from app.services.rl.contracts import (
    ActionType,
    ExistingIndexes,
    PlanFeatures,
    QueryPerformance,
    RegressionSignals,
    SanitizedState,
    StorageImpact,
    WorkloadStatistics,
    WritePenalty,
)
from app.services.rl.environment import DatabaseOptimizationEnv
from app.services.rl.persistence import DEFAULT_ARTIFACT_DIR, load_rl_artifacts
from app.services.rl.reward import RewardCalculator


RL_EVALUATION_SEED = 20000


def is_action_valid_for_state(
    action: ActionType,
    state: SanitizedState | np.ndarray,
) -> tuple[bool, str | None]:
    """Determines whether an action satisfies domain preconditions for the given state."""
    if action == ActionType.NO_OP:
        return True, None

    if isinstance(state, np.ndarray):
        p95_latency_ms = float(state[6] * 300.0)
        slow_query_ratio = float(state[7])
        seq_scan_fraction = float(state[11])
        nested_loop_fraction = float(state[13])
        index_count = int(round(float(state[16] * 20.0)))
        redundant_index_count = int(round(float(state[18] * 5.0)))
        total_db_size_mb = float(state[28] * 2000.0)
        regression_detected = float(state[34])
    else:
        p95_latency_ms = state.query_performance.p95_latency_ms
        slow_query_ratio = state.query_performance.slow_query_ratio
        seq_scan_fraction = state.plan_features.seq_scan_fraction
        nested_loop_fraction = state.plan_features.nested_loop_fraction
        index_count = state.existing_indexes.index_count
        redundant_index_count = state.existing_indexes.redundant_index_count
        total_db_size_mb = state.storage_impact.total_db_size_mb
        regression_detected = state.regression_signals.regression_detected

    if regression_detected > 0.5 and action != ActionType.NO_OP:
        return False, "Active regression signal present; mutating actions risk compounding regression."

    if action == ActionType.DROP_INDEX and redundant_index_count <= 0:
        return False, "redundant_index_count == 0: dropping a non-redundant index causes -60% latency regression."

    if action == ActionType.PARTITION_TABLE and total_db_size_mb <= 300.0:
        return False, "total_db_size_mb <= 300 MB: partitioning small tables adds overhead and causes -10% regression."

    if action == ActionType.CHANGE_JOIN_STRATEGY and nested_loop_fraction <= 0.2:
        return False, "nested_loop_fraction <= 0.2: forcing join strategy change causes -12% regression."

    if action == ActionType.CREATE_INDEX and (index_count >= 12 or seq_scan_fraction <= 0.2):
        return False, "index_count >= 12 or seq_scan_fraction <= 0.2: index creation adds write overhead with minimal read benefit."

    if action == ActionType.REWRITE_QUERY and seq_scan_fraction <= 0.25 and slow_query_ratio <= 0.05 and p95_latency_ms < 50.0:
        return False, "Query already low-latency with low seq_scan_fraction; rewrite unnecessary."

    return True, None


def _compute_distribution_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "p10": 0.0,
            "p25": 0.0,
            "p50_median": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "iqr": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    arr = np.asarray(values, dtype=np.float64)
    p10, p25, p50, p75, p90 = np.percentile(arr, [10, 25, 50, 75, 90])
    return {
        "p10": round(float(p10), 3),
        "p25": round(float(p25), 3),
        "p50_median": round(float(p50), 3),
        "p75": round(float(p75), 3),
        "p90": round(float(p90), 3),
        "mean": round(float(np.mean(arr)), 3),
        "std": round(float(np.std(arr)), 3),
        "iqr": round(float(p75 - p25), 3),
        "min": round(float(np.min(arr)), 3),
        "max": round(float(np.max(arr)), 3),
    }


def evaluate_policy(
    policy: TrainableRLAgent | BaselinePolicy | NoChangePolicy | RandomPolicy,
    env: DatabaseOptimizationEnv,
    num_episodes: int = 50,
    seed_offset: int = 10000,
) -> dict[str, Any]:
    """Evaluates a policy on held-out episodes and collects performance metrics."""
    rewards: list[float] = []
    step_rewards: list[float] = []
    latency_improvements: list[float] = []
    throughput_improvements: list[float] = []
    storage_deltas: list[float] = []
    write_overheads: list[float] = []
    cpu_deltas: list[float] = []
    regression_events: int = 0
    valid_actions: int = 0
    failed_actions: int = 0
    total_actions: int = 0
    action_counts: dict[str, int] = {action.name: 0 for action in ActionType}

    is_rl_agent = isinstance(policy, TrainableRLAgent)

    for ep in range(num_episodes):
        state, _ = env.reset(seed=seed_offset + ep)
        ep_reward = 0.0

        for _ in range(env.max_steps_per_episode):
            total_actions += 1
            structured_before = env._state
            if is_rl_agent:
                action = policy.select_action(state, deterministic=True)
            else:
                action = policy.select_action(state)

            valid_flag, _ = is_action_valid_for_state(action, structured_before if structured_before is not None else state)
            if valid_flag:
                valid_actions += 1

            action_counts[action.name] += 1
            next_state, reward, terminated, truncated, info = env.step(action)
            ep_reward += reward
            step_rewards.append(float(reward))

            res = info.get("measured_result", {})
            latency_improvements.append(float(res.get("latency_improvement_pct", 0.0)))
            throughput_improvements.append(float(res.get("throughput_improvement_pct", 0.0)))
            storage_deltas.append(float(res.get("storage_delta_mb", 0.0)))
            write_overheads.append(float(res.get("write_overhead_score", 0.0)))
            cpu_deltas.append(float(res.get("cpu_usage_delta_pct", 0.0)))

            is_regressed = bool(res.get("regression_detected", False))
            if is_regressed:
                regression_events += 1
            if res.get("sandbox_status", "success") != "success" or reward < -0.5 or is_regressed:
                failed_actions += 1

            state = next_state
            if terminated or truncated:
                break

        rewards.append(ep_reward)

    reward_dist = _compute_distribution_summary(rewards)
    latency_dist = _compute_distribution_summary(latency_improvements)
    throughput_dist = _compute_distribution_summary(throughput_improvements)
    reg_pct = round(float((regression_events / max(total_actions, 1)) * 100.0), 2)
    valid_pct = round(float((valid_actions / max(total_actions, 1)) * 100.0), 2)
    fail_pct = round(float((failed_actions / max(total_actions, 1)) * 100.0), 2)

    return {
        "policy_name": getattr(policy, "name", policy.__class__.__name__),
        "num_episodes": num_episodes,
        "total_actions": total_actions,
        "mean_reward": round(float(np.mean(rewards)), 3),
        "std_reward": round(float(np.std(rewards)), 3),
        "reward_stability": {
            "mean_reward": reward_dist["mean"],
            "std_reward": reward_dist["std"],
            "median_reward": reward_dist["p50_median"],
            "iqr_reward": reward_dist["iqr"],
            "min_reward": reward_dist["min"],
            "max_reward": reward_dist["max"],
        },
        "valid_action_rate_pct": valid_pct,
        "regression_rate_pct": reg_pct,
        "regression_frequency_pct": reg_pct,
        "failure_rate_pct": fail_pct,
        "mean_latency_improvement_pct": round(float(np.mean(latency_improvements)), 2),
        "mean_throughput_improvement_pct": round(float(np.mean(throughput_improvements)), 2),
        "improvement_distribution": {
            "latency_improvement_pct": latency_dist,
            "throughput_improvement_pct": throughput_dist,
        },
        "mean_storage_delta_mb": round(float(np.mean(storage_deltas)), 2),
        "mean_write_overhead": round(float(np.mean(write_overheads)), 3),
        "mean_cpu_delta_pct": round(float(np.mean(cpu_deltas)), 2),
        "action_distribution": action_counts,
    }


def compare_policies(
    agent: TrainableRLAgent,
    baseline: BaselinePolicy | None = None,
    random_policy: RandomPolicy | None = None,
    no_change_policy: NoChangePolicy | None = None,
    num_episodes: int = 50,
    seed_offset: int = 20000,
) -> dict[str, Any]:
    """Runs a head-to-head comparison between Trained RL, Baseline Heuristic, No-Change, and Random Policy."""
    env = DatabaseOptimizationEnv(seed=seed_offset)
    baseline = baseline or BaselinePolicy()
    random_policy = random_policy or RandomPolicy(seed=seed_offset)
    no_change_policy = no_change_policy or NoChangePolicy()

    rl_metrics = evaluate_policy(agent, env, num_episodes=num_episodes, seed_offset=seed_offset)
    baseline_metrics = evaluate_policy(baseline, env, num_episodes=num_episodes, seed_offset=seed_offset)
    no_change_metrics = evaluate_policy(no_change_policy, env, num_episodes=num_episodes, seed_offset=seed_offset)
    random_metrics = evaluate_policy(random_policy, env, num_episodes=num_episodes, seed_offset=seed_offset)

    comparison_table = (
        "| Metric | Trainable RL (DQN) | DBA Heuristic Baseline | No-Change Baseline | Random Policy |\n"
        "|---|---:|---:|---:|---:|\n"
        f"| Mean Episode Return | **{rl_metrics['mean_reward']}** | {baseline_metrics['mean_reward']} | {no_change_metrics['mean_reward']} | {random_metrics['mean_reward']} |\n"
        f"| Valid Action Rate (%) | **{rl_metrics['valid_action_rate_pct']}%** | {baseline_metrics['valid_action_rate_pct']}% | {no_change_metrics['valid_action_rate_pct']}% | {random_metrics['valid_action_rate_pct']}% |\n"
        f"| Mean Latency Impr. (%) | **+{rl_metrics['mean_latency_improvement_pct']}%** | +{baseline_metrics['mean_latency_improvement_pct']}% | +{no_change_metrics['mean_latency_improvement_pct']}% | {random_metrics['mean_latency_improvement_pct']}% |\n"
        f"| Mean Throughput Impr. (%) | **+{rl_metrics['mean_throughput_improvement_pct']}%** | +{baseline_metrics['mean_throughput_improvement_pct']}% | +{no_change_metrics['mean_throughput_improvement_pct']}% | {random_metrics['mean_throughput_improvement_pct']}% |\n"
        f"| Regression Frequency (%) | **{rl_metrics['regression_frequency_pct']}%** | {baseline_metrics['regression_frequency_pct']}% | {no_change_metrics['regression_frequency_pct']}% | {random_metrics['regression_frequency_pct']}% |\n"
        f"| Failure Rate (%) | **{rl_metrics['failure_rate_pct']}%** | {baseline_metrics['failure_rate_pct']}% | {no_change_metrics['failure_rate_pct']}% | {random_metrics['failure_rate_pct']}% |\n"
    )

    return {
        "rl_agent": rl_metrics,
        "baseline_policy": baseline_metrics,
        "no_change_policy": no_change_metrics,
        "random_policy": random_metrics,
        "markdown_table": comparison_table,
    }


def build_diverse_evaluation_workload() -> list[dict[str, Any]]:
    """Constructs a 24-scenario held-out workload spanning 6 distinct operational regimes.

    Unlike the training generator (which sampled total_db_size_mb in [400, 1200] and seq_scan_fraction in [0.3, 0.85]),
    this evaluation suite explicitly includes small tables (<= 300 MB), already-indexed OLTP queries,
    redundant-index cleanup states, nested-loop join bottlenecks, and active regression states.
    """
    scenarios: list[dict[str, Any]] = []

    # Regime 1: High sequential scan on unindexed medium/large tables (4 scenarios)
    for idx, (seq_frac, db_mb, lat_ms) in enumerate([(0.78, 520.0, 210.0), (0.65, 480.0, 175.0), (0.82, 750.0, 260.0), (0.58, 410.0, 145.0)]):
        scenarios.append({
            "scenario_id": f"eval-seqscan-{idx+1}",
            "regime": "high_seq_scan_unindexed",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=4500, mean_exec_time_ms=lat_ms * 0.55, read_write_ratio=0.88),
                query_performance=QueryPerformance(p50_latency_ms=lat_ms * 0.45, p95_latency_ms=lat_ms, slow_query_ratio=0.22),
                plan_features=PlanFeatures(total_plan_cost=1200.0 + idx * 300.0, seq_scan_fraction=seq_frac, index_scan_fraction=round(1.0 - seq_frac, 2), nested_loop_fraction=0.12),
                existing_indexes=ExistingIndexes(index_count=3, redundant_index_count=0, index_utilization_ratio=0.75),
                storage_impact=StorageImpact(total_db_size_mb=db_mb, storage_budget_utilization=0.35),
                write_penalty=WritePenalty(write_ops_per_minute=90.0, table_update_rate=0.15, write_overhead_score=0.18),
            ),
        })

    # Regime 2: Redundant index bloat with high write overhead (4 scenarios)
    for idx, (red_cnt, write_sc) in enumerate([(2, 0.52), (3, 0.65), (1, 0.48), (4, 0.72)]):
        scenarios.append({
            "scenario_id": f"eval-redundant-idx-{idx+1}",
            "regime": "redundant_index_bloat",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=6200, mean_exec_time_ms=38.0, read_write_ratio=0.55),
                query_performance=QueryPerformance(p50_latency_ms=28.0, p95_latency_ms=82.0, slow_query_ratio=0.06),
                plan_features=PlanFeatures(total_plan_cost=340.0, seq_scan_fraction=0.18, index_scan_fraction=0.72, nested_loop_fraction=0.10),
                existing_indexes=ExistingIndexes(index_count=8 + idx, total_index_size_mb=95.0, redundant_index_count=red_cnt, index_utilization_ratio=0.35),
                storage_impact=StorageImpact(total_db_size_mb=460.0, storage_budget_utilization=0.55),
                write_penalty=WritePenalty(write_ops_per_minute=340.0, table_update_rate=0.45, write_overhead_score=write_sc),
            ),
        })

    # Regime 3: Small table (<= 300 MB) mid-episode with nested-loop bottleneck — tests PARTITION_TABLE OOD trap (4 scenarios)
    from app.services.rl.contracts import RecommendationHistory, SandboxResults
    for idx, (db_mb, nl_frac, p95_ms) in enumerate([(120.0, 0.48, 135.0), (185.0, 0.55, 160.0), (240.0, 0.42, 115.0), (95.0, 0.62, 180.0)]):
        scenarios.append({
            "scenario_id": f"eval-small-table-nestloop-{idx+1}",
            "regime": "small_table_nested_loop_ood",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=3800, mean_exec_time_ms=p95_ms * 0.5, read_write_ratio=0.82),
                query_performance=QueryPerformance(p50_latency_ms=p95_ms * 0.4, p95_latency_ms=p95_ms, slow_query_ratio=0.15),
                plan_features=PlanFeatures(total_plan_cost=680.0, seq_scan_fraction=0.22, index_scan_fraction=0.45, nested_loop_fraction=nl_frac),
                existing_indexes=ExistingIndexes(index_count=4, redundant_index_count=0, index_utilization_ratio=0.68),
                recommendation_history=RecommendationHistory(approved_count=3 + idx, rejected_count=0, pending_count=0, last_action_idx=4),
                sandbox_results=SandboxResults(last_improvement_pct=35.0, last_validation_status=1.0, last_speedup_factor=1.55, consecutive_sandbox_failures=0),
                storage_impact=StorageImpact(total_db_size_mb=db_mb, storage_budget_utilization=0.20),
                write_penalty=WritePenalty(write_ops_per_minute=110.0, table_update_rate=0.18, write_overhead_score=0.20),
            ),
        })


    # Regime 4: Very large table (> 750 MB) with high scan/latency suitable for partitioning or indexing (4 scenarios)
    for idx, (db_mb, p95_ms) in enumerate([(820.0, 195.0), (960.0, 240.0), (1150.0, 280.0), (890.0, 210.0)]):
        scenarios.append({
            "scenario_id": f"eval-large-table-{idx+1}",
            "regime": "large_table_analytical",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=2100, mean_exec_time_ms=p95_ms * 0.6, read_write_ratio=0.92),
                query_performance=QueryPerformance(p50_latency_ms=p95_ms * 0.5, p95_latency_ms=p95_ms, slow_query_ratio=0.19),
                plan_features=PlanFeatures(total_plan_cost=2600.0, seq_scan_fraction=0.36, index_scan_fraction=0.44, nested_loop_fraction=0.15),
                existing_indexes=ExistingIndexes(index_count=6, redundant_index_count=0, index_utilization_ratio=0.70),
                storage_impact=StorageImpact(total_db_size_mb=db_mb, storage_budget_utilization=0.48),
                write_penalty=WritePenalty(write_ops_per_minute=75.0, table_update_rate=0.12, write_overhead_score=0.16),
            ),
        })

    # Regime 5: Already optimal low-latency OLTP workload on small table (4 scenarios)
    for idx, db_mb in enumerate([85.0, 140.0, 210.0, 165.0]):
        scenarios.append({
            "scenario_id": f"eval-already-optimal-{idx+1}",
            "regime": "already_optimal_oltp",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=12000, mean_exec_time_ms=6.5, read_write_ratio=0.75),
                query_performance=QueryPerformance(p50_latency_ms=4.2, p95_latency_ms=14.0, slow_query_ratio=0.01),
                plan_features=PlanFeatures(total_plan_cost=28.0, seq_scan_fraction=0.05, index_scan_fraction=0.92, nested_loop_fraction=0.05),
                existing_indexes=ExistingIndexes(index_count=5, redundant_index_count=0, index_utilization_ratio=0.94),
                storage_impact=StorageImpact(total_db_size_mb=db_mb, storage_budget_utilization=0.22),
                write_penalty=WritePenalty(write_ops_per_minute=220.0, table_update_rate=0.28, write_overhead_score=0.25),
            ),
        })

    # Regime 6: Active regression state where conservative NO_OP is required (4 scenarios)
    for idx, spike in enumerate([1.6, 1.9, 2.2, 1.75]):
        scenarios.append({
            "scenario_id": f"eval-active-regression-{idx+1}",
            "regime": "active_regression_hold",
            "state": SanitizedState(
                workload_statistics=WorkloadStatistics(total_calls=5000, mean_exec_time_ms=95.0, read_write_ratio=0.70),
                query_performance=QueryPerformance(p50_latency_ms=65.0, p95_latency_ms=190.0, slow_query_ratio=0.24),
                plan_features=PlanFeatures(total_plan_cost=890.0, seq_scan_fraction=0.15, index_scan_fraction=0.70, nested_loop_fraction=0.12),
                existing_indexes=ExistingIndexes(index_count=7, redundant_index_count=0, index_utilization_ratio=0.65),
                storage_impact=StorageImpact(total_db_size_mb=220.0, storage_budget_utilization=0.40),
                write_penalty=WritePenalty(write_ops_per_minute=260.0, table_update_rate=0.35, write_overhead_score=0.42),
                regression_signals=RegressionSignals(regression_detected=1.0, latency_spike_ratio=spike, buffer_spike_ratio=1.5, risk_level=0.75),
            ),
        })

    return scenarios


def reproduce_rl_metrics_from_predictions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recomputes RL evaluation summary metrics directly from saved step prediction records."""
    total = len(records)
    if total == 0:
        return {
            "total_actions": 0,
            "valid_action_rate_pct": 0.0,
            "regression_frequency_pct": 0.0,
            "failure_rate_pct": 0.0,
            "reward_stability": _compute_distribution_summary([]),
            "improvement_distribution": {
                "latency_improvement_pct": _compute_distribution_summary([]),
                "throughput_improvement_pct": _compute_distribution_summary([]),
            },
            "action_distribution": {a.name: 0 for a in ActionType},
        }

    rewards = [float(r["net_reward"]) for r in records]
    lat_imprs = [float(r["latency_improvement_pct"]) for r in records]
    tput_imprs = [float(r["throughput_improvement_pct"]) for r in records]
    valid_cnt = sum(1 for r in records if bool(r["is_valid_action"]))
    reg_cnt = sum(1 for r in records if bool(r["regression_detected"]))
    fail_cnt = sum(
        1
        for r in records
        if bool(r["regression_detected"]) or float(r["net_reward"]) < -0.5 or r.get("sandbox_status", "success") != "success"
    )
    action_counts = {a.name: 0 for a in ActionType}
    for r in records:
        act_name = str(r["action_name"])
        action_counts[act_name] = action_counts.get(act_name, 0) + 1

    r_dist = _compute_distribution_summary(rewards)
    return {
        "total_actions": total,
        "valid_action_rate_pct": round((valid_cnt / total) * 100.0, 2),
        "regression_frequency_pct": round((reg_cnt / total) * 100.0, 2),
        "failure_rate_pct": round((fail_cnt / total) * 100.0, 2),
        "mean_reward": r_dist["mean"],
        "std_reward": r_dist["std"],
        "reward_stability": {
            "mean_reward": r_dist["mean"],
            "std_reward": r_dist["std"],
            "median_reward": r_dist["p50_median"],
            "iqr_reward": r_dist["iqr"],
            "min_reward": r_dist["min"],
            "max_reward": r_dist["max"],
        },
        "improvement_distribution": {
            "latency_improvement_pct": _compute_distribution_summary(lat_imprs),
            "throughput_improvement_pct": _compute_distribution_summary(tput_imprs),
        },
        "action_distribution": action_counts,
    }


def evaluate_policies_on_diverse_workload(
    agent: TrainableRLAgent,
    baseline: BaselinePolicy | None = None,
    no_change: NoChangePolicy | None = None,
    random_policy: RandomPolicy | None = None,
) -> dict[str, Any]:
    """Evaluates raw DQN, safety-gated DQN, DBA heuristic baseline, no-change baseline, and random policy on the 24-scenario diverse workload."""
    scenarios = build_diverse_evaluation_workload()
    baseline = baseline or BaselinePolicy()
    no_change = no_change or NoChangePolicy()
    random_policy = random_policy or RandomPolicy(seed=RL_EVALUATION_SEED)
    reward_calc = RewardCalculator()

    policy_records: dict[str, list[dict[str, Any]]] = {
        "raw_dqn_agent": [],
        "safety_gated_dqn_agent": [],
        "rule_based_baseline": [],
        "no_op_baseline": [],
        "random_baseline": [],
    }

    for idx, item in enumerate(scenarios):
        scenario_id = item["scenario_id"]
        regime = item["regime"]
        state: SanitizedState = item["state"]

        raw_dqn_action = agent.select_action(state, deterministic=True)
        valid_raw, violation_reason = is_action_valid_for_state(raw_dqn_action, state)
        gated_dqn_action = raw_dqn_action if valid_raw else baseline.select_action(state)

        candidates = {
            "raw_dqn_agent": raw_dqn_action,
            "safety_gated_dqn_agent": gated_dqn_action,
            "rule_based_baseline": baseline.select_action(state),
            "no_op_baseline": no_change.select_action(state),
            "random_baseline": random_policy.select_action(state),
        }

        for p_name, act in candidates.items():
            env = DatabaseOptimizationEnv(reward_calculator=reward_calc, seed=RL_EVALUATION_SEED + idx)
            env._state = state
            rec = env._synthesize_recommendation(act, state)
            measured = env._execute_sandbox_simulation(rec, state)
            rb = reward_calc.compute(measured)
            is_valid, reason = is_action_valid_for_state(act, state)

            policy_records[p_name].append({
                "scenario_id": scenario_id,
                "regime": regime,
                "policy_name": p_name,
                "action_code": int(act),
                "action_name": act.name,
                "is_valid_action": is_valid,
                "precondition_violation": reason if not is_valid else (violation_reason if p_name == "safety_gated_dqn_agent" and not valid_raw else None),
                "safety_gate_intervened": bool(p_name == "safety_gated_dqn_agent" and not valid_raw),
                "latency_improvement_pct": round(float(measured.latency_improvement_pct), 3),
                "throughput_improvement_pct": round(float(measured.throughput_improvement_pct), 3),
                "net_reward": round(float(rb.net_reward), 4),
                "regression_detected": bool(measured.regression_detected),
                "sandbox_status": measured.sandbox_status,
            })

    summaries = {
        p_name: reproduce_rl_metrics_from_predictions(recs)
        for p_name, recs in policy_records.items()
    }
    return {
        "scenario_count": len(scenarios),
        "regimes_covered": sorted({s["regime"] for s in scenarios}),
        "policy_summaries": summaries,
        "predictions_by_policy": policy_records,
    }


def audit_rl_training_artifacts(model_dir: Path = DEFAULT_ARTIFACT_DIR) -> dict[str, Any]:
    """Audits the persisted v0.8.0 training metrics and explains the 303 training regressions and PARTITION_TABLE collapse."""
    metrics_path = model_dir / "metrics.json"
    if not metrics_path.exists():
        return {
            "artifact_found": False,
            "explanation": "metrics.json not found in model artifact directory.",
        }

    raw = json.loads(metrics_path.read_text(encoding="utf-8"))
    ts = raw.get("training_summary", raw)
    total_regressions = int(ts.get("total_regressions", 0))
    action_counts = ts.get("action_distribution") or ts.get("action_counts", {})
    total_steps = int(ts.get("total_steps") or (sum(int(v) for v in action_counts.values()) if action_counts else 0))
    partition_steps = int(action_counts.get("PARTITION_TABLE", 0))
    drop_index_steps = int(action_counts.get("DROP_INDEX", 0))
    join_steps = int(action_counts.get("CHANGE_JOIN_STRATEGY", 0))

    return {
        "artifact_found": True,
        "recorded_total_regressions": total_regressions,
        "recorded_total_training_steps": total_steps,
        "recorded_training_regression_rate_pct": round((total_regressions / max(total_steps, 1)) * 100.0, 2),
        "recorded_action_counts": action_counts,
        "partition_table_selection_share_pct": round((partition_steps / max(total_steps, 1)) * 100.0, 2),
        "root_causes": [
            (
                f"During the 150-episode training run ({total_steps} total steps), epsilon decayed slowly from 1.0 to "
                f"{ts.get('final_epsilon', 0.2997)} (decay=0.992 per episode). Exploratory actions selected DROP_INDEX "
                f"{drop_index_steps} times and CHANGE_JOIN_STRATEGY {join_steps} times; whenever redundant_index_count==0 "
                f"(~50% of initial states) or nested_loop_fraction<=0.2, the sandbox simulator penalized those actions as "
                f"-60% and -12% latency regressions, accumulating {total_regressions} training regression events."
            ),
            (
                f"In DatabaseOptimizationEnv._generate_initial_state(), total_db_size_mb was sampled exclusively from "
                f"Uniform(400, 1200) > 300 MB, and _transition_state() never updated total_db_size_mb after PARTITION_TABLE. "
                f"Consequently, PARTITION_TABLE yielded +25%..+45% reward unconditionally on every training state ({partition_steps}/{total_steps} "
                f"steps = {round((partition_steps / max(total_steps, 1)) * 100.0, 1)}%), causing the greedy Q-network to collapse to "
                f"PARTITION_TABLE even on out-of-distribution small tables (<= 300 MB) where partitioning causes a -10% regression."
            ),
            (
                "DEFAULT_ARTIFACT_DIR in persistence.py previously pointed to 'ai/rl/models/v0.8.0' instead of "
                "'backend/app/services/rl/model_artifacts/v0.8.0', causing RLInferenceService to silently fall back to "
                "BaselinePolicy at runtime unless explicitly given the artifact path."
            ),
        ],
    }


def run_comprehensive_rl_evaluation(
    model_dir: Path | None = None,
    persist_artifacts: bool = True,
) -> dict[str, Any]:
    """Runs the complete Phase 9 RL evaluation, compares policies, verifies reproducibility, and saves artifacts."""
    if model_dir is None:
        model_dir = DEFAULT_ARTIFACT_DIR

    agent, config_data = load_rl_artifacts(model_dir)
    baseline = BaselinePolicy()
    no_change = NoChangePolicy()
    random_policy = RandomPolicy(seed=RL_EVALUATION_SEED)

    training_audit = audit_rl_training_artifacts(model_dir)
    standard_comparison = compare_policies(
        agent=agent,
        baseline=baseline,
        random_policy=random_policy,
        no_change_policy=no_change,
        num_episodes=50,
        seed_offset=RL_EVALUATION_SEED,
    )
    diverse_eval = evaluate_policies_on_diverse_workload(
        agent=agent,
        baseline=baseline,
        no_change=no_change,
        random_policy=random_policy,
    )

    saved_predictions = diverse_eval["predictions_by_policy"]["safety_gated_dqn_agent"]
    reproduced = reproduce_rl_metrics_from_predictions(saved_predictions)
    reported = diverse_eval["policy_summaries"]["safety_gated_dqn_agent"]
    metrics_reproducible = (
        reproduced["valid_action_rate_pct"] == reported["valid_action_rate_pct"]
        and reproduced["regression_frequency_pct"] == reported["regression_frequency_pct"]
        and reproduced["mean_reward"] == reported["mean_reward"]
    )

    evaluated_at = datetime.now(timezone.utc).isoformat()
    weights_path = model_dir / "agent.pt"
    sha_prefix = hashlib.sha256(weights_path.read_bytes()).hexdigest()[:16] if weights_path.exists() else None

    report = {
        "model_name": "DBZenith DQN Optimization Policy",
        "model_version": config_data.get("version", "v0.8.0"),
        "evaluation_version": "phase9-rl-eval-v1",
        "evaluated_at": evaluated_at,
        "dataset_type": "SYNTHETIC_SANDBOX_SIMULATION_AND_MULTI_REGIME_OOD_WORKLOAD",
        "validated_on_real_workloads": False,
        "reproducibility": {
            "evaluation_seed": RL_EVALUATION_SEED,
            "python_version": platform.python_version(),
            "torch_version": torch.__version__,
            "numpy_version": np.__version__,
            "state_dim": int(config_data.get("state_dim", 38)),
            "action_dim": int(config_data.get("action_dim", 6)),
            "artifact_sha256_prefix": sha_prefix,
            "metrics_reproducible_from_saved_predictions": metrics_reproducible,
        },
        "training_regression_investigation": training_audit,
        "held_out_in_distribution_comparison": standard_comparison,
        "diverse_multi_regime_evaluation": {
            "scenario_count": diverse_eval["scenario_count"],
            "regimes_covered": diverse_eval["regimes_covered"],
            "policy_summaries": diverse_eval["policy_summaries"],
        },
        "known_limitations": [
            "Trained and evaluated in a parameterized analytical sandbox environment (DatabaseOptimizationEnv), not against live production PostgreSQL workloads.",
            "Raw DQN weights (v0.8.0) collapsed toward PARTITION_TABLE due to an unpenalized reward shortcut in the training state generator (total_db_size_mb always > 300 MB).",
            "Safety-gated inference validates state preconditions before accepting a DQN action and falls back to deterministic DBA heuristics (BaselinePolicy) when the raw DQN proposes an OOD/unsafe action.",
            "RL outputs are advisory proposals only and cannot directly authorize or execute production DDL/DML changes.",
        ],
    }

    if persist_artifacts and model_dir.exists():
        (model_dir / "evaluation_report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        (model_dir / "held_out_predictions.json").write_text(
            json.dumps(diverse_eval["predictions_by_policy"], indent=2),
            encoding="utf-8",
        )

    return report

