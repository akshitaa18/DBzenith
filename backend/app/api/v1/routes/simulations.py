from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.recommendation import OptimizationRecommendation
from app.models.simulation import OptimizationSimulation
from app.schemas.simulations import SimulationRequest, SimulationResponse
from app.services.sandbox.simulator import SandboxSimulator

router = APIRouter(prefix="/simulations", tags=["simulations"])


def _response(row: OptimizationSimulation) -> SimulationResponse:
    return SimulationResponse.model_validate(row)


@router.post("", response_model=SimulationResponse)
def create_simulation(request: SimulationRequest, db: Session = Depends(get_db)) -> SimulationResponse:
    recommendation = db.get(OptimizationRecommendation, request.recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    if not recommendation.requires_approval:
        raise HTTPException(status_code=409, detail="simulation_requires_approval_gated_recommendation")
    try:
        row = SandboxSimulator().simulate(db, recommendation, request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"simulation_failed: {exc}") from exc
    return _response(row)


@router.get("", response_model=list[SimulationResponse])
def list_simulations(limit: int = 50, db: Session = Depends(get_db)) -> list[SimulationResponse]:
    rows = db.query(OptimizationSimulation).order_by(OptimizationSimulation.id.desc()).limit(limit).all()
    return [_response(r) for r in rows]


@router.get("/{simulation_id}", response_model=SimulationResponse)
def get_simulation(simulation_id: int, db: Session = Depends(get_db)) -> SimulationResponse:
    row = db.get(OptimizationSimulation, simulation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="simulation_not_found")
    return _response(row)
