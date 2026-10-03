from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: int = Field(gt=0)
    benchmark_runs: int = Field(default=3, ge=0, le=5)
    statement_timeout_ms: int = Field(default=5000, ge=250, le=30000)
    max_rows_per_table: int = Field(default=25000, ge=100, le=100000)


class SimulationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    recommendation_id: int | None
    status: str
    baseline_cost: float | None
    proposed_cost: float | None
    improvement: float | None
    affected_queries: list[Any]
    plan_differences: list[Any]
    estimated_storage_impact: dict[str, Any]
    write_overhead_estimate: dict[str, Any]
    confidence: float
    limitations: list[str]
    benchmark: dict[str, Any]
    baseline_plans: list[Any]
    proposed_plans: list[Any]
    error: str | None
