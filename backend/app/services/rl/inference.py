"""Inference service for the DBZenith RL Optimization Engine.

Guarantees the strict invariant:
RL -> recommendation -> sandbox -> measured result -> reward
Never modifies production directly, and human approval / backend authorization
remain strictly independent of model confidence.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any
import numpy as np
from pydantic import ValidationError
import torch

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
from app.services.rl.evaluate import (
    is_action_valid_for_state,
    run_comprehensive_rl_evaluation,
)
from app.services.rl.persistence import (
    DEFAULT_ARTIFACT_DIR,
    RLArtifactMissingError,
    load_rl_artifacts,
)
from app.services.rl.reward import RewardCalculator

logger = logging.getLogger(__name__)

_CACHED_RL_EVAL_REPORT: dict[str, Any] | None = None
_CACHED_RL_EVAL_DIR: str | None = None


class RLInputValidationError(ValueError):
    """Raised when an RL state input fails schema, finiteness, or safety validation."""


def get_rl_evaluation_report(
    model_dir: Path = DEFAULT_ARTIFACT_DIR,
    *,
    force_recompute: bool = False,
) -> dict[str, Any]:
    """Load or compute the comprehensive RL evaluation and transparency report."""
    global _CACHED_RL_EVAL_REPORT, _CACHED_RL_EVAL_DIR
    resolved = str(model_dir.resolve()) if model_dir.exists() else str(model_dir)
    if not force_recompute and _CACHED_RL_EVAL_REPORT is not None and _CACHED_RL_EVAL_DIR == resolved:
        return _CACHED_RL_EVAL_REPORT

    report_path = model_dir / "evaluation_report.json"
    if not force_recompute and report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            _CACHED_RL_EVAL_REPORT = report
            _CACHED_RL_EVAL_DIR = resolved
            return report
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read cached RL evaluation_report.json (%s); recomputing.", exc)

    report = run_comprehensive_rl_evaluation(model_dir, persist_artifacts=model_dir.exists())
    _CACHED_RL_EVAL_REPORT = report
    _CACHED_RL_EVAL_DIR = resolved
    return report


def _check_nested_finite(obj: Any, path: str = "state") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise RLInputValidationError(f"Non-string key in {path}.")
            _check_nested_finite(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            _check_nested_finite(item, f"{path}[{idx}]")
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise RLInputValidationError(f"Non-finite float value (NaN/Inf) at {path}.")
    elif isinstance(obj, str):
        upper = obj.upper()
        for forbidden in ("DROP ", "ALTER ", "TRUNCATE ", "DELETE ", "UPDATE ", "INSERT "):
            if forbidden in upper:
                raise RLInputValidationError(
                    f"Unsafe raw SQL/DDL token '{forbidden.strip()}' rejected in sanitized state field {path}."
                )


def validate_rl_state(state: SanitizedState | dict[str, Any]) -> tuple[SanitizedState, list[str]]:
    """Validates an RL state input for schema integrity, finite numbers, and OOD boundaries."""
    if isinstance(state, dict):
        _check_nested_finite(state)
        try:
            sanitized_state = SanitizedState(**state)
        except ValidationError as exc:
            raise RLInputValidationError(f"Invalid SanitizedState schema: {exc}") from exc
    elif isinstance(state, SanitizedState):
        sanitized_state = state
    else:
        raise RLInputValidationError("State must be a SanitizedState instance or valid state dictionary.")

    vec = sanitized_state.to_vector()
    if vec.shape != (SanitizedState.state_dim(),):
        raise RLInputValidationError(
            f"State vector dimension mismatch: expected {SanitizedState.state_dim()}, got {vec.shape}."
        )
    if np.isnan(vec).any() or np.isinf(vec).any():
        raise RLInputValidationError("State vector contains NaN or Inf values after normalization.")

    # Reject extreme corrupted / adversarial numeric values
    if sanitized_state.plan_features.total_plan_cost > 1e9:
        raise RLInputValidationError("Out-of-bounds total_plan_cost (> 1e9); rejected as corrupted telemetry.")
    if sanitized_state.query_performance.p95_latency_ms > 1e7:
        raise RLInputValidationError("Out-of-bounds p95_latency_ms (> 1e7 ms); rejected as corrupted telemetry.")
    if sanitized_state.storage_impact.total_db_size_mb > 1e7:
        raise RLInputValidationError("Out-of-bounds total_db_size_mb (> 1e7 MB); rejected as corrupted telemetry.")

    # Flag out-of-distribution (OOD) regimes relative to training generator
    ood_warnings: list[str] = []
    db_mb = sanitized_state.storage_impact.total_db_size_mb
    seq_frac = sanitized_state.plan_features.seq_scan_fraction
    if db_mb <= 300.0:
        ood_warnings.append(
            f"total_db_size_mb ({db_mb:.1f} MB) is <= 300 MB (outside training distribution Uniform[400, 1200] MB); "
            "PARTITION_TABLE is unsafe in this regime."
        )
    elif db_mb > 1200.0:
        ood_warnings.append(
            f"total_db_size_mb ({db_mb:.1f} MB) exceeds training distribution upper bound (1200 MB)."
        )
    if seq_frac < 0.30 or seq_frac > 0.85:
        ood_warnings.append(
            f"seq_scan_fraction ({seq_frac:.2f}) is outside training initial state range [0.30, 0.85]."
        )
    if sanitized_state.regression_signals.regression_detected > 0.5:
        ood_warnings.append("Active regression signal detected (regression_detected > 0.5); conservative hold advised.")

    return sanitized_state, ood_warnings


class RLInferenceService:
    """Safe, sandbox-gated inference service for the RL optimization engine."""

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_ARTIFACT_DIR,
        fallback_policy: BaselinePolicy | None = None,
        reward_calculator: RewardCalculator | None = None,
        device: str = "cpu",
        allow_fallback: bool = True,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.fallback_policy = fallback_policy or BaselinePolicy()
        self.reward_calculator = reward_calculator or RewardCalculator()
        self.device = device
        self.allow_fallback = allow_fallback
        self._agent: TrainableRLAgent | None = None
        self._model_metadata: dict[str, Any] = {}
        self._fallback_reason: str | None = None
        self._load_agent()

    def _load_agent(self) -> None:
        """Attempts to load trained RL model; falls back to deterministic baseline policy if unavailable."""
        try:
            self._agent, self._model_metadata = load_rl_artifacts(self.model_dir, device=self.device)
            self._fallback_reason = None
        except Exception as exc:
            if not self.allow_fallback:
                raise RLArtifactMissingError(f"RL model artifact unavailable at {self.model_dir}: {exc}") from exc
            self._agent = None
            self._fallback_reason = str(exc)
            self._model_metadata = {
                "model_type": "BaselineHeuristicFallback",
                "version": "v0.8.0-fallback",
                "is_fallback": True,
                "fallback_reason": self._fallback_reason,
            }

    @property
    def is_trained_agent_available(self) -> bool:
        return self._agent is not None

    def _compute_agent_q_confidence(self, state: SanitizedState, selected_action: ActionType) -> float:
        """Computes softmax action probability from the learned Q-network without inventing numbers."""
        assert self._agent is not None
        vec = state.to_vector()
        state_t = torch.tensor(vec, dtype=torch.float32, device=self._agent.device).unsqueeze(0)
        with torch.no_grad():
            q_values = self._agent.q_net(state_t).squeeze(0)
            probs = torch.softmax(q_values, dim=0)
            conf = float(probs[int(selected_action)].item())
        return round(conf, 4)

    def optimize(
        self,
        state: SanitizedState | dict[str, Any],
    ) -> dict[str, Any]:
    
        sanitized_state, ood_warnings = validate_rl_state(state)

        safety_gate_triggered = False
        safety_gate_reason: str | None = None
        raw_dqn_action: str | None = None

        # 1. Action selection with OOD & precondition safety gate
        if self._agent is not None:
            proposed_action = self._agent.select_action(sanitized_state, deterministic=True)
            raw_dqn_action = proposed_action.name
            is_valid, violation_reason = is_action_valid_for_state(proposed_action, sanitized_state)
            if is_valid:
                action = proposed_action
                policy_used = "trainable_dqn"
                is_fallback = False
                source_classification = "LEARNED_MODEL"
                conf: float | None = self._compute_agent_q_confidence(sanitized_state, action)
                confidence_source = "learned_dqn_q_softmax"
            else:
                safety_gate_triggered = True
                safety_gate_reason = violation_reason
                action = self.fallback_policy.select_action(sanitized_state)
                policy_used = "safety_gated_baseline_fallback"
                is_fallback = True
                source_classification = "DETERMINISTIC_FALLBACK"
                conf = None
                confidence_source = "none_deterministic_fallback"
        else:
            action = self.fallback_policy.select_action(sanitized_state)
            policy_used = "baseline_heuristic"
            is_fallback = True
            source_classification = "DETERMINISTIC_FALLBACK"
            conf = None
            confidence_source = "none_deterministic_fallback"

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

        # 6. Safety summary — model output can NEVER directly authorize production execution
        is_safe = (
            not measured_result.regression_detected
            and measured_result.sandbox_status == "success"
            and recommendation.requires_approval
        )

        eval_report: dict[str, Any] | None = None
        if DEFAULT_ARTIFACT_DIR.exists():
            try:
                eval_report = get_rl_evaluation_report(DEFAULT_ARTIFACT_DIR)
            except Exception as exc:
                logger.warning("Unable to load RL evaluation report: %s", exc)

        transparency = {
            "model_name": (
                "BaselinePolicy (Deterministic DBA Heuristic)"
                if is_fallback
                else "DBZenith DQN Optimization Policy"
            ),
            "model_version": self._model_metadata.get("version", "v0.8.0"),
            "source_classification": source_classification,
            "simulation_source_classification": "SANDBOX_SIMULATION",
            "is_fallback": is_fallback,
            "fallback_reason": safety_gate_reason if safety_gate_triggered else self._fallback_reason,
            "safety_gate_triggered": safety_gate_triggered,
            "raw_dqn_proposed_action": raw_dqn_action,
            "ood_warnings": ood_warnings,
            "evaluation_dataset_type": (
                eval_report.get("dataset_type", "SYNTHETIC_SANDBOX_SIMULATION_AND_MULTI_REGIME_OOD_WORKLOAD")
                if eval_report
                else "SYNTHETIC_SANDBOX_SIMULATION_AND_MULTI_REGIME_OOD_WORKLOAD"
            ),
            "validated_on_real_workloads": False,
            "last_evaluation_time": eval_report.get("evaluated_at") if eval_report else None,
            "known_limitations": (
                eval_report.get("known_limitations")
                if eval_report
                else [
                    "Trained and evaluated in a parameterized analytical sandbox environment (DatabaseOptimizationEnv), not against live production PostgreSQL workloads.",
                    "Deterministic fallback does not produce neural confidence values (confidence is null when fallback is active).",
                    "RL outputs cannot directly authorize or execute production changes.",
                ]
            ),
        }

        return {
            "policy_used": policy_used,
            "policy_version": self._model_metadata.get("version", "v0.8.0-dqn"),
            "model_type": (
                "BaselineHeuristicFallback"
                if is_fallback
                else self._model_metadata.get("model_type", "DQN")
            ),
            "source_classification": source_classification,
            "simulation_source_classification": "SANDBOX_SIMULATION",
            "is_fallback": is_fallback,
            "fallback_reason": safety_gate_reason if safety_gate_triggered else self._fallback_reason,
            "safety_gate_triggered": safety_gate_triggered,
            "raw_dqn_proposed_action": raw_dqn_action,
            "ood_warnings": ood_warnings,
            "action_type": action.name,
            "action_code": int(action),
            "confidence": conf,
            "confidence_source": confidence_source,
            "predicted_reward": round(reward_breakdown.net_reward, 4),
            "simulated_cost_reduction_pct": round(measured_result.latency_improvement_pct, 2),
            "explanation": recommendation.reason,
            "recommendation": recommendation.model_dump(),
            "sandbox_measured_result": measured_result.model_dump(),
            "reward_breakdown": reward_breakdown.model_dump(),
            "is_safe_for_approval": is_safe,
            "requires_human_approval": True,
            "can_authorize_production": False,
            "approval_independent_of_confidence": True,
            "production_modified": False,
            "model_metadata": self._model_metadata,
            "transparency": transparency,
        }

