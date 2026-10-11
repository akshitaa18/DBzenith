from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.provenance import ProvenanceBadgeLabel, ProvenanceState, badge_for_state


class PlanAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: int | str | None = None
    sql: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    plan: dict[str, Any] | list[Any] | None = None

    @model_validator(mode="after")
    def require_source(self):
        supplied = sum(x is not None for x in (self.query_id, self.sql, self.plan))
        if supplied != 1:
            raise ValueError("provide exactly one of query_id, sql, or plan")
        return self


class PlanAnalysisResponse(BaseModel):
    id: int
    created_at: datetime
    query_id: int | None
    structural_hash: str
    sanitized_plan: dict[str, Any] | list[Any]
    graph: dict[str, Any]
    features: dict[str, Any]
    bottlenecks: list[dict[str, Any]]
    explanation: dict[str, Any]
    provenance_state: str = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    provenance_badge: str = ProvenanceBadgeLabel.ESTIMATED.value
    source_identifier: str | None = None
    is_synthetic: bool = False
    is_measured: bool = False
    model_version: str | None = "deterministic-plan-analyzer-v0.7.0"

    @model_validator(mode="after")
    def normalize_provenance(self):
        if self.is_synthetic or self.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value:
            self.provenance_state = ProvenanceState.SYNTHETIC_DEMO.value
            self.provenance_badge = ProvenanceBadgeLabel.DEMO.value
            self.is_synthetic = True
            self.is_measured = False
        else:
            self.provenance_badge = badge_for_state(self.provenance_state)
        return self


class PlanCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_plan: dict[str, Any] | list[Any] | None = None
    candidate_plan: dict[str, Any] | list[Any] | None = None
    query_id: int | str | None = None
    simulation_id: int | None = None
    recommendation_id: int | None = None
    baseline_sql: str | None = Field(default=None, max_length=500_000)
    candidate_sql: str | None = Field(default=None, max_length=500_000)
    candidate_index_ddl: str | None = Field(default=None, max_length=10_000)


class SafeBenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_sql: str | None = Field(default=None, max_length=500_000)
    candidate_sql: str | None = Field(default=None, max_length=500_000)
    candidate_index_ddl: str | None = Field(default=None, max_length=10_000)
    query_id: int | str | None = None
    recommendation_id: int | None = None
    baseline_plan: dict[str, Any] | list[Any] | None = None
    candidate_plan: dict[str, Any] | list[Any] | None = None
    parameters: dict[str, Any] | list[Any] | None = None
    warmup_runs: int = Field(default=1, ge=0, le=5)
    benchmark_runs: int = Field(default=3, ge=1, le=10)
    statement_timeout_ms: int = Field(default=3000, ge=50, le=15000)
    run_id: str | None = Field(default=None, max_length=128)
    pre_cancelled: bool = False


class PlanExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(default="json", pattern="^(json|csv|JSON|CSV)$")
    comparison: dict[str, Any] | None = None
    baseline_plan: dict[str, Any] | list[Any] | None = None
    candidate_plan: dict[str, Any] | list[Any] | None = None
    baseline_sql: str | None = Field(default=None, max_length=500_000)
    candidate_sql: str | None = Field(default=None, max_length=500_000)
    candidate_index_ddl: str | None = Field(default=None, max_length=10_000)
    recommendation_id: int | None = None
