from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    provenance_state: str = ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    provenance_badge: str = ProvenanceBadgeLabel.ESTIMATED.value
    source_identifier: str | None = None
    query_fingerprint: str | None = None
    is_synthetic: bool = False
    is_measured: bool = False
    model_version: str | None = "advisor-engine-v0.7.0"

    @model_validator(mode="after")
    def normalize_provenance(self):
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
