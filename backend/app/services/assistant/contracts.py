"""Contracts, state definitions, and schemas for the Conversational DBA Assistant."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict
from pydantic import BaseModel, Field


class ControlledToolName(str, Enum):
    GET_SLOW_QUERIES = "get_slow_queries"
    GET_QUERY_DETAILS = "get_query_details"
    GET_EXECUTION_PLAN = "get_execution_plan"
    ANALYZE_PLAN = "analyze_plan"
    GET_RECOMMENDATIONS = "get_recommendations"
    SIMULATE_RECOMMENDATION = "simulate_recommendation"
    COMPARE_SIMULATIONS = "compare_simulations"
    EXPLAIN_BOTTLENECK = "explain_bottleneck"
    GET_WORKLOAD_SUMMARY = "get_workload_summary"
    REQUEST_MIGRATION_APPROVAL = "request_migration_approval"


class UserRole(str, Enum):
    DBA = "dba"
    ANALYST = "analyst"
    VIEWER = "viewer"
    UNAUTHORIZED = "unauthorized"


class AuditEvent(BaseModel):
    timestamp: str
    session_id: str
    event_type: str
    tool_name: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_summary: str | None = None
    authorized: bool = True
    security_flag: str | None = None


class ApprovalRequest(BaseModel):
    recommendation_id: int
    target_table: str
    proposed_change: str
    reason: str
    expected_benefit: str
    status: str = "pending_dba_review"
    requires_human_approval: bool = True
    agent_approved: bool = False  # Strictly False: agent can never self-approve!
    requested_at: str


class AssistantState(TypedDict, total=False):
    session_id: str
    user_role: str
    user_message: str
    messages: list[dict[str, str]]
    parsed_intent: str
    extracted_entities: dict[str, Any]
    safety_check_passed: bool
    safety_violation_reason: str | None
    evidence: dict[str, Any]
    analysis: dict[str, Any]
    recommendations: list[dict[str, Any]]
    simulations: list[dict[str, Any]]
    simulation_comparisons: dict[str, Any]
    explanation: str
    approval_request: dict[str, Any] | None
    audit_trail: list[dict[str, Any]]
    final_response: str
