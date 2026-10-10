import os

import pytest
from sqlalchemy import create_engine, text

from app.db.session import get_session_factory
from app.models.recommendation import OptimizationRecommendation
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.services.sandbox.simulator import SandboxSimulator

PRODUCTION_URL = os.getenv("DBZENITH_INTEGRATION_DATABASE_URL")
SANDBOX_URL = os.getenv("DBZENITH_INTEGRATION_SANDBOX_URL") or os.getenv("SANDBOX_DATABASE_URL")


def _available(url: str | None) -> bool:
    if not url or not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _available(PRODUCTION_URL) or not _available(SANDBOX_URL), reason="Set DBZENITH_INTEGRATION_DATABASE_URL and SANDBOX_DATABASE_URL to isolated test PostgreSQL instances")
def test_index_simulation_isolated_from_production():
    engine = create_engine(PRODUCTION_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sandbox_sim_orders"))
        conn.execute(text("CREATE TABLE sandbox_sim_orders (id bigserial PRIMARY KEY, customer_id integer NOT NULL, payload text)"))
        conn.execute(text("INSERT INTO sandbox_sim_orders (customer_id, payload) SELECT (g % 10), 'x' FROM generate_series(1, 200) g"))
        conn.execute(text("ANALYZE sandbox_sim_orders"))

    with get_session_factory()() as db:
        snapshot = WorkloadSnapshot(window_seconds=30, total_calls=50, total_exec_time_ms=1000, unique_queries=1, slow_queries=0)
        db.add(snapshot)
        db.flush()
        stat = QueryStatistic(
            snapshot_id=snapshot.id, query_id=987654321, database_oid=0, user_oid=0,
            normalized_query="SELECT id, payload FROM sandbox_sim_orders WHERE customer_id = $1",
            calls=50, total_exec_time_ms=1000, mean_exec_time_ms=20, min_exec_time_ms=1,
            max_exec_time_ms=40, rows=20, query_frequency_per_minute=10, shared_blks_read=100,
            predicate_info=None, explain_plan=None,
        )
        db.add(stat)
        db.flush()
        rec = OptimizationRecommendation(
            recommendation_key="sandbox-integration-index",
            type="index_where", target="sandbox_sim_orders",
            proposed_change="CREATE INDEX CONCURRENTLY ON sandbox_sim_orders (customer_id);",
            reason="integration test", evidence={}, expected_benefit="test", risk="test",
            confidence=0.8, affected_queries=[{"query_id": 987654321}], requires_approval=True, status="pending",
        )
        db.add(rec)
        db.commit()

        result = SandboxSimulator().simulate(
            db, rec,
            type("Request", (), {"max_rows_per_table": 1000, "statement_timeout_ms": 5000, "benchmark_runs": 1})(),
        )
        assert result.status == "completed"
        assert result.baseline_cost is not None
        assert result.proposed_cost is not None
        assert result.plan_differences
        assert result.limitations

    with engine.connect() as conn:
        # The sandbox index is cleaned up and production was never modified by simulation DDL.
        assert conn.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename='sandbox_sim_orders' AND indexname LIKE 'dbzenith_sim_%'" )).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename='sandbox_sim_orders' AND indexname ILIKE '%customer_id%'" )).scalar_one() == 0
