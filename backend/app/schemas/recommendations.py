from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class RecommendationPage(BaseModel):
    items: list[RecommendationResponse]
    page: int
    page_size: int
    total: int


class RecommendationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="operator decision", min_length=1, max_length=500)
