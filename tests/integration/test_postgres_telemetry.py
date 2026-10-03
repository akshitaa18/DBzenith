import os

import pytest
from sqlalchemy import create_engine, text

from app.services.collector.telemetry import TelemetryCollector


DATABASE_URL = os.getenv("DBZENITH_INTEGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")


def _postgres_available() -> bool:
    if not DATABASE_URL or not DATABASE_URL.startswith("postgresql"):
        return False
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_pg_stat_statements_is_enabled():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        enabled = conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')")
        ).scalar()
        preload = conn.execute(
            text("SELECT current_setting('shared_preload_libraries') LIKE '%pg_stat_statements%'")
        ).scalar()
    assert enabled is True
    assert preload is True


@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_real_telemetry_snapshot_contains_pg_statistics():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS telemetry_test (id integer, value text)"))
        conn.execute(text("INSERT INTO telemetry_test VALUES (1, 'a'), (2, 'b')"))
        conn.execute(text("SELECT count(*) FROM telemetry_test"))

    collector = TelemetryCollector()
    snapshot = collector.collect_once()
    assert snapshot.unique_queries >= 1
    assert snapshot.total_calls >= 1

@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_real_explain_json_can_be_analyzed():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS telemetry_plan_test (id integer, value text)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS telemetry_plan_test_id_idx ON telemetry_plan_test(id)"))
        conn.execute(text("INSERT INTO telemetry_plan_test VALUES (1, 'a'), (2, 'b'), (3, 'c') ON CONFLICT DO NOTHING"))
        raw = conn.execute(text("EXPLAIN (FORMAT JSON) SELECT * FROM telemetry_plan_test WHERE id = 2")).scalar_one()
    from app.services.plans.analyzer import analyze_plan
    from app.services.privacy.contracts import RawPlan
    result = analyze_plan(RawPlan(plan=raw))
    assert result["features"]["node_count"] >= 1
    assert result["graph"]["nodes"]

@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_deterministic_recommendations_from_synthetic_workload():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS recommendation_test (id integer, customer_id integer, status text, created_at timestamp)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS recommendation_test_customer_idx ON recommendation_test(customer_id)"))
        conn.execute(text("INSERT INTO recommendation_test VALUES (1, 7, 'open', now()), (2, 8, 'closed', now())"))
        for _ in range(20):
            conn.execute(text("SELECT * FROM recommendation_test WHERE status = 'open' ORDER BY created_at DESC"))
            conn.execute(text("SELECT count(*) FROM recommendation_test a JOIN recommendation_test b ON a.customer_id = b.customer_id"))
    from app.services.collector.telemetry import TelemetryCollector
    TelemetryCollector().collect_once()
    from app.services.recommendations.engine import RecommendationEngine
    from app.db.session import get_session_factory
    with get_session_factory()() as db:
        rows = RecommendationEngine().generate(db)
        assert all(r.requires_approval for r in rows)
        assert all(r.status == "pending" for r in rows)
