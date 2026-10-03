"""Contracts and schemas for the DBZenith Safe SQL Rewriting Subsystem.

Every rewrite must contain:
- original query
- rewritten query
- transformation
- reason
- expected benefit
- confidence
- validation status

Production safety guarantee:
All rewrites are validated strictly in the sandbox; production SQL is never directly modified.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TransformationType(str, Enum):
    """Conservative, semantically verifiable SQL AST transformations."""
    NO_OP = "NO_OP"
    REDUNDANT_DISTINCT_ELIMINATION = "REDUNDANT_DISTINCT_ELIMINATION"
    OR_TO_IN_LIST = "OR_TO_IN_LIST"
    EXISTS_SELECT_ONE_SIMPLIFICATION = "EXISTS_SELECT_ONE_SIMPLIFICATION"
    IN_SUBQUERY_ORDER_BY_ELIMINATION = "IN_SUBQUERY_ORDER_BY_ELIMINATION"
    LEFT_JOIN_TO_INNER_JOIN = "LEFT_JOIN_TO_INNER_JOIN"
    PREDICATE_PUSHDOWN = "PREDICATE_PUSHDOWN"
    UNION_ALL_OPTIMIZATION = "UNION_ALL_OPTIMIZATION"


class ValidationStatus(str, Enum):
    """Validation outcomes from the isolated sandbox simulation."""
    PENDING = "pending"
    VALIDATED_IN_SANDBOX = "validated_in_sandbox"
    REJECTED_SEMANTIC_REGRESSION = "rejected_semantic_regression"
    UNSAFE_REJECTED = "unsafe_rejected"
    COST_REGRESSION_REJECTED = "cost_regression_rejected"


class SQLRewriteResult(BaseModel):
    """Contract representing a safe AST-transformed query and its sandbox validation."""
    model_config = ConfigDict(extra="forbid")

    original_query: str = Field(description="Original SQL query statement.")
    rewritten_query: str = Field(description="Semantically transformed SQL query statement.")
    transformation: str = Field(description="Name of the AST transformation applied.")
    reason: str = Field(description="Technical rationale explaining why the rewrite is advantageous.")
    expected_benefit: str = Field(description="Anticipated optimizer or execution advantage.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score of transformation correctness.")
    validation_status: str = Field(
        default=ValidationStatus.PENDING.value,
        description="Validation outcome produced by the isolated sandbox.",
    )
    safety_verdict: str = Field(
        default="safe",
        description="Safety status: 'safe', 'unsafe', or 'rejected'.",
    )
    rejection_reason: str | None = Field(default=None, description="Detailed explanation if rewrite was rejected.")
    ast_diff: str | None = Field(default=None, description="Structural AST difference summary.")
    baseline_cost: float | None = Field(default=None, description="Estimated total cost of the original query.")
    rewritten_cost: float | None = Field(default=None, description="Estimated total cost of the rewritten query.")
    cost_improvement_pct: float | None = Field(default=None, description="Percentage cost improvement (>0 is faster).")
    semantic_match: bool | None = Field(default=None, description="True if sandbox verified exact result row match.")
    production_modified: bool = Field(default=False, description="Strict safety invariant flag: always False.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional transformation metadata.")

    @property
    def transformed(self) -> bool:
        return self.transformation != TransformationType.NO_OP.value and self.original_query != self.rewritten_query

    @property
    def is_safe(self) -> bool:
        return self.safety_verdict == "safe"

