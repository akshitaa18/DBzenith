from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.schemas.telemetry import WorkloadSummary
from app.services.collector.telemetry import TelemetryCollector
from app.services.recommendations.engine import RecommendationEngine

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
            "id": q.id,
            "query_id": q.query_id,
            "mean_exec_time_ms": q.mean_exec_time_ms,
            "total_exec_time_ms": q.total_exec_time_ms,
            "calls": q.calls,
            "query": q.normalized_query,
        } for q in top],
    )


@router.post("/collect")
def collect_telemetry(db: Session = Depends(get_db)):
    """Triggers an immediate telemetry collection snapshot and recommendation synthesis."""
    collector = TelemetryCollector()
    snapshot = collector.collect_once()
    engine = RecommendationEngine()
    recs = engine.generate(db, limit=50)
    return {
        "status": "success",
        "snapshot_id": snapshot.id,
        "total_calls": snapshot.total_calls,
        "slow_queries": snapshot.slow_queries,
        "recommendations_generated": len(recs),
    }


@router.post("/seed-demo")
def seed_demo_workload(db: Session = Depends(get_db)):
    """Executes synthetic realistic e-commerce traffic on demo tables, captures telemetry, and generates optimizations."""
    # Ensure telemetry demo table exists with realistic unindexed workload
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS telemetry_demo_orders (
            id SERIAL PRIMARY KEY,
            customer_id INT NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            status VARCHAR(32) NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        );
    """))

    count = db.execute(text("SELECT count(*) FROM telemetry_demo_orders;")).scalar() or 0
    if count < 5000:
        db.execute(text("""
            INSERT INTO telemetry_demo_orders (customer_id, amount, status, created_at)
            SELECT (g % 300) + 1,
                   round((random() * 1200 + 10)::numeric, 2),
                   CASE (g % 4)
                       WHEN 0 THEN 'pending'
                       WHEN 1 THEN 'completed'
                       WHEN 2 THEN 'processing'
                       ELSE 'cancelled'
                   END,
                   now() - ((g % 60) || ' days')::interval
            FROM generate_series(1, 10000) AS g;
        """))
        db.commit()

    # Execute representative slow queries to register in pg_stat_statements
    demo_queries = [
        "SELECT customer_id, count(*), sum(amount) FROM telemetry_demo_orders WHERE status = 'pending' GROUP BY customer_id ORDER BY sum(amount) DESC LIMIT 20;",
        "SELECT a.customer_id, count(*) FROM telemetry_demo_orders a JOIN telemetry_demo_orders b ON b.customer_id = a.customer_id WHERE a.amount > 800 GROUP BY a.customer_id LIMIT 10;",
        "SELECT id, customer_id, amount FROM telemetry_demo_orders WHERE status = 'processing' AND amount BETWEEN 100 AND 500 ORDER BY created_at DESC LIMIT 50;",
        "SELECT status, avg(amount), max(amount) FROM telemetry_demo_orders GROUP BY status;",
    ]

    for q in demo_queries:
        try:
            for _ in range(5):
                db.execute(text(q))
        except Exception:
            pass
    db.commit()

    # Collect telemetry snapshot and generate optimization recommendations
    collector = TelemetryCollector()
    snapshot = collector.collect_once()
    engine = RecommendationEngine()
    recs = engine.generate(db, limit=50)

    return {
        "status": "success",
        "message": "Demo workload generated, telemetry snapshot captured, and optimization recommendations synthesized.",
        "snapshot_id": snapshot.id,
        "total_calls": snapshot.total_calls,
        "slow_queries": snapshot.slow_queries,
        "recommendations_count": len(recs),
    }

