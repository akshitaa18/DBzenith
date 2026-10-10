"""API routes for the DBZenith Reinforcement Learning Optimization Engine."""

from typing import Any
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_analyst, require_viewer
from app.core.security import TokenPayload
from app.db.session import get_db
from app.services.rl.contracts import SanitizedState
from app.services.rl.inference import RLInferenceService

router = APIRouter(prefix="/rl", tags=["reinforcement_learning"])
inference_service = RLInferenceService()


@router.get("/status")
def get_rl_status(
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Returns RL model status, version, and active policy."""
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
    }


@router.post("/optimize")
def optimize_workload(
    payload: dict[str, Any] | None = Body(default=None),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Generates an RL-driven optimization recommendation validated in the sandbox."""
    if not payload:
        state = SanitizedState()
    elif "workload_metrics" in payload and isinstance(payload["workload_metrics"], dict):
        from app.services.rl.contracts import PlanFeatures
        wm = payload["workload_metrics"]
        seq_frac = float(wm.get("seq_scan_ratio", wm.get("seq_scan_fraction", 0.4)))
        seq_frac = min(1.0, max(0.0, seq_frac))
        state = SanitizedState(
            plan_features=PlanFeatures(
                total_plan_cost=max(0.0, float(wm.get("total_cost", wm.get("total_plan_cost", 450.0)))),
                seq_scan_fraction=seq_frac,
                index_scan_fraction=round(max(0.0, 1.0 - seq_frac - 0.1), 4),
            ),
        )
    else:
        allowed_keys = set(SanitizedState.model_fields.keys())
        filtered = {k: v for k, v in payload.items() if k in allowed_keys}
        state = SanitizedState(**filtered)

    result = inference_service.optimize(state)
    return result

