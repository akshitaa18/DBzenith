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
def query_detail(query_id: int, db: Session = Depends(get_db)) -> QueryDetail:
    row = db.scalar(
        select(QueryStatistic)
        .where(QueryStatistic.query_id == query_id)
        .order_by(desc(QueryStatistic.id))
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="query_not_found")
    return QueryDetail.from_model(row)
