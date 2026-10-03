"""FastAPI endpoints for the Conversational DBA Assistant."""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.assistant.audit import get_assistant_audit_logger
from app.services.assistant.contracts import AssistantState, ControlledToolName, UserRole
from app.services.assistant.graph import create_dba_assistant_graph

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    message: str = Field(..., description="User query or instruction to the DBA assistant.")
    session_id: str | None = Field(default=None, description="Optional conversation session ID.")
    role: str = Field(default="dba", description="User role: 'dba', 'analyst', or 'viewer'.")


class AssistantChatResponse(BaseModel):
    session_id: str
    response: str
    safety_check_passed: bool
    safety_violation_reason: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    simulations: list[dict[str, Any]] = Field(default_factory=list)
    approval_request: dict[str, Any] | None = None
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/chat", response_model=AssistantChatResponse)
def chat_with_assistant(
    request: AssistantChatRequest,
    db: Session = Depends(get_db),
) -> AssistantChatResponse:
    """Interacts with the Conversational DBA Assistant using LangGraph."""
    session_id = request.session_id or str(uuid.uuid4())
    audit = get_assistant_audit_logger()

    # Build compiled LangGraph for this session/role
    graph = create_dba_assistant_graph(db, user_role=request.role)

    # Initial state
    initial_state: AssistantState = {
        "session_id": session_id,
        "user_role": request.role,
        "user_message": request.message,
        "messages": audit.get_session_history(session_id),
        "evidence": {},
        "analysis": {},
        "recommendations": [],
        "simulations": [],
        "audit_trail": [],
    }

    # Execute graph
    final_state = graph.invoke(initial_state)

    # Record turn
    reply = final_state.get("final_response", "Analysis completed.")
    audit.record_turn(session_id, request.message, reply)

    # Fetch audit events for this session
    session_audit = audit.get_session_audit_trail(session_id)

    return AssistantChatResponse(
        session_id=session_id,
        response=reply,
        safety_check_passed=final_state.get("safety_check_passed", True),
        safety_violation_reason=final_state.get("safety_violation_reason"),
        evidence=final_state.get("evidence", {}),
        analysis=final_state.get("analysis", {}),
        recommendations=final_state.get("recommendations", []),
        simulations=final_state.get("simulations", []),
        approval_request=final_state.get("approval_request"),
        audit_trail=session_audit,
    )


@router.get("/history/{session_id}")
def get_session_history(session_id: str) -> dict[str, Any]:
    """Retrieves conversation history and audit log for a specific session."""
    audit = get_assistant_audit_logger()
    return {
        "session_id": session_id,
        "messages": audit.get_session_history(session_id),
        "audit_trail": audit.get_session_audit_trail(session_id),
    }


@router.get("/tools")
def list_controlled_tools() -> list[dict[str, str]]:
    """Returns the list and descriptions of all 10 authorized controlled tools."""
    tool_docs = [
        {"name": ControlledToolName.GET_SLOW_QUERIES.value, "description": "Fetches slow queries filtered through privacy gateway."},
        {"name": ControlledToolName.GET_QUERY_DETAILS.value, "description": "Fetches normalized query metrics without raw constants."},
        {"name": ControlledToolName.GET_EXECUTION_PLAN.value, "description": "Retrieves sanitized EXPLAIN execution plan."},
        {"name": ControlledToolName.ANALYZE_PLAN.value, "description": "Extracts plan features, GNN structural hashes, and bottlenecks."},
        {"name": ControlledToolName.GET_RECOMMENDATIONS.value, "description": "Retrieves pending index, partition, rewrite recommendations."},
        {"name": ControlledToolName.SIMULATE_RECOMMENDATION.value, "description": "Runs isolated sandbox simulation (HypoPG/ephemeral)."},
        {"name": ControlledToolName.COMPARE_SIMULATIONS.value, "description": "Compares multiple recommendation simulations side-by-side."},
        {"name": ControlledToolName.EXPLAIN_BOTTLENECK.value, "description": "Generates natural language bottleneck diagnosis."},
        {"name": ControlledToolName.GET_WORKLOAD_SUMMARY.value, "description": "Retrieves privacy-preserving aggregate workload stats."},
        {"name": ControlledToolName.REQUEST_MIGRATION_APPROVAL.value, "description": "Creates human DBA review request (strictly non-self-approving)."},
    ]
    return tool_docs
