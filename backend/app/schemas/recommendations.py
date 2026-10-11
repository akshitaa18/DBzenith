from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.lifecycle import LifecycleState, status_for_lifecycle_state
from app.core.provenance import ProvenanceBadgeLabel, ProvenanceState, badge_for_state


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None
    type: str
    target: str
    proposed_change: str
    reason: str
    evidence: dict[str, Any]
    expected_benefit: str
    risk: str
    confidence: float
    affected_queries: list[Any]
    requires_approval: bool
    status: str
    lifecycle_state: str = LifecycleState.AWAITING_APPROVAL.value
    candidate_simulation_id: int | None = None
    baseline_metrics: dict[str, Any] | None = None
    post_change_metrics: dict[str, Any] | None = None
    impact_summary: dict[str, Any] | None = None
    deployment_details: dict[str, Any] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    applied_at: datetime | None = None
    validated_at: datetime | None = None
    provenance_state: str = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    provenance_badge: str = ProvenanceBadgeLabel.ESTIMATED.value
    source_identifier: str | None = None
    query_fingerprint: str | None = None
    is_synthetic: bool = False
    is_measured: bool = False
    model_version: str | None = "advisor-engine-v0.7.0"

    @model_validator(mode="after")
    def normalize_provenance(self):
        if not self.lifecycle_state:
            if self.status == "approved":
                self.lifecycle_state = LifecycleState.APPROVED.value
            elif self.status == "rejected":
                self.lifecycle_state = LifecycleState.REJECTED.value
            else:
                self.lifecycle_state = LifecycleState.AWAITING_APPROVAL.value

        if self.is_synthetic or self.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value:
            self.provenance_state = ProvenanceState.SYNTHETIC_DEMO.value
            self.provenance_badge = ProvenanceBadgeLabel.DEMO.value
            self.is_synthetic = True
            self.is_measured = False
        else:
            self.provenance_badge = badge_for_state(self.provenance_state)
        if not self.model_version:
            self.model_version = "advisor-engine-v0.7.0"
        return self


class RecommendationPage(BaseModel):
    items: list[RecommendationResponse]
    page: int
    page_size: int
    total: int


class RecommendationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="operator decision", min_length=1, max_length=500)


class RecommendationTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_state: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(default="lifecycle transition", min_length=1, max_length=500)


class RecommendationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_applied: bool = False
    verify_catalog: bool = False
    deployment_reference: str | None = Field(default=None, max_length=255)
    reason: str = Field(default="Confirmed deployment of approved optimization", min_length=1, max_length=500)


class PostChangeObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: int | None = None
    normalized_query: str | None = None
    query_fingerprint: str | None = None
    captured_at: datetime | str | None = None
    window_seconds: float | None = Field(default=60.0)
    calls: int | None = Field(default=100, ge=0)
    mean_exec_time_ms: float | None = None
    min_exec_time_ms: float | None = None
    max_exec_time_ms: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p99_latency_ms: float | None = None
    total_exec_time_ms: float | None = None
    rows: int | None = Field(default=0, ge=0)
    shared_blks_hit: int | None = Field(default=0, ge=0)
    shared_blks_read: int | None = Field(default=0, ge=0)
    temp_blks_read: int | None = Field(default=0, ge=0)
    temp_blks_written: int | None = Field(default=0, ge=0)
    blk_read_time_ms: float | None = Field(default=0.0, ge=0.0)
    blk_write_time_ms: float | None = Field(default=0.0, ge=0.0)
    query_frequency_per_minute: float | None = None
    error_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    validation_failed: bool = False
    source_identifier: str | None = None
    provenance_state: str = ProvenanceState.LIVE_TELEMETRY.value
    is_synthetic: bool = False
    is_measured: bool = True
    environment: str = "production"


class RecommendationValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: int | None = None
    simulation_id: int | None = None
    use_sandbox_benchmark: bool = False
    post_change_observation: PostChangeObservationInput | None = None
    min_sample_size: int = Field(default=1, ge=1, le=100000)
    reason: str = Field(default="Post-change telemetry validation", min_length=1, max_length=500)
