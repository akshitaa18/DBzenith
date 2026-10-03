from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.plan import PlanAnalysis
from app.models.workload import QueryStatistic
from app.schemas.plans import PlanAnalysisResponse, PlanAnalyzeRequest
from app.services.plans.analyzer import analyze_plan
from app.services.privacy.contracts import RawPlan
from app.services.privacy.gateway import PrivacyGateway

router = APIRouter(prefix="/plans", tags=["plans"])


def _explain_sql(db: Session, sql: str) -> Any:
    stripped = sql.strip()
    if ";" in stripped:
        raise HTTPException(status_code=400, detail="multi_statement_sql_not_allowed")
    # Block SQL comment injection tricks designed to mask DDL/DML
    if "--" in stripped or "/*" in stripped:
        raise HTTPException(status_code=400, detail="sql_comments_not_allowed")
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first not in {"SELECT", "WITH", "VALUES"}:
        raise HTTPException(status_code=400, detail="only_read_only_sql_is_supported")
    # EXPLAIN without ANALYZE plans the statement but does not execute it.
    with db.begin_nested():
        db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        result = db.execute(text(f"EXPLAIN (FORMAT JSON) {stripped}"))
        row = result.scalar_one()
    if isinstance(row, str):
        return json.loads(row)
    return row


def _response(row: PlanAnalysis) -> PlanAnalysisResponse:
    return PlanAnalysisResponse(
        id=row.id,
        created_at=row.created_at,
        query_id=row.query_id,
        structural_hash=row.structural_hash,
        sanitized_plan=row.sanitized_plan,
        graph=row.graph,
        features=row.features,
        bottlenecks=row.bottlenecks,
        explanation={**row.explanation, "gnn": row.explanation.get("gnn")} if isinstance(row.explanation, dict) else row.explanation,
    )


@router.post("/analyze", response_model=PlanAnalysisResponse)
def analyze(request: PlanAnalyzeRequest, db: Session = Depends(get_db)) -> PlanAnalysisResponse:
    query_id = request.query_id
    if request.query_id is not None:
        stat = db.query(QueryStatistic).filter(QueryStatistic.query_id == request.query_id).order_by(QueryStatistic.id.desc()).first()
        if stat is None or stat.explain_plan is None:
            raise HTTPException(status_code=404, detail="query_plan_not_found")
        raw_plan = stat.explain_plan
    elif request.sql is not None:
        raw_plan = _explain_sql(db, request.sql)
    else:
        raw_plan = request.plan

    try:
        # Raw plans cross the mandatory privacy gateway before any persistence or analysis.
        sanitized_input = PrivacyGateway().sanitize_plan(RawPlan(plan=raw_plan, query_id=query_id))
        result = analyze_plan(RawPlan(plan=sanitized_input.plan, query_id=query_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sanitized = result["sanitized_plan"]
    row = PlanAnalysis(
        query_id=query_id,
        structural_hash=sanitized.structural_hash,
        sanitized_plan=sanitized.plan,
        graph=result["graph"],
        features=result["features"],
        bottlenecks=result["bottlenecks"],
        explanation={**result["explanation"], "gnn": result.get("gnn")},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _response(row)


@router.get("/{analysis_id}", response_model=PlanAnalysisResponse)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)) -> PlanAnalysisResponse:
    row = db.get(PlanAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="plan_analysis_not_found")
    return _response(row)
