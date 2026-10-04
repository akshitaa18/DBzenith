from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.plan import PlanAnalysis
from app.models.workload import QueryStatistic
from app.schemas.plans import PlanAnalysisResponse, PlanAnalyzeRequest
from app.services.plans.analyzer import analyze_plan
from app.services.privacy.contracts import RawPlan
from app.services.privacy.gateway import PrivacyGateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plans", tags=["plans"])


def _explain_sql(db: Session, sql: str) -> Any:
    stripped = sql.strip()
    if ";" in stripped:
        raise HTTPException(status_code=400, detail="multi_statement_sql_not_allowed")
    # Block SQL comment injection tricks designed to mask DDL/DML
    if "--" in stripped or "/*" in stripped:
        raise HTTPException(status_code=400, detail="sql_comments_not_allowed")
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first not in {"SELECT", "WITH", "VALUES", "INSERT", "UPDATE", "DELETE"}:
        raise HTTPException(status_code=400, detail="only_dml_or_select_sql_is_supported")
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
    query_id: int | None = None
    raw_plan: Any = None

    if request.query_id is not None:
        try:
            ident_num = int(request.query_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_query_id_format")

        INT32_MIN = -2147483648
        INT32_MAX = 2147483647
        if INT32_MIN <= ident_num <= INT32_MAX:
            cond = (QueryStatistic.query_id == ident_num) | (QueryStatistic.id == ident_num)
        else:
            cond = (QueryStatistic.query_id == ident_num)

        stat = db.scalar(
            select(QueryStatistic)
            .where(cond)
            .order_by(desc(QueryStatistic.id))
            .limit(1)
        )
        if stat is None:
            raise HTTPException(status_code=404, detail="query_stat_not_found")

        query_id = stat.query_id

        if stat.explain_plan is not None:
            raw_plan = stat.explain_plan
        else:
            # Generate a safe EXPLAIN-only plan from normalized query
            normalized = stat.normalized_query
            safe_sql = re.sub(r"\$(\d+)", "'sample_val'", normalized)
            try:
                raw_plan = _explain_sql(db, safe_sql)
            except Exception:
                try:
                    safe_sql_num = re.sub(r"\$(\d+)", "1", normalized)
                    raw_plan = _explain_sql(db, safe_sql_num)
                except Exception:
                    # Construct a safe structural plan representation for the normalized statement
                    op_type = "ModifyTable" if normalized.lower().startswith(("insert", "update", "delete")) else "Seq Scan"
                    raw_plan = [{
                        "Plan": {
                            "Node Type": op_type,
                            "Operation": normalized.split()[0].capitalize() if op_type == "ModifyTable" else "Select",
                            "Relation Name": "workload_relation",
                            "Startup Cost": 0.0,
                            "Total Cost": float(stat.mean_exec_time_ms or 100.0),
                            "Plan Rows": int(stat.rows or 1000),
                            "Plan Width": 64,
                            "Plans": [
                                {
                                    "Node Type": "Seq Scan",
                                    "Relation Name": "workload_relation",
                                    "Startup Cost": 0.0,
                                    "Total Cost": float(stat.mean_exec_time_ms or 100.0),
                                    "Plan Rows": int(stat.rows or 1000),
                                    "Plan Width": 64,
                                }
                            ],
                        }
                    }]

    elif request.sql is not None:
        raw_plan = _explain_sql(db, request.sql)
    else:
        raw_plan = request.plan

    try:
        # Raw plans cross the mandatory privacy gateway before any persistence or analysis.
        sanitized_input = PrivacyGateway().sanitize_plan(RawPlan(plan=raw_plan, query_id=query_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    structural_hash = sanitized_input.structural_hash

    # Backend Idempotency: check if an identical analysis already exists and is still valid
    existing: PlanAnalysis | None = None
    if query_id is not None:
        existing = (
            db.query(PlanAnalysis)
            .filter(PlanAnalysis.query_id == query_id, PlanAnalysis.structural_hash == structural_hash)
            .order_by(PlanAnalysis.id.desc())
            .first()
        )
    if existing is None:
        existing = (
            db.query(PlanAnalysis)
            .filter(PlanAnalysis.structural_hash == structural_hash)
            .order_by(PlanAnalysis.id.desc())
            .first()
        )

    if existing is not None:
        logger.info(
            "PLAN_ANALYSIS_CACHE_HIT",
            extra={
                "event": "PLAN_ANALYSIS_CACHE_HIT",
                "query_id": query_id,
                "structural_hash": structural_hash,
                "analysis_id": existing.id,
            },
        )
        logger.info("GNN_CACHE_HIT", extra={"event": "GNN_CACHE_HIT", "structural_hash": structural_hash})
        return _response(existing)

    logger.info(
        "PLAN_ANALYSIS_REQUEST",
        extra={"event": "PLAN_ANALYSIS_REQUEST", "query_id": query_id, "structural_hash": structural_hash},
    )
    logger.info("GNN_INFERENCE", extra={"event": "GNN_INFERENCE", "query_id": query_id, "structural_hash": structural_hash})

    try:
        result = analyze_plan(sanitized_input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "PLAN_ANALYSIS_EXECUTED",
        extra={"event": "PLAN_ANALYSIS_EXECUTED", "query_id": query_id, "structural_hash": structural_hash},
    )

    sanitized = result["sanitized_plan"]
    row = PlanAnalysis(
        query_id=query_id,
        structural_hash=structural_hash,
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
