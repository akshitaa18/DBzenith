from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import require_analyst, require_viewer
from app.core.config import get_settings
from app.core.provenance import ProvenanceState, sanitize_source_identifier
from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.plan import PlanAnalysis
from app.models.recommendation import OptimizationRecommendation
from app.models.simulation import OptimizationSimulation
from app.models.workload import QueryStatistic
from app.schemas.plans import (
    PlanAnalysisResponse,
    PlanAnalyzeRequest,
    PlanCompareRequest,
    PlanExportRequest,
    SafeBenchmarkRequest,
)
from app.services.plans.analyzer import analyze_plan
from app.services.plans.workbench import (
    SafeBenchmarkRunner,
    cancel_benchmark_run,
    compare_execution_plans,
    export_plan_comparison_report,
    scrub_sql_text,
)
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
        provenance_state=row.provenance_state or "HYPOTHETICAL_PLAN_ESTIMATE",
        source_identifier=row.source_identifier,
        is_synthetic=bool(row.is_synthetic),
        is_measured=bool(row.is_measured),
        model_version=row.model_version or "deterministic-plan-analyzer-v0.7.0",
    )


def _build_synthetic_candidate_plan(baseline_plan: Any, index_ddl: str | None = None, target_table: str | None = None) -> dict[str, Any]:
    """Builds a hypothetical candidate plan estimate in planner_cost_units (never milliseconds) when only a baseline plan is present."""
    from app.services.plans.workbench import parse_plan_tree_detailed

    parsed = parse_plan_tree_detailed(baseline_plan)
    base_cost = parsed.total_cost if parsed.total_cost > 0 else 120.0
    est_rows = max(1, int(parsed.estimated_rows if parsed.estimated_rows > 0 else 250))
    rel = target_table or (parsed.nodes[0].relation_name if parsed.nodes else None) or "orders"
    idx_name = f"idx_{rel}_candidate"
    if index_ddl:
        m = re.search(r"INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)", index_ddl, re.IGNORECASE)
        if m:
            idx_name = m.group(1)

    cand_cost = round(max(4.2, base_cost * 0.28), 2)
    return {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": rel,
            "Alias": rel,
            "Index Name": idx_name,
            "Startup Cost": round(cand_cost * 0.08, 2),
            "Total Cost": cand_cost,
            "Plan Rows": est_rows,
            "Plan Width": 64,
        }
    }


def _resolve_plans_and_sql_from_db(
    db: Session,
    *,
    query_id: int | str | None = None,
    simulation_id: int | None = None,
    recommendation_id: int | None = None,
    baseline_sql: str | None = None,
    candidate_sql: str | None = None,
    candidate_index_ddl: str | None = None,
    baseline_plan: Any = None,
    candidate_plan: Any = None,
) -> tuple[Any, Any, str | None, str | None, str | None, int | None]:
    """Resolves stored metadata from ORM rows without executing user SQL on the production database."""
    resolved_base_plan = baseline_plan
    resolved_cand_plan = candidate_plan
    resolved_base_sql = baseline_sql
    resolved_cand_sql = candidate_sql
    resolved_index_ddl = candidate_index_ddl
    resolved_rec_id = recommendation_id

    if simulation_id is not None:
        sim = db.get(OptimizationSimulation, simulation_id)
        if sim is None:
            raise HTTPException(status_code=404, detail="simulation_not_found")
        if resolved_base_plan is None and sim.baseline_plans:
            resolved_base_plan = sim.baseline_plans[0]
        if resolved_cand_plan is None and sim.proposed_plans:
            resolved_cand_plan = sim.proposed_plans[0]
        if resolved_rec_id is None:
            resolved_rec_id = sim.recommendation_id

    if resolved_rec_id is not None:
        rec = db.get(OptimizationRecommendation, resolved_rec_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")
        prop = (rec.proposed_change or "").strip()
        if prop.upper().startswith("CREATE") and "INDEX" in prop.upper():
            if not resolved_index_ddl:
                resolved_index_ddl = prop
        elif prop.upper().startswith(("SELECT", "WITH")):
            if not resolved_cand_sql:
                resolved_cand_sql = prop

        if resolved_base_plan is None or resolved_cand_plan is None:
            latest_sim = (
                db.query(OptimizationSimulation)
                .filter(OptimizationSimulation.recommendation_id == rec.id)
                .order_by(OptimizationSimulation.id.desc())
                .first()
            )
            if latest_sim is not None:
                if resolved_base_plan is None and latest_sim.baseline_plans:
                    resolved_base_plan = latest_sim.baseline_plans[0]
                if resolved_cand_plan is None and latest_sim.proposed_plans:
                    resolved_cand_plan = latest_sim.proposed_plans[0]

        if query_id is None and isinstance(rec.affected_queries, list) and rec.affected_queries:
            first_aff = rec.affected_queries[0]
            if isinstance(first_aff, dict) and "query_id" in first_aff:
                query_id = first_aff["query_id"]
            elif isinstance(first_aff, (int, str)):
                query_id = first_aff

    if query_id is not None:
        from app.api.v1.routes.queries import find_query_statistic
        stat = find_query_statistic(db, str(query_id))
        if stat is not None:
            if not resolved_base_sql:
                resolved_base_sql = stat.normalized_query
            if resolved_base_plan is None and stat.explain_plan is not None:
                resolved_base_plan = stat.explain_plan
            if resolved_base_plan is None:
                est_rows = max(1, int(stat.rows or 1000))
                # Pure planner cost unit estimate from cardinality (never derived from mean_exec_time_ms)
                est_cost = round(max(15.0, est_rows * 0.18), 2)
                resolved_base_plan = {
                    "Plan": {
                        "Node Type": "Seq Scan",
                        "Relation Name": "orders",
                        "Alias": "orders",
                        "Startup Cost": 0.0,
                        "Total Cost": est_cost,
                        "Plan Rows": est_rows,
                        "Plan Width": 64,
                    }
                }

    if resolved_base_plan is not None and resolved_cand_plan is None:
        resolved_cand_plan = _build_synthetic_candidate_plan(
            resolved_base_plan,
            index_ddl=resolved_index_ddl,
        )

    return (
        resolved_base_plan,
        resolved_cand_plan,
        resolved_base_sql,
        resolved_cand_sql,
        resolved_index_ddl,
        resolved_rec_id,
    )


@router.post("/analyze", response_model=PlanAnalysisResponse)
def analyze(
    request: PlanAnalyzeRequest,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> PlanAnalysisResponse:
    query_id: int | None = None
    raw_plan: Any = None
    is_synthetic = False

    if request.query_id is not None:
        from app.api.v1.routes.queries import find_query_statistic
        stat = find_query_statistic(db, str(request.query_id))
        if stat is None:
            raise HTTPException(status_code=404, detail="query_stat_not_found")

        query_id = stat.query_id
        is_synthetic = bool(stat.is_synthetic) or stat.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value

        if stat.explain_plan is not None:
            raw_plan = stat.explain_plan
        else:
            normalized = stat.normalized_query
            safe_sql = re.sub(r"\$(\d+)", "'sample_val'", normalized)
            try:
                raw_plan = _explain_sql(db, safe_sql)
            except Exception:
                try:
                    safe_sql_num = re.sub(r"\$(\d+)", "1", normalized)
                    raw_plan = _explain_sql(db, safe_sql_num)
                except Exception:
                    op_type = "ModifyTable" if normalized.lower().startswith(("insert", "update", "delete")) else "Seq Scan"
                    est_rows = max(1, int(stat.rows or 1000))
                    # Planner cost units estimated from cardinality — never mean_exec_time_ms!
                    est_planner_cost = round(max(12.0, est_rows * 0.15), 2)
                    raw_plan = [{
                        "Plan": {
                            "Node Type": op_type,
                            "Operation": normalized.split()[0].capitalize() if op_type == "ModifyTable" else "Select",
                            "Relation Name": "workload_relation",
                            "Startup Cost": 0.0,
                            "Total Cost": est_planner_cost,
                            "Plan Rows": est_rows,
                            "Plan Width": 64,
                            "Plans": [
                                {
                                    "Node Type": "Seq Scan",
                                    "Relation Name": "workload_relation",
                                    "Startup Cost": 0.0,
                                    "Total Cost": est_planner_cost,
                                    "Plan Rows": est_rows,
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
        sanitized_input = PrivacyGateway().sanitize_plan(RawPlan(plan=raw_plan, query_id=query_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    structural_hash = sanitized_input.structural_hash

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

    gnn_out = result.get("gnn")
    model_ver = (
        f"gnn-{gnn_out.get('model_type', 'gcn')}-v0.7.0"
        if isinstance(gnn_out, dict)
        else "deterministic-plan-analyzer-v0.7.0"
    )
    prov_state = (
        ProvenanceState.SYNTHETIC_DEMO.value
        if is_synthetic
        else ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    )
    source_id = (
        "synthetic://demo-workload-generator"
        if is_synthetic
        else sanitize_source_identifier(get_settings().database_url)
    )

    sanitized = result["sanitized_plan"]
    row = PlanAnalysis(
        query_id=query_id,
        structural_hash=structural_hash,
        sanitized_plan=sanitized.plan,
        graph=result["graph"],
        features=result["features"],
        bottlenecks=result["bottlenecks"],
        explanation={**result["explanation"], "gnn": gnn_out},
        provenance_state=prov_state,
        source_identifier=source_id,
        is_synthetic=is_synthetic,
        is_measured=False,
        model_version=model_ver,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    from app.services.audit.recorder import AuditEventCategory, record_audit_event
    record_audit_event(
        db=db,
        event_category=AuditEventCategory.AI_BOUNDARY,
        action="plan_analyzed",
        actor_id=str(_user.user_id),
        actor_username=_user.username,
        actor_role=_user.role.value,
        target_entity="PlanAnalysis",
        target_id=str(row.id),
        status="SUCCESS",
        details={
            "query_id": query_id,
            "structural_hash": structural_hash,
            "provenance_state": prov_state,
            "model_version": model_ver,
        },
    )
    return _response(row)


@router.post("/compare")
def compare_plans_endpoint(
    request: PlanCompareRequest,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Compares baseline and candidate PostgreSQL execution plans side-by-side."""
    (
        base_plan,
        cand_plan,
        base_sql,
        cand_sql,
        index_ddl,
        rec_id,
    ) = _resolve_plans_and_sql_from_db(
        db,
        query_id=request.query_id,
        simulation_id=request.simulation_id,
        recommendation_id=request.recommendation_id,
        baseline_sql=request.baseline_sql,
        candidate_sql=request.candidate_sql,
        candidate_index_ddl=request.candidate_index_ddl,
        baseline_plan=request.baseline_plan,
        candidate_plan=request.candidate_plan,
    )

    return compare_execution_plans(
        base_plan,
        cand_plan,
        baseline_sql=base_sql,
        candidate_sql=cand_sql,
        candidate_index_ddl=index_ddl,
        recommendation_id=rec_id,
    )


@router.post("/benchmark")
def run_safe_benchmark_endpoint(
    request: SafeBenchmarkRequest,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Runs a safe, bounded query benchmark and plan comparison against the isolated sandbox."""
    (
        base_plan,
        cand_plan,
        base_sql,
        cand_sql,
        index_ddl,
        rec_id,
    ) = _resolve_plans_and_sql_from_db(
        db,
        query_id=request.query_id,
        recommendation_id=request.recommendation_id,
        baseline_sql=request.baseline_sql,
        candidate_sql=request.candidate_sql,
        candidate_index_ddl=request.candidate_index_ddl,
        baseline_plan=request.baseline_plan,
        candidate_plan=request.candidate_plan,
    )

    runner = SafeBenchmarkRunner()
    result = runner.run_benchmark(
        baseline_sql=base_sql or "",
        candidate_sql=cand_sql,
        candidate_index_ddl=index_ddl,
        baseline_plan_raw=base_plan,
        candidate_plan_raw=cand_plan,
        parameters=request.parameters,
        warmup_runs=request.warmup_runs,
        benchmark_runs=request.benchmark_runs,
        statement_timeout_ms=request.statement_timeout_ms,
        run_id=request.run_id,
        pre_cancelled=request.pre_cancelled,
        recommendation_id=rec_id,
    )

    from app.services.audit.recorder import AuditEventCategory, record_audit_event
    record_audit_event(
        db=db,
        event_category=AuditEventCategory.SIMULATION,
        action="sandbox_benchmark_executed",
        actor_id=str(_user.user_id),
        actor_username=_user.username,
        actor_role=_user.role.value,
        target_entity="SandboxBenchmark",
        target_id=str(result.get("run_id")),
        status="SUCCESS" if result.get("status") in {"completed", "estimate_only"} else "BLOCKED",
        details={
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "comparison_verdict": result.get("comparison_verdict"),
            "warmup_runs": request.warmup_runs,
            "benchmark_runs": request.benchmark_runs,
            "statement_timeout_ms": request.statement_timeout_ms,
            "sanitized_baseline_sql": scrub_sql_text(base_sql),
            "candidate_index_ddl": index_ddl,
        },
    )

    return result


@router.post("/benchmark/{run_id}/cancel")
def cancel_benchmark_endpoint(
    run_id: str,
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Requests cancellation of an active sandbox benchmark run."""
    return cancel_benchmark_run(run_id)


@router.post("/compare/export")
def export_plan_comparison_endpoint(
    request: PlanExportRequest,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Exports a plan comparison and benchmark report as sanitized JSON or CSV without sensitive literals."""
    payload = request.comparison
    if payload is None:
        (
            base_plan,
            cand_plan,
            base_sql,
            cand_sql,
            index_ddl,
            rec_id,
        ) = _resolve_plans_and_sql_from_db(
            db,
            recommendation_id=request.recommendation_id,
            baseline_sql=request.baseline_sql,
            candidate_sql=request.candidate_sql,
            candidate_index_ddl=request.candidate_index_ddl,
            baseline_plan=request.baseline_plan,
            candidate_plan=request.candidate_plan,
        )
        payload = compare_execution_plans(
            base_plan,
            cand_plan,
            baseline_sql=base_sql,
            candidate_sql=cand_sql,
            candidate_index_ddl=index_ddl,
            recommendation_id=rec_id,
        )

    fmt = request.format.lower()
    content_type, content = export_plan_comparison_report(
        payload,
        export_format=fmt,
        exported_by=_user.username,
    )

    from app.services.audit.recorder import AuditEventCategory, record_audit_event
    record_audit_event(
        db=db,
        event_category=AuditEventCategory.AI_BOUNDARY,
        action="plan_comparison_exported",
        actor_id=str(_user.user_id),
        actor_username=_user.username,
        actor_role=_user.role.value,
        target_entity="PlanComparisonExport",
        target_id=fmt,
        status="SUCCESS",
        details={
            "format": fmt,
            "literals_scrubbed": True,
        },
    )

    return {
        "format": fmt,
        "content_type": content_type,
        "filename": f"dbzenith_plan_comparison.{fmt}",
        "literals_scrubbed": True,
        "content": content,
    }


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
