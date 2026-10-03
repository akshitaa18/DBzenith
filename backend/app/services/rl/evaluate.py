"""Evaluation pipeline comparing the trained RL agent against baseline policies."""

from __future__ import annotations

from typing import Any
import numpy as np

from app.services.rl.agent import TrainableRLAgent
from app.services.rl.baseline import BaselinePolicy, RandomPolicy
from app.services.rl.contracts import ActionType
from app.services.rl.environment import DatabaseOptimizationEnv


def evaluate_policy(
    policy: TrainableRLAgent | BaselinePolicy | RandomPolicy,
    env: DatabaseOptimizationEnv,
    num_episodes: int = 50,
    seed_offset: int = 10000,
) -> dict[str, Any]:
    """Evaluates a policy on held-out episodes and collects performance metrics."""
    rewards: list[float] = []
    latency_improvements: list[float] = []
    throughput_improvements: list[float] = []
    storage_deltas: list[float] = []
    write_overheads: list[float] = []
    cpu_deltas: list[float] = []
    regression_events: int = 0
    total_actions: int = 0
    action_counts: dict[str, int] = {action.name: 0 for action in ActionType}

    is_rl_agent = isinstance(policy, TrainableRLAgent)

    for ep in range(num_episodes):
        state, _ = env.reset(seed=seed_offset + ep)
        ep_reward = 0.0

        for _ in range(env.max_steps_per_episode):
            total_actions += 1
            if is_rl_agent:
                action = policy.select_action(state, deterministic=True)
            else:
                action = policy.select_action(state)

            action_counts[action.name] += 1
            next_state, reward, terminated, truncated, info = env.step(action)
            ep_reward += reward

            res = info.get("measured_result", {})
            latency_improvements.append(res.get("latency_improvement_pct", 0.0))
            throughput_improvements.append(res.get("throughput_improvement_pct", 0.0))
            storage_deltas.append(res.get("storage_delta_mb", 0.0))
            write_overheads.append(res.get("write_overhead_score", 0.0))
            cpu_deltas.append(res.get("cpu_usage_delta_pct", 0.0))

            if res.get("regression_detected", False):
                regression_events += 1

            state = next_state
            if terminated or truncated:
                break

        rewards.append(ep_reward)

    return {
        "policy_name": getattr(policy, "name", policy.__class__.__name__),
        "num_episodes": num_episodes,
        "total_actions": total_actions,
        "mean_reward": round(float(np.mean(rewards)), 3),
        "std_reward": round(float(np.std(rewards)), 3),
        "mean_latency_improvement_pct": round(float(np.mean(latency_improvements)), 2),
        "mean_throughput_improvement_pct": round(float(np.mean(throughput_improvements)), 2),
        "mean_storage_delta_mb": round(float(np.mean(storage_deltas)), 2),
        "mean_write_overhead": round(float(np.mean(write_overheads)), 3),
        "mean_cpu_delta_pct": round(float(np.mean(cpu_deltas)), 2),
        "regression_rate_pct": round(float((regression_events / max(total_actions, 1)) * 100.0), 2),
        "action_distribution": action_counts,
    }


def compare_policies(
    agent: TrainableRLAgent,
    baseline: BaselinePolicy | None = None,
    random_policy: RandomPolicy | None = None,
    num_episodes: int = 50,
    seed_offset: int = 20000,
) -> dict[str, Any]:
    """Runs a head-to-head comparison between Trained RL, Baseline Heuristic, and Random Policy."""
    env = DatabaseOptimizationEnv(seed=seed_offset)
    baseline = baseline or BaselinePolicy()
    random_policy = random_policy or RandomPolicy(seed=seed_offset)

    rl_metrics = evaluate_policy(agent, env, num_episodes=num_episodes, seed_offset=seed_offset)
    baseline_metrics = evaluate_policy(baseline, env, num_episodes=num_episodes, seed_offset=seed_offset)
    random_metrics = evaluate_policy(random_policy, env, num_episodes=num_episodes, seed_offset=seed_offset)

    # Format markdown comparison summary
    comparison_table = (
        "| Metric | Trainable RL (DQN) | Baseline Policy (Heuristic) | Random Policy |\n"
        "|---|---:|---:|---:|\n"
        f"| Mean Episode Return | **{rl_metrics['mean_reward']}** | {baseline_metrics['mean_reward']} | {random_metrics['mean_reward']} |\n"
        f"| Mean Latency Impr. (%) | **+{rl_metrics['mean_latency_improvement_pct']}%** | +{baseline_metrics['mean_latency_improvement_pct']}% | {random_metrics['mean_latency_improvement_pct']}% |\n"
        f"| Mean Throughput Impr. (%) | **+{rl_metrics['mean_throughput_improvement_pct']}%** | +{baseline_metrics['mean_throughput_improvement_pct']}% | {random_metrics['mean_throughput_improvement_pct']}% |\n"
        f"| Mean Storage Delta (MB) | {rl_metrics['mean_storage_delta_mb']} MB | {baseline_metrics['mean_storage_delta_mb']} MB | {random_metrics['mean_storage_delta_mb']} MB |\n"
        f"| Mean Write Overhead | {rl_metrics['mean_write_overhead']} | {baseline_metrics['mean_write_overhead']} | {random_metrics['mean_write_overhead']} |\n"
        f"| Regression Rate (%) | **{rl_metrics['regression_rate_pct']}%** | {baseline_metrics['regression_rate_pct']}% | {random_metrics['regression_rate_pct']}% |\n"
    )

    return {
        "rl_agent": rl_metrics,
        "baseline_policy": baseline_metrics,
        "random_policy": random_metrics,
        "markdown_table": comparison_table,
    }
