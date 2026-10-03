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


@router.post("/rewrite", response_model=SQLRewriteResult)
def rewrite_sql(request: SQLRewriteApiRequest) -> SQLRewriteResult:
    """Safely rewrite a SQL query using AST transformations and sandbox validation."""
    engine = get_rewrite_engine()
    return engine.rewrite(request.sql, validate_sandbox=request.validate_sandbox)
