"""Explicit contracts for the DBZenith privacy boundary.

RawQuery and RawPlan are ingestion-only contracts. SanitizedQuery, SanitizedPlan,
and AIWorkloadRecord are the only contracts permitted past the AI boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=1_000_000)
    query_id: int | None = None
    source: str = Field(default="telemetry", max_length=100)


class SanitizedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_sql: str = Field(min_length=1, max_length=20_000)
    structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identifier_tokens: list[str] = Field(default_factory=list, max_length=500)
    literal_counts: dict[str, int] = Field(default_factory=dict)
    statement_type: str = Field(min_length=1, max_length=32)


class RawPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Any
    query_id: int | None = None


class SanitizedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: dict[str, Any] | list[Any]
    structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_types: list[str] = Field(default_factory=list, max_length=500)
    relation_tokens: list[str] = Field(default_factory=list, max_length=500)


class AIWorkloadRecord(BaseModel):
    """The only workload contract that may be consumed by AI-facing modules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: SanitizedQuery
    plan: SanitizedPlan | None = None
    calls: int = Field(ge=0)
    query_frequency_per_minute: float = Field(ge=0)
    duration_ms_bucket: int = Field(ge=0)
    rows_bucket: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    privacy_version: Literal["1"] = "1"

    @field_validator("query_frequency_per_minute")
    @classmethod
    def finite_frequency(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("query_frequency_per_minute must be finite")
        return value
