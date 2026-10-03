"""API routes for the DBZenith Reinforcement Learning Optimization Engine."""

from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.rl.contracts import SanitizedState
from app.services.rl.inference import RLInferenceService

router = APIRouter(prefix="/rl", tags=["reinforcement_learning"])
inference_service = RLInferenceService()


@router.get("/status")
def get_rl_status() -> dict[str, Any]:
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
    state: SanitizedState | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generates an RL-driven optimization recommendation validated in the sandbox."""
    if state is None:
        state = SanitizedState()

    result = inference_service.optimize(state)
    return result
