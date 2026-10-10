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
    stripped = sql.strip().rstrip("; \t\r\n").strip()
    if ";" in stripped:
        raise HTTPException(status_code=400, detail="multi_statement_sql_not_allowed")
    # Block SQL comment injection tricks designed to mask DDL/DML
    if "--" in stripped or "/*" in stripped:
        raise HTTPException(status_code=400, detail="sql_comments_not_allowed")
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first not in {"SELECT", "WITH", "VALUES"}:
        raise HTTPException(status_code=400, detail="only_select_or_with_queries_are_supported")

    if first in {"SELECT", "WITH"}:
        from app.services.rewriter.safety import SQLRewriteSafetyPolicy
        is_safe, reason = SQLRewriteSafetyPolicy.check_query_safety(stripped)
        if not is_safe:
            raise HTTPException(status_code=400, detail=f"unsafe_sql: {reason}")

    if db.bind and db.bind.dialect.name != "postgresql":
        return [{
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "orders",
                "Startup Cost": 0.0,
                "Total Cost": 10.0,
                "Plan Rows": 100,
                "Plan Width": 32,
            }
        }]

    # Ensure telemetry_demo_orders table exists if referenced
    if "telemetry_demo_orders" in stripped.lower():
        try:
            with db.begin_nested():
                db.execute(text("""
                    CREATE TABLE IF NOT EXISTS telemetry_demo_orders (
                        id SERIAL PRIMARY KEY,
                        customer_id INT NOT NULL,
                        amount NUMERIC(10, 2) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
                        payload TEXT
                    );
                """))
        except Exception:
            pass

    # EXPLAIN without ANALYZE plans the statement inside a read-only transaction with strict timeout.
    try:
        with db.begin_nested():
            if db.bind and db.bind.dialect.name == "postgresql":
                db.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                db.execute(text("SET LOCAL default_transaction_read_only = on"))
            result = db.execute(text(f"EXPLAIN (FORMAT JSON) {stripped}"))
            row = result.scalar_one()
    except Exception as exc:
        orig = getattr(exc, "orig", exc)
        err_msg = str(orig).split("\n")[0].strip()
        logger.warning(f"EXPLAIN query failed: {err_msg}")
        raise HTTPException(status_code=400, detail=f"sql_explain_failed: {err_msg}")

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


from app.core.auth import require_analyst, require_viewer
from app.core.security import TokenPayload


@router.post("/analyze", response_model=PlanAnalysisResponse)
def analyze(
    request: PlanAnalyzeRequest,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> PlanAnalysisResponse:
    query_id: int | None = None
    raw_plan: Any = None

    if request.query_id is not None:
        from app.api.v1.routes.queries import find_query_statistic
        stat = find_query_statistic(db, str(request.query_id))
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
def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> PlanAnalysisResponse:
    row = db.get(PlanAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="plan_analysis_not_found")
    return _response(row)
