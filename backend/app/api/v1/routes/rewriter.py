"""API routes for safe SQL AST rewriting."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.rewriter.contracts import SQLRewriteResult
from app.services.rewriter.engine import get_rewrite_engine

router = APIRouter(prefix="/rewriter", tags=["rewriter"])


class SQLRewriteApiRequest(BaseModel):
    sql: str = Field(..., description="Target candidate SQL query to rewrite.")
    validate_sandbox: bool = Field(
        default=True,
        description="Whether to run isolated sandbox EXPLAIN cost and semantic regression check.",
    )


from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.auth import get_current_user_optional
from app.core.security import TokenPayload
from app.services.audit.recorder import AuditEventCategory, record_audit_event


@router.post("/rewrite", response_model=SQLRewriteResult)
def rewrite_sql(
    request: SQLRewriteApiRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload | None = Depends(get_current_user_optional),
) -> SQLRewriteResult:
    """Safely rewrite a SQL query using AST transformations and sandbox validation."""
    engine = get_rewrite_engine()
    result = engine.rewrite(request.sql, validate_sandbox=request.validate_sandbox)

    record_audit_event(
        db=db,
        event_category=AuditEventCategory.AI_BOUNDARY,
        action="sql_ast_rewrite",
        actor_id=current_user.user_id if current_user else "anonymous",
        actor_username=current_user.username if current_user else "analyst",
        actor_role=current_user.role.value if current_user else "ANALYST",
        target_entity="SQLQuery",
        status="SUCCESS" if result.safety_verdict == "safe" else "REJECTED",
        details={
            "transformation": result.transformation,
            "validation_status": result.validation_status,
            "safety_verdict": result.safety_verdict,
            "rejection_reason": result.rejection_reason,
            "cost_improvement_pct": result.cost_improvement_pct,
        },
    )

    return result
