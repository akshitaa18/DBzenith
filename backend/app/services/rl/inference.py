"""Inference service for the DBZenith RL Optimization Engine.

Guarantees the strict invariant:
RL -> recommendation -> sandbox -> measured result -> reward
Never modifies production directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np

from app.services.rl.agent import TrainableRLAgent
from app.services.rl.baseline import BaselinePolicy
from app.services.rl.contracts import (
    ActionType,
    MeasuredSandboxResult,
    RewardBreakdown,
    RLRecommendation,
    SanitizedState,
)
from app.services.rl.environment import DatabaseOptimizationEnv
from app.services.rl.persistence import DEFAULT_ARTIFACT_DIR, load_rl_artifacts
from app.services.rl.reward import RewardCalculator


class RLInferenceService:
    """Safe, sandbox-gated inference service for the RL optimization engine."""

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_ARTIFACT_DIR,
        fallback_policy: BaselinePolicy | None = None,
        reward_calculator: RewardCalculator | None = None,
        device: str = "cpu",
    ) -> None:
        self.model_dir = Path(model_dir)
        self.fallback_policy = fallback_policy or BaselinePolicy()
        self.reward_calculator = reward_calculator or RewardCalculator()
        self.device = device
        self._agent: TrainableRLAgent | None = None
        self._model_metadata: dict[str, Any] = {}
        self._load_agent()

    def _load_agent(self) -> None:
        """Attempts to load trained RL model; falls back to baseline policy if not yet trained."""
        try:
            self._agent, self._model_metadata = load_rl_artifacts(self.model_dir, device=self.device)
        except Exception:
            self._agent = None
            self._model_metadata = {"model_type": "BaselineHeuristicFallback", "version": "v0.8.0-fallback"}

    @property
    def is_trained_agent_available(self) -> bool:
        return self._agent is not None

    def optimize(
        self,
        state: SanitizedState | dict[str, Any],
    ) -> dict[str, Any]:
        """Executes full RL pipeline through recommendation and sandbox validation.

        Pipeline:
        1. Parse sanitized state
        2. RL action selection
        3. Recommendation synthesis
        4. Sandbox simulation
        5. Measured outcome extraction
        6. Reward calculation
        7. Production safety enforcement
        """
        if isinstance(state, dict):
            sanitized_state = SanitizedState(**state)
        elif isinstance(state, SanitizedState):
            sanitized_state = state
        else:
            raise TypeError("State must be SanitizedState or valid state dictionary.")

        # 1. Action selection
        if self._agent is not None:
            action = self._agent.select_action(sanitized_state, deterministic=True)
            policy_used = "trainable_dqn"
        else:
            action = self.fallback_policy.select_action(sanitized_state)
            policy_used = "baseline_heuristic"

        # 2. Ephemeral sandbox environment for isolated evaluation
        env = DatabaseOptimizationEnv(reward_calculator=self.reward_calculator)
        env._state = sanitized_state

        # 3. Recommendation synthesis & safety check
        recommendation: RLRecommendation = env._synthesize_recommendation(action, sanitized_state)
        env._assert_production_safety(recommendation)

        # 4. Sandbox simulation
        measured_result: MeasuredSandboxResult = env._execute_sandbox_simulation(recommendation, sanitized_state)

        # 5. Reward calculation
        reward_breakdown: RewardBreakdown = self.reward_calculator.compute(measured_result)

        # 6. Safety summary
        is_safe = (
            not measured_result.regression_detected
            and measured_result.sandbox_status == "success"
            and recommendation.requires_approval
        )

        return {
            "policy_used": policy_used,
            "action_type": action.name,
            "action_code": int(action),
            "recommendation": recommendation.model_dump(),
            "sandbox_measured_result": measured_result.model_dump(),
            "reward_breakdown": reward_breakdown.model_dump(),
            "is_safe_for_approval": is_safe,
            "production_modified": False,
            "model_metadata": self._model_metadata,
        }
