from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.schemas.telemetry import WorkloadSummary

router = APIRouter(prefix="/workload", tags=["workload"])


@router.get("/summary", response_model=WorkloadSummary)
def workload_summary(db: Session = Depends(get_db)) -> WorkloadSummary:
    snapshot = db.scalar(
        select(WorkloadSnapshot).order_by(desc(WorkloadSnapshot.captured_at), desc(WorkloadSnapshot.id)).limit(1)
    )
    if snapshot is None:
        return WorkloadSummary(
            snapshot_id=None, captured_at=None, window_seconds=0, total_calls=0,
            total_exec_time_ms=0, unique_queries=0, slow_queries=0, top_queries=[]
        )

    top = db.scalars(
        select(QueryStatistic)
        .where(QueryStatistic.snapshot_id == snapshot.id)
        .order_by(desc(QueryStatistic.total_exec_time_ms))
        .limit(5)
    ).all()
    return WorkloadSummary(
        snapshot_id=snapshot.id,
        captured_at=snapshot.captured_at,
        window_seconds=snapshot.window_seconds,
        total_calls=snapshot.total_calls,
        total_exec_time_ms=snapshot.total_exec_time_ms,
        unique_queries=snapshot.unique_queries,
        slow_queries=snapshot.slow_queries,
        top_queries=[{
            "query_id": q.query_id,
            "mean_exec_time_ms": q.mean_exec_time_ms,
            "total_exec_time_ms": q.total_exec_time_ms,
            "calls": q.calls,
            "query": q.normalized_query,
        } for q in top],
    )
