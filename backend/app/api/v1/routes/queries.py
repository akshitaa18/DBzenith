from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.schemas.telemetry import PaginatedQueries, QueryDetail

router = APIRouter(prefix="/queries", tags=["queries"])


def _latest_query_rows(db: Session, slow_only: bool = False, threshold: float = 100.0):
    latest = select(
        QueryStatistic.query_id,
        func.max(QueryStatistic.id).label("max_id"),
    ).group_by(QueryStatistic.query_id).subquery()
    stmt = (
        select(QueryStatistic)
        .join(latest, QueryStatistic.id == latest.c.max_id)
        .order_by(desc(QueryStatistic.mean_exec_time_ms), desc(QueryStatistic.calls))
    )
    if slow_only:
        stmt = stmt.where(QueryStatistic.mean_exec_time_ms >= threshold)
    return stmt


@router.get("/slow", response_model=PaginatedQueries)
def slow_queries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    min_mean_ms: float | None = Query(None, ge=0),
    database_name: str | None = Query(None),
    user_name: str | None = Query(None),
    db: Session = Depends(get_db),
) -> PaginatedQueries:
    from app.core.config import get_settings
    threshold = min_mean_ms if min_mean_ms is not None else get_settings().slow_query_threshold_ms
    base = _latest_query_rows(db, slow_only=True, threshold=threshold)
    if database_name:
        base = base.where(QueryStatistic.database_name == database_name)
    if user_name:
        base = base.where(QueryStatistic.user_name == user_name)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.offset((page - 1) * page_size).limit(page_size)).all()
    return PaginatedQueries(
        items=[QueryDetail.from_model(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{query_id}", response_model=QueryDetail)
def query_detail(query_id: str, db: Session = Depends(get_db)) -> QueryDetail:
    """Retrieves query statistics by PostgreSQL queryid or internal table row id."""
    try:
        ident_num = int(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_query_id_format")

    INT32_MIN = -2147483648
    INT32_MAX = 2147483647

    # Check by PostgreSQL query_id first; include primary key row id only if ident_num fits in 32-bit integer
    if INT32_MIN <= ident_num <= INT32_MAX:
        cond = (QueryStatistic.query_id == ident_num) | (QueryStatistic.id == ident_num)
    else:
        cond = (QueryStatistic.query_id == ident_num)

    row = db.scalar(
        select(QueryStatistic)
        .where(cond)
        .order_by(desc(QueryStatistic.id))
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="query_not_found")
    return QueryDetail.from_model(row)


@router.get("/{query_id}/trace")
def query_optimization_trace(query_id: str, db: Session = Depends(get_db)) -> dict:
    from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
    from app.models.simulation import OptimizationSimulation
    from app.schemas.recommendations import RecommendationResponse
    from app.schemas.simulations import SimulationResponse

    try:
        ident_num = int(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_query_id_format")

    INT32_MIN = -2147483648
    INT32_MAX = 2147483647

    if INT32_MIN <= ident_num <= INT32_MAX:
        cond = (QueryStatistic.query_id == ident_num) | (QueryStatistic.id == ident_num)
    else:
        cond = (QueryStatistic.query_id == ident_num)

    row = db.scalar(
        select(QueryStatistic)
        .where(cond)
        .order_by(desc(QueryStatistic.id))
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="query_not_found")

    effective_query_id = row.query_id

    # Match recommendations by affected queries or table mention
    all_recs = db.query(OptimizationRecommendation).all()
    matching_recs = []
    for r in all_recs:
        is_affected = False
        if r.affected_queries:
            for aq in r.affected_queries:
                if isinstance(aq, dict) and aq.get("query_id") == effective_query_id:
                    is_affected = True
                    break
        if not is_affected and r.target and r.target.lower() in row.normalized_query.lower():
            is_affected = True
        if is_affected:
            matching_recs.append(r)

    # Find latest simulation among matching recommendations
    latest_sim = None
    if matching_recs:
        rec_ids = [r.id for r in matching_recs]
        latest_sim = (
            db.query(OptimizationSimulation)
            .filter(OptimizationSimulation.recommendation_id.in_(rec_ids))
            .order_by(OptimizationSimulation.id.desc())
            .first()
        )

    # Find audit events
    audit_events = []
    if matching_recs:
        rec_ids = [r.id for r in matching_recs]
        audit_events = (
            db.query(RecommendationAuditEvent)
            .filter(RecommendationAuditEvent.recommendation_id.in_(rec_ids))
            .order_by(RecommendationAuditEvent.created_at.desc())
            .limit(10)
            .all()
        )

    return {
        "query": QueryDetail.from_model(row).model_dump(),
        "matching_recommendations": [RecommendationResponse.model_validate(r).model_dump() for r in matching_recs],
        "latest_simulation": SimulationResponse.model_validate(latest_sim).model_dump() if latest_sim else None,
        "audit_events": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "action": e.action,
                "previous_status": e.previous_status,
                "new_status": e.new_status,
                "reason": e.reason,
            }
            for e in audit_events
        ],
    }
