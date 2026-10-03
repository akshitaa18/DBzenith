"""Multi-objective reward function for the DBZenith RL Optimization Engine.

Considers:
1. Latency improvement (+)
2. Throughput improvement (+)
3. Storage impact (-)
4. Write overhead (-)
5. CPU/resource usage (-)
6. Plan regressions (-)
7. Risk penalty (-)
"""

from __future__ import annotations

from app.services.rl.contracts import MeasuredSandboxResult, RewardBreakdown


class RewardCalculator:
    """Computes multi-objective reward from measured sandbox simulation results."""

    def __init__(
        self,
        w_latency: float = 1.5,
        w_throughput: float = 1.0,
        w_storage: float = 0.4,
        w_write: float = 0.6,
        w_cpu: float = 0.3,
        w_regression: float = 2.5,
        w_risk: float = 0.8,
    ) -> None:
        self.w_latency = w_latency
        self.w_throughput = w_throughput
        self.w_storage = w_storage
        self.w_write = w_write
        self.w_cpu = w_cpu
        self.w_regression = w_regression
        self.w_risk = w_risk

    def compute(self, result: MeasuredSandboxResult) -> RewardBreakdown:
        """Calculates multi-objective reward and returns detailed breakdown."""
        # 1. Latency improvement: positive when latency drops
        lat_ratio = result.latency_improvement_pct / 50.0
        lat_reward = max(min(lat_ratio, 2.0), -2.0)

        # 2. Throughput improvement: positive when QPS increases
        thr_ratio = result.throughput_improvement_pct / 50.0
        thr_reward = max(min(thr_ratio, 2.0), -2.0)

        # 3. Storage penalty: positive storage delta penalizes, negative (drop index) gives credit
        # e.g., 20 MB -> 0.2 penalty
        storage_penalty = max(min(result.storage_delta_mb / 100.0, 2.0), -0.5)

        # 4. Write overhead penalty
        write_penalty = max(min(result.write_overhead_score, 2.0), 0.0)

        # 5. CPU usage penalty
        cpu_penalty = max(min(result.cpu_usage_delta_pct / 50.0, 2.0), 0.0)

        # 6. Regression penalty: heavy deterministic penalty if regression occurs
        regression_penalty = 1.5 if result.regression_detected else 0.0

        # 7. Risk penalty
        risk_penalty = max(min(result.risk_score, 1.0), 0.0)

        # If sandbox failed or invalid action, add explicit failure penalty
        if result.sandbox_status != "success":
            regression_penalty += 1.0

        net_reward = (
            self.w_latency * lat_reward
            + self.w_throughput * thr_reward
            - self.w_storage * storage_penalty
            - self.w_write * write_penalty
            - self.w_cpu * cpu_penalty
            - self.w_regression * regression_penalty
            - self.w_risk * risk_penalty
        )

        return RewardBreakdown(
            latency_reward=round(float(self.w_latency * lat_reward), 4),
            throughput_reward=round(float(self.w_throughput * thr_reward), 4),
            storage_penalty=round(float(self.w_storage * storage_penalty), 4),
            write_penalty=round(float(self.w_write * write_penalty), 4),
            cpu_penalty=round(float(self.w_cpu * cpu_penalty), 4),
            regression_penalty=round(float(self.w_regression * regression_penalty), 4),
            risk_penalty=round(float(self.w_risk * risk_penalty), 4),
            net_reward=round(float(net_reward), 4),
        )
