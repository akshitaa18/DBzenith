from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: int | None = None
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
