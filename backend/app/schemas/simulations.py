from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.provenance import ProvenanceBadgeLabel, ProvenanceState


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
    provenance_state: str = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    provenance_badge: str = ProvenanceBadgeLabel.ESTIMATED.value
    source_identifier: str | None = None
    simulation_method: str = "hypopg_plan_estimate"
    result_type: str = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    is_synthetic: bool = False
    is_measured: bool = False
    is_verified_speedup: bool = False
    model_version: str | None = "hypopg-sandbox-v0.7.0"
    estimate_vs_measured_explanation: str = (
        "Estimated from PostgreSQL planner cost model (EXPLAIN / HypoPG); not a measured runtime benchmark speedup."
    )

    @model_validator(mode="after")
    def normalize_simulation_provenance(self):
        if self.is_synthetic or self.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value:
            self.provenance_state = ProvenanceState.SYNTHETIC_DEMO.value
            self.provenance_badge = ProvenanceBadgeLabel.DEMO.value
            self.result_type = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
            self.is_synthetic = True
            self.is_measured = False
            self.is_verified_speedup = False
            self.estimate_vs_measured_explanation = (
                "Synthetic demo simulation estimate — generated for demonstration and not a measured runtime speedup."
            )
        elif self.provenance_state == ProvenanceState.VERIFIED_POST_CHANGE.value:
            self.provenance_badge = ProvenanceBadgeLabel.VERIFIED.value
            self.result_type = ProvenanceState.VERIFIED_POST_CHANGE.value
            self.is_measured = True
            self.is_verified_speedup = True
            self.estimate_vs_measured_explanation = "Verified post-change production observation."
        elif (
            self.provenance_state == ProvenanceState.SANDBOX_BENCHMARK.value
            or self.result_type == ProvenanceState.SANDBOX_BENCHMARK.value
            or self.is_measured
        ):
            self.provenance_state = ProvenanceState.SANDBOX_BENCHMARK.value
            self.provenance_badge = ProvenanceBadgeLabel.SIMULATED.value
            self.result_type = ProvenanceState.SANDBOX_BENCHMARK.value
            self.is_measured = True
            self.is_verified_speedup = False
            self.estimate_vs_measured_explanation = (
                "Measured execution timing in an isolated sandbox benchmark; not yet verified in production."
            )
        else:
            self.provenance_state = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
            self.provenance_badge = ProvenanceBadgeLabel.ESTIMATED.value
            self.result_type = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
            self.is_measured = False
            self.is_verified_speedup = False
            self.estimate_vs_measured_explanation = (
                "Estimated from PostgreSQL planner cost model (EXPLAIN / HypoPG); not a measured runtime benchmark speedup."
            )
        return self
