"""API routes for the DBZenith Reinforcement Learning Optimization Engine."""

import math
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_analyst, require_viewer
from app.core.security import TokenPayload
from app.db.session import get_db
from app.services.rl.contracts import PlanFeatures, SanitizedState
from app.services.rl.inference import (
    RLInferenceService,
    RLInputValidationError,
    get_rl_evaluation_report,
    validate_rl_state,
)

router = APIRouter(prefix="/rl", tags=["reinforcement_learning"])
inference_service = RLInferenceService()


@router.get("/status")
def get_rl_status(
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Returns RL model status, version, active policy, and transparency metadata."""
    eval_report = get_rl_evaluation_report()
    return {
        "status": "ready",
        "trained_agent_available": inference_service.is_trained_agent_available,
        "metadata": inference_service._model_metadata,
        "actions_supported": [
            "NO_OP",
            "CREATE_INDEX",
            "DROP_INDEX",
            "REWRITE_QUERY",
            "PARTITION_TABLE",
            "CHANGE_JOIN_STRATEGY",
        ],
        "safety_invariant": "RL -> recommendation -> sandbox -> measured result -> reward (production mutation forbidden)",
        "transparency": {
            "model_name": eval_report.get("model_name", "DBZenith DQN Optimization Policy"),
            "model_version": eval_report.get("model_version", "v0.8.0"),
            "source_classification": (
                "LEARNED_MODEL" if inference_service.is_trained_agent_available else "DETERMINISTIC_FALLBACK"
            ),
            "simulation_source_classification": "SANDBOX_SIMULATION",
            "evaluation_dataset_type": eval_report.get(
                "dataset_type",
                "SYNTHETIC_SANDBOX_SIMULATION_AND_MULTI_REGIME_OOD_WORKLOAD",
            ),
            "validated_on_real_workloads": False,
            "last_evaluation_time": eval_report.get("evaluated_at"),
            "known_limitations": eval_report.get("known_limitations", []),
        },
    }


@router.get("/evaluation")
def get_rl_evaluation(
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Returns the comprehensive RL policy evaluation, training regression audit, and transparency report."""
    return get_rl_evaluation_report()


@router.post("/optimize")
def optimize_workload(
    payload: dict[str, Any] | None = Body(default=None),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Generates an RL-driven optimization recommendation validated in the sandbox."""
    try:
        if not payload:
            state: SanitizedState | dict[str, Any] = SanitizedState()
        elif "workload_metrics" in payload:
            wm = payload["workload_metrics"]
            if not isinstance(wm, dict):
                raise RLInputValidationError("'workload_metrics' must be a JSON object.")
            extra_top = set(payload.keys()) - {"workload_metrics"}
            if extra_top:
                raise RLInputValidationError(f"Unsupported top-level fields alongside workload_metrics: {sorted(extra_top)}")
            raw_seq = wm.get("seq_scan_ratio", wm.get("seq_scan_fraction", 0.4))
            raw_cost = wm.get("total_cost", wm.get("total_plan_cost", 450.0))
            if not isinstance(raw_seq, (int, float)) or math.isnan(float(raw_seq)) or math.isinf(float(raw_seq)):
                raise RLInputValidationError("seq_scan_ratio must be a finite number.")
            if not isinstance(raw_cost, (int, float)) or math.isnan(float(raw_cost)) or math.isinf(float(raw_cost)):
                raise RLInputValidationError("total_cost must be a finite number.")
            seq_val = float(raw_seq)
            cost_val = float(raw_cost)
            if seq_val < 0.0 or seq_val > 1.0:
                raise RLInputValidationError("seq_scan_ratio must be in [0.0, 1.0].")
            if cost_val < 0.0 or cost_val > 1e9:
                raise RLInputValidationError("total_cost must be in [0.0, 1e9].")
            state = SanitizedState(
                plan_features=PlanFeatures(
                    total_plan_cost=cost_val,
                    seq_scan_fraction=seq_val,
                    index_scan_fraction=round(max(0.0, 1.0 - seq_val - 0.1), 4),
                ),
            )
        else:
            state, _ = validate_rl_state(payload)

        return inference_service.optimize(state)
    except RLInputValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


